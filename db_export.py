#!/usr/bin/env python3
"""
db_export.py — Export all local user and job data to a JSON seed file.
Run this locally, then commit db_seed.json and run db_import.py on Render.

Usage:
    python db_export.py
    -> creates db_seed.json in the project root
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from app import create_app, db
from app.models import User, JobDescription

app = create_app()

with app.app_context():
    users = User.query.all()
    jobs = JobDescription.query.all()

    data = {
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "password_hash": u.password_hash,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "user_type": u.user_type,
                "is_active": u.is_active,
                "api_key": u.api_key,
                "firebase_uid": u.firebase_uid,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ],
        "job_descriptions": [
            {
                "id": j.id,
                "hr_id": j.hr_id,
                "title": j.title,
                "description": j.description,
                "is_active": j.is_active,
                "created_at": j.created_at.isoformat() if j.created_at else None,
            }
            for j in jobs
        ],
    }

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db_seed.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"✅ Exported {len(data['users'])} users and {len(data['job_descriptions'])} jobs → db_seed.json")
    print("Next: commit db_seed.json, push to GitHub, then run python db_import.py on Render Shell.")
