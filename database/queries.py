import datetime

from database.db import get_db


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
    return {"name": row["name"], "email": row["email"], "member_since": dt.strftime("%B %Y")}


# ------------------------------------------------------------------ #
# SA2: Summary stats                                                  #
# ------------------------------------------------------------------ #

def get_summary_stats(user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total_spent, COUNT(*) AS transaction_count "
        "FROM expenses WHERE user_id = ?", (user_id,)
    ).fetchone()
    top = conn.execute(
        "SELECT category FROM expenses WHERE user_id = ? "
        "GROUP BY category ORDER BY SUM(amount) DESC LIMIT 1", (user_id,)
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

def get_recent_transactions(user_id, limit=10):
    conn = get_db()
    rows = conn.execute(
        "SELECT date, description, category, amount "
        "FROM expenses WHERE user_id = ? ORDER BY date DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        dt = datetime.datetime.strptime(row["date"], "%Y-%m-%d")
        result.append({
            "date": dt.strftime("%B %-d, %Y"),
            "description": row["description"] or "",
            "category": row["category"],
            "amount": row["amount"],
        })
    return result


# ------------------------------------------------------------------ #
# SA3: Category breakdown                                             #
# ------------------------------------------------------------------ #

def get_category_breakdown(user_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT category AS name, SUM(amount) AS amount "
        "FROM expenses WHERE user_id = ? GROUP BY category ORDER BY amount DESC",
        (user_id,),
    ).fetchall()
    conn.close()
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
