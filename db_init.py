import sqlite3
from datetime import datetime

# 1. Connect (will create the file if missing)
DB_PATH = "db/parking.db"
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# 2. Drop old tables if they exist
c.execute("DROP TABLE IF EXISTS spots")
c.execute("DROP TABLE IF EXISTS users")

# 3. Recreate spots table with TEXT IDs
c.execute("""
CREATE TABLE spots (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    assigned_to TEXT,
    reserved_at DATETIME,
    release_at DATETIME
)
""")

# 4. Recreate users table (with new gate columns)
c.execute("""
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    plate TEXT NOT NULL,
    vehicle TEXT NOT NULL,        -- will hold 'small','medium','large'
    spot TEXT NOT NULL,           -- e.g. 'S1','M5','B12'
    duration TEXT NOT NULL,       -- 'monthly' or 'yearly'
    submitted_at DATETIME NOT NULL,
    confirmed INTEGER DEFAULT 0,
    confirmed_at DATETIME,
    release_at DATETIME,
    gate_added INTEGER DEFAULT 0,
    gate_slot INTEGER
)
""")

# 5. Seed the spots rows
small_ids  = [f"S{i}" for i in range(1,5)]
medium_ids = [f"M{i}" for i in range(1,20)]
large_ids  = [f"B{i}" for i in range(1,24)]
for spot_id in (small_ids + medium_ids + large_ids):
    c.execute("INSERT INTO spots (id, status) VALUES (?, 'available')", (spot_id,))

conn.commit()
conn.close()
print("✅ Database initialized with spots S1–S4, M1–M19, B1–B23")
