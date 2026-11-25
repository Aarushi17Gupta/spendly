"""Tests for Step 10 — credits: GET/POST /credits/add, /credits/<id>/edit, /credits/<id>/delete."""

import re
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

import database.db as db_module
from app import app as flask_app
from database.db import (
    add_credit,
    add_expense,
    create_user,
    delete_credit,
    get_credit,
    get_db,
    get_user_by_email,
    init_db,
    update_credit,
)
from database.queries import count_credits, get_recent_credits

EMAIL = "credits@spendly.test"
OTHER_EMAIL = "other@spendly.test"
OLD_TIMESTAMP = "2020-01-01 00:00:00"
SOURCES = {"Salary", "Freelance", "Interest", "Refund", "Gift", "Other"}
VALID = {
    "amount": "2500.50",
    "source": "Salary",
    "date": "2026-06-02",
    "description": "June pay",
}
ADD_URL = "/credits/add"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setitem(flask_app.config, "TESTING", True)
    init_db()
    create_user("Credits", EMAIL, "creditspass")
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


# ---- Helpers ---------------------------------------------------------- #


def saved_credits():
    with closing(get_db()) as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM credits ORDER BY id")]


def saved_expenses():
    with closing(get_db()) as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM expenses ORDER BY id")]


def insert(
    user_id, amount=1000, source="Freelance", date="2026-05-01", description="Project"
):
    add_credit(user_id, amount, source, date, description)
    with closing(get_db()) as conn, conn:
        conn.execute("UPDATE credits SET created_at = ?", (OLD_TIMESTAMP,))
    return saved_credits()[-1]["id"]


def insert_expense(
    user_id, amount=45.5, category="Food", date="2026-05-01", description="Lunch"
):
    add_expense(user_id, amount, category, date, description)
    return saved_expenses()[-1]["id"]


@pytest.fixture()
def credit_id(user_id):
    return insert(user_id)


def edit_url(credit_id):
    return f"/credits/{credit_id}/edit"


def delete_url(credit_id):
    return f"/credits/{credit_id}/delete"


def section(html, heading_id):
    match = re.search(
        rf'<section[^>]*aria-labelledby="{heading_id}".*?</section>', html, re.S
    )
    assert match, f"section {heading_id!r} not found"
    return match.group(0)


def stats_and_categories(html):
    stats = re.search(r'<section[^>]*class="profile-stats".*?</section>', html, re.S)
    assert stats, "stats section not found"
    return stats.group(0), section(html, "cat-heading")


def profile_html(client, query=""):
    response = client.get("/profile" + query)
    assert response.status_code == 200
    return response.get_data(as_text=True)


def credits_section(client, query=""):
    return section(profile_html(client, query), "credit-heading")


def action_tag(html, href, css_class):
    pattern = rf'<a\b[^>]*href="{re.escape(href)}"[^>]*>'
    for tag in re.findall(pattern, html):
        if css_class in tag:
            return tag
    pytest.fail(f"no {css_class} link for {href}")


ROUTES = {
    "add": lambda _id: ADD_URL,
    "edit": edit_url,
    "delete": delete_url,
}


def send(client, route, method, target=1, data=None):
    path = ROUTES[route](target)
    if method == "get":
        return client.get(path)
    return client.post(path, data=VALID if data is None else data)


both_methods = pytest.mark.parametrize("method", ["get", "post"])
id_routes = pytest.mark.parametrize("route", ["edit", "delete"])
all_routes = pytest.mark.parametrize("route", ["add", "edit", "delete"])
form_modes = pytest.mark.parametrize("mode", ["add", "edit"])


def submit(client, mode, credit_id, data):
    path = ADD_URL if mode == "add" else edit_url(credit_id)
    return client.post(path, data=data)


# ---- Database --------------------------------------------------------- #


def test_init_db_on_old_schema_adds_credits_table_and_keeps_rows(client, user_id):
    insert_expense(user_id, description="Keep me")
    with closing(get_db()) as conn, conn:
        conn.execute("DROP TABLE credits")
    users_before = [
        dict(r) for r in get_db().execute("SELECT * FROM users ORDER BY id")
    ]
    expenses_before = saved_expenses()
    with closing(sqlite3.connect(db_module.DB_PATH)) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert "credits" not in names, "precondition: old schema has no credits table"

    init_db()
    init_db()

    with closing(sqlite3.connect(db_module.DB_PATH)) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert "credits" in names
    assert saved_credits() == []
    assert saved_expenses() == expenses_before
    users_after = [dict(r) for r in get_db().execute("SELECT * FROM users ORDER BY id")]
    assert users_after == users_before


def test_init_db_twice_keeps_existing_credits(user_id, credit_id):
    before = saved_credits()
    init_db()
    assert saved_credits() == before


def test_credits_table_has_spec_columns(client):
    with closing(get_db()) as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(credits)")}
    assert columns == {
        "id",
        "user_id",
        "amount",
        "source",
        "date",
        "description",
        "created_at",
    }


def test_no_credits_are_seeded(client):
    assert saved_credits() == []


def test_get_credit_is_scoped_to_owner(user_id, other_id, credit_id):
    assert get_credit(credit_id, user_id)["description"] == "Project"
    assert get_credit(credit_id, other_id) is None
    assert get_credit(9999, user_id) is None


def test_update_credit_is_scoped_to_owner(user_id, other_id, credit_id):
    values = (1000, "Freelance", "2026-05-01", "Project")
    before = saved_credits()
    assert update_credit(credit_id, other_id, 1, "Gift", "2026-01-01") is False
    assert update_credit(9999, user_id, *values) is False
    assert update_credit(credit_id, user_id, *values) is True
    assert saved_credits() == before


def test_delete_credit_is_scoped_to_owner_and_deletes_once(
    user_id, other_id, credit_id
):
    before = saved_credits()
    assert delete_credit(credit_id, other_id) is False
    assert delete_credit(9999, user_id) is False
    assert saved_credits() == before
    sibling = insert(user_id, description="Sibling")
    assert delete_credit(credit_id, user_id) is True
    assert delete_credit(credit_id, user_id) is False
    assert [row["id"] for row in saved_credits()] == [sibling]


def test_add_credit_helper_stores_null_description_by_default(user_id):
    add_credit(user_id, 5, "Gift", "2026-05-01")
    [row] = saved_credits()
    assert (row["user_id"], row["amount"], row["source"], row["date"]) == (
        user_id,
        5,
        "Gift",
        "2026-05-01",
    )
    assert row["description"] is None
    assert row["created_at"]


def test_credit_queries_order_limit_and_filter(user_id, other_id):
    for day in range(1, 13):
        insert(user_id, date=f"2026-05-{day:02d}", description=f"c{day}")
    insert(other_id, date="2026-05-20", description="theirs")
    rows = get_recent_credits(user_id)
    assert len(rows) == 10
    assert [r["date_iso"] for r in rows] == [
        f"2026-05-{day:02d}" for day in range(12, 2, -1)
    ]
    assert count_credits(user_id) == 12
    assert count_credits(user_id, date_from="2026-05-05", date_to="2026-05-07") == 3
    assert len(get_recent_credits(user_id, limit=2)) == 2
    assert count_credits(other_id) == 1


# ---- Access ----------------------------------------------------------- #


@all_routes
@both_methods
def test_logged_out_redirects_to_login_and_changes_nothing(
    client, credit_id, other_id, route, method
):
    before = saved_credits()
    for target in (credit_id, 9999):
        data = {**VALID, "user_id": str(other_id)}
        response = send(client, route, method, target, data)
        assert response.status_code == 302
        assert response.headers["Location"] == "/login"
    assert saved_credits() == before


@all_routes
@both_methods
def test_logged_out_invalid_data_redirects_without_validating(
    client, credit_id, route, method
):
    before = saved_credits()
    response = send(client, route, method, credit_id, {**VALID, "amount": "-1"})
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"
    assert saved_credits() == before


@all_routes
@both_methods
def test_deleted_user_session_is_cleared(client, credit_id, route, method):
    with client.session_transaction() as sess:
        sess["user_id"] = 9999
    before = saved_credits()
    response = send(client, route, method, credit_id)
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"
    with client.session_transaction() as sess:
        assert "user_id" not in sess
    assert saved_credits() == before


@id_routes
@both_methods
@pytest.mark.parametrize("missing", [0, 9999, 2**63 - 1, 2**63])
def test_unknown_credit_is_404(auth_client, credit_id, route, method, missing):
    before = saved_credits()
    assert send(auth_client, route, method, missing).status_code == 404
    assert saved_credits() == before


@id_routes
@both_methods
def test_other_users_credit_is_404_even_with_forged_user_id(
    auth_client, user_id, other_id, route, method
):
    target = insert(other_id, description="Private")
    before = saved_credits()
    for forged in (user_id, other_id):
        data = {**VALID, "user_id": str(forged)}
        response = send(auth_client, route, method, target, data)
        assert response.status_code == 404
        assert "Private" not in response.get_data(as_text=True)
    assert saved_credits() == before


def test_update_matching_no_row_is_404(auth_client, credit_id, monkeypatch):
    monkeypatch.setattr("app.db_update_credit", lambda *args: False)
    assert auth_client.post(edit_url(credit_id), data=VALID).status_code == 404


def test_delete_matching_no_row_is_404(auth_client, credit_id, monkeypatch):
    monkeypatch.setattr("app.db_delete_credit", lambda *args: False)
    assert auth_client.post(delete_url(credit_id)).status_code == 404


# ---- Add form --------------------------------------------------------- #


def test_add_form_has_four_fields_and_exactly_six_sources(auth_client):
    response = auth_client.get(ADD_URL)
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    for field in ("amount", "source", "date", "description"):
        assert f'name="{field}"' in html
    assert 'name="category"' not in html, "credit form must not use category"
    select = re.search(r"<select[^>]*>(.*?)</select>", html, re.S).group(1)
    options = [v for v in re.findall(r'<option value="([^"]*)"', select) if v]
    assert len(options) == 6
    assert set(options) == SOURCES
    assert "Food" not in select
    assert "Add Credit" in html
    assert 'href="/profile"' in html
    assert "Save Changes" not in html


def test_valid_add_saves_one_credit_for_logged_in_user(auth_client, user_id, other_id):
    data = {**VALID, "user_id": str(other_id)}
    response = auth_client.post(ADD_URL, data=data)
    assert response.status_code == 302
    assert response.headers["Location"] == "/profile"
    [row] = saved_credits()
    assert row["user_id"] == user_id
    assert (row["amount"], row["source"], row["date"], row["description"]) == (
        2500.50,
        "Salary",
        "2026-06-02",
        "June pay",
    )
    assert saved_expenses() == []


def test_valid_add_flashes_message_once_and_shows_credit_immediately(auth_client):
    response = auth_client.post(ADD_URL, data=VALID, follow_redirects=True)
    html = response.get_data(as_text=True)
    assert "Credit added successfully." in html
    block = section(html, "credit-heading")
    assert "June pay" in block
    assert "₹2,500.50" in block
    assert "Salary" in block
    assert "Credit added successfully." not in profile_html(auth_client)


@pytest.mark.parametrize("blank", ["", "   "])
@form_modes
def test_blank_description_is_stored_as_null(auth_client, credit_id, mode, blank):
    submit(auth_client, mode, credit_id, {**VALID, "description": blank})
    assert saved_credits()[-1]["description"] is None


@form_modes
@pytest.mark.parametrize(
    "field, value",
    [
        ("amount", "0.01"),
        ("amount", "10000000"),
        ("description", "x" * 200),
        ("description", "'; DROP TABLE credits;--"),
    ],
)
def test_boundary_values_are_saved(auth_client, credit_id, mode, field, value):
    response = submit(auth_client, mode, credit_id, {**VALID, field: value})
    assert response.status_code == 302
    stored = saved_credits()[-1][field]
    assert stored == (float(value) if field == "amount" else value)
    assert len(saved_credits()) == (2 if mode == "add" else 1)


@form_modes
@pytest.mark.parametrize("source", sorted(SOURCES))
def test_every_allowed_source_is_accepted(auth_client, credit_id, mode, source):
    response = submit(auth_client, mode, credit_id, {**VALID, "source": source})
    assert response.status_code == 302
    assert saved_credits()[-1]["source"] == source


# ---- Validation (add and edit) ---------------------------------------- #

INVALID_CASES = [
    *(
        ("amount", value, "Amount must be a positive number.")
        for value in (None, "0", "-5", "abc", "nan", "inf")
    ),
    ("amount", "0.001", "Amount must be between"),
    ("amount", "10000000.01", "Amount must be between"),
    *(
        ("source", value, "Please select a valid source.")
        for value in ("Food", "", "salary", None)
    ),
    *(
        ("date", value, "Date must be a valid date")
        for value in ("20260501", "2026-02-30", "")
    ),
    ("description", "x" * 201, "Description must be 200 characters"),
]


@form_modes
@pytest.mark.parametrize("field, value, message", INVALID_CASES)
def test_invalid_input_is_rejected_and_values_preserved(
    auth_client, credit_id, mode, field, value, message
):
    before = saved_credits()
    data = {**VALID, field: value}
    data = {k: v for k, v in data.items() if v is not None}
    response = submit(auth_client, mode, credit_id, data)
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Location" not in response.headers
    assert message in html
    assert "auth-error" in html
    assert "Credit added successfully." not in html
    assert "Credit updated successfully." not in html
    for name in ("amount", "date", "description"):
        if name in data:
            assert f'value="{data[name]}"' in html, f"{name} not preserved"
    if field != "source":
        assert '<option value="Salary" selected>' in html
    else:
        assert '<option value="Freelance" selected>' not in html, "stored value leaked"
    assert saved_credits() == before


@form_modes
def test_posting_only_category_is_rejected(auth_client, credit_id, mode):
    before = saved_credits()
    data = {k: v for k, v in VALID.items() if k != "source"}
    data["category"] = "Food"
    response = submit(auth_client, mode, credit_id, data)
    assert response.status_code == 200
    assert "Please select a valid source." in response.get_data(as_text=True)
    assert saved_credits() == before


@form_modes
def test_expense_category_name_is_not_accepted_as_source(auth_client, credit_id, mode):
    before = saved_credits()
    data = {**VALID, "source": "Food", "category": "Salary"}
    response = submit(auth_client, mode, credit_id, data)
    assert response.status_code == 200
    assert "Please select a valid source." in response.get_data(as_text=True)
    assert saved_credits() == before


@form_modes
def test_validation_failure_does_not_write_expenses(
    auth_client, user_id, credit_id, mode
):
    insert_expense(user_id)
    before = saved_expenses()
    submit(auth_client, mode, credit_id, {**VALID, "amount": "0"})
    assert saved_expenses() == before


# ---- Edit ------------------------------------------------------------- #


def test_edit_form_is_prefilled(auth_client, credit_id):
    response = auth_client.get(edit_url(credit_id))
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'value="1000.00"' in html
    assert '<option value="Freelance" selected>' in html
    assert 'value="2026-05-01"' in html
    assert 'value="Project"' in html
    assert f'action="{edit_url(credit_id)}"' in html
    assert "Save Changes" in html
    assert 'href="/profile"' in html
    assert 'name="category"' not in html


def test_edit_form_with_null_description_is_empty(auth_client, user_id):
    add_credit(user_id, 5, "Gift", "2026-05-01")
    target = saved_credits()[-1]["id"]
    html = auth_client.get(edit_url(target)).get_data(as_text=True)
    assert 'value=""' in html
    assert 'value="None"' not in html


def test_get_edit_changes_nothing(auth_client, credit_id):
    before = saved_credits()
    assert auth_client.get(edit_url(credit_id)).status_code == 200
    assert saved_credits() == before


def test_valid_edit_updates_only_that_row(auth_client, user_id, credit_id):
    sibling = insert(user_id, description="Sibling")
    before = {row["id"]: row for row in saved_credits()}
    response = auth_client.post(edit_url(credit_id), data=VALID)
    assert response.status_code == 302
    assert response.headers["Location"] == "/profile"
    after = {row["id"]: row for row in saved_credits()}
    assert after[sibling] == before[sibling]
    assert set(after) == set(before)
    assert after[credit_id] == {
        **before[credit_id],
        "amount": 2500.50,
        "source": "Salary",
        "date": "2026-06-02",
        "description": "June pay",
    }


def test_edit_keeps_user_id_and_created_at_and_ignores_forged_fields(
    auth_client, user_id, other_id, credit_id
):
    forged = {"id": "777", "user_id": str(other_id), "created_at": "2030-01-01"}
    auth_client.post(edit_url(credit_id), data={**VALID, **forged})
    [row] = saved_credits()
    assert row["id"] == credit_id
    assert row["user_id"] == user_id
    assert row["created_at"] == OLD_TIMESTAMP


def test_edit_success_flashes_updated_message(auth_client, credit_id):
    response = auth_client.post(edit_url(credit_id), data=VALID, follow_redirects=True)
    html = response.get_data(as_text=True)
    assert "Credit updated successfully." in html
    assert "June pay" in section(html, "credit-heading")
    assert "Credit updated successfully." not in profile_html(auth_client)


def test_unchanged_edit_succeeds(auth_client, credit_id):
    before = saved_credits()
    data = {
        "amount": "1000.00",
        "source": "Freelance",
        "date": "2026-05-01",
        "description": "Project",
    }
    response = auth_client.post(edit_url(credit_id), data=data, follow_redirects=True)
    assert "Credit updated successfully." in response.get_data(as_text=True)
    assert saved_credits() == before


# ---- Delete ----------------------------------------------------------- #


def test_confirmation_page_shows_details_and_changes_nothing(auth_client, user_id):
    target = insert(
        user_id,
        amount=1234567.5,
        source="Interest",
        date="2026-09-05",
        description="Bank",
    )
    before = saved_credits()
    response = auth_client.get(delete_url(target))
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "₹1,234,567.50" in html
    assert "Interest" in html
    assert "September 5, 2026" in html
    assert "Bank" in html
    assert "undone" in html.lower()
    assert "Delete Credit" in html
    assert re.search(
        r'<form[^>]*method="post"[^>]*action="%s"' % delete_url(target), html, re.I
    )
    assert "Cancel" in html
    assert 'href="/profile"' in html
    assert saved_credits() == before


def test_confirmation_page_null_description_shows_placeholder(auth_client, user_id):
    add_credit(user_id, 5, "Gift", "2026-05-01")
    target = saved_credits()[-1]["id"]
    html = auth_client.get(delete_url(target)).get_data(as_text=True)
    assert "No description" in html
    assert "None" not in html


def test_head_and_cancel_target_delete_nothing(auth_client, credit_id):
    before = saved_credits()
    auth_client.head(delete_url(credit_id))
    assert auth_client.get("/profile").status_code == 200
    assert saved_credits() == before


def test_confirm_deletes_only_that_credit_and_flashes(
    auth_client, user_id, other_id, credit_id
):
    sibling = insert(user_id, description="Sibling")
    foreign = insert(other_id, description="Theirs")
    expense = insert_expense(user_id)
    before = {row["id"]: row for row in saved_credits()}
    expenses_before = saved_expenses()
    response = auth_client.post(delete_url(credit_id), data={"user_id": str(other_id)})
    assert response.status_code == 302
    assert response.headers["Location"] == "/profile"
    after = {row["id"]: row for row in saved_credits()}
    assert set(after) == {sibling, foreign}
    assert after[sibling] == before[sibling]
    assert after[foreign] == before[foreign]
    assert saved_expenses() == expenses_before
    assert expense
    assert "Credit deleted successfully." in profile_html(auth_client)
    assert "Credit deleted successfully." not in profile_html(auth_client)


def test_second_delete_submission_is_404_and_deletes_nothing_else(
    auth_client, user_id, credit_id
):
    sibling = insert(user_id, description="Sibling")
    assert auth_client.post(delete_url(credit_id)).status_code == 302
    before = saved_credits()
    assert auth_client.post(delete_url(credit_id)).status_code == 404
    assert saved_credits() == before
    assert [row["id"] for row in before] == [sibling]


def test_edit_page_for_deleted_credit_is_404(auth_client, credit_id):
    auth_client.post(delete_url(credit_id))
    assert auth_client.get(edit_url(credit_id)).status_code == 404


# ---- Expense / credit isolation --------------------------------------- #


@pytest.fixture()
def same_id_pair(user_id):
    expense = insert_expense(user_id, description="Expense row")
    credit = insert(user_id, description="Credit row")
    assert expense == credit, "precondition: shared id"
    return expense


def test_editing_credit_leaves_expense_unchanged(auth_client, same_id_pair):
    before = saved_expenses()
    auth_client.post(edit_url(same_id_pair), data=VALID)
    assert saved_expenses() == before
    assert saved_credits()[0]["description"] == "June pay"


def test_deleting_credit_leaves_expense_unchanged(auth_client, same_id_pair):
    before = saved_expenses()
    auth_client.post(delete_url(same_id_pair))
    assert saved_expenses() == before
    assert saved_credits() == []


def test_editing_expense_leaves_credit_unchanged(auth_client, same_id_pair):
    before = saved_credits()
    data = {
        "amount": "9",
        "category": "Bills",
        "date": "2026-07-01",
        "description": "x",
    }
    response = auth_client.post(f"/expenses/{same_id_pair}/edit", data=data)
    assert response.status_code == 302
    assert saved_credits() == before
    assert saved_expenses()[0]["category"] == "Bills"


def test_deleting_expense_leaves_credit_unchanged(auth_client, same_id_pair):
    before = saved_credits()
    auth_client.post(f"/expenses/{same_id_pair}/delete")
    assert saved_credits() == before
    assert saved_expenses() == []


# ---- Profile: stats unchanged ----------------------------------------- #


def test_credit_add_edit_delete_leave_stats_and_breakdown_identical(
    auth_client, user_id
):
    insert_expense(user_id, amount=45.5, category="Food")
    insert_expense(user_id, amount=10, category="Bills", description="Power")
    baseline = stats_and_categories(profile_html(auth_client))

    auth_client.post(ADD_URL, data=VALID)
    assert stats_and_categories(profile_html(auth_client)) == baseline

    target = saved_credits()[-1]["id"]
    auth_client.post(
        edit_url(target), data={**VALID, "amount": "99999", "source": "Gift"}
    )
    assert stats_and_categories(profile_html(auth_client)) == baseline

    auth_client.post(delete_url(target))
    assert saved_credits() == []
    assert stats_and_categories(profile_html(auth_client)) == baseline


def test_stats_with_only_credits_show_no_spending(auth_client, user_id):
    insert(user_id, amount=5000)
    html = profile_html(auth_client)
    assert "₹0.00" in html
    stats, categories = stats_and_categories(html)
    assert "₹5,000.00" not in stats
    assert "₹5,000.00" not in categories


# ---- Profile: list ---------------------------------------------------- #


def test_profile_shows_add_credit_button_beside_add_expense(auth_client):
    html = profile_html(auth_client)
    assert "+ Add Expense" in html
    assert "+ Add Credit" in html
    assert 'href="/credits/add"' in html
    assert html.index("+ Add Expense") < html.index("+ Add Credit")
    assert html.index("+ Add Credit") - html.index("+ Add Expense") < 400


def test_profile_css_handles_button_group_at_600px():
    css = (
        Path(__file__).resolve().parent.parent / "static/css/profile.css"
    ).read_text()
    narrow = css.split("@media (max-width: 600px)", 1)
    assert len(narrow) == 2, "expected a 600px breakpoint"
    assert ".profile-actions" in narrow[1]
    assert "#" not in "".join(re.findall(r"\.btn-add-credit[^}]*}", css)).replace(
        "&#", ""
    ), "credit button must use CSS variables, not hex values"


def test_credits_section_has_heading_and_credit_rows(auth_client, user_id):
    insert(
        user_id, amount=1234.5, source="Gift", date="2026-05-01", description="Birthday"
    )
    block = credits_section(auth_client)
    assert "Recent Credits" in block
    assert "Birthday" in block
    assert "₹1,234.50" in block
    assert "May 1, 2026" in block
    assert "Gift" in block
    for header in ("Date", "Description", "Source", "Amount", "Actions"):
        assert f">{header}</th>" in block
    assert ">Category</th>" not in block


def test_column_headers_five_without_credits_ten_with_one_expense_and_one_credit(
    auth_client, user_id
):
    insert_expense(user_id)
    assert profile_html(auth_client).count('role="columnheader"') == 5
    insert(user_id)
    assert profile_html(auth_client).count('role="columnheader"') == 10


def test_credits_table_keeps_explicit_aria_roles(auth_client, user_id):
    insert(user_id)
    block = credits_section(auth_client)
    assert 'role="table"' in block
    assert block.count('role="rowgroup"') == 2
    assert 'role="row"' in block
    assert 'role="cell"' in block
    assert block.count('role="columnheader"') == 5


def test_credit_action_links_have_exact_aria_labels(auth_client, user_id):
    with_desc = insert(user_id, amount=1234.5, source="Gift", description="Birthday")
    no_desc_id = None
    add_credit(user_id, 7, "Refund", "2026-05-01")
    no_desc_id = saved_credits()[-1]["id"]
    html = profile_html(auth_client)
    assert 'aria-label="Edit credit Birthday, ₹1,234.50, May 1, 2026"' in html
    assert 'aria-label="Delete credit Birthday, ₹1,234.50, May 1, 2026"' in html
    assert 'aria-label="Edit credit Refund, ₹7.00, May 1, 2026"' in html
    assert 'aria-label="Delete credit Refund, ₹7.00, May 1, 2026"' in html
    for target in (with_desc, no_desc_id):
        assert 'class="tx-edit"' in action_tag(html, edit_url(target), "tx-edit")
        assert "tx-delete" in action_tag(html, delete_url(target), "tx-delete")


def test_credit_action_icons_have_no_visible_text(auth_client, user_id):
    target = insert(user_id)
    block = credits_section(auth_client)
    match = re.search(
        rf'<a\b[^>]*href="{re.escape(delete_url(target))}"[^>]*>(.*?)</a>', block, re.S
    )
    assert match
    inner = match.group(1)
    assert "<svg" in inner
    assert re.sub(r"<svg.*?</svg>", "", inner, flags=re.S).strip() == ""


def test_credits_section_does_not_use_category_colour_classes(auth_client, user_id):
    for source in sorted(SOURCES):
        insert(user_id, source=source, description=source)
    block = credits_section(auth_client)
    assert "cat-" not in block


def test_null_description_is_shown_as_placeholder(auth_client, user_id):
    add_credit(user_id, 5, "Gift", "2026-05-01")
    block = credits_section(auth_client)
    assert "No description" in block
    assert "None" not in block


def test_credits_newest_first_with_id_tiebreak(auth_client, user_id):
    insert(user_id, date="2026-05-01", description="old-one")
    insert(user_id, date="2026-05-03", description="same-day-first")
    insert(user_id, date="2026-05-03", description="same-day-second")
    insert(user_id, date="2026-05-02", description="middle-one")
    block = credits_section(auth_client)
    order = [
        block.index(name)
        for name in ("same-day-second", "same-day-first", "middle-one", "old-one")
    ]
    assert order == sorted(order), "expected date DESC then id DESC"


def test_twelve_credits_listed_behind_see_more(auth_client, user_id):
    for day in range(1, 13):
        insert(user_id, date=f"2026-05-{day:02d}", description=f"entry-{day:02d}")
    block = credits_section(auth_client)
    assert block.count('class="tx-edit"') == 12
    assert "See more+" in block
    assert "entry-12" in block
    assert "entry-01" in block


def test_no_see_more_when_five_or_fewer_credits(auth_client, user_id):
    for day in range(1, 6):
        insert(user_id, date=f"2026-05-{day:02d}")
    block = credits_section(auth_client)
    assert block.count('class="tx-edit"') == 5
    assert "See more+" not in block


def test_users_see_only_their_own_credits(auth_client, user_id, other_id):
    insert(user_id, description="Mine")
    foreign = insert(other_id, amount=777, description="Theirs")
    html = profile_html(auth_client)
    block = section(html, "credit-heading")
    assert "Mine" in block
    assert "Theirs" not in html
    assert f'href="{edit_url(foreign)}"' not in html
    assert f'href="{delete_url(foreign)}"' not in html
    assert "See more+" not in block


# ---- Profile: date filter and empty states ---------------------------- #


def test_date_filter_bounds_are_inclusive_for_credits(auth_client, user_id):
    for date, name in [
        ("2026-04-30", "before-range"),
        ("2026-05-01", "first-day"),
        ("2026-05-15", "mid-month"),
        ("2026-05-31", "last-day"),
        ("2026-06-01", "after-range"),
    ]:
        insert(user_id, date=date, description=name)
    block = credits_section(auth_client, "?from=2026-05-01&to=2026-05-31")
    for name in ("first-day", "mid-month", "last-day"):
        assert name in block
    for name in ("before-range", "after-range"):
        assert name not in block


@pytest.mark.parametrize(
    "query, kept, dropped",
    [
        ("?from=2026-05-15", {"mid-month", "last-day"}, {"first-day"}),
        ("?to=2026-05-15", {"first-day", "mid-month"}, {"last-day"}),
    ],
)
def test_single_sided_date_filter_applies_to_credits(
    auth_client, user_id, query, kept, dropped
):
    for date, name in [
        ("2026-05-01", "first-day"),
        ("2026-05-15", "mid-month"),
        ("2026-05-31", "last-day"),
    ]:
        insert(user_id, date=date, description=name)
    block = credits_section(auth_client, query)
    assert all(name in block for name in kept)
    assert not any(name in block for name in dropped)


def test_date_filter_limits_the_credits_listed(auth_client, user_id):
    for day in range(1, 13):
        insert(user_id, date=f"2026-05-{day:02d}", description=f"in-{day:02d}")
    for date in ("2026-04-01", "2026-04-02", "2026-06-20"):
        insert(user_id, date=date, description="outside")
    block = credits_section(auth_client, "?from=2026-05-01&to=2026-05-31")
    assert block.count('class="tx-edit"') == 12
    assert "outside" not in block
    unfiltered = credits_section(auth_client)
    assert unfiltered.count('class="tx-edit"') == 15


def test_credits_empty_state_for_user_without_credits(auth_client, user_id):
    insert_expense(user_id)
    block = credits_section(auth_client)
    assert "No credits yet." in block
    assert 'href="/credits/add"' in block
    assert "<table" not in block


def test_credits_filtered_empty_state_links_to_all_time(auth_client, user_id):
    insert(user_id, date="2026-05-01")
    block = credits_section(auth_client, "?from=2027-01-01&to=2027-01-31")
    assert "No credits in this period." in block
    assert "Show all time" in block
    assert 'href="/profile"' in block
    assert "<table" not in block


def test_other_users_credits_do_not_hide_empty_state(auth_client, other_id):
    insert(other_id)
    assert "No credits yet." in credits_section(auth_client)


# ---- Escaping --------------------------------------------------------- #


def test_html_in_description_is_displayed_as_text(auth_client, user_id):
    target = insert(user_id, description='<script>x</script>"><b>Tom & Jerry</b>')
    for path in ("/profile", edit_url(target), delete_url(target)):
        html = auth_client.get(path).get_data(as_text=True)
        assert "<script>x" not in html, path
        assert "<b>Tom" not in html, path
    assert "&lt;script&gt;x&lt;/script&gt;" in credits_section(auth_client)


def test_aria_label_escapes_quotes_and_markup(auth_client, user_id):
    target = insert(user_id, description='<i>A&B</i>" onfocus="alert(1)')
    html = profile_html(auth_client)
    tag = action_tag(html, delete_url(target), "tx-delete")
    assert ' onfocus="' not in tag
    assert "<i>" not in tag
    assert "&lt;i&gt;A&amp;B&lt;/i&gt;" in tag


def test_html_in_failed_submission_is_escaped_when_redisplayed(auth_client):
    data = {**VALID, "amount": "0", "description": '"><script>y</script>'}
    html = auth_client.post(ADD_URL, data=data).get_data(as_text=True)
    assert "<script>y" not in html


# ---- Expense pages unchanged ------------------------------------------ #


def test_add_expense_page_still_uses_category(auth_client):
    html = auth_client.get("/expenses/add").get_data(as_text=True)
    for field in ("amount", "category", "date", "description"):
        assert f'name="{field}"' in html
    assert 'name="source"' not in html
    assert '<option value="Food"' in html
    assert '<option value="Salary"' not in html


def test_edit_expense_page_still_uses_category(auth_client, user_id):
    target = insert_expense(user_id)
    html = auth_client.get(f"/expenses/{target}/edit").get_data(as_text=True)
    assert 'name="category"' in html
    assert 'name="source"' not in html
    assert '<option value="Food" selected>' in html


@pytest.mark.parametrize("bad", ["Salary", "", "Rent"])
def test_expense_add_still_reports_category_error(auth_client, bad):
    data = {"amount": "10", "category": bad, "date": "2026-05-01", "description": "x"}
    html = auth_client.post("/expenses/add", data=data).get_data(as_text=True)
    assert "Please select a valid category." in html
    assert "Please select a valid source." not in html
    assert saved_expenses() == []


def test_expense_edit_still_reports_category_error(auth_client, user_id):
    target = insert_expense(user_id)
    data = {
        "amount": "10",
        "category": "Salary",
        "date": "2026-05-01",
        "description": "x",
    }
    html = auth_client.post(f"/expenses/{target}/edit", data=data).get_data(
        as_text=True
    )
    assert "Please select a valid category." in html
    assert "Please select a valid source." not in html
    assert saved_expenses()[0]["category"] == "Food"


def test_expense_add_still_works_and_does_not_touch_credits(auth_client, user_id):
    data = {
        "amount": "10",
        "category": "Bills",
        "date": "2026-05-01",
        "description": "x",
    }
    assert auth_client.post("/expenses/add", data=data).status_code == 302
    assert len(saved_expenses()) == 1
    assert saved_credits() == []
