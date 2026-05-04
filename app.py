import os

from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from database.db import create_user, get_db, get_user_by_email, get_user_by_id, init_db, seed_db

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret')

with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    if session.get("user_id"):
        return redirect(url_for("profile"))
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("profile"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if not all([name, email, password, confirm_password]):
            flash("All fields are required.", "error")
            return render_template("register.html")

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("register.html")

        if get_user_by_email(email):
            flash("An account with that email already exists.", "error")
            return render_template("register.html")

        create_user(name, email, password)
        flash("Account created! Please sign in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("profile"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()

        if not email or not password:
            flash("Email and password are required.", "error")
            return render_template("login.html")

        user = get_user_by_email(email)
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Invalid email or password.", "error")
            return render_template("login.html")

        session["user_id"] = user["id"]
        return redirect(url_for("profile"))

    return render_template("login.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))


@app.route("/profile")
def profile():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user = {
        "name": "Alex Morgan",
        "email": "alex@example.com",
        "member_since": "January 2024",
        "initials": "AM",
    }
    stats = {
        "total_spent": 321.00,
        "transaction_count": 8,
        "top_category": "Bills",
    }
    transactions = [
        {"date": "May 20, 2026", "description": "Miscellaneous",     "category": "Other",         "amount": 25.00},
        {"date": "May 17, 2026", "description": "Coffee and snacks", "category": "Food",          "amount": 8.50},
        {"date": "May 13, 2026", "description": "New shoes",         "category": "Shopping",      "amount": 65.00},
        {"date": "May 10, 2026", "description": "Movie ticket",      "category": "Entertainment", "amount": 15.00},
        {"date": "May 08, 2026", "description": "Vitamins",          "category": "Health",        "amount": 30.00},
        {"date": "May 05, 2026", "description": "Electric bill",     "category": "Bills",         "amount": 120.00},
        {"date": "May 03, 2026", "description": "Bus pass",          "category": "Transport",     "amount": 12.00},
        {"date": "May 01, 2026", "description": "Grocery shopping",  "category": "Food",          "amount": 45.50},
    ]
    categories = [
        {"name": "Bills",         "total": 120.00, "pct": 37},
        {"name": "Shopping",      "total": 65.00,  "pct": 20},
        {"name": "Food",          "total": 54.00,  "pct": 17},
        {"name": "Other",         "total": 25.00,  "pct": 8},
        {"name": "Health",        "total": 30.00,  "pct": 9},
        {"name": "Entertainment", "total": 15.00,  "pct": 5},
        {"name": "Transport",     "total": 12.00,  "pct": 4},
    ]
    return render_template("profile.html",
                           user=user, stats=stats,
                           transactions=transactions, categories=categories)


@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
