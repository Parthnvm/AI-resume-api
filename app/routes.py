import os
import json
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify, send_from_directory
from flask_login import login_user, logout_user, login_required, current_user
from app import db, bcrypt
from app.models import User, ResumeUpload, CandidateAnalysis
from app.utils import extract_text_from_pdf, analyze_single_resume

# Blueprints
auth_bp = Blueprint('auth_bp', __name__)
student_bp = Blueprint('student_bp', __name__)
hr_bp = Blueprint('hr_bp', __name__)

# --- AUTHENTICATION ROUTES ---
@auth_bp.route('/', methods=['GET'])
def index():
    if current_user.is_authenticated:
        return redirect(url_for(f'{current_user.user_type}_bp.dashboard'))
    return redirect(url_for('auth_bp.auth'))

@auth_bp.route('/auth', methods=['GET', 'POST'])
def auth():
    if current_user.is_authenticated:
        return redirect(url_for(f'{current_user.user_type}_bp.dashboard'))

    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'login':
            email = request.form.get('email')
            password = request.form.get('password')
            user = User.query.filter_by(email=email).first()
            if user and bcrypt.check_password_hash(user.password_hash, password):
                login_user(user)
                return redirect(url_for(f'{user.user_type}_bp.dashboard'))
            flash('Invalid email or password', 'error')

        elif action == 'register':
            email = request.form.get('email')
            password = request.form.get('password')
            user_type = request.form.get('user_type')
            
            if User.query.filter_by(email=email).first():
                flash('Email already registered', 'error')
            else:
                hashed = bcrypt.generate_password_hash(password).decode('utf-8')
                new_user = User(
                    email=email, password_hash=hashed, user_type=user_type,
                    first_name=request.form.get('first_name'),
                    last_name=request.form.get('last_name')
                )
                db.session.add(new_user)
                db.session.commit()
                login_user(new_user)
                return redirect(url_for(f'{new_user.user_type}_bp.dashboard'))

    return render_template('auth.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth_bp.auth'))

# --- STUDENT ROUTES ---
@student_bp.route('/dashboard')
@login_required
def dashboard():
    if current_user.user_type != 'student': return redirect(url_for('hr_bp.dashboard'))
    uploads = ResumeUpload.query.filter_by(user_id=current_user.id).order_by(ResumeUpload.upload_date.desc()).all()
    return render_template('student_dashboard.html', uploads=uploads)

@student_bp.route('/upload', methods=['POST'])
@login_required
def upload():
    if 'resume' not in request.files:
        flash('No file part', 'error')
        return redirect(url_for('student_bp.dashboard'))
    
    file = request.files['resume']
    if file.filename == '':
        flash('No selected file', 'error')
        return redirect(url_for('student_bp.dashboard'))
        
    if file and file.filename.endswith('.pdf'):
        filename = secure_filename(file.filename)
        safe_filename = f"{current_user.id}_{filename}"
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], safe_filename)
        file.save(filepath)
        
        upload_record = ResumeUpload(
            user_id=current_user.id,
            filename=safe_filename,
            original_filename=file.filename,
            file_path=filepath
        )
        db.session.add(upload_record)
        db.session.commit()
        flash('Resume uploaded successfully!', 'success')
    else:
        flash('Only PDF files are allowed.', 'error')
        
    return redirect(url_for('student_bp.dashboard'))

# --- HR ROUTES ---
@hr_bp.route('/dashboard')
@login_required
def dashboard():
    if current_user.user_type != 'hr': return redirect(url_for('student_bp.dashboard'))
    candidates = ResumeUpload.query.order_by(ResumeUpload.upload_date.desc()).all()
    return render_template('hr_dashboard.html', candidates=candidates)

@hr_bp.route('/analyze/<upload_id>', methods=['POST'])
@login_required
def analyze(upload_id):
    if current_user.user_type != 'hr': return jsonify({"error": "Unauthorized"}), 403
    
    upload = ResumeUpload.query.get_or_404(upload_id)
    text = extract_text_from_pdf(upload.file_path)
    
    req_data = request.get_json(force=True, silent=True) or {}
    custom_jd = req_data.get('job_description', '').strip()
    
    if not text:
        return jsonify({"error": "Failed to extract text from PDF."}), 400
        
    try:
        result = analyze_single_resume(text, upload.original_filename, custom_jd)
        
        analysis = CandidateAnalysis.query.filter_by(upload_id=upload.id).first()
        if not analysis:
            analysis = CandidateAnalysis(upload_id=upload.id)
            db.session.add(analysis)
            
        analysis.total_score = result.get('match_score', 0)
        analysis.technical_skills_score = result.get('skill_score', 0)
        analysis.experience_score = result.get('content_score', 0)
        analysis.reasoning = result.get('reasoning', "")
        
        # Save exact JD without fallbacks
        analysis.job_description = custom_jd
        
        analysis.key_strengths = json.dumps(result.get('found_skills', []))
        analysis.concerns = json.dumps(result.get('missing_skills', []))
        
        upload.status = 'analyzed'
        db.session.commit()
        
        return jsonify({"success": True, "message": "Analysis complete!"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@hr_bp.route('/update_status/<upload_id>', methods=['POST'])
@login_required
def update_status(upload_id):
    if current_user.user_type != 'hr': return jsonify({"error": "Unauthorized"}), 403
    upload = ResumeUpload.query.get_or_404(upload_id)
    status = request.json.get('status')
    if status in ['shortlisted', 'rejected', 'pending']:
        upload.status = status
        db.session.commit()
        return jsonify({"success": True})
    return jsonify({"error": "Invalid status"}), 400

@hr_bp.route('/view_resume/<upload_id>')
@login_required
def view_resume(upload_id):
    upload = ResumeUpload.query.get_or_404(upload_id)
    
    if current_user.user_type == 'student' and upload.user_id != current_user.id:
        return "Unauthorized", 403
    elif current_user.user_type not in ['hr', 'student']:
        return "Unauthorized", 403
    
    if not os.path.exists(upload.file_path):
        return "Resume file not found on the server.", 404
        
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], upload.filename)

@hr_bp.route('/delete/<upload_id>', methods=['POST'])
@login_required
def delete_resume(upload_id):
    if current_user.user_type != 'hr': return jsonify({"error": "Unauthorized"}), 403
    upload = ResumeUpload.query.get_or_404(upload_id)
    
    try:
        analysis = CandidateAnalysis.query.filter_by(upload_id=upload.id).first()
        if analysis:
            db.session.delete(analysis)
            
        if os.path.exists(upload.file_path):
            os.remove(upload.file_path)
            
        db.session.delete(upload)
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500