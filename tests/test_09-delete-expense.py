"""Tests for Step 9 — GET/POST /expenses/<id>/delete."""

import re
from contextlib import closing

import pytest

import database.db as db_module
from app import app as flask_app
from database.db import (
    add_expense,
    create_user,
    delete_expense,
    get_db,
    get_expense,
    get_user_by_email,
    init_db,
)

EMAIL = "deleter@spendly.test"
OTHER_EMAIL = "other@spendly.test"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setitem(flask_app.config, "TESTING", True)
    init_db()
    create_user("Deleter", EMAIL, "deleterpass")
    create_user("Other", OTHER_EMAIL, "otherpass")
    return flask_app.test_client()


@pytest.fixture()
def user_id(client):
    return get_user_by_email(EMAIL)["id"]


@pytest.fixture()
def other_id(client):
    return get_user_by_email(OTHER_EMAIL)["id"]


@pytest.fixture()
def auth_client(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
    return client


def saved_expenses():
    with closing(get_db()) as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM expenses ORDER BY id")]


def insert(user_id, amount=45.5, category="Food", date="2026-09-05", description=None):
    add_expense(user_id, amount, category, date, description)
    return saved_expenses()[-1]["id"]


@pytest.fixture()
def expense_id(user_id):
    return insert(user_id, description="Lunch")


def url(expense_id):
    return f"/expenses/{expense_id}/delete"


def send(client, method, expense_id, data=None):
    if method == "get":
        return client.get(url(expense_id))
    return client.post(url(expense_id), data=data or {})


def stat_value(html, label):
    pattern = (
        r'<span class="stat-label">' + re.escape(label) + r"</span>\s*"
        r'<span class="stat-value">([^<]*)</span>'
    )
    match = re.search(pattern, html)
    assert match, f"stat card {label!r} not found"
    return match.group(1)


def delete_link(html, target):
    """Return (opening tag, inner html) of the delete icon link for an expense."""
    pattern = rf'(<a\b[^>]*href="{re.escape(url(target))}"[^>]*>)(.*?)</a>'
    for tag, inner in re.findall(pattern, html, re.S):
        if "tx-delete" in tag:
            return tag, inner
    pytest.fail(f"no delete icon link for expense {target}")


both_methods = pytest.mark.parametrize("method", ["get", "post"])


# ---- Access ---------------------------------------------------------- #


@both_methods
def test_logged_out_redirects_to_login(client, expense_id, other_id, method):
    before = saved_expenses()
    for target in (expense_id, 9999):
        response = send(client, method, target, {"user_id": str(other_id)})
        assert response.status_code == 302
        assert response.headers["Location"] == "/login"
    assert saved_expenses() == before


@both_methods
def test_deleted_user_session_is_cleared(client, expense_id, method):
    with client.session_transaction() as sess:
        sess["user_id"] = 9999
    before = saved_expenses()
    response = send(client, method, expense_id)
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"
    with client.session_transaction() as sess:
        assert "user_id" not in sess
    assert saved_expenses() == before


@both_methods
@pytest.mark.parametrize("missing", [0, 9999, 2**63 - 1, 2**63])
def test_unknown_expense_is_404(auth_client, expense_id, method, missing):
    before = saved_expenses()
    assert send(auth_client, method, missing).status_code == 404
    assert saved_expenses() == before


@both_methods
def test_other_users_expense_is_404_even_with_forged_user_id(
    auth_client, user_id, other_id, method
):
    target = insert(other_id, description="Private")
    before = saved_expenses()
    for forged in (user_id, other_id):
        response = send(auth_client, method, target, {"user_id": str(forged)})
        assert response.status_code == 404
        assert "Private" not in response.get_data(as_text=True)
    assert saved_expenses() == before


def test_post_deleted_before_confirm_is_404(auth_client, expense_id, monkeypatch):
    monkeypatch.setattr("app.db_delete_expense", lambda *args: False)
    assert auth_client.post(url(expense_id)).status_code == 404


# ---- Confirmation page ------------------------------------------------ #


def test_confirmation_page_shows_details_and_changes_nothing(auth_client, user_id):
    target = insert(user_id, amount=1234567.5, category="Bills", description="Rent")
    before = saved_expenses()
    response = auth_client.get(url(target))
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "₹1,234,567.50" in html
    assert "Bills" in html
    assert "September 5, 2026" in html
    assert "Rent" in html
    assert "undone" in html.lower()
    assert "Delete Expense" in html
    assert re.search(
        r'<form[^>]*method="post"[^>]*action="%s"' % url(target), html, re.I
    ) or (
        re.search(r'<form[^>]*action="%s"[^>]*method="post"' % url(target), html, re.I)
    )
    assert "Cancel" in html
    assert 'href="/profile"' in html
    assert saved_expenses() == before


def test_head_deletes_nothing(auth_client, expense_id):
    before = saved_expenses()
    auth_client.head(url(expense_id))
    assert saved_expenses() == before


def test_cancel_link_target_deletes_nothing(auth_client, expense_id):
    before = saved_expenses()
    assert auth_client.get("/profile").status_code == 200
    assert saved_expenses() == before


def test_null_description_shows_placeholder(auth_client, user_id):
    html = auth_client.get(url(insert(user_id))).get_data(as_text=True)
    assert "No description" in html
    assert "None" not in html


def test_confirmation_page_escapes_description(auth_client, user_id):
    target = insert(user_id, description="<b>Tom & \"Jerry\" 'x'</b>")
    html = auth_client.get(url(target)).get_data(as_text=True)
    assert "<b>Tom" not in html
    assert "&lt;b&gt;Tom &amp; " in html
    assert "&lt;/b&gt;" in html


# ---- Deleting --------------------------------------------------------- #


def test_confirm_deletes_only_that_row_and_flashes(
    auth_client, user_id, other_id, expense_id
):
    sibling = insert(user_id, description="Sibling")
    foreign = insert(other_id, description="Theirs")
    before = {row["id"]: row for row in saved_expenses()}
    response = auth_client.post(url(expense_id))
    assert response.status_code == 302
    assert response.headers["Location"] == "/profile"
    after = {row["id"]: row for row in saved_expenses()}
    assert set(after) == {sibling, foreign}
    assert after[sibling] == before[sibling]
    assert after[foreign] == before[foreign]
    page = auth_client.get("/profile").get_data(as_text=True)
    assert "Expense deleted successfully." in page
    again = auth_client.get("/profile").get_data(as_text=True)
    assert "Expense deleted successfully." not in again


def test_forged_user_id_in_own_delete_is_ignored(
    auth_client, user_id, other_id, expense_id
):
    foreign = insert(other_id, description="Theirs")
    auth_client.post(url(expense_id), data={"user_id": str(other_id)})
    assert [row["id"] for row in saved_expenses()] == [foreign]


def test_double_submit_is_404_and_deletes_nothing_else(
    auth_client, user_id, expense_id
):
    sibling = insert(user_id, description="Sibling")
    assert auth_client.post(url(expense_id)).status_code == 302
    before = saved_expenses()
    assert auth_client.post(url(expense_id)).status_code == 404
    assert saved_expenses() == before
    assert [row["id"] for row in before] == [sibling]


def test_edit_page_for_deleted_expense_is_404(auth_client, expense_id):
    auth_client.post(url(expense_id))
    assert auth_client.get(f"/expenses/{expense_id}/edit").status_code == 404


# ---- Profile ---------------------------------------------------------- #


def test_profile_stats_and_breakdown_reflect_deletion(auth_client, user_id, expense_id):
    insert(user_id, amount=10, category="Bills", description="Power")
    response = auth_client.post(url(expense_id), follow_redirects=True)
    html = response.get_data(as_text=True)
    assert stat_value(html, "Total Spent") == "₹10.00"
    assert stat_value(html, "Expenses") == "1"
    assert stat_value(html, "Top Category") == "Bills"
    assert '<span class="category-name">Food</span>' not in html
    assert '<span class="category-name">Bills</span>' in html
    assert "Lunch" not in html


def test_deleting_last_expense_shows_empty_state(auth_client, expense_id):
    response = auth_client.post(url(expense_id), follow_redirects=True)
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "No expenses yet." in html
    assert "Expense deleted successfully." in html


def test_profile_has_icon_only_delete_link_per_row(auth_client, user_id, expense_id):
    second = insert(user_id, category="Bills", amount=1234.5)
    html = auth_client.get("/profile").get_data(as_text=True)
    for target in (expense_id, second):
        tag, inner = delete_link(html, target)
        assert 'title="Delete"' in tag
        assert "<svg" in inner
        assert 'aria-hidden="true"' in inner
        assert 'focusable="false"' in inner
        assert 'stroke="currentColor"' in inner
        text = re.sub(r"<svg.*?</svg>", "", inner, flags=re.S)
        assert text.strip() == "", "delete icon must have no visible text"
        assert f'href="{url(target).replace("delete", "edit")}"' in html
    assert 'aria-label="Delete Lunch, ₹45.50, September 5, 2026"' in html
    assert 'aria-label="Delete Bills, ₹1,234.50, September 5, 2026"' in html
    assert html.count('role="columnheader"') == 5
    assert ">Actions</th>" in html
    assert ">Edit</th>" not in html


def test_profile_delete_links_only_for_own_expenses(auth_client, other_id, expense_id):
    foreign = insert(other_id, description="Theirs")
    html = auth_client.get("/profile").get_data(as_text=True)
    assert f'href="{url(expense_id)}"' in html
    assert f'href="{url(foreign)}"' not in html


def test_profile_aria_label_escapes_html_quotes_and_ampersands(auth_client, user_id):
    target = insert(user_id, description='<i>A&B</i>" onfocus="alert(1)')
    html = auth_client.get("/profile").get_data(as_text=True)
    tag, _ = delete_link(html, target)
    assert ' onfocus="' not in tag
    assert "<i>" not in tag
    assert "&lt;i&gt;A&amp;B&lt;/i&gt;" in tag
    assert "&#34; onfocus=&#34;" in tag


# ---- DB helper -------------------------------------------------------- #


def test_delete_expense_helper_is_scoped_to_owner(user_id, other_id, expense_id):
    before = saved_expenses()
    assert delete_expense(expense_id, other_id) is False
    assert delete_expense(9999, user_id) is False
    assert saved_expenses() == before
    assert get_expense(expense_id, user_id) is not None


def test_delete_expense_helper_deletes_once(user_id, expense_id):
    sibling = insert(user_id, description="Sibling")
    assert delete_expense(expense_id, user_id) is True
    assert delete_expense(expense_id, user_id) is False
    assert [row["id"] for row in saved_expenses()] == [sibling]
