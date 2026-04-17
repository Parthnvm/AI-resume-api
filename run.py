#!/usr/bin/env python3
"""
run.py — Local development entry point.

Do NOT use this in production. Use gunicorn via wsgi.py instead:
  gunicorn wsgi:app --workers 2 --threads 2 --timeout 120

Usage:
  FLASK_ENV=development python run.py
"""

import os
from dotenv import load_dotenv

# Load .env before initialising the app so all keys are available
load_dotenv()

from app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV", "development").lower() == "development"

    print(f"[Dev Server] Starting on http://localhost:{port}  (debug={debug})")
    print("[Dev Server] For production use: gunicorn wsgi:app")

    app.run(host="0.0.0.0", port=port, debug=debug)