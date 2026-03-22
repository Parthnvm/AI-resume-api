"""
app/ai_engine.py — AI-powered resume analysis engine.

Provider fallback chain:
  1. Gemini  (google-genai SDK)  — tried first; returns RATE_LIMITED sentinel on 429
  2. Groq    (groq SDK)          — used immediately when Gemini is rate-limited or fails
  3. TF-IDF  (resume_screener_api.MatchingEngine) — always-available local fallback,
             invoked from utils.py when both LLM providers are unavailable

Each provider logs which model/provider it used, making it easy to trace which
tier is active in production logs.
"""

import hashlib
import os
import json
import logging
import re
import time
import unicodedata
from typing import Optional

logger = logging.getLogger("AIEngine")

# ── Sentinel returned when Gemini hits a rate-limit ────────────────────────
RATE_LIMITED = "RATE_LIMITED"


# ── Gemini config ─────────────────────────────────────────────────────────
GEMINI_MODELS = [
    "gemini-2.0-flash",       # latest, best quality
    "gemini-2.0-flash-lite",  # lighter model, higher free-tier quota
]

# Polite delay before every Gemini request (free tier: 15 RPM per model).
# Set to 0 if you are on a paid tier.
REQUEST_DELAY_SECONDS = 4

# ── Groq config ────────────────────────────────────────────────────────────
# Free tier: 30 RPM / 14,400 RPD — much higher headroom than Gemini free.
GROQ_MODEL = "llama-3.3-70b-versatile"


# ── Shared prompt template ─────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an advanced Resume Screening AI.
Analyze the provided resume against the job description and return ONLY a valid JSON object with no extra text.

IMPORTANT PARSING NOTES:
- The resume may contain Unicode bullets (•, ◦, ‣), box-drawing dividers (────────), em-dashes, or smart quotes.
  Treat these as section separators or list item markers. DO NOT ignore content after them.
- Scan ALL sections of the resume: Summary, Skills, Experience, Education, Projects, Certifications.
  Do not stop reading after the first section.
- Extract skills even if they appear after bullets, dashes, or dividers.
- found_skills MUST include every skill/technology from the resume that is also required by the JD.
  Do not leave found_skills empty unless the resume truly has no relevant skills.

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
    "Return ONLY the JSON array. No markdown fences."
)


# ── Shared helpers ─────────────────────────────────────────────────────────

# Unicode → ASCII replacements (mirrors TextProcessor in resume_screener_api.py)
_LLM_UNICODE_SUBS = [
    (re.compile(r'[\u2500-\u257F\u2580-\u259F]+'), ' | '),  # box-drawing → pipe separator
    (re.compile(r'[\u2022\u2023\u25E6\u2043\u2219\u29BF\u25CF\u25CB]'), '-'),  # bullets → dash
    (re.compile(r'[\u2013\u2014\u2012]'), '-'),  # em/en dash → hyphen
    (re.compile(r'[\u2018\u2019]'), "'"),
    (re.compile(r'[\u201C\u201D]'), '"'),
]


def _preprocess_for_llm(text: str) -> str:
    """Normalize Unicode in resume text before sending to an LLM.

    Converts box-drawing dividers and Unicode bullets to plain ASCII so the
    LLM sees clean section structure rather than garbled characters.
    The text is NOT lowercased — case matters for proper nouns in skills.
    """
    text = unicodedata.normalize('NFKC', text)
    for pattern, replacement in _LLM_UNICODE_SUBS:
        text = pattern.sub(replacement, text)
    # Collapse excessive blank lines (>2 in a row) to keep within token budget
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text



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
            "JSON parse error: %s | text_length=%d sha256_prefix=%s",
            e, len(text), _digest,
        )
        return None


def _coerce_list(value) -> list:
    """Safely coerce a model value to a clean list of non-empty strings."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        parts = [v.strip() for v in value.split(",")]
        return [p for p in parts if p]
    return [str(value)] if str(value).strip() else []


def _safe_int(value, default: int = 0) -> int:
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return default


def _safe_float(value, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace('%', '').strip())
    except (ValueError, TypeError):
        return default


def _strip_batch_prefix(text: str) -> str:
    """Remove legacy 'Batch ID: ...' prefix lines."""
    lines = text.splitlines()
    cleaned = [l for l in lines if not l.strip().startswith("Batch ID:")]
    return "\n".join(cleaned).strip()


def _normalise(r: dict) -> dict:
    """Normalise a single result dict — handle camelCase aliases from the model."""
    def _get(*keys, default=None):
        for k in keys:
            v = r.get(k)
            if v is not None:
                return v
        return default

    return {
        "match_score":      round(_safe_float(_get("matchScore",    "matchscore",    "match_score",    default=0)), 2),
        "skill_score":      round(_safe_float(_get("skillScore",    "skillscore",    "skill_score",    default=0)), 2),
        "content_score":    round(_safe_float(_get("contentScore",  "contentscore",  "content_score",  default=0)), 2),
        "reasoning":        _strip_batch_prefix(str(_get("reasoning", default=""))),
        "found_skills":     _coerce_list(_get("foundSkills",   "found_skills",   "foundsills")),
        "missing_skills":   _coerce_list(_get("missingSkills",  "missing_skills",  "missingskills")),
        "status":           str(_get("status", default="success")),
        "phone":            str(_get("phone",     default="Not found")),
        "email":            str(_get("email",     default="Not found")),
        "education":        str(_get("education", default="Not specified")),
        "experience_years": _safe_int(_get("experienceYears", "experienceyears", "experience_years", default=0)),
    }


def _is_rate_limit(err_str: str) -> bool:
    """Return True if the error string indicates a rate-limit / quota exhausted."""
    signals = ("429", "rate_limit_exceeded", "resource_exhausted",
               "too many requests", "toomanyrequests")
    lower = err_str.lower()
    return any(s in lower for s in signals)


# ── Gemini ─────────────────────────────────────────────────────────────────

def _get_gemini_client():
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from google import genai
        return genai.Client(api_key=api_key)
    except Exception as e:
        logger.error(f"Gemini client init failed: {e}")
        return None


def analyze_with_gemini(resume_text: str, jd_text: str, filename: str = ""):
    """
    Analyze a single resume with Gemini.

    Returns:
      - normalised result dict  → success
      - RATE_LIMITED sentinel   → all attempts failed due to rate-limiting
      - None                    → all attempts failed for other reasons
    """
    client = _get_gemini_client()
    if not client:
        return None

    from google.genai import types

    resume_snippet = _preprocess_for_llm(resume_text)[:6000]
    jd_snippet     = jd_text[:2000]
    file_label     = f"Resume filename: {filename}\n" if filename else ""

    prompt = (
        f"{file_label}"
        f"JOB DESCRIPTION:\n{jd_snippet}\n\n"
        f"RESUME:\n{resume_snippet}"
    )

    hit_rate_limit = False

    for model in GEMINI_MODELS:
        for attempt in range(2):
            try:
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
                    break
                logger.info(f"Analysis OK: provider=gemini model={model}")
                return _normalise(raw)

            except Exception as e:
                err_str = str(e)
                if _is_rate_limit(err_str):
                    hit_rate_limit = True
                    logger.warning(
                        f"Gemini rate-limited on {model} (attempt {attempt+1}) — switching provider immediately"
                    )
                    break  # skip remaining attempts & models; return sentinel
                else:
                    logger.error(f"Gemini error model={model}: {e}")
                    break

    if hit_rate_limit:
        logger.warning("All Gemini models rate-limited — returning RATE_LIMITED sentinel")
        return RATE_LIMITED

    logger.error(f"All Gemini models failed for '{filename}'")
    return None


def batch_analyze_with_gemini(resumes: list, jd_text: str):
    """
    Batch-analyze multiple resumes with Gemini.

    resumes : list of (resume_text, filename) tuples
    Returns : list of normalised result dicts, RATE_LIMITED sentinel, or None
    """
    client = _get_gemini_client()
    if not client:
        return None

    from google.genai import types

    jd_snippet    = jd_text[:2000]
    resumes_block = ""
    for idx, (text, fname) in enumerate(resumes, start=1):
        resumes_block += f"\n--- Resume {idx} | Filename: {fname} ---\n{text[:4000]}\n"

    prompt = f"JOB DESCRIPTION:\n{jd_snippet}\n\nRESUMES:{resumes_block}"

    hit_rate_limit = False

    for model in GEMINI_MODELS:
        for attempt in range(2):
            try:
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
                if len(normalised) != len(resumes):
                    logger.warning(
                        "Gemini batch cardinality mismatch model=%s: expected=%d actual=%d",
                        model, len(resumes), len(normalised),
                    )
                    break
                normalised.sort(key=lambda x: x["match_score"], reverse=True)
                logger.info(f"Batch analysis OK: provider=gemini model={model}")
                return normalised

            except Exception as e:
                err_str = str(e)
                if _is_rate_limit(err_str):
                    hit_rate_limit = True
                    logger.warning(f"Gemini batch rate-limited on {model} (attempt {attempt+1}) — switching provider immediately")
                    break  # skip remaining attempts & models; return sentinel
                else:
                    logger.error(f"Gemini batch error model={model}: {e}")
                    break

    if hit_rate_limit:
        return RATE_LIMITED
    return None


# ── Groq ───────────────────────────────────────────────────────────────────

def _get_groq_client():
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from groq import Groq
        return Groq(api_key=api_key)
    except Exception as e:
        logger.error(f"Groq client init failed: {e}")
        return None


def analyze_with_groq(resume_text: str, jd_text: str, filename: str = "") -> Optional[dict]:
    """
    Analyze a single resume with Groq (llama-3.3-70b-versatile).
    Returns a normalised result dict, or None on failure.
    """
    client = _get_groq_client()
    if not client:
        return None

    resume_snippet = _preprocess_for_llm(resume_text)[:6000]
    jd_snippet     = jd_text[:2000]
    file_label     = f"Resume filename: {filename}\n" if filename else ""

    user_message = (
        f"{file_label}"
        f"JOB DESCRIPTION:\n{jd_snippet}\n\n"
        f"RESUME:\n{resume_snippet}"
    )

    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": user_message},
                ],
                temperature=0.2,
                max_tokens=2048,
                response_format={"type": "json_object"},
            )
            raw_text = response.choices[0].message.content or ""
            raw = _parse_json_response(raw_text)
            if raw is None or not isinstance(raw, dict):
                logger.warning("Groq returned non-dict JSON — skipping")
                return None
            logger.info(f"Analysis OK: provider=groq model={GROQ_MODEL}")
            return _normalise(raw)

        except Exception as e:
            err_str = str(e)
            if _is_rate_limit(err_str):
                wait = 15 if attempt == 0 else 0
                logger.warning(
                    f"Groq rate-limited (attempt {attempt+1})"
                    + (f", waiting {wait}s" if wait else "")
                )
                if wait:
                    time.sleep(wait)
                continue
            else:
                logger.error(f"Groq error: {e}")
                return None

    logger.error("Groq exhausted all retries — returning None")
    return None


def batch_analyze_with_groq(resumes: list, jd_text: str) -> Optional[list]:
    """
    Batch-analyze multiple resumes with Groq (one call per resume — Groq
    doesn't reliably support multi-resume batch JSON arrays).

    resumes : list of (resume_text, filename) tuples
    Returns : list of normalised result dicts sorted desc by match_score, or None
    """
    client = _get_groq_client()
    if not client:
        return None

    results = []
    for resume_text, filename in resumes:
        result = analyze_with_groq(resume_text, jd_text, filename)
        if result is None:
            logger.warning(f"Groq failed for '{filename}' in batch — aborting Groq batch")
            return None
        results.append(result)

    results.sort(key=lambda x: x["match_score"], reverse=True)
    logger.info(f"Batch analysis OK: provider=groq ({len(results)} resumes)")
    return results


# ── Resume Analytics Module (standalone, Gemini only) ─────────────────────

ANALYZE_RESUME_PROMPT = """You are an advanced Resume Screening AI.
Analyze the provided resume text against general professional standards and extract key insights.
Return ONLY a valid JSON object with no extra text.

Required JSON schema:
{
  "experienceScore": 75,
  "educationScore": 60,
  "skillMatchScore": 85,
  "strengths": ["Strong React skills", "Solid 3 years of experience"],
  "weaknesses": ["Limited backend exposure", "No formal certification"]
}

Scoring Methodology (0-100 scale for each):
- experienceScore: Based on years of experience, depth of roles, and career progression.
- educationScore: Based on level of education, relevance to tech/professional roles, and certifications.
- skillMatchScore: Based on the breadth, depth, and modern relevance of listed skills.

Return ONLY the JSON object. No explanation outside the JSON."""


def analyze_resume_module(resume_text: str) -> Optional[dict]:
    """
    Analyze a resume to generate an analytics breakdown (scores & insights).
    Tries Gemini first, then Groq as fallback.
    """
    # -- Try Gemini first
    gemini_client = _get_gemini_client()
    if gemini_client:
        from google.genai import types
        resume_snippet = resume_text[:6000]
        prompt = f"RESUME:\n{resume_snippet}"

        for model in [GEMINI_MODELS[0]]:
            for attempt in range(2):
                try:
                    if REQUEST_DELAY_SECONDS > 0:
                        time.sleep(REQUEST_DELAY_SECONDS)

                    response = gemini_client.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=ANALYZE_RESUME_PROMPT,
                            temperature=0.2,
                            max_output_tokens=1024,
                            response_mime_type="application/json",
                        ),
                    )
                    raw = _parse_json_response(response.text)
                    if raw is None or not isinstance(raw, dict):
                        break

                    logger.info("Resume module analysis OK: provider=gemini")
                    return {
                        "experienceScore":  _safe_float(raw.get("experienceScore", 0)),
                        "educationScore":   _safe_float(raw.get("educationScore", 0)),
                        "skillMatchScore":  _safe_float(raw.get("skillMatchScore", 0)),
                        "strengths":        _coerce_list(raw.get("strengths", [])),
                        "weaknesses":       _coerce_list(raw.get("weaknesses", [])),
                    }

                except Exception as e:
                    err_str = str(e)
                    if _is_rate_limit(err_str):
                        wait = 30 if attempt == 0 else 0
                        logger.warning("Gemini rate-limited in analyze_resume_module")
                        if wait:
                            time.sleep(wait)
                        continue
                    else:
                        logger.error(f"Gemini error in analyze_resume_module: {e}")
                        break

    # -- Fallback: Groq
    groq_client = _get_groq_client()
    if groq_client:
        resume_snippet = resume_text[:6000]
        try:
            response = groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": ANALYZE_RESUME_PROMPT},
                    {"role": "user",   "content": f"RESUME:\n{resume_snippet}"},
                ],
                temperature=0.2,
                max_tokens=1024,
                response_format={"type": "json_object"},
            )
            raw_text = response.choices[0].message.content or ""
            raw = _parse_json_response(raw_text)
            if raw and isinstance(raw, dict):
                logger.info("Resume module analysis OK: provider=groq")
                return {
                    "experienceScore":  _safe_float(raw.get("experienceScore", 0)),
                    "educationScore":   _safe_float(raw.get("educationScore", 0)),
                    "skillMatchScore":  _safe_float(raw.get("skillMatchScore", 0)),
                    "strengths":        _coerce_list(raw.get("strengths", [])),
                    "weaknesses":       _coerce_list(raw.get("weaknesses", [])),
                }
        except Exception as e:
            logger.error(f"Groq error in analyze_resume_module: {e}")

    logger.warning("analyze_resume_module: all LLM providers failed — returning None")
    return None
