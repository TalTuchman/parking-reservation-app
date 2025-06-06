from dotenv import load_dotenv
load_dotenv()
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session
#from flask import Markup  # Optional for injecting HTML snippets
import os

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "fallback-secret")

def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapped


DB_PATH = "db/parking.db"

def connect_db():
    return sqlite3.connect(DB_PATH)


PRICES = {
    ("small","monthly"): 35,  ("small","yearly"): 378,
    ("medium","monthly"):45,  ("medium","yearly"):486,
    ("large","monthly"): 50,  ("large","yearly"): 540,
}

PAYPAL_LINKS = {  # placeholders – fill real URLs later
    ("small","monthly") :"https://paypal.small.monthly",
    ("small","yearly")  :"https://paypal.small.yearly",
    ("medium","monthly"):"https://paypal.medium.monthly",
    ("medium","yearly") :"https://paypal.medium.yearly",
    ("large","monthly") :"https://paypal.large.monthly",
    ("large","yearly")  :"https://paypal.large.yearly",
}

SPOT_POOLS = {
    "small" : [f"S{i}" for i in range(1,5)],
    "medium": [f"M{i}" for i in range(1,20)],
    "large" : [f"B{i}" for i in range(1,24)],
}

# ─── after your PRICES, PAYPAL_LINKS, SPOT_POOLS dicts ───

def price_sql_case(alias=""):
    """
    Returns a SQL CASE expression mapping size+duration → price.
    If you pass alias="income", you’ll get "... END AS income".
    """
    return f"""
      CASE
        WHEN duration = 'monthly' AND vehicle = 'small'  THEN {PRICES[('small','monthly')]}
        WHEN duration = 'yearly'  AND vehicle = 'small'  THEN {PRICES[('small','yearly')]}
        WHEN duration = 'monthly' AND vehicle = 'medium' THEN {PRICES[('medium','monthly')]}
        WHEN duration = 'yearly'  AND vehicle = 'medium' THEN {PRICES[('medium','yearly')]}
        WHEN duration = 'monthly' AND vehicle = 'large'  THEN {PRICES[('large','monthly')]}
        WHEN duration = 'yearly'  AND vehicle = 'large'  THEN {PRICES[('large','yearly')]}
        ELSE 0
      END {alias}
    """

def _get_unavailable_spots():
    """
    Return a list of spot IDs (strings) whose status is NOT 'available'.
    Used by the index GET to filter out full spots.
    """
    conn = connect_db()
    c = conn.cursor()
    c.execute("SELECT id FROM spots WHERE status != 'available'")
    rows = [row[0] for row in c.fetchall()]
    conn.close()
    return rows

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        if (username == os.getenv("ADMIN_USERNAME")
            and password == os.getenv("ADMIN_PASSWORD")):
            session["admin_logged_in"] = True
            return redirect(url_for("admin"))
        flash("Invalid credentials", "error")
        return redirect(url_for("login"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("login"))
    
@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
    # 1. Extract form data
        size     = request.form["size"]           # "small", "medium" or "large"
        spot     = request.form["spot"].strip()   # e.g. "S1", "M5", "B12"
        duration = request.form["duration"]       # "monthly" or "yearly"
        name     = request.form["name"].strip()
        phone    = request.form["phone"].strip()
        plate    = request.form["plate"].strip()

    # 2. Validate required fields
        if not (name and phone and plate):
            return "Missing required fields", 400

    # 3. Validate spot is in the correct pool (or fallback to next tier)
        valid_pool = SPOT_POOLS[size].copy()
        if spot not in valid_pool:
            if size == "small":
                valid_pool += SPOT_POOLS["medium"]
            elif size == "medium":
                valid_pool += SPOT_POOLS["large"]
        if spot not in valid_pool:
            return "Invalid spot selection", 400

    # 4. Reserve in DB with a 24-hour hold
        conn = connect_db()
        c = conn.cursor()

        # 4a. Check it’s still available
        c.execute("SELECT status FROM spots WHERE id = ?", (spot,))
        row = c.fetchone()
        if not row or row[0] != "available":
            conn.close()
            return "Spot no longer available", 400

        now     = datetime.now()
        release = now + timedelta(hours=24)

        # 4b. Mark as temporarily reserved for 24h
        c.execute("""
            UPDATE spots
               SET status      = 'reserved',
                   assigned_to = ?,
                   reserved_at = ?,
                   release_at  = ?
             WHERE id = ?
        """, (name, now, release, spot))

        # 5. Save the user reservation
        c.execute("""
            INSERT INTO users
                (name, phone, plate, vehicle, spot, duration, submitted_at, release_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, phone, plate, size, spot, duration, now, release))

        conn.commit()
        conn.close()

        # 6. Redirect to PayPal
        paypal_url = PAYPAL_LINKS.get((size, duration))
        if not paypal_url:
            return "Payment link not configured", 500

        return redirect(paypal_url)

    # GET: render the form
    lang = session.get("lang", "el")
    unavailable = _get_unavailable_spots()  # or inline your query here
    return render_template("index.html", lang=lang, unavailable_spots=unavailable)

@app.route("/admin")
@login_required
def admin():
    cleanup_expired_reservations()
    conn = connect_db()
    c = conn.cursor()

    c.execute('''
    SELECT users.id, name, phone, plate, vehicle, spot, duration, 
           submitted_at, confirmed, confirmed_at, release_at,
           gate_added, gate_slot
    FROM users
    ORDER BY submitted_at DESC
    ''')
    reservations = c.fetchall()

    c.execute('''
    SELECT id, status, assigned_to, release_at
        FROM spots
        ORDER BY id ASC
    ''')
    spots = c.fetchall()

    # Spot usage
    c.execute("SELECT COUNT(*) FROM spots WHERE status = 'available'")
    available_spots = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM spots WHERE status = 'occupied'")
    occupied_spots = c.fetchone()[0]

    # Total income across all confirmed users
    c.execute(f"SELECT SUM({price_sql_case()}) FROM users WHERE confirmed = 1")
    total_income = c.fetchone()[0] or 0

    # Income per month
    c.execute(f"""
        SELECT strftime('%Y-%m', confirmed_at) AS month,
            SUM({price_sql_case()})
        FROM users
        WHERE confirmed = 1
    GROUP BY month
    ORDER BY month DESC
    """)
    monthly_income = c.fetchall()

    # Income per user
    c.execute(f"""
        SELECT name, phone,
            SUM({price_sql_case()}) AS income
        FROM users
        WHERE confirmed = 1
    GROUP BY name, phone
    ORDER BY income DESC
    """)
    user_income = c.fetchall()

    # Income per spot
    c.execute(f"""
        SELECT spot,
            SUM({price_sql_case()}) AS income
        FROM users
        WHERE confirmed = 1
    GROUP BY spot
    ORDER BY spot
    """)
    spot_income = c.fetchall()

    conn.close()

    return render_template("admin.html", 
        reservations=reservations,
        spots=spots,
        available_spots=available_spots,
        occupied_spots=occupied_spots,
        total_income=total_income,
        monthly_income=monthly_income,
        user_income=user_income,
        spot_income=spot_income
    )

@app.route("/set-gate-access/<int:user_id>", methods=["POST"])
def set_gate_access(user_id):
    slot = request.form.get("slot")
    
    try:
        slot = int(slot)
        if not (1 <= slot <= 200):
            raise ValueError("Invalid slot number")
    except:
        return "Invalid slot", 400

    conn = connect_db()
    c = conn.cursor()
    c.execute("UPDATE users SET gate_added = 1, gate_slot = ? WHERE id = ?", (slot, user_id))
    conn.commit()
    conn.close()
    return redirect(url_for("admin"))

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

@app.route("/release/<spot_id>", methods=["POST"])
def release_spot(spot_id):
    """
    spot_id is now a string like "S1", "M5", etc.
    """
    conn = connect_db()
    c = conn.cursor()

    # Free the spot
    c.execute("""
        UPDATE spots 
        SET status = 'available',
            assigned_to = NULL, 
            reserved_at = NULL, 
            release_at = NULL 
        WHERE id = ?
    """, (spot_id,))

    # Remove any confirmed user for that spot
    c.execute("""
        DELETE FROM users 
        WHERE spot = ? 
          AND confirmed = 1
    """, (spot_id,))

    conn.commit()
    conn.close()
    return redirect(url_for("admin"))

@app.route("/lang/<lang_code>")
def change_language(lang_code):
    if lang_code in ["el", "en"]:
        session["lang"] = lang_code
    return redirect("/")

from flask import flash

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
