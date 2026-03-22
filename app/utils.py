import os
import re
import zipfile
from pathlib import Path
from pypdf import PdfReader

# Import the core TF-IDF engine (root-level module)
try:
    from resume_screener_api import MatchingEngine
except ImportError:
    import sys
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from resume_screener_api import MatchingEngine

# Import AI engine providers
try:
    from app.ai_engine import (
        analyze_with_gemini,
        analyze_with_groq,
        batch_analyze_with_gemini,
        batch_analyze_with_groq,
        RATE_LIMITED,
    )
except ImportError:
    from ai_engine import (
        analyze_with_gemini,
        analyze_with_groq,
        batch_analyze_with_gemini,
        batch_analyze_with_groq,
        RATE_LIMITED,
    )

ROOT_DIR = Path(__file__).resolve().parent.parent

import docx


def extract_text(file_path: str) -> str:
    ext = file_path.lower().rsplit('.', 1)[-1]
    text = ""
    try:
        if ext == 'pdf':
            reader = PdfReader(file_path)
            text = "".join((page.extract_text() or "") + "\n" for page in reader.pages)
        elif ext in ('docx', 'doc'):
            doc = docx.Document(file_path)
            text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
        elif ext == 'txt':
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
        elif ext == 'rtf':
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                raw = f.read()
            text = re.sub(r'\\[a-z*]+[-\d]*\s?', ' ', raw)
            text = re.sub(r'[{}]', '', text)
            text = re.sub(r'\s+', ' ', text).strip()
        elif ext == 'odt':
            with zipfile.ZipFile(file_path, 'r') as z:
                if 'content.xml' in z.namelist():
                    with z.open('content.xml') as xf:
                        xml_content = xf.read().decode('utf-8', errors='ignore')
                    text = re.sub(r'<[^>]+>', ' ', xml_content)
                    text = re.sub(r'\s+', ' ', text).strip()
        return text
    except Exception as e:
        print(f"Error reading file {file_path}: {e}")
        return ""


def load_text_file(filename: str, default_content: str) -> str:
    path = ROOT_DIR / filename
    if not path.exists():
        with open(path, "w", encoding="utf-8") as f:
            f.write(default_content)
        return default_content
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _tfidf_analyze(resume_text: str, jd_text: str, filename: str = "") -> dict:
    """Run the local TF-IDF + skill matching engine and return a normalised dict."""
    engine = MatchingEngine(jd_text=jd_text, resume_text=resume_text)
    result = engine.analyze(filename=filename)
    try:
        return result.model_dump()   # Pydantic v2
    except AttributeError:
        return result.dict()          # Pydantic v1


def analyze_single_resume(resume_text: str, filename: str = "", custom_jd: str = "") -> dict:
    """
    Analyze a single resume against a job description.

    3-tier fallback chain:
      1. Gemini AI (google-genai)   — best quality; if rate-limited → go to tier 2 immediately
      2. Groq AI  (llama-3.3-70b)  — fast, generous free tier; if unavailable → go to tier 3
      3. TF-IDF   (MatchingEngine)  — local, always available, no external dependencies

    Returns a dict with keys:
      match_score, skill_score, content_score, reasoning,
      found_skills, missing_skills, status,
      email, phone, education, experience_years
    """
    job_desc = custom_jd.strip() if custom_jd and custom_jd.strip() else \
        load_text_file("job_description.md", "Default Job Description...")

    # ── Tier 1: Gemini ──────────────────────────────────────────────────────
    gemini_result = analyze_with_gemini(resume_text, job_desc, filename)

    if gemini_result is RATE_LIMITED:
        # Rate-limited → skip straight to Groq without waiting further
        import logging
        logging.getLogger("Utils").warning(
            "Gemini rate-limited — falling back to Groq immediately"
        )
    elif gemini_result is not None:
        return gemini_result
    # else: non-rate-limit failure from Gemini → also try Groq

    # ── Tier 2: Groq ────────────────────────────────────────────────────────
    groq_result = analyze_with_groq(resume_text, job_desc, filename)
    if groq_result is not None:
        return groq_result

    # ── Tier 3: TF-IDF (always works) ───────────────────────────────────────
    import logging
    logging.getLogger("Utils").info("Both LLM providers unavailable — using TF-IDF engine")
    return _tfidf_analyze(resume_text, job_desc, filename)


def batch_analyze_resumes(resumes: list, jd_text: str) -> list:
    """
    Analyze a list of (resume_text, filename) tuples against a job description.

    Same 3-tier chain as analyze_single_resume but operates in batch mode
    where supported:
      1. Gemini batch  — single API call for all resumes
      2. Groq batch    — one call per resume (sequential)
      3. TF-IDF batch  — fully local

    Returns list of normalised result dicts sorted descending by match_score.
    """
    import logging
    log = logging.getLogger("Utils")

    # ── Tier 1: Gemini batch ─────────────────────────────────────────────────
    gemini_result = batch_analyze_with_gemini(resumes, jd_text)

    if gemini_result is RATE_LIMITED:
        log.warning("Gemini batch rate-limited — falling back to Groq batch")
    elif gemini_result is not None:
        return gemini_result

    # ── Tier 2: Groq batch ───────────────────────────────────────────────────
    groq_result = batch_analyze_with_groq(resumes, jd_text)
    if groq_result is not None:
        return groq_result

    # ── Tier 3: TF-IDF batch (always works) ─────────────────────────────────
    log.info("Both LLM providers unavailable for batch — using TF-IDF engine")
    engine = MatchingEngine(jd_text=jd_text, resume_text="")
    raw_results = engine.analyze_batch(resumes)
    out = []
    for r in raw_results:
        try:
            out.append(r.model_dump())
        except AttributeError:
            out.append(r.dict())
    return out