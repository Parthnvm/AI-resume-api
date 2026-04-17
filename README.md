# 🤖 SmartHire — AI Resume Screener API

> An intelligent, production-ready resume screening platform powered by Google Gemini, Groq, and a local TF-IDF fallback engine. Built with Flask, Firebase Auth, and SQLAlchemy.

[![Python 3.11](https://img.shields.io/badge/python-3.11-blue?logo=python)](https://www.python.org/)
[![Flask 3.0](https://img.shields.io/badge/Flask-3.0-lightgrey?logo=flask)](https://flask.palletsprojects.com/)
[![Gemini AI](https://img.shields.io/badge/AI-Gemini%20%2B%20Groq-purple?logo=google)](https://aistudio.google.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| **AI Resume Analysis** | Gemini → Groq → TF-IDF 3-tier fallback chain; never fails |
| **Smart Scoring** | Match score, skill score, content score with detailed reasoning |
| **HR Dashboard** | Paginated candidate board with search, sort, filter, bulk actions |
| **Student Portal** | Students upload their own resume and view personalized AI feedback |
| **Job Board** | HR posts roles; students apply to specific jobs |
| **Batch Upload** | Drop a ZIP of PDFs — processed in background (Render/Docker) or synchronously (Vercel) |
| **Firebase Auth** | Industry-standard email/password authentication with password reset |
| **API Key Access** | Every HR account gets a Bearer token for programmatic API access |
| **CSV Export** | One-click export of shortlisted candidates |
| **Dark Mode** | Polished UI with full dark/light mode toggle |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Flask App                               │
│                                                                 │
│  auth_bp (/, /auth, /logout, /forgot-password, /health)         │
│  student_bp (/student/dashboard, /student/upload, ...)          │
│  hr_bp (/hr/dashboard, /hr/api/*, /hr/analyze/*, ...)           │
│                                                                 │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐     │
│  │  ai_engine   │   │    utils     │   │  firebase_auth   │     │
│  │  (Gemini/    │   │  (extract,   │   │  (REST API)      │     │
│  │   Groq/TFIDF)│   │   analyze)   │   │                  │     │
│  └──────────────┘   └──────────────┘   └──────────────────┘     │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              SQLAlchemy ORM (SQLite / PostgreSQL)        │   │
│  │  User · JobDescription · ResumeUpload · CandidateAnalysis│   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### AI Fallback Chain

```
Request → Gemini 2.0 Flash → (rate-limited?) → Groq Llama 3.3 70B → (unavailable?) → TF-IDF Engine
```

All three tiers return the same normalised result schema, so the caller never knows which tier was used.

---

## 🚀 Quick Start (Local Development)

### 1. Clone & install

```bash
git clone https://github.com/Parthnvm/AI-resume-api.git
cd AI-resume-api
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in your API keys
```

### 3. Run

```bash
FLASK_ENV=development python run.py
# → http://localhost:5000
```

---

## 🌍 Deploying to Render.com

### One-click deploy

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

### Manual steps

1. Push your code to GitHub
2. Go to [render.com](https://render.com) → **New** → **Web Service**
3. Connect your GitHub repo
4. Render auto-detects the `render.yaml` blueprint
5. In **Environment** → add the following secret variables:

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/app/apikey) |
| `GROQ_API_KEY` | [Groq Console](https://console.groq.com/keys) |
| `FIREBASE_API_KEY` | Firebase Console → Project Settings → Web API Key |

6. Click **Deploy** — the app will be live in ~2 minutes

> [!NOTE]
> The `render.yaml` mounts a **1 GB persistent disk** at `/opt/render/project/src/resumes` so uploaded files survive redeploys. The `UPLOAD_DIR` env var is pre-configured to this path.

---

## ▲ Deploying to Vercel

### Prerequisites

1. **External PostgreSQL database** — Vercel has no built-in database. Use one of:
   - [Neon](https://neon.tech) (free tier, serverless Postgres — recommended)
   - [Supabase](https://supabase.com) (free tier, Postgres)
   - Any Postgres provider that gives you a connection string

2. **Vercel CLI** (optional for local testing):
   ```bash
   npm i -g vercel
   vercel login
   ```

### Deploy steps

1. **Push to GitHub** and connect your repo at [vercel.com/new](https://vercel.com/new)
2. Vercel auto-detects `vercel.json` and uses `api/index.py` as the entry point
3. In **Project Settings → Environment Variables**, add:

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DATABASE_URL` | Postgres connection string from Neon/Supabase |
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/app/apikey) |
| `GROQ_API_KEY` | [Groq Console](https://console.groq.com/keys) |
| `FIREBASE_API_KEY` | Firebase Console → Project Settings → Web API Key |
| `FLASK_ENV` | `production` |

4. Click **Deploy** — the app will be live at `https://<your-project>.vercel.app`

### Vercel-specific behaviour

> [!IMPORTANT]
> **File uploads** are stored in `/tmp/resumes` which is ephemeral. Files persist for the lifetime of a single warm function instance but are lost on cold starts. For production persistence, pipe uploads to an object store (Cloudflare R2, AWS S3) and serve signed URLs.

> [!NOTE]
> **Batch ZIP upload** runs synchronously on Vercel instead of in a background thread. Large ZIPs may approach the 60-second function timeout on the free plan.

> [!NOTE]
> **SQLite is not supported on Vercel.** `DATABASE_URL` pointing to an external Postgres instance is required. The app will refuse to start in production without it.

### Local testing with Vercel CLI

```bash
vercel dev
# → app served at http://localhost:3000 using the serverless runtime
```

---



```bash
# Build
docker build -t ai-resume-api .

# Run (pass real keys via env file)
docker run -p 5000:5000 --env-file .env ai-resume-api

# Health check
curl http://localhost:5000/health
# → {"status":"ok","version":"1.0.0"}
```

---

## 🔧 Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | ✅ | Flask session encryption key. Generate with `secrets.token_hex(32)` |
| `GEMINI_API_KEY` | ✅ | Google Gemini API key (primary AI provider) |
| `GROQ_API_KEY` | ✅ | Groq API key (AI fallback — free tier: 30 RPM) |
| `FIREBASE_API_KEY` | ✅ | Firebase Web API key for Auth |
| `FLASK_ENV` | ❌ | `production` (default) or `development` |
| `DATABASE_URL` | ❌ | PostgreSQL URL. Leave blank for SQLite |
| `UPLOAD_DIR` | ❌ | Absolute path for resume storage. Default: `./resumes` |
| `LOG_LEVEL` | ❌ | `DEBUG` / `INFO` / `WARNING`. Default: `INFO` |
| `PORT` | ❌ | Port for gunicorn. Set automatically by Render/Railway |

---

## 📡 API Reference

All endpoints require a `Authorization: Bearer <api_key>` header (except `/health` and auth routes).

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Liveness probe — no auth required |
| `GET` | `/hr/api/candidates` | Paginated candidate list with filters |
| `GET` | `/hr/api/stats` | Dashboard statistics |
| `POST` | `/hr/analyze/<id>` | Analyze a single resume |
| `POST` | `/hr/api/bulk_analyze` | Analyze all pending resumes |
| `POST` | `/hr/api/batch_upload` | Upload a ZIP of PDFs for batch processing |
| `GET` | `/hr/api/export` | Download shortlisted candidates as CSV |
| `POST` | `/hr/update_status/<id>` | Update candidate status |
| `POST` | `/hr/bulk_action` | Bulk shortlist / reject / delete |
| `GET` | `/student/api/insights/<id>` | Resume AI insights for a student |

### Candidate List Parameters (`/hr/api/candidates`)

| Param | Type | Description |
|-------|------|-------------|
| `page` | int | Page number (default: 1) |
| `limit` | int | Results per page (default: 10) |
| `status` | string | `pending` / `analyzed` / `shortlisted` / `rejected` |
| `job_id` | string | Filter by job UUID |
| `min_score` | float | Minimum AI match score (0–100) |
| `q` | string | Search by name, email, or education |
| `sort` | string | `date_desc` (default) or `score_desc` |

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Web framework | Flask 3.0 |
| ORM | SQLAlchemy + Flask-SQLAlchemy |
| Auth | Firebase Auth (REST) + Flask-Login |
| Password hashing | Flask-Bcrypt (bcrypt) |
| AI (primary) | Google Gemini 2.0 Flash |
| AI (fallback) | Groq — Llama 3.3 70B |
| AI (local) | TF-IDF + scikit-learn |
| PDF parsing | pypdf + python-docx |
| WSGI server | Gunicorn |
| Database | SQLite (dev) / PostgreSQL (prod) |
| Frontend | Tailwind CSS + Alpine.js |

---

## 📁 Project Structure

```
AI-resume-api/
├── api/
│   └── index.py             # Vercel serverless entry point
├── app/
│   ├── __init__.py          # Flask app factory
│   ├── routes.py            # Auth / Student / HR blueprints
│   ├── models.py            # SQLAlchemy models
│   ├── ai_engine.py         # Gemini + Groq AI providers
│   ├── utils.py             # Text extraction, analysis orchestration
│   ├── tasks.py             # Batch processing (async on Render, sync on Vercel)
│   ├── firebase_auth.py     # Firebase REST auth helpers
│   ├── logging_config.py    # Structured logging
│   └── templates/           # Jinja2 HTML templates
├── config.py                # Dev / Prod / Test config classes
├── wsgi.py                  # Gunicorn WSGI entrypoint (Render / Docker)
├── run.py                   # Local dev server
├── resume_screener_api.py   # TF-IDF local engine
├── requirements.txt
├── vercel.json              # Vercel deployment config
├── Procfile                 # Heroku/Render start command
├── render.yaml              # Render.com blueprint
├── Dockerfile               # Multi-stage production Docker image
├── .dockerignore
├── .python-version          # Python 3.11.9
├── .env.example             # Environment variable template
└── .gitignore
```

---

## 🔐 Security Notes

- All sessions use `HttpOnly`, `SameSite=Lax` cookies; `Secure` flag is enforced in production
- Passwords stored as bcrypt hashes; Firebase is the password authority for all new accounts
- File uploads are sanitised with `werkzeug.secure_filename` and prefixed with user ID
- `SECRET_KEY` validation at startup — rejects insecure defaults in production
- Rate limiting and auth validation on all sensitive endpoints

---

## 📄 License

MIT © 2025 SmartHire API