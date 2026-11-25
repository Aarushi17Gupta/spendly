"""Tests for the profile page design (Step 4, on live data)."""

import pytest
from werkzeug.security import generate_password_hash

import database.db as db_module
from app import app as flask_app
from database.db import add_expense, get_db, init_db


@pytest.fixture()
def user_id(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setitem(flask_app.config, "TESTING", True)
    init_db()
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Page User", "page@spendly.test", generate_password_hash("pagepass")),
    )
    conn.commit()
    conn.close()
    return cur.lastrowid


@pytest.fixture()
def client(user_id):
    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
    return client


def get_html(client, url="/profile"):
    resp = client.get(url)
    assert resp.status_code == 200
    return resp.data.decode("utf-8")


def test_logged_out_redirects_to_login(user_id):
    resp = flask_app.test_client().get("/profile")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_navbar_shows_username_and_logout(client):
    nav = get_html(client).split("<nav", 1)[1].split("</nav>")[0]
    assert "Page User" in nav
    assert 'href="/logout"' in nav


def test_deleted_user_gets_signed_out(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 99999
    assert "Get started" in get_html(client, "/terms")
    assert "/login" in client.get("/profile").headers["Location"]
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_add_expense_flash_shown_once(client):
    client.post("/expenses/add", data={
        "amount": "10", "category": "Food",
        "date": "2026-05-01", "description": "Tea",
    })
    assert "Expense added successfully." in get_html(client)
    assert "Expense added successfully." not in get_html(client)


def test_new_user_empty_state(client):
    html = get_html(client)
    assert "No expenses yet" in html
    assert "No expenses in this period" not in html


def test_filtered_empty_state(client, user_id):
    add_expense(user_id, 10, "Food", "2026-05-01", "Tea")
    html = get_html(client, "/profile?from=2025-01-01&to=2025-01-31")
    assert "No expenses in this period" in html
    assert "No expenses yet" not in html


@pytest.mark.parametrize("query, label", [
    ("", "All time"),
    ("?from=2026-05-01", "From May 1, 2026"),
    ("?to=2026-05-10", "Until May 10, 2026"),
    ("?from=2026-05-01&to=2026-05-10", "May 1, 2026 – May 10, 2026"),
    ("?from=garbage", "All time"),
])
def test_period_label(client, query, label):
    assert f"<strong>{label}</strong>" in get_html(client, "/profile" + query)


def test_amounts_use_thousands_separator(client, user_id):
    add_expense(user_id, 1234.5, "Bills", "2026-05-01", None)
    html = get_html(client)
    assert "₹1,234.50" in html
    assert "No description" in html


def test_category_percentage_and_bar(client, user_id):
    add_expense(user_id, 75, "Bills", "2026-05-01", "a")
    add_expense(user_id, 25, "Food", "2026-05-02", "b")
    html = get_html(client)
    assert ">75%<" in html
    assert 'width="75%"' in html
    assert 'class="cat cat-bills"' in html


def test_long_table_has_see_more(client, user_id):
    for day in range(1, 13):
        add_expense(user_id, 5, "Food", f"2026-05-{day:02d}", "Tea")
    html = get_html(client)
    assert html.count('class="tx-edit"') == 12
    assert "See more+" in html


def test_no_inline_styles_or_cdn_scripts(client, user_id):
    add_expense(user_id, 10, "Food", "2026-05-01", "Tea")
    html = get_html(client)
    assert "style=" not in html
    assert "unpkg" not in html
