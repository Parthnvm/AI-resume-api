from app import db
from flask_login import UserMixin
from datetime import datetime, timedelta
import uuid
import secrets
import hashlib

def generate_uuid():
    return str(uuid.uuid4())

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    user_type = db.Column(db.String(20), nullable=False)  # 'student' or 'hr'
    is_active = db.Column(db.Boolean, default=True)
    api_key = db.Column(db.String(64), unique=True, index=True)
    firebase_uid = db.Column(db.String(128), nullable=True, unique=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Password-reset columns
    reset_token_hash = db.Column(db.String(128), nullable=True, index=True)
    reset_token_expiry = db.Column(db.DateTime, nullable=True)

    uploads = db.relationship('ResumeUpload', backref='student', lazy=True)

    def generate_api_key(self):
        self.api_key = secrets.token_urlsafe(32)

    # --- Password-reset helpers ---
    def set_reset_token(self):
        """Generate a raw token, store its hash+expiry, return the raw token."""
        raw = secrets.token_urlsafe(32)
        self.reset_token_hash = hashlib.sha256(raw.encode()).hexdigest()
        self.reset_token_expiry = datetime.utcnow() + timedelta(minutes=30)
        return raw

    def verify_reset_token(self, raw_token):
        """Return True if raw_token matches the stored hash and hasn't expired."""
        if not self.reset_token_hash or not self.reset_token_expiry:
            return False
        if datetime.utcnow() > self.reset_token_expiry:
            return False
        return hashlib.sha256(raw_token.encode()).hexdigest() == self.reset_token_hash

    def clear_reset_token(self):
        self.reset_token_hash = None
        self.reset_token_expiry = None

class JobDescription(db.Model):
    __tablename__ = 'job_descriptions'
    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    hr_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    uploads = db.relationship('ResumeUpload', backref='job', lazy=True)

class ResumeUpload(db.Model):
    __tablename__ = 'resume_uploads'
    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    job_id = db.Column(db.String(36), db.ForeignKey('job_descriptions.id'), nullable=True)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='pending')  # pending, analyzed, shortlisted, rejected
    
    # Extracted fields
    extracted_email = db.Column(db.String(120), nullable=True)
    extracted_phone = db.Column(db.String(50), nullable=True)
    extracted_education = db.Column(db.String(200), nullable=True)
    extracted_experience_years = db.Column(db.Integer, nullable=True)
    
    analysis = db.relationship('CandidateAnalysis', backref='resume', uselist=False, lazy=True)

class CandidateAnalysis(db.Model):
    __tablename__ = 'candidate_analyses'
    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    upload_id = db.Column(db.String(36), db.ForeignKey('resume_uploads.id'), nullable=False)
    
    # Scores (0-100 float)
    technical_skills_score = db.Column(db.Float, nullable=False, default=0)
    experience_score = db.Column(db.Float, nullable=False, default=0)
    industry_relevance_score = db.Column(db.Float, nullable=False, default=0)
    education_score = db.Column(db.Float, nullable=False, default=0)
    overall_fit_score = db.Column(db.Float, nullable=False, default=0)
    total_score = db.Column(db.Float, nullable=False, default=0)  # 0-100
    
    # Reasoning
    reasoning_summary = db.Column(db.Text)
    key_strengths = db.Column(db.Text)
    concerns = db.Column(db.Text)
    
    analyzed_at = db.Column(db.DateTime, default=datetime.utcnow)
    job_description = db.Column(db.Text, nullable=True)