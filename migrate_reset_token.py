"""
One-off migration: add reset_token_hash and reset_token_expiry columns to the users table.
Safe to re-run — duplicate-column errors are caught and ignored.
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'resume_shortlister.db')

def migrate():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    for col, dtype in [
        ('reset_token_hash',   'TEXT'),
        ('reset_token_expiry', 'DATETIME'),
    ]:
        try:
            cur.execute(f'ALTER TABLE users ADD COLUMN {col} {dtype}')
            print(f'  Added column: {col}')
        except sqlite3.OperationalError as e:
            if 'duplicate column' in str(e).lower():
                print(f'  Column already exists (skipped): {col}')
            else:
                raise

    conn.commit()
    conn.close()
    print('Migration complete.')

if __name__ == '__main__':
    migrate()
