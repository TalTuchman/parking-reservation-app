import sqlite3
from datetime import datetime

conn = sqlite3.connect("db/parking.db")
c = conn.cursor()

# Create spots table
c.execute('''
CREATE TABLE IF NOT EXISTS spots (
    id INTEGER PRIMARY KEY,
    status TEXT CHECK(status IN ('available', 'reserved', 'occupied')) NOT NULL DEFAULT 'available',
    assigned_to TEXT,
    reserved_at DATETIME,
    release_at DATETIME
)
''')

# Create users table
c.execute('''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    plate TEXT NOT NULL,
    vehicle TEXT NOT NULL,
    spot INTEGER NOT NULL,
    duration TEXT CHECK(duration IN ('monthly', 'yearly')) NOT NULL,
    confirmed INTEGER DEFAULT 0,
    submitted_at DATETIME,
    confirmed_at DATETIME,
    release_at DATETIME
)
''')

# Initialize 71 spots
for i in range(1, 72):
    c.execute("INSERT OR IGNORE INTO spots (id, status) VALUES (?, 'available')", (i,))

conn.commit()
conn.close()
print("Database initialized.")
