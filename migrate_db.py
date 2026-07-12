"""
migrate_db.py
─────────────────────────────────────────────────────────────
Run this ONCE to add the `password_set` column to the existing
`mentors` table.

Usage (from the project root):
    python migrate_db.py

Safe to run multiple times — it detects if the column already
exists and skips the migration if so.
"""

import sqlite3, os

# ── Locate the database ────────────────────────────────────────
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH  = os.path.join(BASE_DIR, 'empower.db')

if not os.path.exists(DB_PATH):
    print(f"❌  Database not found at: {DB_PATH}")
    print("    Make sure you run this script from the same folder as app.py")
    raise SystemExit(1)

conn = sqlite3.connect(DB_PATH)
cur  = conn.cursor()

# ── Check whether the column already exists ────────────────────
cur.execute("PRAGMA table_info(mentors)")
columns = [row[1] for row in cur.fetchall()]

if 'password_set' in columns:
    print("✅  Column 'password_set' already exists — nothing to do.")
    conn.close()
    raise SystemExit(0)

# ── Add the new column ─────────────────────────────────────────
print("🔧  Adding column 'password_set' to mentors table …")
cur.execute("""
    ALTER TABLE mentors
    ADD COLUMN password_set INTEGER NOT NULL DEFAULT 0
""")

# ── Back-fill: any mentor who already has a password_hash
#    is treated as having completed setup (password_set = 1)
cur.execute("""
    UPDATE mentors
    SET password_set = 1
    WHERE password_hash IS NOT NULL AND password_hash != ''
""")

conn.commit()
conn.close()

# ── Report ─────────────────────────────────────────────────────
print("✅  Migration complete.")
print()
print("   • 'password_set' added with default 0 (False).")
print("   • Existing mentors with a password_hash → set to 1 (True)")
print("     so they can log in normally without being forced to")
print("     re-create their password.")
print()
print("You can now restart app.py normally.")