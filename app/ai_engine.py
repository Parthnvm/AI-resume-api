"""
app/ai_engine.py — Gemini AI-powered resume analysis engine.

Uses the new `google-genai` SDK (google.genai) with a model fallback chain:
  1. gemini-2.0-flash  (latest, best quality)
  2. gemini-1.5-flash  (stable, higher free-tier quota)
Falls back gracefully to None on any error so utils.py can use TF-IDF instead.
"""

import hashlib
import os
import json
import logging
import re
import time
from typing import Optional

logger = logging.getLogger("AIEngine")

# Model fallback chain — tried in order until one succeeds
GEMINI_MODELS = [
    "gemini-2.0-flash",       # latest, best quality
    "gemini-2.0-flash-lite",  # lighter model, higher free-tier quota
]

# Seconds to sleep before every Gemini request.
# Free tier: 15 RPM per model → one request every ~4 s stays safely under the cap.
# Set to 0 if you are on a paid tier.
REQUEST_DELAY_SECONDS = 4


# ── Prompt template ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an advanced Resume Screening AI.
Analyze the provided resume against the job description and return ONLY a valid JSON object with no extra text.

Required JSON schema:
{
  "match_score": 85.5,
  "skill_score": 92.0,
  "content_score": 78.3,
  "reasoning": "...",
  "found_skills": ["React", "Node.js", "AWS"],
  "missing_skills": ["Docker", "Kubernetes"],
  "status": "success",
  "phone": "+1-123-456-7890 or Not found",
  "email": "candidate@email.com or Not found",
  "education": "Masters Degree or Not specified",
  "experience_years": 5
}

Scoring Methodology:
- skill_score  : % of JD-required skills found in the resume (0-100)
- content_score: semantic/contextual alignment with JD responsibilities (0-100)
- match_score  : (skill_score * 0.6) + (content_score * 0.4)

The "reasoning" field MUST follow this exact structure:
Score Factors:
  - Skills Match: X/N required skills found (e.g. skill1, skill2, skill3)
  - Missing Skills: skill_a, skill_b
  - Experience Alignment: Y yrs found vs Z yrs required

Role Fit: [one line on strengths/gaps]

Why This Score (XX.X%): [1-2 sentences explaining the number]

Evidence:
  "direct quote or snippet from resume line 1"
  "direct quote or snippet from resume line 2"

Edge Cases:
- No skills match → score < 30, note "Missing core technical requirements"
- Unclear resume → flag: "Limited extractable info"

Return ONLY the JSON object. No markdown fences. No explanation outside the JSON."""

BATCH_SYSTEM_PROMPT = SYSTEM_PROMPT.replace(
    "Return ONLY the JSON object. No markdown fences. No explanation outside the JSON.",
    "For BATCH input return a JSON ARRAY of the above objects sorted descending by match_score.\n"
    "Prefix each reasoning with 'Batch ID: [filename]\\n'.\n"
    "Return ONLY the JSON array. No markdown fences."
)


def _get_client():
    """Return a configured google.genai Client, or None if unavailable."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        return client
    except Exception as e:
        logger.error(f"Gemini client init failed: {e}")
        return None


def _parse_json_response(text: str) -> Optional[dict | list]:
    """Strip markdown fences if present and parse JSON."""
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        _digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]
        logger.error(
            "Gemini JSON parse error: %s | text_length=%d sha256_prefix=%s",
            e, len(text), _digest,
        )
        return None


def _normalise(r: dict) -> dict:
    """Normalise a single result dict — handle camelCase aliases from the model."""
    def _get(*keys, default=None):
        for k in keys:
            v = r.get(k)
            if v is not None:
                return v
        return default

    return {
        "match_score":      round(float(_get("matchScore",    "matchscore",    "match_score",    default=0)), 2),
        "skill_score":      round(float(_get("skillScore",    "skillscore",    "skill_score",    default=0)), 2),
        "content_score":    round(float(_get("contentScore",  "contentscore",  "content_score",  default=0)), 2),
        "reasoning":        str(_get("reasoning", default="")),
        "found_skills":     list(_get("foundSkills",   "found_skills",   "foundsills",    default=[])),
        "missing_skills":   list(_get("missingSkills",  "missing_skills",  "missingskills",  default=[])),
        "status":           str(_get("status", default="success")),
        "phone":            str(_get("phone",     default="Not found")),
        "email":            str(_get("email",     default="Not found")),
        "education":        str(_get("education", default="Not specified")),
        "experience_years": int(_get("experienceYears", "experienceyears", "experience_years", default=0)),
    }


def analyze_with_gemini(resume_text: str, jd_text: str, filename: str = "") -> Optional[dict]:
    """
    Analyze a single resume against a job description using Gemini.
    Returns a normalised result dict, or None on failure.
    """
    client = _get_client()
    if not client:
        return None

    from google.genai import types

    resume_snippet = resume_text[:6000]
    jd_snippet     = jd_text[:2000]
    file_label     = f"Resume filename: {filename}\n" if filename else ""

    prompt = (
        f"{file_label}"
        f"JOB DESCRIPTION:\n{jd_snippet}\n\n"
        f"RESUME:\n{resume_snippet}"
    )

    for model in GEMINI_MODELS:
        for attempt in range(2):  # one retry per model
            try:
                # Polite delay before each call (free-tier rate-limit guard)
                if REQUEST_DELAY_SECONDS > 0:
                    time.sleep(REQUEST_DELAY_SECONDS)

                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=0.2,
                        max_output_tokens=2048,
                        response_mime_type="application/json",
                    ),
                )
                raw = _parse_json_response(response.text)
                if raw is None or not isinstance(raw, dict):
                    break  # bad response — try next model
                logger.info(f"Gemini analysis OK with model={model}")
                return _normalise(raw)

            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    wait = 30 if attempt == 0 else 0
                    logger.warning(f"Rate limit on {model} (attempt {attempt+1}), waiting {wait}s")
                    if wait:
                        time.sleep(wait)
                    continue  # retry same model
                else:
                    logger.error(f"Gemini error with model={model}: {e}")
                    break  # non-rate-limit error — try next model

    logger.error(f"All Gemini models failed for '{filename}'. Falling back to TF-IDF.")
    return None


def batch_analyze_with_gemini(resumes: list, jd_text: str) -> Optional[list]:
    """
    Analyze multiple resumes in one Gemini call.

    resumes : list of (resume_text, filename) tuples
    Returns : list of normalised result dicts sorted desc by match_score, or None.
    """
    client = _get_client()
    if not client:
        return None

    from google.genai import types

    jd_snippet     = jd_text[:2000]
    resumes_block  = ""
    for idx, (text, fname) in enumerate(resumes, start=1):
        resumes_block += f"\n--- Resume {idx} | Filename: {fname} ---\n{text[:4000]}\n"

    prompt = f"JOB DESCRIPTION:\n{jd_snippet}\n\nRESUMES:{resumes_block}"

    for model in GEMINI_MODELS:
        for attempt in range(2):
            try:
                # Polite delay before each call (free-tier rate-limit guard)
                if REQUEST_DELAY_SECONDS > 0:
                    time.sleep(REQUEST_DELAY_SECONDS)

                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=BATCH_SYSTEM_PROMPT,
                        temperature=0.2,
                        max_output_tokens=8192,
                        response_mime_type="application/json",
                    ),
                )
                raw = _parse_json_response(response.text)
                if raw is None:
                    break
                items = raw if isinstance(raw, list) else raw.get("results", [])
                normalised = [_normalise(r) for r in items if isinstance(r, dict)]
                normalised.sort(key=lambda x: x["match_score"], reverse=True)
                logger.info(f"Gemini batch OK with model={model}")
                return normalised

            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    wait = 30 if attempt == 0 else 0
                    logger.warning(f"Rate limit on {model} (batch, attempt {attempt+1}), waiting {wait}s")
                    if wait:
                        time.sleep(wait)
                    continue
                else:
                    logger.error(f"Gemini batch error with model={model}: {e}")
                    break

    logger.error("All Gemini models failed for batch. Falling back to TF-IDF.")
    return None
