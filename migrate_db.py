"""
migrate_db.py — One-time migration script.

Fixes the database schema after models.py changes:
  1. Renames  candidate_analyses.job_description_text → job_description
  2. No data is lost.

Run once:  python migrate_db.py
"""

import sqlite3
import os

DB_PATH = os.path.join("instance", "resume_shortlister.db")

if not os.path.exists(DB_PATH):
    print(f"Database not found at {DB_PATH}. Nothing to migrate.")
    raise SystemExit(0)

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# ── Check current columns ──────────────────────────────────────────────────────
cursor.execute("PRAGMA table_info(candidate_analyses)")
cols = {row[1] for row in cursor.fetchall()}
print("Current columns in candidate_analyses:", cols)

changes = []

# 1. Rename job_description_text → job_description (if not already done)
if "job_description_text" in cols and "job_description" not in cols:
    print("Renaming job_description_text → job_description ...")
    cursor.execute(
        "ALTER TABLE candidate_analyses RENAME COLUMN job_description_text TO job_description"
    )
    changes.append("Renamed job_description_text → job_description")
elif "job_description" in cols:
    print("job_description column already present — skipping rename.")
elif "job_description_text" not in cols and "job_description" not in cols:
    # Neither exists — add the column fresh
    print("Adding missing job_description column ...")
    cursor.execute("ALTER TABLE candidate_analyses ADD COLUMN job_description TEXT")
    changes.append("Added job_description column")

conn.commit()
conn.close()

if changes:
    print("\n✅ Migration complete. Changes applied:")
    for c in changes:
        print(f"   • {c}")
else:
    print("\n✅ Database already up-to-date. No changes needed.")
