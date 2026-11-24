import datetime

from database.db import get_db

# The paid_from value for savings that came out of the user's account.
# Only these reduce the available balance.
OWN_ACCOUNT = "My account"


def format_date(value):
    """Format an ISO date for display, e.g. May 1, 2026."""
    day = datetime.date.fromisoformat(value)
    return f"{day:%B} {day.day}, {day.year}"


def _user_date_filter(user_id, date_from=None, date_to=None):
    """Return a WHERE clause and its parameters for a user's date range."""
    where, params = "WHERE user_id = ?", [user_id]
    if date_from:
        where += " AND date >= ?"
        params.append(date_from)
    if date_to:
        where += " AND date <= ?"
        params.append(date_to)
    return where, params


# ------------------------------------------------------------------ #
# SA2: User data                                                      #
# ------------------------------------------------------------------ #


def get_user_by_id(user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT name, email, created_at FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    dt = datetime.datetime.fromisoformat(row["created_at"])
    return {
        "name": row["name"],
        "email": row["email"],
        "member_since": dt.strftime("%B %Y"),
    }


# ------------------------------------------------------------------ #
# SA2: Summary stats                                                  #
# ------------------------------------------------------------------ #


def get_summary_stats(user_id, date_from=None, date_to=None):
    where, params = _user_date_filter(user_id, date_from, date_to)
    conn = get_db()
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total_spent, COUNT(*) AS transaction_count "
        "FROM expenses " + where,
        params,
    ).fetchone()
    top = conn.execute(
        "SELECT category FROM expenses "
        + where
        + " GROUP BY category ORDER BY SUM(amount) DESC LIMIT 1",
        params,
    ).fetchone()
    conn.close()
    return {
        "total_spent": row["total_spent"],
        "transaction_count": row["transaction_count"],
        "top_category": top["category"] if top else "—",
    }


# ------------------------------------------------------------------ #
# SA1: Transaction history                                            #
# ------------------------------------------------------------------ #


def get_recent_transactions(user_id, limit=10, date_from=None, date_to=None):
    where, params = _user_date_filter(user_id, date_from, date_to)
    params.append(limit)
    conn = get_db()
    rows = conn.execute(
        "SELECT id, date, description, category, amount "
        "FROM expenses " + where + " ORDER BY date DESC LIMIT ?",
        params,
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        result.append(
            {
                "id": row["id"],
                "date_iso": row["date"],
                "date": format_date(row["date"]),
                "description": row["description"] or "",
                "category": row["category"],
                "amount": row["amount"],
            }
        )
    return result


# ------------------------------------------------------------------ #
# SA3: Category breakdown                                             #
# ------------------------------------------------------------------ #


def _with_percentages(rows):
    """Add whole percentages that sum to 100 to name/amount rows."""
    if not rows:
        return []
    total = sum(r["amount"] for r in rows)
    items = [(r["name"], r["amount"], r["amount"] / total * 100) for r in rows]
    floors = [(n, a, int(p), p - int(p)) for n, a, p in items]
    remainder = 100 - sum(f[2] for f in floors)
    for i, _ in sorted(enumerate(floors), key=lambda x: -x[1][3])[:remainder]:
        n, a, fl, rem = floors[i]
        floors[i] = (n, a, fl + 1, rem)
    return [{"name": n, "amount": a, "pct": p} for n, a, p, _ in floors]


def get_category_breakdown(user_id, date_from=None, date_to=None):
    where, params = _user_date_filter(user_id, date_from, date_to)
    conn = get_db()
    rows = conn.execute(
        "SELECT category AS name, SUM(amount) AS amount "
        "FROM expenses " + where + " GROUP BY category ORDER BY amount DESC",
        params,
    ).fetchall()
    conn.close()
    return _with_percentages(rows)


# ------------------------------------------------------------------ #
# Credits                                                             #
# ------------------------------------------------------------------ #


def get_recent_credits(user_id, limit=10, date_from=None, date_to=None):
    where, params = _user_date_filter(user_id, date_from, date_to)
    params.append(limit)
    conn = get_db()
    rows = conn.execute(
        "SELECT id, date, description, source, amount "
        "FROM credits " + where + " ORDER BY date DESC, id DESC LIMIT ?",
        params,
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        result.append(
            {
                "id": row["id"],
                "date_iso": row["date"],
                "date": format_date(row["date"]),
                "description": row["description"] or "",
                "source": row["source"],
                "amount": row["amount"],
            }
        )
    return result


def count_credits(user_id, date_from=None, date_to=None):
    where, params = _user_date_filter(user_id, date_from, date_to)
    conn = get_db()
    row = conn.execute("SELECT COUNT(*) FROM credits " + where, params).fetchone()
    conn.close()
    return row[0]


# ------------------------------------------------------------------ #
# Net                                                                 #
# ------------------------------------------------------------------ #


def get_net_summary(user_id, date_from=None, date_to=None):
    """Return the period's credits, expenses and the difference between them."""
    where, params = _user_date_filter(user_id, date_from, date_to)
    conn = get_db()
    credits = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM credits " + where, params
    ).fetchone()[0]
    spent = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM expenses " + where, params
    ).fetchone()[0]
    conn.close()
    # Subtracting rounded totals matches the cards and avoids negative zero.
    total_credits = round(credits, 2)
    total_spent = round(spent, 2)
    return {
        "total_credits": total_credits,
        "total_spent": total_spent,
        "net": round(total_credits - total_spent, 2),
    }


def get_available_summary(user_id, date_from=None, date_to=None):
    """Return the period's credits, expenses, own-account savings and what is left."""
    net_summary = get_net_summary(user_id, date_from, date_to)
    where, params = _user_date_filter(user_id, date_from, date_to)
    conn = get_db()
    saved = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM savings " + where + " AND paid_from = ?",
        [*params, OWN_ACCOUNT],
    ).fetchone()[0]
    conn.close()
    saved_from_account = round(saved, 2)
    return {
        "total_credits": net_summary["total_credits"],
        "total_spent": net_summary["total_spent"],
        "saved_from_account": saved_from_account,
        # Subtracting from the rounded net avoids negative zero.
        "available": round(net_summary["net"] - saved_from_account, 2),
    }


# ------------------------------------------------------------------ #
# Savings                                                             #
# ------------------------------------------------------------------ #


def _saving_details(row):
    """Return the optional facts shown under a saving's description."""
    details = []
    if row["institution"]:
        details.append(row["institution"])
    if row["interest_rate"] is not None:
        details.append(f"{row['interest_rate']:g}%")
    if row["maturity_date"]:
        details.append(f"Matures {format_date(row['maturity_date'])}")
    if row["paid_from"] != OWN_ACCOUNT:
        details.append(row["paid_from"])
    return details


def get_recent_savings(user_id, limit=10, date_from=None, date_to=None):
    where, params = _user_date_filter(user_id, date_from, date_to)
    params.append(limit)
    conn = get_db()
    rows = conn.execute(
        "SELECT id, date, description, type, amount, institution, interest_rate, "
        "maturity_date, paid_from "
        "FROM savings " + where + " ORDER BY date DESC, id DESC LIMIT ?",
        params,
    ).fetchall()
    conn.close()
    return [
        {
            **dict(row),
            "date_iso": row["date"],
            "date": format_date(row["date"]),
            "description": row["description"] or "",
            "details": _saving_details(row),
        }
        for row in rows
    ]


def get_savings_summary(user_id, date_from=None, date_to=None):
    where, params = _user_date_filter(user_id, date_from, date_to)
    conn = get_db()
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS count "
        "FROM savings " + where,
        params,
    ).fetchone()
    conn.close()
    return {"total": row["total"], "count": row["count"]}


def get_savings_breakdown(user_id, date_from=None, date_to=None):
    where, params = _user_date_filter(user_id, date_from, date_to)
    conn = get_db()
    rows = conn.execute(
        "SELECT type AS name, SUM(amount) AS amount "
        "FROM savings " + where + " GROUP BY type ORDER BY amount DESC",
        params,
    ).fetchall()
    conn.close()
    return _with_percentages(rows)
