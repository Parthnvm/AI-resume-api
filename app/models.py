from app import db
from flask_login import UserMixin
from datetime import datetime
import uuid

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    uploads = db.relationship('ResumeUpload', backref='student', lazy=True)

class ResumeUpload(db.Model):
    __tablename__ = 'resume_uploads'
    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='pending')  # pending, analyzed, shortlisted, rejected
    
    analysis = db.relationship('CandidateAnalysis', backref='resume', uselist=False, lazy=True)

class JobDescription(db.Model):
    __tablename__ = 'job_descriptions'
    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class CandidateAnalysis(db.Model):
    __tablename__ = 'candidate_analyses'
    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    upload_id = db.Column(db.String(36), db.ForeignKey('resume_uploads.id'), nullable=False)
    
    # Scores (out of 10)
    technical_skills_score = db.Column(db.Integer, nullable=False, default=0)
    experience_score = db.Column(db.Integer, nullable=False, default=0)
    industry_relevance_score = db.Column(db.Integer, nullable=False, default=0)
    education_score = db.Column(db.Integer, nullable=False, default=0)
    overall_fit_score = db.Column(db.Integer, nullable=False, default=0)
    total_score = db.Column(db.Integer, nullable=False, default=0)  # out of 50
    
    # Reasoning
    reasoning_summary = db.Column(db.Text)
    key_strengths = db.Column(db.Text)
    concerns = db.Column(db.Text)
    
    analyzed_at = db.Column(db.DateTime, default=datetime.utcnow)
    job_description = db.Column(db.Text, nullable=True)