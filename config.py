"""
config.py — Flask configuration classes.

Usage:
  Selected automatically by create_app() based on the FLASK_ENV environment variable.

  FLASK_ENV=production  → ProductionConfig  (default when not set)
  FLASK_ENV=development → DevelopmentConfig
  FLASK_ENV=testing     → TestingConfig
"""

import os
from pathlib import Path

# Root directory of the project
ROOT_DIR = Path(__file__).resolve().parent

# True when running inside a Vercel serverless function.
# Vercel automatically injects VERCEL=1 into every function's environment.
IS_VERCEL: bool = os.environ.get("VERCEL", "") == "1"


class BaseConfig:
    """Shared configuration for all environments."""

    # ── Flask ────────────────────────────────────────────────────────────────
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "")
    MAX_CONTENT_LENGTH: int = 16 * 1024 * 1024  # 16 MB upload limit

    # ── Database ─────────────────────────────────────────────────────────────
    # Supports PostgreSQL via DATABASE_URL (e.g. Render's managed Postgres).
    # Falls back to SQLite for local dev / single-server deployments.
    _db_url = os.environ.get("DATABASE_URL", "")
    if _db_url.startswith("postgres://"):
        # SQLAlchemy 1.4+ requires postgresql:// scheme
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)
    # Use .as_posix() so the path uses forward slashes on all operating systems.
    # sqlite:/// + absolute path (3 slashes + full path from root).
    _sqlite_path = (ROOT_DIR / "instance" / "resume_shortlister.db").as_posix()
    SQLALCHEMY_DATABASE_URI: str = _db_url or f"sqlite:///{_sqlite_path}"
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    SQLALCHEMY_ENGINE_OPTIONS: dict = {
        "pool_pre_ping": True,   # drop stale connections automatically
        "pool_recycle": 300,     # recycle connections every 5 minutes
    }

    # ── File uploads ─────────────────────────────────────────────────────────
    # UPLOAD_DIR env var lets cloud platforms point to a persistent disk
    # (e.g. Render mounts a disk at /opt/render/project/src/resumes).
    #
    # On Vercel the project root is read-only; only /tmp is writable.
    # Files stored in /tmp are ephemeral (lost on cold-start / between
    # different function invocations), which is acceptable for single-request
    # resume processing. For persistent storage, integrate an object store
    # (Cloudflare R2, AWS S3, etc.) and replace this with a signed-URL flow.
    _default_upload = "/tmp/resumes" if IS_VERCEL else (ROOT_DIR / "resumes").as_posix()
    UPLOAD_FOLDER: str = os.environ.get("UPLOAD_DIR", _default_upload)

    # ── Session / Cookie security ────────────────────────────────────────────
    SESSION_COOKIE_HTTPONLY: bool = True
    SESSION_COOKIE_SAMESITE: str = "Lax"
    PERMANENT_SESSION_LIFETIME: int = 86400  # 24 hours in seconds

    # ── Firebase Auth ─────────────────────────────────────────────────────────
    FIREBASE_API_KEY: str = os.environ.get("FIREBASE_API_KEY", "")

    # ── App metadata ─────────────────────────────────────────────────────────
    APP_VERSION: str = "1.0.0"


class DevelopmentConfig(BaseConfig):
    """Local development — verbose errors, no HTTPS enforcement."""
    DEBUG: bool = True
    TESTING: bool = False
    SESSION_COOKIE_SECURE: bool = False   # allow HTTP in local dev


class ProductionConfig(BaseConfig):
    """Production — strict security, no debug output."""
    DEBUG: bool = False
    TESTING: bool = False
    SESSION_COOKIE_SECURE: bool = True    # HTTPS only

    @classmethod
    def validate(cls) -> None:
        """Raise early with a helpful message if critical env vars are missing."""
        missing = [k for k in ("SECRET_KEY", "FIREBASE_API_KEY") if not os.environ.get(k)]
        if missing:
            raise RuntimeError(
                f"[ProductionConfig] Missing required environment variables: {', '.join(missing)}. "
                "Set them in your hosting platform's environment settings."
            )
        if os.environ.get("SECRET_KEY") in ("dev-super-secret-key", "changeme", ""):
            raise RuntimeError(
                "[ProductionConfig] SECRET_KEY is set to an insecure default. "
                "Generate a strong key with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )


class TestingConfig(BaseConfig):
    """Automated tests — in-memory SQLite, no external side-effects."""
    DEBUG: bool = True
    TESTING: bool = True
    SQLALCHEMY_DATABASE_URI: str = "sqlite:///:memory:"
    SESSION_COOKIE_SECURE: bool = False
    WTF_CSRF_ENABLED: bool = False


# Mapping used by create_app()
config_map = {
    "development": DevelopmentConfig,
    "production":  ProductionConfig,
    "testing":     TestingConfig,
}


def get_config():
    """Return the appropriate config class based on FLASK_ENV."""
    env = os.environ.get("FLASK_ENV", "production").lower()
    return config_map.get(env, ProductionConfig)
