import sqlite3
import secrets
conn = sqlite3.connect('instance/resume_shortlister.db')
c = conn.cursor()
try:
    c.execute('ALTER TABLE users ADD COLUMN api_key VARCHAR(64)')
    c.execute('CREATE UNIQUE INDEX ix_users_api_key ON users(api_key)')
except Exception as e:
    print("Alter table error:", e)
    
try:
    c.execute('SELECT id FROM users WHERE api_key IS NULL')
    rows = c.fetchall()
    for r in rows:
        c.execute('UPDATE users SET api_key=? WHERE id=?', (secrets.token_urlsafe(32), r[0]))
    conn.commit()
    print("Migration completed.")
except Exception as e:
    print("Update error:", e)
finally:
    conn.close()
