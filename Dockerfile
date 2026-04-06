# ─── AI Resume Screener — Dockerfile ─────────────────────────────────────────
# Multi-stage build for a lean, secure production image (~200 MB final layer).
#
# Build:  docker build -t ai-resume-api .
# Run:    docker run -p 5000:5000 --env-file .env ai-resume-api
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.11-slim AS builder

# Install build deps (needed for scikit-learn / some wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: runtime image ────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Security: run as non-root user
RUN groupadd --gid 1001 appgroup \
 && useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

WORKDIR /app

# Copy installed packages from builder stage
COPY --from=builder /install /usr/local

# Copy application source
COPY --chown=appuser:appgroup . .

# Create required directories and set permissions
RUN mkdir -p resumes results instance \
 && chown -R appuser:appgroup resumes results instance

# Switch to non-root user
USER appuser

# Expose app port
EXPOSE 5000

# Production environment defaults
ENV FLASK_ENV=production \
    PORT=5000 \
    LOG_LEVEL=INFO \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Health check — Docker will mark the container unhealthy if this fails
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:$PORT/health')" \
    || exit 1

# Start gunicorn
CMD gunicorn wsgi:app \
        --workers 2 \
        --threads 2 \
        --timeout 120 \
        --bind "0.0.0.0:$PORT" \
        --access-logfile - \
        --error-logfile -
