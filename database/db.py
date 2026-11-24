import datetime
import os
import sqlite3
from contextlib import closing

from werkzeug.security import generate_password_hash

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "spendly.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with closing(get_db()) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT    NOT NULL,
                email         TEXT    UNIQUE NOT NULL,
                password_hash TEXT    NOT NULL,
                created_at    TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS expenses (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                amount      REAL    NOT NULL,
                category    TEXT    NOT NULL,
                date        TEXT    NOT NULL,
                description TEXT,
                created_at  TEXT    DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
        """)


def get_user_by_email(email):
    with closing(get_db()) as conn:
        return conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


def get_user_by_id(user_id):
    with closing(get_db()) as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def create_user(name, email, password):
    password_hash = generate_password_hash(password)
    with closing(get_db()) as conn, conn:
        conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, password_hash),
        )


def add_expense(user_id, amount, category, date, description=None):
    with closing(get_db()) as conn, conn:
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, category, date, description),
        )


def get_expense(expense_id, user_id):
    """Return the expense if it belongs to the user, else None."""
    with closing(get_db()) as conn:
        return conn.execute(
            "SELECT * FROM expenses WHERE id = ? AND user_id = ?",
            (expense_id, user_id),
        ).fetchone()


def update_expense(expense_id, user_id, amount, category, date, description=None):
    """Update a user's expense; return whether a row was matched."""
    with closing(get_db()) as conn, conn:
        cursor = conn.execute(
            "UPDATE expenses SET amount = ?, category = ?, date = ?, description = ? "
            "WHERE id = ? AND user_id = ?",
            (amount, category, date, description, expense_id, user_id),
        )
        return cursor.rowcount > 0


def delete_expense(expense_id, user_id):
    """Delete a user's expense; return whether a row was deleted."""
    with closing(get_db()) as conn, conn:
        cursor = conn.execute(
            "DELETE FROM expenses WHERE id = ? AND user_id = ?",
            (expense_id, user_id),
        )
        return cursor.rowcount > 0


def seed_db():
    with closing(get_db()) as conn, conn:
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
            return

        user_id = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Demo User", "demo@spendly.com", generate_password_hash("demo123")),
        ).lastrowid

        # All days are <= 28, so they exist in every month.
        sample_expenses = [
            (45.50, "Food", 1, "Grocery shopping"),
            (12.00, "Transport", 3, "Bus pass"),
            (120.00, "Bills", 5, "Electric bill"),
            (30.00, "Health", 8, "Vitamins"),
            (15.00, "Entertainment", 10, "Movie ticket"),
            (65.00, "Shopping", 13, "New shoes"),
            (8.50, "Food", 17, "Coffee and snacks"),
            (25.00, "Other", 20, "Miscellaneous"),
        ]
        today = datetime.date.today()
        conn.executemany(
            "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
            [
                (
                    user_id,
                    amount,
                    category,
                    today.replace(day=day).isoformat(),
                    description,
                )
                for amount, category, day, description in sample_expenses
            ],
        )
