from flask import Flask, render_template, request, redirect
from datetime import datetime
import os

app = Flask(__name__)

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
        # Extract form data
        vehicle = request.form["vehicle"]
        spot = int(request.form["spot"])
        duration = request.form["duration"]
        name = request.form["name"].strip()
        phone = request.form["phone"].strip()
        plate = request.form["plate"].strip()

        # Validate (simple server-side check)
        if not (name and phone and plate):
            return "Missing required fields", 400

        # Log or later: save to DB
        print("NEW RESERVATION:")
        print(vehicle, spot, duration, name, phone, plate)

        # Get PayPal URL
        key = (vehicle, duration)
        paypal_url = PAYPAL_LINKS.get(key)

        if not paypal_url:
            return "Invalid selection", 400

        return redirect(paypal_url)

    return render_template("index.html")

if __name__ == '__main__':
    app.run(debug=True)
