import os
import json
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify, send_from_directory
from flask_login import login_user, logout_user, login_required, current_user
from app import db, bcrypt
from app.models import User, ResumeUpload, CandidateAnalysis
from app.utils import extract_text, analyze_single_resume

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
                new_user.generate_api_key()
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
    
    # Get all active jobs to display on the board
    from app.models import JobDescription
    jobs = JobDescription.query.filter_by(is_active=True).order_by(JobDescription.created_at.desc()).all()
    
    uploads = ResumeUpload.query.filter_by(user_id=current_user.id).order_by(ResumeUpload.upload_date.desc()).all()
    return render_template('student_dashboard.html', uploads=uploads, jobs=jobs)

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
        
        job_id = request.form.get('job_id')
        
        upload_record = ResumeUpload(
            user_id=current_user.id,
            job_id=job_id if job_id else None,
            filename=safe_filename,
            original_filename=file.filename,
            file_path=filepath
        )
        db.session.add(upload_record)
        db.session.commit()
        flash('Resume submitted successfully!', 'success')
    else:
        flash('Only PDF files are allowed.', 'error')
        
    return redirect(url_for('student_bp.dashboard'))

@student_bp.route('/api/insights/<upload_id>')
@login_required
def insights(upload_id):
    if current_user.user_type != 'student': return jsonify({"error": "Unauthorized"}), 403
    
    upload = ResumeUpload.query.get_or_404(upload_id)
    if upload.user_id != current_user.id:
        return jsonify({"error": "Unauthorized"}), 403
        
    if not upload.analysis:
        return jsonify({"error": "No analysis available"}), 404
        
    try:
        strengths = json.loads(upload.analysis.key_strengths) if upload.analysis.key_strengths else []
    except:
        strengths = []
        
    try:
        concerns = json.loads(upload.analysis.concerns) if upload.analysis.concerns else []
    except:
        concerns = []
        
    return jsonify({
        "total_score": upload.analysis.total_score,
        "technical_skills_score": upload.analysis.technical_skills_score,
        "experience_score": upload.analysis.experience_score,
        "reasoning": upload.analysis.reasoning_summary,
        "key_strengths": strengths,
        "concerns": concerns
    })

# --- HR ROUTES ---
@hr_bp.route('/dashboard')
@login_required
def dashboard():
    if current_user.user_type != 'hr': return redirect(url_for('student_bp.dashboard'))
    
    # Render the initial frame without all data (data fetched via API below)
    from app.models import JobDescription
    jobs = JobDescription.query.filter_by(hr_id=current_user.id).order_by(JobDescription.created_at.desc()).all()
    
    return render_template('hr_dashboard.html', jobs=jobs)

@hr_bp.route('/api/candidates')
@login_required
def get_candidates():
    if current_user.user_type != 'hr': return jsonify({"error": "Unauthorized"}), 403
    
    # 1. Pagination Parameters
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)
    
    # 2. Filtering Parameters
    status = request.args.get('status')
    job_id = request.args.get('job_id')
    min_score = request.args.get('min_score', type=float)
    search = request.args.get('q', '').strip()
    
    # 3. Sorting Parameters
    sort_by = request.args.get('sort', 'date_desc')
    
    query = ResumeUpload.query.options(db.joinedload(ResumeUpload.student), db.joinedload(ResumeUpload.analysis))
    
    if status and status in ['pending', 'analyzed', 'shortlisted', 'rejected']:
        query = query.filter(ResumeUpload.status == status)
    if job_id:
        query = query.filter(ResumeUpload.job_id == job_id)
        
    if min_score is not None:
        query = query.join(CandidateAnalysis).filter(CandidateAnalysis.total_score >= min_score)
        
    if search:
        from sqlalchemy import or_
        from app.models import User
        # Search against name or email or extracted text
        query = query.join(User).filter(
            or_(
                User.first_name.ilike(f'%{search}%'),
                User.last_name.ilike(f'%{search}%'),
                User.email.ilike(f'%{search}%'),
                ResumeUpload.extracted_email.ilike(f'%{search}%'),
                ResumeUpload.extracted_education.ilike(f'%{search}%')
            )
        )
        
    if sort_by == 'score_desc':
        # Need outerjoin to avoid dropping null analyses when sorting by score
        if min_score is None: 
            query = query.outerjoin(CandidateAnalysis)
        query = query.order_by(CandidateAnalysis.total_score.desc().nullslast())
    else:
        query = query.order_by(ResumeUpload.upload_date.desc())
        
    pagination = query.paginate(page=page, per_page=limit, error_out=False)
    
    # Serialize candidates
    candidates_list = []
    from flask import url_for
    for c in pagination.items:
        score = c.analysis.total_score if c.analysis else 0
        reasoning = c.analysis.reasoning_summary if c.analysis else "Not yet analyzed"
        job_t = c.job.title if hasattr(c, 'job') and c.job else "General Profile"
        
        candidates_list.append({
            "id": c.id,
            "filename": c.original_filename,
            "status": c.status,
            "first_name": c.student.first_name,
            "last_name": c.student.last_name,
            "account_email": c.student.email,
            "extracted_email": c.extracted_email or "",
            "extracted_phone": c.extracted_phone or "",
            "extracted_education": c.extracted_education or "Not specified",
            "extracted_experience_years": c.extracted_experience_years or 0,
            "job_title": job_t,
            "score": score,
            "reasoning": reasoning,
            "view_url": url_for('hr_bp.view_resume', upload_id=c.id),
            "has_analysis": c.analysis is not None
        })
        
    return jsonify({
        "candidates": candidates_list,
        "total": pagination.total,
        "pages": pagination.pages,
        "current_page": page,
        "has_next": pagination.has_next,
        "has_prev": pagination.has_prev
    })

@hr_bp.route('/job', methods=['POST'])
@login_required
def create_job():
    if current_user.user_type != 'hr': return jsonify({"error": "Unauthorized"}), 403
    from app.models import JobDescription
    
    title = request.form.get('title')
    description = request.form.get('description')
    
    if title and description:
        job = JobDescription(hr_id=current_user.id, title=title, description=description)
        db.session.add(job)
        db.session.commit()
        flash('Job posted successfully!', 'success')
    else:
        flash('Title and description are required', 'error')
        
    return redirect(url_for('hr_bp.dashboard'))

@hr_bp.route('/api/stats')
@login_required
def hr_stats():
    if current_user.user_type != 'hr': return jsonify({"error": "Unauthorized"}), 403
    
    total = ResumeUpload.query.count()
    pending = ResumeUpload.query.filter_by(status='pending').count()
    analyzed = ResumeUpload.query.filter_by(status='analyzed').count()
    shortlisted = ResumeUpload.query.filter_by(status='shortlisted').count()
    rejected = ResumeUpload.query.filter_by(status='rejected').count()
    
    analyses = CandidateAnalysis.query.filter(CandidateAnalysis.total_score != None).all()
    avg_score = sum(a.total_score for a in analyses) / len(analyses) if analyses else 0
    
    return jsonify({
        "total": total,
        "pending": pending,
        "analyzed": analyzed,
        "shortlisted": shortlisted,
        "rejected": rejected,
        "avg_score": round(avg_score, 1)
    })

@hr_bp.route('/api/batch_upload', methods=['POST'])
@login_required
def batch_upload():
    if current_user.user_type != 'hr': return jsonify({"error": "Unauthorized"}), 403
    
    if 'zip_file' not in request.files:
        return jsonify({"error": "No file part"}), 400
        
    file = request.files['zip_file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
        
    job_id = request.form.get('job_id')
    webhook_url = request.form.get('webhook_url')
    
    if file and file.filename.endswith('.zip'):
        from app.tasks import start_batch_processing
        upload_folder = current_app.config['UPLOAD_FOLDER']
        filename = secure_filename(file.filename)
        file_path = os.path.join(upload_folder, f"upload_{filename}")
        file.save(file_path)
        
        start_batch_processing(current_app._get_current_object(), file_path, current_user.id, job_id, webhook_url)
        
        return jsonify({"message": "Batch processing started. Processing runs in the background."}), 202
    else:
        return jsonify({"error": "File must be a .zip archive"}), 400

@hr_bp.route('/api/analytics/trends')
@login_required
def analytics_trends():
    if current_user.user_type != 'hr': return jsonify({"error": "Unauthorized"}), 403
    
    from sqlalchemy import text
    query = text("""
        SELECT DATE(upload_date) as day, COUNT(*) as count 
        FROM resume_uploads 
        GROUP BY DATE(upload_date) 
        ORDER BY day DESC LIMIT 30
    """)
    result = db.session.execute(query)
    
    data = [{"date": row[0], "count": row[1]} for row in result]
    return jsonify(data[::-1])  # chronologically sorted

@hr_bp.route('/api/analytics/skills')
@login_required
def analytics_skills():
    if current_user.user_type != 'hr': return jsonify({"error": "Unauthorized"}), 403
    
    analyses = CandidateAnalysis.query.order_by(CandidateAnalysis.id.desc()).limit(200).all()
    
    skill_counts = {}
    import json
    for a in analyses:
        if a.concerns:
            try:
                concerns = json.loads(a.concerns)
                for missing in concerns:
                    # Naively extracting the first few words as a "skill name"
                    k = str(missing).lower().split('.')[0].strip()
                    # Filter out long strings
                    if k and len(k) < 40:
                        skill_counts[k] = skill_counts.get(k, 0) + 1
            except:
                pass
                
    sorted_skills = sorted(skill_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    data = [{"skill": k.title(), "frequency": v} for k, v in sorted_skills]
    
    return jsonify(data)

@hr_bp.route('/analyze/<upload_id>', methods=['POST'])
@login_required
def analyze(upload_id):
    if current_user.user_type != 'hr': return jsonify({"error": "Unauthorized"}), 403
    
    upload = ResumeUpload.query.get_or_404(upload_id)
    text = extract_text(upload.file_path)
    
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
        analysis.reasoning_summary = result.get('reasoning', "")
        
        # Save exact JD without fallbacks
        analysis.job_description = custom_jd
        
        analysis.key_strengths = json.dumps(result.get('found_skills', []))
        analysis.concerns = json.dumps(result.get('missing_skills', []))
        
        # Save extracted candidate details
        upload.extracted_email = result.get('email', '')
        upload.extracted_phone = result.get('phone', '')
        upload.extracted_education = result.get('education', '')
        upload.extracted_experience_years = result.get('experience_years', 0)
        
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

@hr_bp.route('/bulk_action', methods=['POST'])
@login_required
def bulk_action():
    if current_user.user_type != 'hr': return jsonify({"error": "Unauthorized"}), 403
    
    data = request.get_json(force=True, silent=True)
    if not data or not data.get('action') or not data.get('candidate_ids'):
        return jsonify({"error": "Invalid data"}), 400
        
    action = data['action']
    candidate_ids = data['candidate_ids']
    
    try:
        uploads = ResumeUpload.query.filter(ResumeUpload.id.in_(candidate_ids)).all()
        for upload in uploads:
            if action in ['shortlisted', 'rejected', 'pending']:
                upload.status = action
            elif action == 'delete':
                analysis = CandidateAnalysis.query.filter_by(upload_id=upload.id).first()
                if analysis:
                    db.session.delete(analysis)
                if os.path.exists(upload.file_path):
                    os.remove(upload.file_path)
                db.session.delete(upload)
                
        db.session.commit()
        return jsonify({"success": True, "message": f"Successfully performed '{action}' on {len(uploads)} candidates."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@hr_bp.route('/api/export')
@login_required
def export_csv():
    if current_user.user_type != 'hr': return "Unauthorized", 403
    
    import csv
    from io import StringIO
    from flask import Response
    
    # Export shortlisted candidates
    candidates = ResumeUpload.query.filter_by(status='shortlisted').all()
    
    output = StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow([
        'Candidate Name', 'Email (Account)', 'Extracted Phone', 
        'Extracted Email', 'Education Profile', 'Years Experience', 
        'AI Match Score (%)', 'AI Decision/Key Strengths'
    ])
    
    for c in candidates:
        name = f"{c.student.first_name} {c.student.last_name}"
        act_email = c.student.email
        ex_phone = c.extracted_phone or "N/A"
        ex_email = c.extracted_email or "N/A"
        ex_edu = c.extracted_education or "N/A"
        ex_exp = c.extracted_experience_years or 0
        
        score = c.analysis.total_score if c.analysis else 0
        
        strengths = ""
        if c.analysis and c.analysis.key_strengths:
            try:
                s_list = json.loads(c.analysis.key_strengths)
                strengths = ", ".join(s_list)
            except:
                strengths = c.analysis.reasoning_summary or ""
        
        writer.writerow([name, act_email, ex_phone, ex_email, ex_edu, ex_exp, score, strengths])
        
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=shortlisted_candidates.csv"}
    )