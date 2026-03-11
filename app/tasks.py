import os
import json
import zipfile
import threading
import requests
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
        hr_user = User.query.get(hr_user_id)
        job = JobDescription.query.get(job_id) if job_id else None

        extracted_files = []
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                upload_folder = current_app.config['UPLOAD_FOLDER']

                batch_folder = os.path.join(upload_folder, f"batch_{os.path.basename(zip_path).split('.')[0]}")
                os.makedirs(batch_folder, exist_ok=True)

                for file_info in zip_ref.infolist():
                    if file_info.filename.endswith('.pdf') and not file_info.filename.startswith('__MACOSX'):
                        filename = secure_filename(os.path.basename(file_info.filename))
                        if not filename:
                            continue

                        file_path = os.path.join(batch_folder, filename)

                        with open(file_path, 'wb') as f:
                            f.write(zip_ref.read(file_info.filename))

                        # Use or create a generic bulk candidate user
                        bulk_user = User.query.filter_by(email='bulk@apexhire.internal').first()
                        if not bulk_user:
                            bulk_user = User(
                                email='bulk@apexhire.internal',
                                password_hash='noop',
                                first_name='Bulk',
                                last_name='Upload',
                                user_type='student'
                            )
                            db.session.add(bulk_user)
                            db.session.commit()

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

                        extracted_files.append(new_upload)

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
                                analysis.experience_score = result.get('content_score', 0)
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

                        except Exception as parse_e:
                            print(f"Error parsing {filename}: {parse_e}")

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
