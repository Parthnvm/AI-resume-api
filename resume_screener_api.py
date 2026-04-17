import re
import logging
import unicodedata
from dataclasses import dataclass, field
from typing import List, Set, Tuple, Optional
from io import BytesIO

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from pypdf import PdfReader
from docx import Document


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("ResumeScreener")


SKILL_DB = {
    "languages": {
        "python", "java", "javascript", "c++", "c#", "ruby", "go", "rust", "php",
        "swift", "kotlin", "typescript", "sql", "r", "scala", "perl", "bash", "shell",
        "lua", "matlab", "julia", "groovy", "fortran", "haskell", "elixir", "dart",
    },
    "frameworks": {
        "django", "flask", "fastapi", "react", "angular", "vue", "spring", "dotnet",
        "laravel", "express", "pytorch", "tensorflow", "keras", "nextjs", "nuxt",
        "svelte", "hadoop", "spark", "jax", "huggingface", "transformers",
        "langchain", "llamaindex", "scikit-learn", "sklearn", "xgboost", "lightgbm",
        "catboost", "triton", "onnx", "mlflow", "wandb", "ray", "dask", "polars",
        "airflow", "prefect", "celery", "fasttext", "gensim", "spacy",
    },
    "tools": {
        "docker", "kubernetes", "aws", "azure", "gcp", "git", "jenkins", "jira",
        "redis", "mongodb", "postgresql", "mysql", "elasticsearch", "kafka",
        "terraform", "ansible", "nginx", "linux", "cuda", "tensorrt", "databricks",
        "snowflake", "bigquery", "dbt", "airflow", "kubeflow", "sagemaker",
        "vertex ai", "github actions", "gitlab ci", "prometheus", "grafana",
    },
    "concepts": {
        "machine learning", "nlp", "rest api", "graphql", "ci/cd", "agile", "scrum",
        "devops", "microservices", "ui/ux", "frontend", "backend", "deep learning",
        "data science", "cloud computing", "system design", "reinforcement learning",
        "computer vision", "generative ai", "large language models", "llm", "rag",
        "fine-tuning", "prompt engineering", "distributed systems", "data engineering",
        "feature engineering", "model deployment", "mlops", "etl",
    },
}



@dataclass
class AnalysisResult:
    match_score: float
    skill_score: float
    content_score: float
    reasoning: str
    found_skills: List[str]
    missing_skills: List[str]
    status: str
    phone: str = ""
    email: str = ""
    education: str = ""
    experience_years: int = 0


class DocumentParser:
    @staticmethod
    def extract_text_from_pdf(file_content: bytes) -> str:
        try:
            reader = PdfReader(BytesIO(file_content))
            text = ""
            for page in reader.pages:
                text += page.extract_text() or ""
            return text
        except Exception as e:
            logger.error(f"PDF parsing error: {e}")
            raise ValueError("Invalid or corrupt PDF file")

    @staticmethod
    def extract_text_from_docx(file_content: bytes) -> str:
        try:
            doc = Document(BytesIO(file_content))
            return "\n".join([para.text for para in doc.paragraphs])
        except Exception as e:
            logger.error(f"DOCX parsing error: {e}")
            raise ValueError("Invalid or corrupt DOCX file")

    @classmethod
    def parse_bytes(cls, content: bytes, filename: str) -> str:
        """Parse raw bytes given a filename for extension detection."""
        if filename.endswith(".pdf"):
            return cls.extract_text_from_pdf(content)
        elif filename.endswith(".docx"):
            return cls.extract_text_from_docx(content)
        elif filename.endswith(".txt"):
            return content.decode("utf-8", errors="replace")
        else:
            raise ValueError("Unsupported file format. Use PDF, DOCX, or TXT.")


class TextProcessor:
    # Unicode chars → ASCII equivalents before stripping
    _UNICODE_REPLACEMENTS = [
        # Box-drawing / rule dividers → space (common in resume templates)
        (re.compile(r'[\u2500-\u257F\u2580-\u259F]+'), ' '),
        # Unicode bullets → hyphen so word boundaries are preserved
        (re.compile(r'[\u2022\u2023\u25E6\u2043\u2219\u29BF\u25CF\u25CB]'), '-'),
        # Em/en dash → hyphen
        (re.compile(r'[\u2013\u2014\u2012]'), '-'),
        # Smart quotes → straight quotes
        (re.compile(r'[\u2018\u2019]'), "'"),
        (re.compile(r'[\u201C\u201D]'), '"'),
        # Other common Unicode punctuation → space
        (re.compile(r'[\u00B7\u2027]'), ' '),
    ]

    @classmethod
    def clean(cls, text: str) -> str:
        """Unicode-aware text cleaning that preserves skill tokens."""
        # Step 1: NFKC normalization (resolves ligatures, width chars, etc.)
        text = unicodedata.normalize('NFKC', text)
        # Step 2: Convert known Unicode to meaningful ASCII
        for pattern, replacement in cls._UNICODE_REPLACEMENTS:
            text = pattern.sub(replacement, text)
        text = text.lower()
        # Step 3: Strip characters that can't be part of skill tokens
        # Keep: letters, digits, whitespace, +, #, /, ., -, _ (for scikit-learn etc.)
        text = re.sub(r'[^a-z0-9\s\+\#\/\.\-\_]', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    @staticmethod
    def extract_explicit_skills(text: str) -> Set[str]:
        """Substring-based skill matching for ALL skills (not just 'concepts').
        Uses word-boundary checks for short tokens to avoid false positives."""
        found = set()
        clean_txt = TextProcessor.clean(text)
        # Boundary-aware pattern cache: short tokens (≤3 chars) need word boundaries
        for category in SKILL_DB.values():
            for skill in category:
                clean_skill = TextProcessor.clean(skill)
                if not clean_skill:
                    continue
                if len(clean_skill) <= 3 or ' ' not in clean_skill:
                    # Use word boundary to avoid matching 'go' inside 'google'
                    pattern = r'(?<![a-z0-9])' + re.escape(clean_skill) + r'(?![a-z0-9])'
                    if re.search(pattern, clean_txt):
                        found.add(skill)
                else:
                    # Multi-word: simple substring (clean_txt is already lowercased)
                    if clean_skill in clean_txt:
                        found.add(skill)
        return found


class MatchingEngine:
    def __init__(self, jd_text: str, resume_text: str):
        self.jd_raw = jd_text
        self.resume_raw = resume_text
        self.jd_clean = TextProcessor.clean(jd_text)
        self.resume_clean = TextProcessor.clean(resume_text)

    def calculate_cosine_similarity(self) -> float:
        try:
            vectorizer = TfidfVectorizer(stop_words='english')
            tfidf_matrix = vectorizer.fit_transform([self.jd_clean, self.resume_clean])
            similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
            return float(similarity)
        except ValueError:
            return 0.0

    def calculate_skill_match(self) -> Tuple[float, Set[str], Set[str]]:
        jd_skills = TextProcessor.extract_explicit_skills(self.jd_clean)
        resume_skills = TextProcessor.extract_explicit_skills(self.resume_clean)

        if not jd_skills:
            return 0.0, set(), set()

        matched = jd_skills.intersection(resume_skills)
        missing = jd_skills.difference(resume_skills)
        score = len(matched) / len(jd_skills)
        return score, matched, missing

    def extract_required_experience_from_jd(self) -> int:
        """Parse the number of required experience years from the JD."""
        patterns = [
            r'(\d+)\+?\s*(?:years?|yrs?)(?:\s+of)?\s+experience',
            r'(?:minimum|at least|min\.?)\s+(\d+)\s+(?:years?|yrs?)',
            r'(\d+)\s*-\s*\d+\s+(?:years?|yrs?)',
        ]
        lower_jd = self.jd_raw.lower()
        for pat in patterns:
            m = re.search(pat, lower_jd)
            if m:
                try:
                    return int(m.group(1))
                except (ValueError, IndexError):
                    pass
        return 0  # Not specified

    # Section headers to search for when building evidence snippets
    _SECTION_HEADERS = re.compile(
        r'^\s*(skills|experience|work experience|employment|projects|education|'
        r'technical skills|core competencies|summary|profile)\s*$',
        re.IGNORECASE,
    )

    def _extract_resume_snippets(self) -> List[str]:
        """Extract meaningful evidence lines from the resume.

        Strategy:
        1. Collect the first substantive line (contact/summary).
        2. Find section headers (SKILLS, EXPERIENCE …) and grab the 3 content
           lines immediately following each header.
        3. De-duplicate while preserving order; return up to 6 lines total.
        """
        raw_lines = self.resume_raw.splitlines()
        seen: Set[str] = set()
        result: List[str] = []

        def _add(line: str) -> None:
            stripped = line.strip()
            # Skip divider-only lines (e.g. ────────)
            if not stripped or stripped == re.sub(r'[^a-zA-Z0-9]', '', stripped) == '':
                return
            # Skip lines that are purely non-alphanumeric (dividers)
            if not re.search(r'[a-zA-Z0-9]', stripped):
                return
            key = stripped[:80]
            if key not in seen:
                seen.add(key)
                result.append(stripped)

        # Grab first substantial line (>30 chars, likely header/summary)
        for line in raw_lines:
            if len(line.strip()) > 30:
                _add(line)
                break

        # Scan for section headers and grab content beneath them
        i = 0
        while i < len(raw_lines) and len(result) < 6:
            if self._SECTION_HEADERS.match(raw_lines[i]):
                # Skip divider lines immediately after the header
                j = i + 1
                added = 0
                while j < len(raw_lines) and added < 3:
                    candidate = raw_lines[j].strip()
                    if candidate and re.search(r'[a-zA-Z0-9]', candidate):
                        _add(candidate)
                        added += 1
                    j += 1
            i += 1

        # Fall back: any line >40 chars not yet included
        if not result:
            for line in raw_lines:
                if len(line.strip()) > 40:
                    _add(line)
                if len(result) >= 4:
                    break

        return result[:6]

    def generate_reasoning(
        self,
        final_score: float,
        matched: Set[str],
        missing: Set[str],
        experience_years: int,
        filename: str = ""
    ) -> str:
        """Generates a structured, HR-readable score explanation."""
        score_pct = round(final_score * 100, 1)
        total_jd_skills = len(matched) + len(missing)
        matched_list = sorted(matched)
        missing_list = sorted(missing)

        required_exp = self.extract_required_experience_from_jd()

        # --- Score Factors block ---
        skill_examples = ", ".join(matched_list[:3]) if matched_list else "None"
        missing_examples = ", ".join(missing_list[:3]) if missing_list else "None"

        factors = (
            f"Score Factors:\n"
            f"  - Skills Match: {len(matched)}/{total_jd_skills if total_jd_skills else '?'} required skills found "
            f"(e.g. {skill_examples})\n"
            f"  - Missing Skills: {missing_examples}\n"
        )

        if required_exp > 0:
            exp_line = (
                f"  - Experience Alignment: {experience_years} yrs found vs "
                f"{required_exp} yrs required\n"
            )
        else:
            exp_line = f"  - Experience Alignment: {experience_years} yrs found (JD requirement not specified)\n"
        factors += exp_line

        # --- Role Fit ---
        if score_pct >= 80:
            role_fit = "Role Fit: Strong alignment — candidate covers most responsibilities and required tools."
            why = f"Why This Score ({score_pct}%): Excellent overlap in both technical skills and contextual relevance to the job description."
        elif score_pct >= 60:
            role_fit = f"Role Fit: Good potential — matches core skills but gaps exist in: {missing_examples}."
            why = f"Why This Score ({score_pct}%): Solid skill coverage with minor gaps; experience and content align reasonably well with the role."
        elif score_pct >= 40:
            role_fit = f"Role Fit: Partial match — candidate meets some criteria but is missing critical requirements: {missing_examples}."
            why = f"Why This Score ({score_pct}%): Moderate keyword/semantic overlap; specific technical keywords from the JD are absent."
        elif total_jd_skills > 0 and len(matched) == 0:
            role_fit = "Role Fit: Missing core technical requirements — no skill overlap detected with the job description."
            why = f"Why This Score ({score_pct}%): Missing core technical requirements. None of the required skills were found in the resume."
        else:
            role_fit = f"Role Fit: Weak alignment — resume content differs significantly from the job description."
            why = f"Why This Score ({score_pct}%): Low semantic and skill overlap with the job description."

        # --- Evidence ---
        snippets = self._extract_resume_snippets()
        if snippets:
            evidence_lines = "\n".join(f'  "{s[:120]}"' for s in snippets)
            evidence = f"Evidence:\n{evidence_lines}"
        else:
            evidence = "Evidence: Limited extractable info — resume may be image-based or poorly formatted."

        # --- Batch prefix ---
        prefix = f"Batch ID: {filename}\n" if filename else ""

        return f"{prefix}{factors}{role_fit}\n\n{why}\n\n{evidence}"

    def extract_contact_info(self) -> Tuple[str, str, str, int]:
        # Email
        email_match = re.search(r'[\w\.\+\-]+@[\w\.-]+\.\w{2,}', self.resume_raw)
        email = email_match.group(0) if email_match else "Not found"

        # Phone: international and local formats
        phone_patterns = [
            r'\+?[\d\s\-\.\(\)]{10,17}',          # Generic international
            r'\+?\d{1,3}[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{4}',  # +1 (123) 456-7890
            r'\b\d{3}[\s\-\.]\d{3}[\s\-\.]\d{4}\b',  # 123-456-7890
            r'\b\d{10}\b',                            # 10-digit compact
        ]
        phone = "Not found"
        for pat in phone_patterns:
            m = re.search(pat, self.resume_raw)
            if m:
                candidate = m.group(0).strip()
                digits = re.sub(r'\D', '', candidate)
                if 10 <= len(digits) <= 15:
                    phone = candidate
                    break

        # Education
        lower_raw = self.resume_raw.lower()
        edu = "Not specified"
        if re.search(r'ph\.?d|doctorate|doctor of', lower_raw):
            edu = "Ph.D."
        elif re.search(r"master'?s?|m\.s\.|m\.eng|mba|msc|m\.tech|m\.a\.", lower_raw):
            edu = "Master's Degree"
        elif re.search(r"bachelor'?s?|b\.s\.|b\.e\.|b\.tech|b\.a\.|b\.eng|undergraduate", lower_raw):
            edu = "Bachelor's Degree"
        elif re.search(r"associates?|associate'?s?|diploma|a\.s\.|a\.a\.", lower_raw):
            edu = "Associate's / Diploma"

        # Experience years — take max of all numeric mentions near "year"/"yr"
        exp_years = 0
        exp_matches = re.findall(r'(\d+)\+?\s*(?:years?|yrs?)', lower_raw)
        if exp_matches:
            try:
                exp_years = max(int(y) for y in exp_matches if int(y) < 50)
            except Exception:
                pass

        return email, phone, edu, exp_years

    def analyze(self, filename: str = "") -> AnalysisResult:
        content_score = self.calculate_cosine_similarity()
        skill_score, matched, missing = self.calculate_skill_match()

        # Weighted: 60% skills + 40% content
        final_score = (skill_score * 0.6) + (content_score * 0.4)

        email, phone, edu, exp_years = self.extract_contact_info()
        reasoning_text = self.generate_reasoning(final_score, matched, missing, exp_years, filename)

        return AnalysisResult(
            match_score=round(final_score * 100, 2),
            skill_score=round(skill_score * 100, 2),
            content_score=round(content_score * 100, 2),
            reasoning=reasoning_text,
            found_skills=sorted(matched),
            missing_skills=sorted(missing),
            status="success",
            email=email,
            phone=phone,
            education=edu,
            experience_years=exp_years
        )

    def analyze_batch(self, resumes: List[Tuple[str, str]]) -> List[AnalysisResult]:
        """
        Analyze multiple resumes against this JD.
        resumes: list of (resume_text, filename) tuples.
        Returns results sorted by match_score descending.
        """
        results = []
        for resume_text, filename in resumes:
            engine = MatchingEngine(jd_text=self.jd_raw, resume_text=resume_text)
            result = engine.analyze(filename=filename)
            results.append(result)
        results.sort(key=lambda r: r.match_score, reverse=True)
        return results



if __name__ == "__main__":
    # ── Standalone FastAPI server (development/testing only) ─────────────────
    # This block is NOT executed when the module is imported by the Flask app.
    try:
        from fastapi import FastAPI, UploadFile, File, Form
        from fastapi.middleware.cors import CORSMiddleware
        import uvicorn

        _api = FastAPI(title="Enterprise Resume Screener API", version="2.2.0")
        _api.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        @_api.post("/screen/file")
        async def screen_resume_file(job_description: str = Form(...), file: UploadFile = File(...)):
            logger.info(f"Analyzing file: {file.filename}")
            content = await file.read()
            resume_text = DocumentParser.parse_bytes(content, file.filename)
            engine = MatchingEngine(job_description, resume_text)
            import dataclasses
            return dataclasses.asdict(engine.analyze(filename=file.filename))

        uvicorn.run(_api, host="0.0.0.0", port=8000)
    except ImportError:
        print("FastAPI/uvicorn not installed. Run: pip install fastapi uvicorn")