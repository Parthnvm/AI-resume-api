"""
Bulk migration: import all existing SmartHire users (with bcrypt password hashes)
into Firebase Auth using the Firebase Admin SDK.

Prerequisites:
  1. pip install firebase-admin
  2. Download your Firebase Service Account JSON:
       Firebase Console → Project Settings → Service Accounts → Generate new private key
  3. Save it as  firebase-service-account.json  in this project root
  4. Make sure FIREBASE_API_KEY is set in .env (for the REST helper)

Run:
  python migrate_users_to_firebase.py
"""

import os
import sys
import sqlite3

# ── Load .env ────────────────────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv()

SERVICE_ACCOUNT_PATH = os.path.join(os.path.dirname(__file__), 'firebase-service-account.json')
DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'resume_shortlister.db')
SYSTEM_EMAILS = {'bulk@smarthire.internal'}          # skip synthetic users

# ── Validate paths ────────────────────────────────────────────────────────────
if not os.path.exists(SERVICE_ACCOUNT_PATH):
    print(
        "\n❌  firebase-service-account.json not found.\n"
        "   Download it from:\n"
        "   Firebase Console → Project Settings → Service Accounts → Generate new private key\n"
        "   Then save it as: firebase-service-account.json in this project root.\n"
    )
    sys.exit(1)

# ── Firebase Admin init ───────────────────────────────────────────────────────
import firebase_admin
from firebase_admin import credentials, auth as fb_auth

cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)
firebase_admin.initialize_app(cred)

# ── Load users from SQLite ────────────────────────────────────────────────────
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("""
    SELECT id, email, password_hash, first_name, last_name, firebase_uid
    FROM users
    WHERE firebase_uid IS NULL
""")
users = cur.fetchall()

if not users:
    print("✅  All users already have a firebase_uid. Nothing to migrate.")
    conn.close()
    sys.exit(0)

print(f"Found {len(users)} user(s) to migrate.\n")

# ── Build import payloads ─────────────────────────────────────────────────────
import_users = []
skip_system = []

for u in users:
    if u['email'] in SYSTEM_EMAILS:
        skip_system.append(u['email'])
        continue

    import_users.append(
        fb_auth.ImportUserRecord(
            uid=u['id'],                    # reuse our UUID as Firebase UID
            email=u['email'],
            display_name=f"{u['first_name']} {u['last_name']}",
            password_hash=u['password_hash'].encode('utf-8'),
        )
    )

if skip_system:
    print(f"  Skipping system accounts: {', '.join(skip_system)}")

if not import_users:
    print("Nothing left to import after skipping system accounts.")
    conn.close()
    sys.exit(0)

# ── Import in batches of 1000 (Firebase limit) ───────────────────────────────
BATCH = 1000
succeeded = 0
failed = []

for i in range(0, len(import_users), BATCH):
    batch = import_users[i:i + BATCH]
    result = fb_auth.import_users(
        batch,
        hash_alg=fb_auth.UserImportHash.bcrypt(),
    )
    succeeded += result.success_count
    for err in result.errors:
        failed.append({
            'index': i + err.index,
            'email': batch[err.index].email,
            'reason': str(err.reason),
        })

print(f"\n  ✅  Imported: {succeeded}")
if failed:
    print(f"  ❌  Failed:   {len(failed)}")
    for f in failed:
        print(f"       [{f['index']}] {f['email']}: {f['reason']}")

# ── Back-fill firebase_uid in local DB ───────────────────────────────────────
print("\nUpdating local database with firebase_uid values...")
updated = 0
for u in import_users:
    # We used our own UUID as the Firebase UID, so they match
    cur.execute(
        "UPDATE users SET firebase_uid = ? WHERE id = ?",
        (u.uid, u.uid)
    )
    if cur.rowcount:
        updated += 1

conn.commit()
conn.close()

print(f"  ✅  Local DB updated: {updated} user(s).")
print("\nMigration complete! All users can now log in via Firebase.")
print("Their existing passwords still work — no reset required.")
