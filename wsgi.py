"""
wsgi.py — Production WSGI entrypoint for Gunicorn-based platforms.

Gunicorn start command (used by Procfile and Dockerfile):
  gunicorn wsgi:app --workers 2 --threads 2 --timeout 120 --bind 0.0.0.0:$PORT

This module intentionally stays minimal. All application logic lives in app/.

Vercel deployment uses a separate thin wrapper at api/index.py which
re-exports the same Flask app object. wsgi.py is NOT used on Vercel.
"""

import os
from dotenv import load_dotenv

# Load .env for local production testing.
# On real cloud hosts (Render, Fly, etc.) env vars are injected by the platform.
load_dotenv()

from app import create_app  # noqa: E402

app = create_app()
