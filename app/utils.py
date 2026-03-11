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

# Import Gemini AI engine (optional — degrades gracefully if key missing)
try:
    from app.ai_engine import analyze_with_gemini
except ImportError:
    from ai_engine import analyze_with_gemini

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

    Priority:
      1. Gemini AI engine  (if GEMINI_API_KEY is set)
      2. TF-IDF + skill matching engine  (always available as fallback)

    Returns a dict with keys:
      match_score, skill_score, content_score, reasoning,
      found_skills, missing_skills, status,
      email, phone, education, experience_years
    """
    job_desc = custom_jd.strip() if custom_jd and custom_jd.strip() else \
        load_text_file("job_description.md", "Default Job Description...")

    # 1 — Try Gemini
    ai_result = analyze_with_gemini(resume_text, job_desc, filename)
    if ai_result is not None:
        return ai_result

    # 2 — Fall back to TF-IDF
    return _tfidf_analyze(resume_text, job_desc, filename)