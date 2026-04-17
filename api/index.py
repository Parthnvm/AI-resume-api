"""
api/index.py — Vercel serverless entry point.

Vercel's Python runtime discovers the Flask WSGI app by importing
this module and looking for a callable named `app`.

All application logic lives in the main package (app/).
This file is intentionally kept to a single re-export so that
wsgi.py remains the canonical WSGI entrypoint for every other
platform (Render, Docker, local Gunicorn).

Environment variables must be configured in the Vercel dashboard
(Project → Settings → Environment Variables):
  SECRET_KEY, FIREBASE_API_KEY, GEMINI_API_KEY, GROQ_API_KEY,
  DATABASE_URL  ← required (use Neon / Supabase / any external Postgres)
"""

import os
from dotenv import load_dotenv

# Load .env for local `vercel dev` testing.
# On real Vercel deployments env vars are injected by the platform.
load_dotenv()

from app import create_app  # noqa: E402

app = create_app()
