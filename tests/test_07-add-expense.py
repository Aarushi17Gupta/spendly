"""Tests for Step 7 — GET/POST /expenses/add."""

from contextlib import closing

import pytest

import database.db as db_module
from app import CATEGORIES, app as flask_app
from database.db import create_user, get_db, get_user_by_email, init_db

EMAIL = "adder@spendly.test"
VALID = {
    "amount": "42.50",
    "category": "Food",
    "date": "2026-05-01",
    "description": "Lunch with team",
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setitem(flask_app.config, "TESTING", True)
    init_db()
    create_user("Adder", EMAIL, "adderpass")
    return flask_app.test_client()


@pytest.fixture()
def user_id(client):
    return get_user_by_email(EMAIL)["id"]


@pytest.fixture()
def auth_client(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
    return client


def saved_expenses():
    with closing(get_db()) as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM expenses")]


@pytest.mark.parametrize("method", ["get", "post"])
def test_logged_out_redirects_to_login(client, method):
    response = getattr(client, method)("/expenses/add")
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"
    assert saved_expenses() == []


def test_form_renders_all_fields(auth_client):
    response = auth_client.get("/expenses/add")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    for field in VALID:
        assert f'name="{field}"' in html
    for category in CATEGORIES:
        assert f'value="{category}"' in html


def test_valid_expense_is_saved_for_session_user(auth_client, user_id):
    response = auth_client.post("/expenses/add", data={**VALID, "user_id": "999"})
    assert response.status_code == 302
    assert response.headers["Location"] == "/profile"
    [row] = saved_expenses()
    assert row["user_id"] == user_id
    assert row["amount"] == 42.50
    assert row["category"] == "Food"
    assert row["date"] == "2026-05-01"
    assert row["description"] == "Lunch with team"


def test_new_expense_appears_on_profile(auth_client):
    response = auth_client.post("/expenses/add", data=VALID, follow_redirects=True)
    assert response.status_code == 200
    assert "Lunch with team" in response.get_data(as_text=True)


@pytest.mark.parametrize("description", ["", "   "])
def test_blank_description_is_saved_as_null(auth_client, description):
    response = auth_client.post(
        "/expenses/add", data={**VALID, "description": description}
    )
    assert response.status_code == 302
    assert saved_expenses()[0]["description"] is None


@pytest.mark.parametrize("category", CATEGORIES)
def test_every_category_is_accepted(auth_client, category):
    auth_client.post("/expenses/add", data={**VALID, "category": category})
    assert saved_expenses()[0]["category"] == category


@pytest.mark.parametrize(
    "amount", ["", "0", "-5", "abc", "nan", "NaN", "inf", "-inf", "Infinity", "1e999"]
)
def test_invalid_amount_is_rejected(auth_client, amount):
    response = auth_client.post("/expenses/add", data={**VALID, "amount": amount})
    assert response.status_code == 200
    assert "Amount must be a positive number." in response.get_data(as_text=True)
    assert saved_expenses() == []


@pytest.mark.parametrize(
    "date",
    ["", "not-a-date", "2026-02-30", "01-05-2026", "20260501", "2026-W18-5", "2026W185"],
)
def test_invalid_date_is_rejected(auth_client, date):
    response = auth_client.post("/expenses/add", data={**VALID, "date": date})
    assert response.status_code == 200
    assert "Date must be a valid date" in response.get_data(as_text=True)
    assert saved_expenses() == []


@pytest.mark.parametrize("category", ["", "Rent", "food"])
def test_invalid_category_is_rejected(auth_client, category):
    response = auth_client.post("/expenses/add", data={**VALID, "category": category})
    assert response.status_code == 200
    assert "Please select a valid category." in response.get_data(as_text=True)
    assert saved_expenses() == []


@pytest.mark.parametrize("bad", [{"amount": "-5"}, {"date": "nope"}, {"category": "Rent"}])
def test_input_is_preserved_after_error(auth_client, bad):
    html = auth_client.post("/expenses/add", data={**VALID, **bad}).get_data(as_text=True)
    expected = {**VALID, **bad}
    for field in ("amount", "date", "description"):
        assert f'value="{expected[field]}"' in html
    if "category" not in bad:
        assert '<option value="Food" selected>' in html


def test_sql_in_description_is_stored_literally(auth_client):
    payload = "x'); DROP TABLE expenses; --"
    auth_client.post("/expenses/add", data={**VALID, "description": payload})
    assert saved_expenses()[0]["description"] == payload


def test_success_flash_shown_after_valid_add(auth_client):
    response = auth_client.post("/expenses/add", data=VALID, follow_redirects=True)
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Expense added successfully." in html, "Expected success flash on profile"


def test_success_flash_not_shown_after_failed_add(auth_client):
    response = auth_client.post("/expenses/add", data={**VALID, "amount": "0"})
    assert "Expense added successfully." not in response.get_data(as_text=True)


def test_add_expense_helper_without_description_stores_null(client, user_id):
    db_module.add_expense(user_id, 12.0, "Other", "2026-05-02")
    [row] = saved_expenses()
    assert row["description"] is None
    assert row["user_id"] == user_id
    assert row["amount"] == 12.0
    assert row["category"] == "Other"
    assert row["date"] == "2026-05-02"


def test_add_expense_helper_with_description_stores_it(client, user_id):
    db_module.add_expense(user_id, 3.5, "Bills", "2026-05-03", "Water")
    assert saved_expenses()[0]["description"] == "Water"


def test_profile_ignores_non_canonical_from_to_filters(auth_client, user_id):
    db_module.add_expense(user_id, 10.0, "Food", "2026-04-01", "EarlyMarker")
    db_module.add_expense(user_id, 20.0, "Food", "2026-06-15", "LateMarker")
    unfiltered = auth_client.get("/profile").get_data(as_text=True)
    assert "EarlyMarker" in unfiltered and "LateMarker" in unfiltered
    for params in ("from=20260501", "to=20260501", "from=20260501&to=20260502"):
        response = auth_client.get(f"/profile?{params}")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "EarlyMarker" in html and "LateMarker" in html, (
            f"Non-canonical filter {params} should be ignored"
        )
        assert html == unfiltered, f"Page for {params} should equal unfiltered page"


def test_profile_canonical_filter_differs_from_unfiltered(auth_client, user_id):
    """Control for the non-canonical test: a valid filter does narrow results."""
    db_module.add_expense(user_id, 10.0, "Food", "2026-04-01", "EarlyMarker")
    db_module.add_expense(user_id, 20.0, "Food", "2026-06-15", "LateMarker")
    html = auth_client.get("/profile?from=2026-05-01").get_data(as_text=True)
    assert "LateMarker" in html
    assert "EarlyMarker" not in html


@pytest.mark.parametrize("missing", ["amount", "category", "date"])
def test_missing_required_field_is_rejected(auth_client, missing):
    data = {k: v for k, v in VALID.items() if k != missing}
    response = auth_client.post("/expenses/add", data=data)
    assert response.status_code == 200
    assert saved_expenses() == []


def test_post_with_no_form_data_is_rejected(auth_client):
    response = auth_client.post("/expenses/add", data={})
    assert response.status_code == 200
    assert saved_expenses() == []


def test_missing_description_field_is_allowed(auth_client):
    data = {k: v for k, v in VALID.items() if k != "description"}
    response = auth_client.post("/expenses/add", data=data)
    assert response.status_code == 302
    assert response.headers["Location"] == "/profile"
    assert saved_expenses()[0]["description"] is None


def test_description_surrounding_whitespace_is_trimmed(auth_client):
    response = auth_client.post(
        "/expenses/add", data={**VALID, "description": "  Lunch  "}
    )
    assert response.status_code == 302
    assert saved_expenses()[0]["description"] == "Lunch"


def test_created_at_is_populated(auth_client):
    auth_client.post("/expenses/add", data=VALID)
    assert saved_expenses()[0]["created_at"], "created_at should be set"


def test_only_one_row_created_per_post(auth_client):
    auth_client.post("/expenses/add", data=VALID)
    assert len(saved_expenses()) == 1


@pytest.mark.parametrize("amount", ["0.01", "1", "999999.99"])
def test_valid_positive_amounts_are_accepted(auth_client, amount):
    response = auth_client.post("/expenses/add", data={**VALID, "amount": amount})
    assert response.status_code == 302
    assert saved_expenses()[0]["amount"] == float(amount)


def test_category_preserved_after_non_category_error(auth_client):
    html = auth_client.post(
        "/expenses/add", data={**VALID, "category": "Health", "amount": "-1"}
    ).get_data(as_text=True)
    assert '<option value="Health" selected>' in html


def test_multiple_errors_do_not_save_anything(auth_client):
    response = auth_client.post(
        "/expenses/add",
        data={"amount": "-1", "category": "Rent", "date": "bad", "description": "x"},
    )
    assert response.status_code == 200
    assert saved_expenses() == []


def test_expense_not_visible_to_other_user(client, auth_client):
    create_user("Other", "other@spendly.test", "otherpass")
    auth_client.post("/expenses/add", data=VALID)
    other_id = get_user_by_email("other@spendly.test")["id"]
    with client.session_transaction() as sess:
        sess["user_id"] = other_id
    html = client.get("/profile").get_data(as_text=True)
    assert "Lunch with team" not in html


@pytest.mark.parametrize("method", ["get", "post"])
def test_session_for_deleted_user_is_cleared(client, method):
    with client.session_transaction() as sess:
        sess["user_id"] = 9999
    response = getattr(client, method)("/expenses/add", data=VALID)
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"
    with client.session_transaction() as sess:
        assert "user_id" not in sess
    assert saved_expenses() == []


@pytest.mark.parametrize("amount", ["0.001", "0.0099", "10000000.01", "1e308"])
def test_out_of_range_amount_is_rejected(auth_client, amount):
    response = auth_client.post("/expenses/add", data={**VALID, "amount": amount})
    assert response.status_code == 200
    assert "Amount must be between" in response.get_data(as_text=True)
    assert saved_expenses() == []


def test_maximum_amount_is_accepted(auth_client):
    auth_client.post("/expenses/add", data={**VALID, "amount": "10000000"})
    assert saved_expenses()[0]["amount"] == 10_000_000


def test_profile_survives_rejected_huge_amounts(auth_client):
    for _ in range(2):
        auth_client.post("/expenses/add", data={**VALID, "amount": "1e308"})
    assert auth_client.get("/profile").status_code == 200


def test_description_at_limit_is_accepted(auth_client):
    auth_client.post("/expenses/add", data={**VALID, "description": "x" * 200})
    assert saved_expenses()[0]["description"] == "x" * 200


def test_too_long_description_is_rejected(auth_client):
    response = auth_client.post(
        "/expenses/add", data={**VALID, "description": "x" * 201}
    )
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Description must be 200 characters or fewer." in html
    assert "x" * 201 in html
    assert saved_expenses() == []


def test_form_exposes_limits(auth_client):
    html = auth_client.get("/expenses/add").get_data(as_text=True)
    assert 'min="0.01" max="10000000"' in html
    assert 'maxlength="200"' in html


@pytest.mark.parametrize("path", ["/profile", "/analytics"])
def test_deleted_user_session_is_cleared_on_other_pages(client, path):
    with client.session_transaction() as sess:
        sess["user_id"] = 9999
    response = client.get(path)
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"
    with client.session_transaction() as sess:
        assert "user_id" not in sess
