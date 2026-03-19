import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_bcrypt import Bcrypt
from flask_cors import CORS

# Initialize extensions
db = SQLAlchemy()
login_manager = LoginManager()
bcrypt = Bcrypt()

def create_app():
    app = Flask(__name__)
    CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)
    
    # Configuration
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-super-secret-key')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///resume_shortlister.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Upload folder — uses Render's persistent disk path in production if set
    upload_folder = os.environ.get(
        'UPLOAD_FOLDER',
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'resumes')
    )
    os.makedirs(upload_folder, exist_ok=True)
    app.config['UPLOAD_FOLDER'] = upload_folder
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB limit

    # Security: enforce secure cookies in production (HTTPS)
    app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    # Firebase Auth — set FIREBASE_API_KEY in .env
    app.config['FIREBASE_API_KEY'] = os.environ.get('FIREBASE_API_KEY', '')

    # Init extensions
    db.init_app(app)
    login_manager.init_app(app)
    bcrypt.init_app(app)
    
    login_manager.login_view = 'auth_bp.auth'
    login_manager.login_message_category = 'info'
    
    @login_manager.user_loader
    def load_user(user_id):
        from app.models import User
        return User.query.get(user_id)
        
    @login_manager.request_loader
    def load_user_from_request(request):
        api_key = request.headers.get('Authorization')
        if api_key:
            api_key = api_key.replace('Bearer ', '', 1)
            from app.models import User
            user = User.query.filter_by(api_key=api_key).first()
            if user:
                return user
        return None
    
    # Register Blueprints
    from app.routes import auth_bp, student_bp, hr_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(student_bp, url_prefix='/student')
    app.register_blueprint(hr_bp, url_prefix='/hr')
    
    # Create DB tables
    with app.app_context():
        db.create_all()

    # Inject current_year into every template (used by base.html footer)
    @app.context_processor
    def inject_globals():
        from datetime import datetime
        return {'current_year': datetime.utcnow().year}

    return app

