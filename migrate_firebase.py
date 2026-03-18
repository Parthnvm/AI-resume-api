"""
Migration: add firebase_uid column to users table.
Safe to re-run.
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'resume_shortlister.db')

def migrate():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute('ALTER TABLE users ADD COLUMN firebase_uid TEXT')
        print('  Added column: firebase_uid')
    except sqlite3.OperationalError as e:
        if 'duplicate column' in str(e).lower():
            print('  Column already exists (skipped): firebase_uid')
        else:
            raise
    conn.commit()
    conn.close()
    print('Migration complete.')

if __name__ == '__main__':
    migrate()
