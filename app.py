import datetime
import os

from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from database.db import add_expense as db_add_expense, create_user, get_db, get_user_by_email, init_db, seed_db
from database.queries import get_user_by_id, get_summary_stats, get_recent_transactions, get_category_breakdown

CATEGORIES = ["Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other"]

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret')

with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def _valid_date(s):
    if not s:
        return None
    try:
        datetime.date.fromisoformat(s)
        return s
    except ValueError:
        return None


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

    user_id = session["user_id"]
    date_from = _valid_date(request.args.get("from"))
    date_to = _valid_date(request.args.get("to"))

    # ---- SA2: user dict ------------------------------------------ #
    user_row = get_user_by_id(user_id)
    if user_row is None:
        session.clear()
        return redirect(url_for("login"))
    initials = "".join(w[0].upper() for w in user_row["name"].split())[:2]
    user = {**user_row, "initials": initials}
    # ---- end SA2 ------------------------------------------------- #

    # ---- SA2: stats dict ----------------------------------------- #
    stats = get_summary_stats(user_id, date_from=date_from, date_to=date_to)
    # ---- end SA2 ------------------------------------------------- #

    # ---- SA1: transactions list ----------------------------------- #
    transactions = get_recent_transactions(user_id, date_from=date_from, date_to=date_to)
    # ---- end SA1 ------------------------------------------------- #

    # ---- SA3: categories list ------------------------------------ #
    categories = get_category_breakdown(user_id, date_from=date_from, date_to=date_to)
    # ---- end SA3 ------------------------------------------------- #

    return render_template("profile.html",
                           user=user, stats=stats,
                           transactions=transactions, categories=categories,
                           date_from=date_from, date_to=date_to)


@app.route("/analytics")
def analytics():
    if not session.get("user_id"):
        return redirect(url_for("login"))
    return render_template("analytics.html")


@app.route("/expenses/add", methods=["GET", "POST"])
def add_expense():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    if request.method == "POST":
        amount_raw = request.form.get("amount", "").strip()
        category = request.form.get("category", "").strip()
        date_raw = request.form.get("date", "").strip()
        description = request.form.get("description", "").strip() or None
        form = dict(amount=amount_raw, category=category, date=date_raw, description=description or "")

        try:
            amount = float(amount_raw)
            if amount <= 0:
                raise ValueError
        except ValueError:
            flash("Amount must be a positive number.", "error")
            return render_template("add_expense.html", categories=CATEGORIES, form=form)

        if category not in CATEGORIES:
            flash("Please select a valid category.", "error")
            return render_template("add_expense.html", categories=CATEGORIES, form=form)

        if not _valid_date(date_raw):
            flash("Date must be a valid date (YYYY-MM-DD).", "error")
            return render_template("add_expense.html", categories=CATEGORIES, form=form)

        db_add_expense(session["user_id"], amount, category, date_raw, description)
        flash("Expense added successfully.", "success")
        return redirect(url_for("profile"))

    return render_template("add_expense.html", categories=CATEGORIES, form={})


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
