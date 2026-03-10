import os
import re
import json
import zipfile
from io import BytesIO
from pathlib import Path
from pypdf import PdfReader

# Import your custom engine directly
# (This assumes resume_screener_api.py is in the root directory)
try:
    from resume_screener_api import MatchingEngine
except ImportError:
    # Fallback if Python can't find it automatically
    import sys
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from resume_screener_api import MatchingEngine

# Get the absolute path to the root directory
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
            # python-docx handles both .docx and many .doc files
            doc = docx.Document(file_path)
            text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
        elif ext == 'txt':
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
        elif ext == 'rtf':
            # Basic RTF stripping: remove control words and groups
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                raw = f.read()
            # Remove RTF control words and braces
            text = re.sub(r'\\[a-z*]+[-\d]*\s?', ' ', raw)
            text = re.sub(r'[{}]', '', text)
            text = re.sub(r'\s+', ' ', text).strip()
        elif ext == 'odt':
            # ODT is a zip containing content.xml
            with zipfile.ZipFile(file_path, 'r') as z:
                if 'content.xml' in z.namelist():
                    with z.open('content.xml') as xf:
                        xml_content = xf.read().decode('utf-8', errors='ignore')
                    # Strip XML tags
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

def analyze_single_resume(resume_text: str, filename: str, custom_jd: str = "") -> dict:
    # Use the HR's custom text, otherwise fallback to the default markdown file
    if custom_jd and custom_jd.strip():
        job_desc = custom_jd
    else:
        job_desc = load_text_file("job_description.md", "Default Job Description...")

    # Initialize your custom MatchingEngine with the context
    engine = MatchingEngine(jd_text=job_desc, resume_text=resume_text)
    
    # Run the analysis
    analysis_result = engine.analyze()
    
    return analysis_result.dict()