"""Tests for Step 8 — GET/POST /expenses/<id>/edit."""

from contextlib import closing

import pytest

import database.db as db_module
from app import app as flask_app
from database.db import (
    add_expense,
    create_user,
    get_db,
    get_expense,
    get_user_by_email,
    init_db,
    update_expense,
)

EMAIL = "editor@spendly.test"
OTHER_EMAIL = "other@spendly.test"
OLD_TIMESTAMP = "2020-01-01 00:00:00"
VALID = {
    "amount": "99.90",
    "category": "Health",
    "date": "2026-06-02",
    "description": "Pharmacy",
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setitem(flask_app.config, "TESTING", True)
    init_db()
    create_user("Editor", EMAIL, "editorpass")
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


def insert(user_id, amount=45.5, category="Food", date="2026-05-01", description=None):
    add_expense(user_id, amount, category, date, description)
    with closing(get_db()) as conn, conn:
        conn.execute("UPDATE expenses SET created_at = ?", (OLD_TIMESTAMP,))
    return saved_expenses()[-1]["id"]


@pytest.fixture()
def expense_id(user_id):
    return insert(user_id, description="Lunch")


def url(expense_id):
    return f"/expenses/{expense_id}/edit"


def send(client, method, expense_id, data=VALID):
    if method == "get":
        return client.get(url(expense_id))
    return client.post(url(expense_id), data=data)


both_methods = pytest.mark.parametrize("method", ["get", "post"])


# ---- Access ---------------------------------------------------------- #


@both_methods
def test_logged_out_redirects_to_login(client, expense_id, method):
    before = saved_expenses()
    for target in (expense_id, 9999):
        response = send(client, method, target)
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
@pytest.mark.parametrize("data", [VALID, {**VALID, "amount": "-1"}])
def test_other_users_expense_is_404(auth_client, other_id, method, data):
    target = insert(other_id, description="Private")
    before = saved_expenses()
    response = send(auth_client, method, target, data)
    assert response.status_code == 404
    assert "Private" not in response.get_data(as_text=True)
    assert saved_expenses() == before


def test_expense_deleted_before_save_is_404(auth_client, expense_id, monkeypatch):
    monkeypatch.setattr("app.db_update_expense", lambda *args: False)
    assert auth_client.post(url(expense_id), data=VALID).status_code == 404


# ---- Prefill --------------------------------------------------------- #


def test_form_is_prefilled(auth_client, expense_id):
    response = auth_client.get(url(expense_id))
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'value="45.50"' in html
    assert '<option value="Food" selected>' in html
    assert 'value="2026-05-01"' in html
    assert 'value="Lunch"' in html
    assert f'action="{url(expense_id)}"' in html
    assert "Save Changes" in html
    assert 'href="/profile"' in html


def test_null_description_is_empty(auth_client, user_id):
    html = auth_client.get(url(insert(user_id))).get_data(as_text=True)
    assert 'value=""' in html
    assert 'value="None"' not in html


def test_description_is_escaped(auth_client, user_id):
    target = insert(user_id, description='"><script>x</script>')
    for path in (url(target), "/profile"):
        assert "<script>x" not in auth_client.get(path).get_data(as_text=True)


def test_unknown_stored_category_requires_a_choice(auth_client, user_id):
    target = insert(user_id, category="Rent")
    html = auth_client.get(url(target)).get_data(as_text=True)
    assert '<option value="" disabled selected>' in html
    assert html.count(" selected>") == 1


# ---- Saving ---------------------------------------------------------- #


def test_valid_edit_updates_only_that_row(auth_client, user_id, expense_id):
    sibling = insert(user_id, description="Sibling")
    before = {row["id"]: row for row in saved_expenses()}
    response = auth_client.post(url(expense_id), data=VALID)
    assert response.status_code == 302
    assert response.headers["Location"] == "/profile"
    after = {row["id"]: row for row in saved_expenses()}
    assert after[sibling] == before[sibling]
    assert len(after) == len(before)
    assert after[expense_id] == {
        **before[expense_id],
        "amount": 99.90,
        "category": "Health",
        "date": "2026-06-02",
        "description": "Pharmacy",
    }


def test_forged_fields_are_ignored(auth_client, user_id, other_id, expense_id):
    forged = {"id": "777", "user_id": str(other_id), "created_at": "2030-01-01"}
    auth_client.post(url(expense_id), data={**VALID, **forged})
    [row] = saved_expenses()
    assert row["id"] == expense_id
    assert row["user_id"] == user_id
    assert row["created_at"] == OLD_TIMESTAMP
    assert row["description"] == "Pharmacy"


def test_unchanged_save_succeeds(auth_client, expense_id):
    before = saved_expenses()
    data = {
        "amount": "45.50",
        "category": "Food",
        "date": "2026-05-01",
        "description": "Lunch",
    }
    response = auth_client.post(url(expense_id), data=data, follow_redirects=True)
    assert "Expense updated successfully." in response.get_data(as_text=True)
    assert saved_expenses() == before


@pytest.mark.parametrize("description", ["", "   "])
def test_blank_description_is_saved_as_null(auth_client, expense_id, description):
    data = {**VALID, "description": description}
    assert auth_client.post(url(expense_id), data=data).status_code == 302
    assert saved_expenses()[0]["description"] is None


@pytest.mark.parametrize(
    "field, value, stored",
    [
        ("amount", "0.01", 0.01),
        ("amount", "10000000", 10_000_000),
        ("description", "x" * 200, "x" * 200),
        ("description", "'; DROP TABLE expenses;--", "'; DROP TABLE expenses;--"),
    ],
)
def test_allowed_values_are_saved(auth_client, expense_id, field, value, stored):
    auth_client.post(url(expense_id), data={**VALID, field: value})
    assert saved_expenses()[0][field] == stored


# ---- Validation ------------------------------------------------------ #


@pytest.mark.parametrize(
    "field, value, message",
    [
        *(
            ("amount", value, "Amount must be a positive number.")
            for value in ("", "0", "-5", "abc", "nan", "inf", "-inf", "1e999")
        ),
        ("amount", "0.001", "Amount must be between"),
        ("amount", "10000000.01", "Amount must be between"),
        *(
            ("category", value, "Please select a valid category.")
            for value in ("", "Rent", "food")
        ),
        *(
            ("date", value, "Date must be a valid date")
            for value in ("", "nope", "2026-02-30", "20260501", "2026-W18-5")
        ),
        ("description", "x" * 201, "Description must be 200 characters"),
    ],
)
def test_invalid_input_is_rejected(auth_client, expense_id, field, value, message):
    before = saved_expenses()
    data = {**VALID, field: value}
    response = auth_client.post(url(expense_id), data=data)
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert message in html
    assert "auth-error" in html
    assert "Expense updated successfully." not in html
    assert f'action="{url(expense_id)}"' in html
    for name in ("amount", "date", "description"):
        assert f'value="{data[name]}"' in html
    if field != "category":
        assert '<option value="Health" selected>' in html
    assert saved_expenses() == before


# ---- Profile --------------------------------------------------------- #


def test_profile_has_edit_link_per_row(auth_client, user_id, expense_id):
    second = insert(user_id, category="Bills")
    html = auth_client.get("/profile").get_data(as_text=True)
    for target in (expense_id, second):
        assert f'href="{url(target)}"' in html
    assert 'aria-label="Edit Lunch, ₹45.50, May 1, 2026"' in html
    assert 'aria-label="Edit Bills, ₹45.50, May 1, 2026"' in html
    assert html.count('role="columnheader"') == 5
    assert html.count('<td role="cell" class="tx-action">') == 2


def test_profile_reflects_edit(auth_client, expense_id):
    response = auth_client.post(url(expense_id), data=VALID, follow_redirects=True)
    html = response.get_data(as_text=True)
    assert "Expense updated successfully." in html
    assert '<span class="stat-value">₹99.90</span>' in html
    assert '<span class="stat-value">1</span>' in html
    assert '<span class="category-name">Health</span>' in html
    assert '<span class="category-name">Food</span>' not in html
    assert "₹45.50" not in html


def test_edited_date_moves_between_filters(auth_client, expense_id):
    auth_client.post(url(expense_id), data=VALID)
    may = auth_client.get("/profile?from=2026-05-01&to=2026-05-31")
    june = auth_client.get("/profile?from=2026-06-01&to=2026-06-30")
    assert "Pharmacy" not in may.get_data(as_text=True)
    assert "Pharmacy" in june.get_data(as_text=True)


# ---- Helpers --------------------------------------------------------- #


def test_get_expense_is_scoped_to_owner(user_id, other_id, expense_id):
    assert get_expense(expense_id, user_id)["description"] == "Lunch"
    assert get_expense(expense_id, other_id) is None
    assert get_expense(9999, user_id) is None


def test_update_expense_is_scoped_to_owner(user_id, other_id, expense_id):
    values = (45.5, "Food", "2026-05-01", "Lunch")
    before = saved_expenses()
    assert update_expense(expense_id, other_id, 1, "Bills", "2026-01-01") is False
    assert update_expense(9999, user_id, *values) is False
    assert update_expense(expense_id, user_id, *values) is True
    assert saved_expenses() == before


@pytest.mark.parametrize("missing", ["amount", "category", "date"])
def test_omitted_required_field_is_rejected(auth_client, expense_id, missing):
    before = saved_expenses()
    data = {name: value for name, value in VALID.items() if name != missing}
    response = auth_client.post(url(expense_id), data=data)
    assert response.status_code == 200
    assert "auth-error" in response.get_data(as_text=True)
    assert saved_expenses() == before


# ---- Added: audit against spec ---------------------------------------- #

import re  # noqa: E402
from pathlib import Path  # noqa: E402


def stat_value(html, label):
    """Return the stat-value text that follows the given stat-label."""
    pattern = (
        r'<span class="stat-label">' + re.escape(label) + r"</span>\s*"
        r'<span class="stat-value">([^<]*)</span>'
    )
    match = re.search(pattern, html)
    assert match, f"stat card {label!r} not found"
    return match.group(1)


@pytest.mark.parametrize("bad_category", ["Rent", "food", ""])
def test_invalid_category_keeps_submitted_value_not_stored(
    auth_client, expense_id, bad_category
):
    # Stored category is Food; the invalid submission must not fall back to it.
    before = saved_expenses()
    data = {**VALID, "category": bad_category}
    html = auth_client.post(url(expense_id), data=data).get_data(as_text=True)
    assert "Please select a valid category." in html
    assert '<option value="Food" selected>' not in html, "stored category leaked"
    assert '<option value="Health" selected>' not in html
    assert html.count(" selected>") <= 1, "at most the placeholder may be selected"
    for name in ("amount", "date", "description"):
        assert f'value="{VALID[name]}"' in html
    assert saved_expenses() == before


def test_other_field_failure_keeps_submitted_category_not_stored(
    auth_client, expense_id
):
    data = {**VALID, "category": "Bills", "amount": "abc"}
    html = auth_client.post(url(expense_id), data=data).get_data(as_text=True)
    assert "Amount must be a positive number." in html
    assert '<option value="Bills" selected>' in html
    assert '<option value="Food" selected>' not in html
    assert 'value="abc"' in html
    assert saved_expenses()[0]["category"] == "Food"


def test_failed_edit_does_not_flash_success_or_redirect(auth_client, expense_id):
    response = auth_client.post(url(expense_id), data={**VALID, "amount": "0"})
    assert response.status_code == 200
    assert "Location" not in response.headers
    profile = auth_client.get("/profile").get_data(as_text=True)
    assert "Expense updated successfully." not in profile


@pytest.mark.parametrize("amount, shown", [(5, "5.00"), (12.3, "12.30"), (0.5, "0.50")])
def test_amount_is_prefilled_with_two_decimals(auth_client, user_id, amount, shown):
    target = insert(user_id, amount=amount)
    html = auth_client.get(url(target)).get_data(as_text=True)
    assert f'value="{shown}"' in html


@pytest.mark.parametrize("category", ["Food", "Bills", "Health"])
def test_stored_category_is_the_selected_option(auth_client, user_id, category):
    target = insert(user_id, category=category)
    html = auth_client.get(url(target)).get_data(as_text=True)
    assert f'<option value="{category}" selected>' in html
    assert html.count(" selected>") == 1


def test_get_does_not_modify_expense(auth_client, expense_id):
    before = saved_expenses()
    assert auth_client.get(url(expense_id)).status_code == 200
    assert saved_expenses() == before


def test_success_flash_is_shown_only_once(auth_client, expense_id):
    first = auth_client.post(url(expense_id), data=VALID, follow_redirects=True)
    assert "Expense updated successfully." in first.get_data(as_text=True)
    second = auth_client.get("/profile")
    assert "Expense updated successfully." not in second.get_data(as_text=True)


@both_methods
def test_logged_out_invalid_data_still_redirects_without_validating(
    client, expense_id, method
):
    before = saved_expenses()
    response = send(client, method, expense_id, {**VALID, "amount": "-1"})
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"
    assert saved_expenses() == before


def test_logged_out_post_with_forged_user_id_changes_nothing(
    client, expense_id, other_id
):
    before = saved_expenses()
    data = {**VALID, "user_id": str(other_id)}
    response = client.post(url(expense_id), data=data)
    assert response.status_code == 302
    assert saved_expenses() == before


def test_other_users_expense_is_unchanged_and_forged_user_id_is_ignored(
    auth_client, user_id, other_id
):
    target = insert(other_id, description="Private")
    before = saved_expenses()
    data = {**VALID, "user_id": str(user_id)}
    assert auth_client.post(url(target), data=data).status_code == 404
    assert saved_expenses() == before


def test_edit_does_not_change_row_count(auth_client, user_id, expense_id):
    insert(user_id, description="Second")
    count = len(saved_expenses())
    auth_client.post(url(expense_id), data=VALID)
    assert len(saved_expenses()) == count


def test_profile_stats_and_breakdown_reflect_edit_with_multiple_rows(
    auth_client, user_id, expense_id
):
    insert(user_id, amount=10, category="Bills", description="Power")
    auth_client.post(url(expense_id), data={**VALID, "category": "Bills"})
    html = auth_client.get("/profile").get_data(as_text=True)
    assert stat_value(html, "Total Spent") == "₹109.90"
    assert stat_value(html, "Transactions") == "2"
    assert stat_value(html, "Top Category") == "Bills"
    assert '<span class="category-name">Bills</span>' in html
    assert '<span class="category-name">Food</span>' not in html
    assert '<span class="category-amt">₹109.90</span>' in html


def test_profile_transaction_count_is_exact_label_value(auth_client, expense_id):
    auth_client.post(url(expense_id), data=VALID)
    html = auth_client.get("/profile").get_data(as_text=True)
    assert stat_value(html, "Transactions") == "1"
    assert stat_value(html, "Total Spent") == "₹99.90"
    assert stat_value(html, "Top Category") == "Health"


def test_profile_edit_links_only_for_own_expenses(auth_client, other_id, expense_id):
    foreign = insert(other_id, description="Private")
    html = auth_client.get("/profile").get_data(as_text=True)
    assert f'href="{url(expense_id)}"' in html
    assert f'href="{url(foreign)}"' not in html


def test_profile_edit_link_label_uses_category_when_no_description(
    auth_client, user_id
):
    insert(user_id, category="Bills", amount=7)
    html = auth_client.get("/profile").get_data(as_text=True)
    assert 'aria-label="Edit Bills, ₹7.00, May 1, 2026"' in html


def test_profile_table_keeps_explicit_aria_roles(auth_client, expense_id):
    html = auth_client.get("/profile").get_data(as_text=True)
    assert 'role="table"' in html
    assert html.count('role="rowgroup"') == 2
    assert 'role="row"' in html
    assert 'role="cell"' in html


def test_profile_css_styles_edit_link_in_stacked_layout():
    css = (
        Path(__file__).resolve().parent.parent / "static/css/profile.css"
    ).read_text()
    assert ".tx-edit" in css, "Edit link must be styled"
    narrow = css.split("@media (max-width: 600px)", 1)
    assert len(narrow) == 2, "expected a 600px breakpoint"
    assert ".tx-action" in narrow[1], "Edit link must be styled at 600px and below"


def test_add_expense_page_still_works(auth_client, user_id):
    html = auth_client.get("/expenses/add").get_data(as_text=True)
    for field in ("amount", "category", "date", "description"):
        assert f'name="{field}"' in html
    assert "Save Changes" not in html
    response = auth_client.post("/expenses/add", data=VALID)
    assert response.status_code == 302
    [row] = saved_expenses()
    assert (row["user_id"], row["category"], row["description"]) == (
        user_id,
        "Health",
        "Pharmacy",
    )


def test_add_expense_rejects_invalid_amount_as_before(auth_client):
    response = auth_client.post("/expenses/add", data={**VALID, "amount": "0"})
    assert response.status_code == 200
    assert "auth-error" in response.get_data(as_text=True)
    assert saved_expenses() == []
