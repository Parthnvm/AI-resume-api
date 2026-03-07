import re
import logging
from typing import List, Set, Tuple
from io import BytesIO

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
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
    "languages": {"python", "java", "javascript", "c++", "c#", "ruby", "go", "rust", "php", "swift", "kotlin", "typescript", "sql"},
    "frameworks": {"django", "flask", "fastapi", "react", "angular", "vue", "spring", "dotnet", "laravel", "express", "pytorch", "tensorflow"},
    "tools": {"docker", "kubernetes", "aws", "azure", "gcp", "git", "jenkins", "jira", "redis", "mongodb", "postgresql", "mysql"},
    "concepts": {"machine learning", "nlp", "rest api", "graphql", "ci/cd", "agile", "scrum", "devops", "microservices", "ui/ux", "frontend", "backend"}
}


class AnalysisResult(BaseModel):
    match_score: float
    skill_score: float
    content_score: float
    reasoning: str  # <--- NEW FIELD
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
            raise HTTPException(status_code=400, detail="Invalid or corrupt PDF file")

    @staticmethod
    def extract_text_from_docx(file_content: bytes) -> str:
        try:
            doc = Document(BytesIO(file_content))
            return "\n".join([para.text for para in doc.paragraphs])
        except Exception as e:
            logger.error(f"DOCX parsing error: {e}")
            raise HTTPException(status_code=400, detail="Invalid or corrupt DOCX file")

    @classmethod
    def parse_file(cls, file: UploadFile) -> str:
        content = file.file.read()
        if file.filename.endswith(".pdf"):
            return cls.extract_text_from_pdf(content)
        elif file.filename.endswith(".docx"):
            return cls.extract_text_from_docx(content)
        elif file.filename.endswith(".txt"):
            return content.decode("utf-8")
        else:
            raise HTTPException(status_code=400, detail="Unsupported file format. Use PDF, DOCX, or TXT.")


class TextProcessor:
    @staticmethod
    def clean(text: str) -> str:
        text = text.lower()
        text = re.sub(r'[^a-z0-9\s\+\#]', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    @staticmethod
    def extract_explicit_skills(text: str) -> Set[str]:
        found = set()
        clean_txt = TextProcessor.clean(text)
        words = set(clean_txt.split())
        
        for category in SKILL_DB.values():
            found.update(words.intersection(category))
            
        for concept in SKILL_DB["concepts"]:
            if concept in clean_txt:
                found.add(concept)
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

    def generate_reasoning(self, final_score: float, matched: Set[str], missing: Set[str]) -> str:
        """Generates a human-readable explanation."""
        score_percent = final_score * 100
        missing_list = list(missing)[:3] # Top 3 missing
        
        if score_percent >= 80:
            return f"Excellent Match! The candidate possesses {len(matched)} key skills and aligns well with the job context."
        elif score_percent >= 60:
            return f"Good potential. Matches on core skills like {', '.join(list(matched)[:2])}, but missing specific tools."
        elif score_percent >= 40:
            reason = "Moderate match."
            if missing:
                reason += f" Candidate is missing critical requirements: {', '.join(missing_list)}."
            else:
                reason += " Context is similar, but specific technical keywords are absent."
            return reason
        else:
            return f"Low match. The resume content differs significantly from the job description. Missing: {', '.join(missing_list)}."

    def extract_contact_info(self) -> Tuple[str, str, str, int]:
        email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', self.resume_raw)
        email = email_match.group(0) if email_match else "Not found"
        
        # Phone: very basic check for 10 digits
        phone_match = re.search(r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', self.resume_raw)
        phone = phone_match.group(0) if phone_match else "Not found"
        
        # Basic heuristic for education
        lower_raw = self.resume_raw.lower()
        edu = "Not specified"
        if "master" in lower_raw or "m.s." in lower_raw or "ms" in lower_raw.split():
            edu = "Master's Degree"
        elif "bachelor" in lower_raw or "b.s." in lower_raw or "bs" in lower_raw.split() or "b.a" in lower_raw:
            edu = "Bachelor's Degree"
        elif "phd" in lower_raw or "ph.d" in lower_raw:
            edu = "Ph.D."
            
        # Basic heuristic for experience
        exp_years = 0
        exp_matches = re.findall(r'(\d+)(?:\+)?\s+(?:years|yrs)', lower_raw)
        if exp_matches:
            try:
                exp_years = max([int(y) for y in exp_matches])
            except:
                pass
                
        return email, phone, edu, exp_years

    def analyze(self) -> AnalysisResult:
        content_score = self.calculate_cosine_similarity()
        skill_score, matched, missing = self.calculate_skill_match()
        
        
        final_score = (content_score * 0.4) + (skill_score * 0.6)

        
        reasoning_text = self.generate_reasoning(final_score, matched, missing)
        email, phone, edu, exp_years = self.extract_contact_info()

        return AnalysisResult(
            match_score=round(final_score * 100, 2),
            skill_score=round(skill_score * 100, 2),
            content_score=round(content_score * 100, 2),
            reasoning=reasoning_text,
            found_skills=list(matched),
            missing_skills=list(missing),
            status="success",
            email=email,
            phone=phone,
            education=edu,
            experience_years=exp_years
        )


app = FastAPI(title="Enterprise Resume Screener API", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/screen/file", response_model=AnalysisResult)
async def screen_resume_file(job_description: str = Form(...), file: UploadFile = File(...)):
    logger.info(f"Analyzing file: {file.filename}")
    resume_text = DocumentParser.parse_file(file)
    engine = MatchingEngine(job_description, resume_text)
    return engine.analyze()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)