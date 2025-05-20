from dotenv import load_dotenv
load_dotenv()

import os, sqlite3
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash

DB_PATH = "db/parking.db"
def connect_db(): return sqlite3.connect(DB_PATH)

app = Flask(__name__)
app.secret_key = "mysecretkey"

# ──────────────────────────────────────────────────────────────
#  Pricing + PayPal placeholders
# ──────────────────────────────────────────────────────────────
PRICES = {
    ("small",  "monthly"): 35,
    ("small",  "yearly") : 378,
    ("medium", "monthly"): 45,
    ("medium", "yearly") : 486,
    ("large",  "monthly"): 50,
    ("large",  "yearly") : 540,
}

PAYPAL_LINKS = {          # <----- replace with real links later
    ("small",  "monthly"): "https://paypal.small.monthly",
    ("small",  "yearly") : "https://paypal.small.yearly",
    ("medium", "monthly"): "https://paypal.medium.monthly",
    ("medium", "yearly") : "https://paypal.medium.yearly",
    ("large",  "monthly"): "https://paypal.large.monthly",
    ("large",  "yearly") : "https://paypal.large.yearly",
}

SPOT_POOLS = {
    "small" : [f"S{i}" for i in range(1,5)],                 # S1-S4
    "medium": [f"M{i}" for i in range(1,20)],                # M1-M19
    "large" : [f"B{i}" for i in range(1,24)],                # B1-B23
}

# ──────────────────────────────────────────────────────────────
#  HOME  (reserve)
# ──────────────────────────────────────────────────────────────
@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        # ── 1. extract
        size      = request.form["size"]               # small / medium / large
        spot      = request.form["spot"].strip()       # e.g. "M7"
        duration  = request.form["duration"]           # monthly / yearly
        name      = request.form["name"].strip()
        phone     = request.form["phone"].strip()
        plate     = request.form["plate"].strip()

        if not (name and phone and plate):
            return "Missing required fields", 400

        # ── 2. validate spot in correct (or fallback) pool & availability
        valid_pool = SPOT_POOLS[size]
        # allow spot from higher tier if pool empty
        if spot not in valid_pool:
            if size == "small"  : valid_pool += SPOT_POOLS["medium"]
            if size == "medium" : valid_pool += SPOT_POOLS["large"]
        if spot not in valid_pool:
            return "Invalid spot", 400

        conn = connect_db(); c = conn.cursor()
        # ensure spot still available in DB
        c.execute("SELECT status FROM spots WHERE id = ?", (spot,))
        row = c.fetchone()
        if not row or row[0] != "available":
            conn.close(); return "Spot no longer available", 400

        # ── 3. reserve for 24 h
        now, release = datetime.now(), datetime.now() + timedelta(hours=24)
        c.execute("UPDATE spots SET status='reserved', assigned_to=?, reserved_at=?, release_at=? WHERE id=?",
                  (name, now, release, spot))
        c.execute("""INSERT INTO users
                     (name, phone, plate, vehicle, spot, duration, submitted_at, release_at)
                     VALUES (?,?,?,?,?,?,?,?)""",
                  (name, phone, plate, size, spot, duration, now, release))
        conn.commit(); conn.close()

        paypal_url = PAYPAL_LINKS.get((size, duration))
        if not paypal_url: return "Payment link not configured", 500
        return redirect(paypal_url)

    # ── Render GET
    conn = connect_db(); c = conn.cursor()
    c.execute("SELECT id FROM spots WHERE status!='available'")
    unavailable = [row[0] for row in c.fetchall()]
    conn.close()

    lang = session.get("lang", "el")
    return render_template("index.html", lang=lang, unavailable_spots=unavailable)

# ──────────────────────────────────────────────────────────────
#  (Admin, gate, analytics, login, cleanup)  – unchanged except
#  the income queries now reference the new pricing table
# ──────────────────────────────────────────────────────────────
def price_sql_case(prefix=""):
    return f"""
        CASE
            WHEN duration='monthly' AND vehicle='small'  THEN {PRICES[('small','monthly')]}
            WHEN duration='yearly'  AND vehicle='small'  THEN {PRICES[('small','yearly')]}
            WHEN duration='monthly' AND vehicle='medium' THEN {PRICES[('medium','monthly')]}
            WHEN duration='yearly'  AND vehicle='medium' THEN {PRICES[('medium','yearly')]}
            WHEN duration='monthly' AND vehicle='large'  THEN {PRICES[('large','monthly')]}
            WHEN duration='yearly'  AND vehicle='large'  THEN {PRICES[('large','yearly')]}
            ELSE 0 END {prefix}
    """

from flask import flash   # already imported earlier

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        if username == os.getenv("ADMIN_USERNAME") and password == os.getenv("ADMIN_PASSWORD"):
            session["admin_logged_in"] = True
            return redirect(url_for("admin"))
        flash("Invalid credentials", "error")
        return redirect(url_for("login"))
    return render_template("login.html")

@app.route("/admin")
def admin():
    if not session.get("admin_logged_in"): return redirect(url_for("login"))
    cleanup_expired_reservations()

    conn = connect_db(); c = conn.cursor()
    # reservations
    c.execute("""SELECT id,name,phone,plate,vehicle,spot,duration,
                        submitted_at,confirmed,confirmed_at,release_at,
                        gate_added,gate_slot
                 FROM users ORDER BY submitted_at DESC""")
    reservations = c.fetchall()
    # spots
    c.execute("SELECT id,status,assigned_to,release_at FROM spots ORDER BY id")
    spots = c.fetchall()
    # analytics
    c.execute("SELECT COUNT(*) FROM spots WHERE status='available'"); available = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM spots WHERE status='occupied'");  occupied  = c.fetchone()[0]
    c.execute(f"SELECT SUM({price_sql_case()}) FROM users WHERE confirmed=1")
    total_income = c.fetchone()[0] or 0
    c.execute(f"""SELECT strftime('%Y-%m',confirmed_at) m, SUM({price_sql_case()})
                  FROM users WHERE confirmed=1 GROUP BY m ORDER BY m DESC""")
    monthly_income = c.fetchall()
    c.execute(f"""SELECT name,phone, SUM({price_sql_case()})
                  FROM users WHERE confirmed=1 GROUP BY name,phone ORDER BY 3 DESC""")
    user_income = c.fetchall()
    c.execute(f"""SELECT spot, SUM({price_sql_case()})
                  FROM users WHERE confirmed=1 GROUP BY spot ORDER BY spot""")
    spot_income = c.fetchall()
    conn.close()

    return render_template("admin.html",
        reservations=reservations, spots=spots,
        available_spots=available, occupied_spots=occupied,
        total_income=total_income, monthly_income=monthly_income,
        user_income=user_income, spot_income=spot_income)

@app.route("/lang/<lang_code>")
def change_language(lang_code):
    # accept only el / en
    if lang_code in ("el", "en"):
        session["lang"] = lang_code
    return redirect("/")

# ------------- existing gate access, payment confirmation, release,
#                language toggle, login/logout, cleanup keep unchanged --------------

# (keep your set_gate_access, confirm_payment, release_spot, login, logout, etc.)

if __name__ == "__main__":
    app.run(debug=True)
