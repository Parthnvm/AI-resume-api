#!/usr/bin/env python3
"""
db_import.py — Import users and jobs from db_seed.json into the production DB.
Run this ONCE on Render Shell after deploying.

Usage (on Render Shell):
    python db_import.py
"""
import json
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from app import create_app, db
from app.models import User, JobDescription

app = create_app()

seed_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db_seed.json")

if not os.path.exists(seed_path):
    print("❌ db_seed.json not found. Run db_export.py locally first, then push to GitHub.")
    sys.exit(1)

with open(seed_path, "r", encoding="utf-8") as f:
    data = json.load(f)

with app.app_context():
    db.create_all()

    users_added = 0
    for u in data.get("users", []):
        if User.query.get(u["id"]):
            print(f"  ⏭  User {u['email']} already exists — skipping.")
            continue
        user = User(
            id=u["id"],
            email=u["email"],
            password_hash=u["password_hash"],
            first_name=u["first_name"],
            last_name=u["last_name"],
            user_type=u["user_type"],
            is_active=u.get("is_active", True),
            api_key=u.get("api_key"),
            firebase_uid=u.get("firebase_uid"),
            created_at=datetime.fromisoformat(u["created_at"]) if u.get("created_at") else datetime.utcnow(),
        )
        db.session.add(user)
        users_added += 1

    jobs_added = 0
    for j in data.get("job_descriptions", []):
        if JobDescription.query.get(j["id"]):
            print(f"  ⏭  Job '{j['title']}' already exists — skipping.")
            continue
        # Only insert if the HR user exists
        if not User.query.get(j["hr_id"]):
            print(f"  ⚠️  HR user {j['hr_id']} not found for job '{j['title']}' — skipping.")
            continue
        job = JobDescription(
            id=j["id"],
            hr_id=j["hr_id"],
            title=j["title"],
            description=j["description"],
            is_active=j.get("is_active", True),
            created_at=datetime.fromisoformat(j["created_at"]) if j.get("created_at") else datetime.utcnow(),
        )
        db.session.add(job)
        jobs_added += 1

    db.session.commit()
    print(f"\n✅ Import complete: {users_added} users and {jobs_added} jobs added to the production database.")
