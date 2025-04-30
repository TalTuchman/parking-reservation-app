import sqlite3
from datetime import datetime, timedelta

DB_PATH = "db/parking.db"

def connect_db():
    return sqlite3.connect(DB_PATH)

from flask import Flask, render_template, request, redirect, url_for, session
from flask import Markup  # Optional for injecting HTML snippets
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = "mysecretkey"  # Needed for sessions

# Payment links
PAYPAL_LINKS = {
    ("Scooter", "monthly"): "https://www.paypal.com/ncp/payment/Z36BVWDZMMR76",
    ("Scooter", "yearly"): "https://www.paypal.com/ncp/payment/P9NECY7EPU8NC",
    ("Motorcycle", "monthly"): "https://www.paypal.com/ncp/payment/W57XB9B4SM4UA",
    ("Motorcycle", "yearly"): "https://www.paypal.com/ncp/payment/9CQPHZP79DAQ4"
}

@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
    # 1. Extract form data
        vehicle = request.form["vehicle"]
        spot = int(request.form["spot"])
        duration = request.form["duration"]
        name = request.form["name"].strip()
        phone = request.form["phone"].strip()
        plate = request.form["plate"].strip()

    # 2. Validate required fields
        if not (name and phone and plate):
            return "Missing required fields", 400

    # 3. Connect to the database
        conn = connect_db()
        c = conn.cursor()

        now = datetime.now()
        release = now + timedelta(hours=24)

    # 4. Update spot as temporarily reserved
        c.execute("UPDATE spots SET status = 'reserved', assigned_to = ?, reserved_at = ?, release_at = ? WHERE id = ?", 
                    (name, now, release, spot))

    # 5. Save user reservation
        c.execute('''INSERT INTO users 
            (name, phone, plate, vehicle, spot, duration, submitted_at, release_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (name, phone, plate, vehicle, spot, duration, now, release))

        conn.commit()
        conn.close()

    # 6. Redirect to the correct PayPal link
        key = (vehicle, duration)
        paypal_url = PAYPAL_LINKS.get(key)

        if not paypal_url:
            return "Invalid selection", 400

        return redirect(paypal_url)

        

    return render_template("index.html")

@app.route("/admin")
def admin():
    cleanup_expired_reservations()  # auto-release expired holds
    
    conn = connect_db()
    c = conn.cursor()

    # Get all reservations (ordered: newest first)
    c.execute('''
        SELECT users.id, name, phone, plate, vehicle, spot, duration, 
               submitted_at, confirmed, confirmed_at, release_at
        FROM users
        ORDER BY submitted_at DESC
    ''')
    reservations = c.fetchall()

    # Get all spots
    c.execute('''
        SELECT id, status, assigned_to, release_at
        FROM spots
        ORDER BY id ASC
    ''')
    spots = c.fetchall()

    conn.close()

    return render_template("admin.html", reservations=reservations, spots=spots)

@app.route("/confirm/<int:user_id>", methods=["POST"])
def confirm_payment(user_id):
    conn = connect_db()
    c = conn.cursor()

    # Get user's subscription duration and spot
    c.execute("SELECT duration, spot FROM users WHERE id = ?", (user_id,))
    row = c.fetchone()

    if row:
        duration, spot = row
        now = datetime.now()
        release_at = now + timedelta(days=30 if duration == "monthly" else 365)

        # Update user
        c.execute("UPDATE users SET confirmed = 1, confirmed_at = ?, release_at = ? WHERE id = ?", 
                  (now, release_at, user_id))

        # Update spot
        c.execute("UPDATE spots SET status = 'occupied', release_at = ? WHERE id = ?", 
                  (release_at, spot))

    conn.commit()
    conn.close()
    return redirect(url_for("admin"))

@app.route("/release/<int:spot_id>", methods=["POST"])
def release_spot(spot_id):
    conn = connect_db()
    c = conn.cursor()

    # Free the spot
    c.execute("UPDATE spots SET status = 'available', assigned_to = NULL, reserved_at = NULL, release_at = NULL WHERE id = ?", (spot_id,))

    # Optionally update users table (not mandatory unless you want to show it)
    c.execute("UPDATE users SET release_at = datetime('now') WHERE spot = ? AND confirmed = 1", (spot_id,))

    conn.commit()
    conn.close()
    return redirect(url_for("admin"))

@app.route("/lang/<lang_code>")
def change_language(lang_code):
    if lang_code in ["el", "en"]:
        session["lang"] = lang_code
    return redirect("/")


def cleanup_expired_reservations():
    now = datetime.now()
    conn = connect_db()
    c = conn.cursor()

    # Find expired, unconfirmed reservations
    c.execute('''
        SELECT u.id, u.spot FROM users u
        JOIN spots s ON u.spot = s.id
        WHERE u.confirmed = 0 AND u.release_at <= ?
    ''', (now,))
    expired = c.fetchall()

    for user_id, spot_id in expired:
        # Clear user and free spot
        c.execute("UPDATE spots SET status = 'available', assigned_to = NULL, reserved_at = NULL, release_at = NULL WHERE id = ?", (spot_id,))
        c.execute("DELETE FROM users WHERE id = ?", (user_id,))

    conn.commit()
    conn.close()


if __name__ == '__main__':
    app.run(debug=True)
