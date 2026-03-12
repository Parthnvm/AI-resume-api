import os
import json
import uuid
import zipfile
import threading
import requests
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename
from flask import current_app
from app import db
from app.models import User, ResumeUpload, JobDescription, CandidateAnalysis
from app.utils import extract_text, analyze_single_resume
from io import BytesIO


def trigger_webhook(webhook_url, payload):
    if not webhook_url:
        return
    try:
        requests.post(webhook_url, json=payload, timeout=5)
    except Exception as e:
        print(f"Webhook delivery failed: {str(e)}")


def process_batch_upload(app_instance, zip_path, hr_user_id, job_id, webhook_url=None):
    """
    Background task to extract and process multiple PDFs from a zip file.
    Creates a dummy student profile for each parsed resume if needed.
    """
    with app_instance.app_context():
        # hr_user_id is forwarded in the webhook payload; no need to load the row here.
        job = JobDescription.query.get(job_id) if job_id else None

        extracted_files = []
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                upload_folder = current_app.config['UPLOAD_FOLDER']

                # Unique batch folder per upload to avoid concurrent-upload collisions.
                batch_uid = uuid.uuid4().hex
                zip_stem  = secure_filename(os.path.basename(zip_path).rsplit('.', 1)[0]) or "batch"
                batch_folder = os.path.join(upload_folder, f"batch_{zip_stem}_{batch_uid}")
                os.makedirs(batch_folder, exist_ok=True)

                # Ensure the shared bulk-upload user exists exactly once,
                # using a race-safe insert: try to commit, catch the unique-
                # constraint IntegrityError, rollback, and re-fetch.
                bulk_user = User.query.filter_by(email='bulk@apexhire.internal').first()
                if not bulk_user:
                    try:
                        bulk_user = User(
                            email='bulk@apexhire.internal',
                            password_hash='noop',
                            first_name='Bulk',
                            last_name='Upload',
                            user_type='student'
                        )
                        db.session.add(bulk_user)
                        db.session.commit()
                    except IntegrityError:
                        db.session.rollback()
                        bulk_user = User.query.filter_by(email='bulk@apexhire.internal').first()

                for file_info in zip_ref.infolist():
                    if file_info.filename.endswith('.pdf') and not file_info.filename.startswith('__MACOSX'):
                        # Preserve sub-folder structure from within the ZIP, sanitised.
                        safe_rel = file_info.filename.replace('\\', '/').lstrip('/')
                        safe_parts = [secure_filename(p) for p in safe_rel.split('/') if p]
                        if not safe_parts or not safe_parts[-1]:
                            continue
                        filename = safe_parts[-1]   # leaf file name (for DB / logging)

                        file_path = os.path.join(batch_folder, *safe_parts)
                        os.makedirs(os.path.dirname(file_path), exist_ok=True)

                        with open(file_path, 'wb') as f:
                            f.write(zip_ref.read(file_info.filename))

                        new_upload = ResumeUpload(
                            user_id=bulk_user.id,
                            job_id=job.id if job else None,
                            filename=f"batch/{filename}",
                            original_filename=filename,
                            file_path=file_path,
                            status='pending'
                        )
                        db.session.add(new_upload)
                        db.session.commit()

                        try:
                            resume_text = extract_text(file_path)

                            if resume_text:
                                jd_text = job.description if job else ""
                                result = analyze_single_resume(
                                    resume_text,
                                    filename=filename,
                                    custom_jd=jd_text
                                )

                                analysis = CandidateAnalysis.query.filter_by(upload_id=new_upload.id).first()
                                if not analysis:
                                    analysis = CandidateAnalysis(upload_id=new_upload.id)
                                    db.session.add(analysis)

                                # Use correct keys from AnalysisResult
                                analysis.total_score = result.get('match_score', 0)
                                analysis.technical_skills_score = result.get('skill_score', 0)
                                analysis.industry_relevance_score = result.get('content_score', 0)
                                analysis.experience_score = result.get('experience_years', 0)  # Correct key for experience_score
                                analysis.reasoning_summary = result.get('reasoning', '')
                                analysis.key_strengths = json.dumps(result.get('found_skills', []))
                                analysis.concerns = json.dumps(result.get('missing_skills', []))

                                # Save extracted contact/profile info
                                new_upload.extracted_email = result.get('email', '')
                                new_upload.extracted_phone = result.get('phone', '')
                                new_upload.extracted_education = result.get('education', '')
                                new_upload.extracted_experience_years = result.get('experience_years', 0)

                                new_upload.status = 'analyzed'
                                db.session.commit()

                                # Only count as processed after successful extraction + analysis.
                                extracted_files.append(new_upload)
                            else:
                                new_upload.status = 'failed'
                                db.session.commit()

                        except Exception as parse_e:
                            print(f"Error parsing {filename}: {parse_e}")
                            db.session.rollback()
                            try:
                                new_upload.status = 'failed'
                                db.session.commit()
                            except Exception:
                                db.session.rollback()

        except zipfile.BadZipFile:
            print("Invalid ZIP archive provided.")

        finally:
            if os.path.exists(zip_path):
                os.remove(zip_path)

        payload = {
            "event": "batch_processing_complete",
            "hr_user_id": hr_user_id,
            "job_id": job_id,
            "resumes_processed": len(extracted_files)
        }
        trigger_webhook(webhook_url, payload)


def start_batch_processing(app_instance, zip_path, hr_user_id, job_id, webhook_url=None):
    thread = threading.Thread(
        target=process_batch_upload,
        args=(app_instance, zip_path, hr_user_id, job_id, webhook_url)
    )
    thread.daemon = True
    thread.start()
