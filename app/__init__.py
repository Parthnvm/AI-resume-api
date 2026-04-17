"""
app/__init__.py — Flask application factory.
"""

import os
import logging
from pathlib import Path
from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_bcrypt import Bcrypt

# Extensions — initialised without an app instance
db = SQLAlchemy()
login_manager = LoginManager()
bcrypt = Bcrypt()

logger = logging.getLogger(__name__)


def create_app():
    """
    Application factory.

    Configuration is driven entirely by environment variables.
    Import and call this from wsgi.py (production) or run.py (local dev).
    """
    from app.logging_config import configure_logging
    from config import get_config

    cfg = get_config()

    # Validate production config early — fail fast with a clear message
    if hasattr(cfg, "validate"):
        cfg.validate()

    # Set up logging before anything else so all startup messages are captured
    configure_logging(debug=cfg.DEBUG)

    app = Flask(__name__)
    app.config.from_object(cfg)

    # ── Ensure required directories exist ────────────────────────────────────
    upload_folder = Path(app.config["UPLOAD_FOLDER"])
    upload_folder.mkdir(parents=True, exist_ok=True)

    # On Vercel /var/task is read-only — redirect results to /tmp
    from config import IS_VERCEL as _IS_VERCEL
    if _IS_VERCEL:
        results_folder = Path("/tmp/results")
    else:
        results_folder = Path(__file__).resolve().parent.parent / "results"
    results_folder.mkdir(parents=True, exist_ok=True)

    # Ensure SQLite instance directory exists (no-op for PostgreSQL)
    db_uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if db_uri.startswith("sqlite:///"):
        # Strip the sqlite:/// prefix to get the file path.
        # config.py uses forward slashes on all operating systems.
        raw_path = db_uri[len("sqlite:///"):]
        Path(raw_path).parent.mkdir(parents=True, exist_ok=True)

    # ── Initialise extensions ────────────────────────────────────────────────
    db.init_app(app)
    login_manager.init_app(app)
    bcrypt.init_app(app)

    login_manager.login_view = "auth_bp.auth"
    login_manager.login_message_category = "info"

    @login_manager.user_loader
    def load_user(user_id):
        from app.models import User
        return db.session.get(User, user_id)

    @login_manager.request_loader
    def load_user_from_request(req):
        api_key = req.headers.get("Authorization", "")
        if api_key.startswith("Bearer "):
            api_key = api_key[7:]
        if api_key:
            from app.models import User
            user = User.query.filter_by(api_key=api_key).first()
            if user:
                return user
        return None

    # ── Register Blueprints ──────────────────────────────────────────────────
    from app.routes import auth_bp, student_bp, hr_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(student_bp, url_prefix="/student")
    app.register_blueprint(hr_bp, url_prefix="/hr")

    # ── Create DB tables ─────────────────────────────────────────────────────
    with app.app_context():
        db.create_all()
        logger.info("Database tables OK (URI: %s)", app.config["SQLALCHEMY_DATABASE_URI"].split("@")[-1])

    # ── Template globals ─────────────────────────────────────────────────────
    @app.context_processor
    def inject_globals():
        from datetime import datetime
        return {
            "current_year":  datetime.utcnow().year,
            "app_version":   app.config.get("APP_VERSION", "1.0.0"),
        }

    # ── Global error handlers ────────────────────────────────────────────────
    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith("/api") or request.accept_mimetypes.accept_json:
            return jsonify({"error": "Not found", "status": 404}), 404
        from flask import render_template
        return render_template("404.html"), 404

    @app.errorhandler(413)
    def request_entity_too_large(e):
        return jsonify({"error": "File too large. Maximum upload size is 16 MB.", "status": 413}), 413

    @app.errorhandler(500)
    def internal_error(e):
        db.session.rollback()
        logger.exception("Internal server error: %s", e)
        if request.path.startswith("/api") or request.accept_mimetypes.accept_json:
            return jsonify({"error": "Internal server error", "status": 500}), 500
        from flask import render_template
        return render_template("500.html"), 500

    logger.info(
        "App started | env=%s debug=%s version=%s",
        os.environ.get("FLASK_ENV", "production"),
        app.config["DEBUG"],
        app.config.get("APP_VERSION", "1.0.0"),
    )

    return app
