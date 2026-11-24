import datetime
import math
import os

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash

from database.db import (
    add_credit as db_add_credit,
    add_expense as db_add_expense,
    create_user,
    delete_credit as db_delete_credit,
    delete_expense as db_delete_expense,
    get_credit,
    get_db,
    get_expense,
    get_user_by_email,
    init_db,
    seed_db,
    update_credit as db_update_credit,
    update_expense as db_update_expense,
)
from database.db import get_user_by_id as db_get_user_by_id
from database.queries import (
    get_user_by_id,
    get_summary_stats,
    get_recent_transactions,
    get_category_breakdown,
    get_recent_credits,
    count_credits,
)

CATEGORIES = [
    "Food",
    "Transport",
    "Bills",
    "Health",
    "Entertainment",
    "Shopping",
    "Other",
]
CREDIT_SOURCES = ["Salary", "Freelance", "Interest", "Refund", "Gift", "Other"]

# The dropdown that differs between the expense and credit forms.
EXPENSE_CHOICE = {
    "name": "category",
    "label": "Category",
    "placeholder": "Select a category",
    "options": CATEGORIES,
}
CREDIT_CHOICE = {
    "name": "source",
    "label": "Source",
    "placeholder": "Select a source",
    "options": CREDIT_SOURCES,
}

MIN_AMOUNT = 0.01
MAX_AMOUNT = 10_000_000  # ₹1 crore
MAX_DESCRIPTION_LENGTH = 200

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")

with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #


def _valid_date(s):
    """Return s unchanged if it is a canonical YYYY-MM-DD date, else None."""
    if not s:
        return None
    try:
        parsed = datetime.date.fromisoformat(s)
    except ValueError:
        return None
    # fromisoformat() also accepts forms like 20261124 and 2026-W48-2, which
    # would break text-based date comparisons in SQLite.
    return s if parsed.isoformat() == s else None


def _period_label(date_from, date_to):
    def fmt(value):
        day = datetime.date.fromisoformat(value)
        return f"{day:%b} {day.day}, {day.year}"

    if date_from and date_to:
        return f"{fmt(date_from)} – {fmt(date_to)}"
    if date_from:
        return f"From {fmt(date_from)}"
    if date_to:
        return f"Until {fmt(date_to)}"
    return "All time"


def _display_date(value):
    """Format an ISO date the same way as the profile rows."""
    day = datetime.date.fromisoformat(value)
    return f"{day:%B} {day.day}, {day.year}"


def _current_user_id():
    """Return the logged-in user's id, clearing sessions of deleted users."""
    user_id = session.get("user_id")
    if not user_id:
        return None
    if db_get_user_by_id(user_id) is None:
        session.clear()
        return None
    return user_id


def _entry_form_error(form, choice):
    """Return the first validation error for an expense or credit, or None."""
    try:
        amount = float(form["amount"])
    except ValueError:
        amount = math.nan

    if not math.isfinite(amount) or amount <= 0:
        return "Amount must be a positive number."
    if not MIN_AMOUNT <= amount <= MAX_AMOUNT:
        return "Amount must be between ₹0.01 and ₹1,00,00,000."
    if form[choice["name"]] not in choice["options"]:
        return f"Please select a valid {choice['name']}."
    if not _valid_date(form["date"]):
        return "Date must be a valid date (YYYY-MM-DD)."
    if len(form["description"]) > MAX_DESCRIPTION_LENGTH:
        return f"Description must be {MAX_DESCRIPTION_LENGTH} characters or fewer."
    return None


def _submitted_entry_form(choice):
    return {
        field: request.form.get(field, "").strip()
        for field in ("amount", choice["name"], "date", "description")
    }


def _render_entry_form(template, form, choice, **context):
    return render_template(
        template,
        choice=choice,
        form=form,
        min_amount=MIN_AMOUNT,
        max_amount=MAX_AMOUNT,
        max_description_length=MAX_DESCRIPTION_LENGTH,
        **context,
    )


@app.context_processor
def inject_current_user():
    user_id = session.get("user_id")
    return {"current_user": db_get_user_by_id(user_id) if user_id else None}


# ------------------------------------------------------------------ #
# Routes                                                             #
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
    user_id = _current_user_id()
    if user_id is None:
        return redirect(url_for("login"))

    date_from = _valid_date(request.args.get("from"))
    date_to = _valid_date(request.args.get("to"))

    # ---- SA2: user dict ------------------------------------------ #
    user_row = get_user_by_id(user_id)
    initials = "".join(w[0].upper() for w in user_row["name"].split())[:2]
    user = {**user_row, "initials": initials}
    # ---- end SA2 ------------------------------------------------- #

    # ---- SA2: stats dict ----------------------------------------- #
    stats = get_summary_stats(user_id, date_from=date_from, date_to=date_to)
    # ---- end SA2 ------------------------------------------------- #

    # ---- SA1: transactions list ----------------------------------- #
    transactions = get_recent_transactions(
        user_id, date_from=date_from, date_to=date_to
    )
    # ---- end SA1 ------------------------------------------------- #

    # ---- SA3: categories list ------------------------------------ #
    categories = get_category_breakdown(user_id, date_from=date_from, date_to=date_to)
    # ---- end SA3 ------------------------------------------------- #

    credits = get_recent_credits(user_id, date_from=date_from, date_to=date_to)
    credit_count = count_credits(user_id, date_from=date_from, date_to=date_to)

    return render_template(
        "profile.html",
        user=user,
        stats=stats,
        transactions=transactions,
        categories=categories,
        credits=credits,
        credit_count=credit_count,
        date_from=date_from,
        date_to=date_to,
        period_label=_period_label(date_from, date_to),
    )


@app.route("/analytics")
def analytics():
    if _current_user_id() is None:
        return redirect(url_for("login"))
    return render_template("analytics.html")


@app.route("/expenses/add", methods=["GET", "POST"])
def add_expense():
    user_id = _current_user_id()
    if user_id is None:
        return redirect(url_for("login"))

    if request.method == "POST":
        form = _submitted_entry_form(EXPENSE_CHOICE)
        error = _entry_form_error(form, EXPENSE_CHOICE)
        if error:
            flash(error, "error")
            return _render_entry_form("add_expense.html", form, EXPENSE_CHOICE)

        db_add_expense(
            user_id,
            float(form["amount"]),
            form["category"],
            form["date"],
            form["description"] or None,
        )
        flash("Expense added successfully.", "success")
        return redirect(url_for("profile"))

    return _render_entry_form("add_expense.html", {}, EXPENSE_CHOICE)


# Expense ids are bounded by SQLite's largest integer; bigger ids get a 404.
@app.route("/expenses/<int(max=9223372036854775807):id>/edit", methods=["GET", "POST"])
def edit_expense(id):
    user_id = _current_user_id()
    if user_id is None:
        return redirect(url_for("login"))

    expense = get_expense(id, user_id)
    if expense is None:
        abort(404)

    if request.method == "POST":
        form = _submitted_entry_form(EXPENSE_CHOICE)
        error = _entry_form_error(form, EXPENSE_CHOICE)
        if error:
            flash(error, "error")
            return _render_entry_form(
                "edit_expense.html", form, EXPENSE_CHOICE, expense_id=id
            )

        updated = db_update_expense(
            id,
            user_id,
            float(form["amount"]),
            form["category"],
            form["date"],
            form["description"] or None,
        )
        if not updated:
            abort(404)
        flash("Expense updated successfully.", "success")
        return redirect(url_for("profile"))

    form = {
        "amount": f"{expense['amount']:.2f}",
        "category": expense["category"],
        "date": expense["date"],
        "description": expense["description"] or "",
    }
    return _render_entry_form("edit_expense.html", form, EXPENSE_CHOICE, expense_id=id)


@app.route(
    "/expenses/<int(max=9223372036854775807):id>/delete", methods=["GET", "POST"]
)
def delete_expense(id):
    user_id = _current_user_id()
    if user_id is None:
        return redirect(url_for("login"))

    expense = get_expense(id, user_id)
    if expense is None:
        abort(404)

    if request.method == "POST":
        if not db_delete_expense(id, user_id):
            abort(404)
        flash("Expense deleted successfully.", "success")
        return redirect(url_for("profile"))

    return render_template(
        "delete_expense.html",
        expense=expense,
        expense_date=_display_date(expense["date"]),
    )


@app.route("/credits/add", methods=["GET", "POST"])
def add_credit():
    user_id = _current_user_id()
    if user_id is None:
        return redirect(url_for("login"))

    if request.method == "POST":
        form = _submitted_entry_form(CREDIT_CHOICE)
        error = _entry_form_error(form, CREDIT_CHOICE)
        if error:
            flash(error, "error")
            return _render_entry_form("add_credit.html", form, CREDIT_CHOICE)

        db_add_credit(
            user_id,
            float(form["amount"]),
            form["source"],
            form["date"],
            form["description"] or None,
        )
        flash("Credit added successfully.", "success")
        return redirect(url_for("profile"))

    return _render_entry_form("add_credit.html", {}, CREDIT_CHOICE)


# Credit ids are bounded like expense ids.
@app.route("/credits/<int(max=9223372036854775807):id>/edit", methods=["GET", "POST"])
def edit_credit(id):
    user_id = _current_user_id()
    if user_id is None:
        return redirect(url_for("login"))

    credit = get_credit(id, user_id)
    if credit is None:
        abort(404)

    if request.method == "POST":
        form = _submitted_entry_form(CREDIT_CHOICE)
        error = _entry_form_error(form, CREDIT_CHOICE)
        if error:
            flash(error, "error")
            return _render_entry_form(
                "edit_credit.html", form, CREDIT_CHOICE, credit_id=id
            )

        updated = db_update_credit(
            id,
            user_id,
            float(form["amount"]),
            form["source"],
            form["date"],
            form["description"] or None,
        )
        if not updated:
            abort(404)
        flash("Credit updated successfully.", "success")
        return redirect(url_for("profile"))

    form = {
        "amount": f"{credit['amount']:.2f}",
        "source": credit["source"],
        "date": credit["date"],
        "description": credit["description"] or "",
    }
    return _render_entry_form("edit_credit.html", form, CREDIT_CHOICE, credit_id=id)


@app.route("/credits/<int(max=9223372036854775807):id>/delete", methods=["GET", "POST"])
def delete_credit(id):
    user_id = _current_user_id()
    if user_id is None:
        return redirect(url_for("login"))

    credit = get_credit(id, user_id)
    if credit is None:
        abort(404)

    if request.method == "POST":
        if not db_delete_credit(id, user_id):
            abort(404)
        flash("Credit deleted successfully.", "success")
        return redirect(url_for("profile"))

    return render_template(
        "delete_credit.html",
        credit=credit,
        credit_date=_display_date(credit["date"]),
    )


if __name__ == "__main__":
    app.run(debug=True, port=5001)
