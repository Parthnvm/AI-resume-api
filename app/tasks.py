import os
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
    Creates a dummy student profile for each parsed resume if needed,
    or attaches them to a single generated profile.
    """
    with app_instance.app_context():
        # Fetch the HR User and Job context inside the application context
        hr_user = User.query.get(hr_user_id)
        job = JobDescription.query.get(job_id) if job_id else None
        
        extracted_files = []
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                upload_folder = current_app.config['UPLOAD_FOLDER']
                
                # Create a batch subfolder to avoid collisions
                batch_folder = os.path.join(upload_folder, f"batch_{os.path.basename(zip_path).split('.')[0]}")
                os.makedirs(batch_folder, exist_ok=True)
                
                for file_info in zip_ref.infolist():
                    if file_info.filename.endswith('.pdf') and not file_info.filename.startswith('__MACOSX'):
                        filename = secure_filename(os.path.basename(file_info.filename))
                        if not filename: continue
                        
                        file_path = os.path.join(batch_folder, filename)
                        
                        # Extract file
                        with open(file_path, 'wb') as f:
                            f.write(zip_ref.read(file_info.filename))
                            
                        # Here, we can create a generic 'student' profile for bulk uploaded resumes 
                        # or bind them to the HR user temporarily. To simulate an actual system, 
                        # we'll bind it to a systemic "Bulk Candidate" user, or generate an anonymous one.
                        
                        # Let's search for an anonymous Bulk User or create one
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
                        
                        # Create Upload Record
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
                        
                        # Attempt Extraction & Analysis
                        try:
                            resume_text = extract_text(file_path)
                            
                            if job and resume_text:
                                analysis_result = analyze_single_resume(resume_text, job.description)
                                
                                analysis = CandidateAnalysis(
                                    upload_id=new_upload.id,
                                    job_description_id=job.id,
                                    total_score=analysis_result['total_score'],
                                    technical_skills_score=analysis_result['technical_skills_score'],
                                    experience_score=analysis_result['experience_score'],
                                    reasoning_summary=analysis_result['reasoning_summary'],
                                    key_strengths=str(analysis_result['key_strengths']),
                                    concerns=str(analysis_result['concerns'])
                                )
                                db.session.add(analysis)
                                new_upload.status = 'analyzed'
                                db.session.commit()
                        except Exception as parse_e:
                            print(f"Error parsing {filename}: {parse_e}")
                            
        except zipfile.BadZipFile:
            print("Invalid ZIP archive provided.")
            
        finally:
            # Clean up the original uploaded zip
            if os.path.exists(zip_path):
                os.remove(zip_path)
                
        # Fire Webhook when batch finishes
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
