"""Tests for Step 12 — savings: GET/POST /savings/add, /savings/<id>/edit, /savings/<id>/delete."""

import re
import sqlite3
from contextlib import closing

import pytest

import database.db as db_module
from app import app as flask_app
from database.db import (
    add_credit,
    add_expense,
    add_saving,
    create_user,
    delete_saving,
    get_db,
    get_saving,
    get_user_by_email,
    init_db,
    update_saving,
)
from database.queries import (
    get_recent_savings,
    get_savings_breakdown,
    get_savings_summary,
)

EMAIL = "savings@spendly.test"
OTHER_EMAIL = "other@spendly.test"
OLD_TIMESTAMP = "2020-01-01 00:00:00"
TYPES = [
    "FD",
    "RD",
    "SIP",
    "EPF",
    "VPF",
    "PPF",
    "NPS",
    "Mutual Fund",
    "Stocks/ETF",
    "Bonds",
    "Sukanya Samriddhi",
    "NSC",
    "KVP",
    "SCSS",
    "Post Office MIS",
    "Gold",
    "Emergency Fund",
    "Other",
]
PAID_FROM = [
    "My account",
    "Salary deduction/employer",
    "Already saved before Spendly",
]
VALID = {
    "amount": "5000.50",
    "type": "SIP",
    "date": "2026-06-02",
    "paid_from": "Salary deduction/employer",
    "description": "June SIP",
    "institution": "HDFC Fund",
    "interest_rate": "12.5",
    "maturity_date": "2030-06-02",
}
ADD_URL = "/savings/add"
COLUMNS = {
    "id",
    "user_id",
    "amount",
    "type",
    "date",
    "description",
    "institution",
    "interest_rate",
    "maturity_date",
    "paid_from",
    "created_at",
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setitem(flask_app.config, "TESTING", True)
    init_db()
    create_user("Savings", EMAIL, "savingspass")
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


def rows(table):
    with closing(get_db()) as conn:
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY id")]


def saved_savings():
    return rows("savings")


def saved_credits():
    return rows("credits")


def saved_expenses():
    return rows("expenses")


def insert(
    user_id,
    amount=1000,
    type="PPF",
    date="2026-05-01",
    paid_from="My account",
    description="Deposit",
    institution="SBI",
    interest_rate=7.1,
    maturity_date="2030-05-01",
):
    add_saving(
        user_id,
        amount,
        type,
        date,
        paid_from,
        description,
        institution,
        interest_rate,
        maturity_date,
    )
    with closing(get_db()) as conn, conn:
        conn.execute("UPDATE savings SET created_at = ?", (OLD_TIMESTAMP,))
    return saved_savings()[-1]["id"]


def insert_bare(user_id, amount=7, type="NPS", date="2026-05-01"):
    add_saving(user_id, amount, type, date, "My account")
    return saved_savings()[-1]["id"]


def insert_expense(
    user_id, amount=45.5, category="Food", date="2026-05-01", description="Lunch"
):
    add_expense(user_id, amount, category, date, description)
    return saved_expenses()[-1]["id"]


def insert_credit(user_id, amount=1000, source="Freelance", date="2026-05-01"):
    add_credit(user_id, amount, source, date, "Project")
    return saved_credits()[-1]["id"]


@pytest.fixture()
def saving_id(user_id):
    return insert(user_id)


def edit_url(saving_id):
    return f"/savings/{saving_id}/edit"


def delete_url(saving_id):
    return f"/savings/{saving_id}/delete"


def section(html, heading_id):
    match = re.search(
        rf'<section[^>]*aria-labelledby="{heading_id}".*?</section>', html, re.S
    )
    assert match, f"section {heading_id!r} not found"
    return match.group(0)


def stats_section(html):
    stats = re.search(r'<section[^>]*class="profile-stats".*?</section>', html, re.S)
    assert stats, "stats section not found"
    return stats.group(0)


def spending_view(html):
    """Stats text with the Total Saved card (label and value) removed."""
    tokens = re.sub(r"<[^>]+>", " ", stats_section(html)).split()
    for i in range(len(tokens) - 2):
        if tokens[i] == "Total" and tokens[i + 1] == "Saved":
            assert tokens[i + 2].startswith("₹"), "Total Saved value not found"
            del tokens[i : i + 3]
            break
    else:
        pytest.fail("Total Saved card not found")
    return tokens


def profile_html(client, query=""):
    response = client.get("/profile" + query)
    assert response.status_code == 200
    return response.get_data(as_text=True)


def savings_section(client, query=""):
    return section(profile_html(client, query), "saving-heading")


def action_tag(html, href, css_class):
    pattern = rf'<a\b[^>]*href="{re.escape(href)}"[^>]*>'
    for tag in re.findall(pattern, html):
        if css_class in tag:
            return tag
    pytest.fail(f"no {css_class} link for {href}")


def is_chosen(html, name, value):
    """True if the option/radio `value` of field `name` is selected/checked."""
    for tag in re.findall(r"<(?:option|input)\b[^>]*>", html):
        if f'value="{value}"' not in tag:
            continue
        if not re.search(r"\b(selected|checked)\b", tag):
            continue
        if tag.startswith("<option") or f'name="{name}"' in tag:
            return True
    return False


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


def submit(client, mode, saving_id, data):
    path = ADD_URL if mode == "add" else edit_url(saving_id)
    return client.post(path, data=data)


# ---- Database --------------------------------------------------------- #


def test_init_db_on_old_schema_adds_savings_table_and_keeps_rows(client, user_id):
    insert_expense(user_id, description="Keep me")
    insert_credit(user_id)
    with closing(get_db()) as conn, conn:
        conn.execute("DROP TABLE savings")
    users_before = rows("users")
    expenses_before = saved_expenses()
    credits_before = saved_credits()
    with closing(sqlite3.connect(db_module.DB_PATH)) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert "savings" not in names, "precondition: old schema has no savings table"

    init_db()
    init_db()

    with closing(sqlite3.connect(db_module.DB_PATH)) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert "savings" in names
    assert saved_savings() == []
    assert saved_expenses() == expenses_before
    assert saved_credits() == credits_before
    assert rows("users") == users_before
    add_saving(user_id, 1, "FD", "2026-05-01", "My account")
    assert len(saved_savings()) == 1


def test_init_db_twice_keeps_existing_savings(user_id, saving_id):
    before = saved_savings()
    init_db()
    assert saved_savings() == before


def test_savings_table_has_spec_columns(client):
    with closing(get_db()) as conn:
        info = list(conn.execute("PRAGMA table_info(savings)"))
    assert {row["name"] for row in info} == COLUMNS
    by_name = {row["name"]: row for row in info}
    for required in ("user_id", "amount", "type", "date", "paid_from"):
        assert by_name[required]["notnull"] == 1, f"{required} must be NOT NULL"
    for optional in ("description", "institution", "interest_rate", "maturity_date"):
        assert by_name[optional]["notnull"] == 0, f"{optional} must be nullable"
    assert by_name["id"]["pk"] == 1


def test_savings_table_has_foreign_key_to_users(client):
    with closing(get_db()) as conn:
        fks = list(conn.execute("PRAGMA foreign_key_list(savings)"))
    assert [(fk["table"], fk["from"], fk["to"]) for fk in fks] == [
        ("users", "user_id", "id")
    ]
    with pytest.raises(sqlite3.IntegrityError):
        add_saving(9999, 5, "FD", "2026-05-01", "My account")


def test_no_savings_are_seeded(client):
    assert saved_savings() == []


def test_get_saving_is_scoped_to_owner(user_id, other_id, saving_id):
    assert get_saving(saving_id, user_id)["description"] == "Deposit"
    assert get_saving(saving_id, other_id) is None
    assert get_saving(9999, user_id) is None


def test_update_saving_is_scoped_to_owner(user_id, other_id, saving_id):
    values = (1000, "PPF", "2026-05-01", "My account", "Deposit", "SBI", 7.1)
    before = saved_savings()
    assert (
        update_saving(saving_id, other_id, 1, "FD", "2026-01-01", "My account") is False
    )
    assert update_saving(9999, user_id, *values, "2030-05-01") is False
    assert update_saving(saving_id, user_id, *values, "2030-05-01") is True
    assert saved_savings() == before


def test_update_saving_defaults_optional_fields_to_null(user_id, saving_id):
    assert update_saving(saving_id, user_id, 3, "Gold", "2026-05-02", "My account")
    [row] = saved_savings()
    assert (row["description"], row["institution"]) == (None, None)
    assert (row["interest_rate"], row["maturity_date"]) == (None, None)
    assert (row["amount"], row["type"], row["date"]) == (3, "Gold", "2026-05-02")


def test_delete_saving_is_scoped_to_owner_and_deletes_once(
    user_id, other_id, saving_id
):
    before = saved_savings()
    assert delete_saving(saving_id, other_id) is False
    assert delete_saving(9999, user_id) is False
    assert saved_savings() == before
    sibling = insert(user_id, description="Sibling")
    assert delete_saving(saving_id, user_id) is True
    assert delete_saving(saving_id, user_id) is False
    assert [row["id"] for row in saved_savings()] == [sibling]


def test_add_saving_helper_stores_nulls_by_default(user_id):
    add_saving(user_id, 5, "Gold", "2026-05-01", "Salary deduction/employer")
    [row] = saved_savings()
    assert (row["user_id"], row["amount"], row["type"], row["date"]) == (
        user_id,
        5,
        "Gold",
        "2026-05-01",
    )
    assert row["paid_from"] == "Salary deduction/employer"
    for column in ("description", "institution", "interest_rate", "maturity_date"):
        assert row[column] is None, column
    assert row["created_at"]


def test_saving_queries_order_limit_and_filter(user_id, other_id):
    for day in range(1, 13):
        insert(user_id, date=f"2026-05-{day:02d}", description=f"s{day:02d}")
    insert(other_id, date="2026-05-20", description="theirs")
    recent = get_recent_savings(user_id)
    assert [r["description"] for r in recent] == [f"s{d:02d}" for d in range(12, 2, -1)]
    assert len(get_recent_savings(user_id, limit=2)) == 2
    bounded = get_recent_savings(user_id, date_from="2026-05-05", date_to="2026-05-07")
    assert [r["description"] for r in bounded] == ["s07", "s06", "s05"]
    only_from = get_recent_savings(user_id, limit=50, date_from="2026-05-11")
    assert [r["description"] for r in only_from] == ["s12", "s11"]
    only_to = get_recent_savings(user_id, limit=50, date_to="2026-05-02")
    assert [r["description"] for r in only_to] == ["s02", "s01"]
    assert [r["description"] for r in get_recent_savings(other_id)] == ["theirs"]


def test_recent_savings_same_date_ties_break_by_id_desc(user_id):
    insert(user_id, date="2026-05-03", description="first")
    insert(user_id, date="2026-05-03", description="second")
    assert [r["description"] for r in get_recent_savings(user_id)] == [
        "second",
        "first",
    ]


def test_savings_summary_total_count_and_filter(user_id, other_id):
    insert(user_id, amount=100, date="2026-04-30")
    insert(user_id, amount=200.5, date="2026-05-01")
    insert(user_id, amount=300, date="2026-05-31")
    insert(user_id, amount=400, date="2026-06-01")
    insert(other_id, amount=9999, date="2026-05-10")
    everything = get_savings_summary(user_id)
    assert everything["total"] == pytest.approx(1000.5)
    assert everything["count"] == 4
    inside = get_savings_summary(user_id, "2026-05-01", "2026-05-31")
    assert inside["total"] == pytest.approx(500.5)
    assert inside["count"] == 2


def test_savings_summary_without_savings_is_zero(user_id, other_id):
    insert(other_id)
    summary = get_savings_summary(user_id)
    assert (summary["total"] or 0) == 0
    assert summary["count"] == 0
    assert get_savings_breakdown(user_id) == []


def test_savings_breakdown_groups_by_type_with_percentages(user_id, other_id):
    insert(user_id, amount=3000, type="FD", date="2026-05-01")
    insert(user_id, amount=1000, type="RD", date="2026-05-02")
    insert(user_id, amount=500, type="FD", date="2026-07-01")
    insert(other_id, amount=7777, type="Gold", date="2026-05-02")
    by_name = {r["name"]: r for r in get_savings_breakdown(user_id)}
    assert set(by_name) == {"FD", "RD"}
    assert by_name["FD"]["amount"] == pytest.approx(3500)
    assert by_name["RD"]["amount"] == pytest.approx(1000)
    assert by_name["FD"]["pct"] == pytest.approx(77.8, abs=0.6)
    assert by_name["RD"]["pct"] == pytest.approx(22.2, abs=0.6)

    filtered = {
        r["name"]: r for r in get_savings_breakdown(user_id, "2026-05-01", "2026-05-02")
    }
    assert filtered["FD"]["amount"] == pytest.approx(3000)
    assert filtered["FD"]["pct"] == pytest.approx(75, abs=0.5)
    assert filtered["RD"]["pct"] == pytest.approx(25, abs=0.5)


# ---- Access ----------------------------------------------------------- #


@all_routes
@both_methods
def test_logged_out_redirects_to_login_and_changes_nothing(
    client, saving_id, other_id, route, method
):
    before = saved_savings()
    for target in (saving_id, 9999):
        data = {**VALID, "user_id": str(other_id)}
        response = send(client, route, method, target, data)
        assert response.status_code == 302
        assert response.headers["Location"] == "/login"
    assert saved_savings() == before


@all_routes
@both_methods
def test_logged_out_invalid_data_redirects_without_validating(
    client, saving_id, route, method
):
    before = saved_savings()
    response = send(client, route, method, saving_id, {**VALID, "amount": "-1"})
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"
    assert saved_savings() == before


@all_routes
@both_methods
def test_deleted_user_session_is_cleared(client, saving_id, route, method):
    with client.session_transaction() as sess:
        sess["user_id"] = 9999
    before = saved_savings()
    response = send(client, route, method, saving_id)
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"
    with client.session_transaction() as sess:
        assert "user_id" not in sess
    assert saved_savings() == before


@id_routes
@both_methods
@pytest.mark.parametrize("missing", [0, 9999, 2**63 - 1, 2**63])
def test_unknown_saving_is_404(auth_client, saving_id, route, method, missing):
    before = saved_savings()
    assert send(auth_client, route, method, missing).status_code == 404
    assert saved_savings() == before


@id_routes
@both_methods
def test_other_users_saving_is_404_even_with_forged_user_id(
    auth_client, user_id, other_id, route, method
):
    target = insert(other_id, description="Private", institution="PrivateBank")
    before = saved_savings()
    for forged in (user_id, other_id):
        data = {**VALID, "user_id": str(forged)}
        response = send(auth_client, route, method, target, data)
        assert response.status_code == 404
        text = response.get_data(as_text=True)
        assert "Private" not in text
    assert saved_savings() == before


# ---- Add form --------------------------------------------------------- #


def test_add_form_has_all_fields_and_exactly_the_spec_options(auth_client):
    response = auth_client.get(ADD_URL)
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    for field in (
        "amount",
        "type",
        "date",
        "paid_from",
        "description",
        "institution",
        "interest_rate",
        "maturity_date",
    ):
        assert f'name="{field}"' in html, field
    for absent in ("category", "source"):
        assert f'name="{absent}"' not in html
    select = re.search(r'<select[^>]*name="type"[^>]*>(.*?)</select>', html, re.S)
    assert select, "type select not found"
    options = [v for v in re.findall(r'<option value="([^"]*)"', select.group(1)) if v]
    assert set(options) == set(TYPES)
    assert len(options) == len(TYPES)
    for value in PAID_FROM:
        assert f'value="{value}"' in html
    assert "Add Saving" in html
    assert 'href="/profile"' in html
    assert "Save Changes" not in html


def test_add_form_preselects_my_account(auth_client):
    html = auth_client.get(ADD_URL).get_data(as_text=True)
    assert is_chosen(html, "paid_from", "My account")
    assert not is_chosen(html, "paid_from", "Salary deduction/employer")


def test_add_form_has_no_inline_styles(auth_client):
    html = auth_client.get(ADD_URL).get_data(as_text=True)
    form = re.search(r"<form.*?</form>", html, re.S).group(0)
    assert "style=" not in form
    assert "<style" not in html


def test_valid_add_saves_one_saving_for_logged_in_user(auth_client, user_id, other_id):
    data = {**VALID, "user_id": str(other_id)}
    response = auth_client.post(ADD_URL, data=data)
    assert response.status_code == 302
    assert response.headers["Location"] == "/profile"
    [row] = saved_savings()
    assert row["user_id"] == user_id
    assert row["amount"] == 5000.50
    for column in (
        "type",
        "date",
        "paid_from",
        "description",
        "institution",
        "maturity_date",
    ):
        assert row[column] == VALID[column], column
    assert row["interest_rate"] == 12.5
    assert saved_expenses() == []
    assert saved_credits() == []


def test_valid_add_with_only_required_fields_stores_nulls(auth_client):
    data = {k: VALID[k] for k in ("amount", "type", "date", "paid_from")}
    assert auth_client.post(ADD_URL, data=data).status_code == 302
    [row] = saved_savings()
    for column in ("description", "institution", "interest_rate", "maturity_date"):
        assert row[column] is None, column


def test_valid_add_flashes_message_once_and_shows_saving_immediately(auth_client):
    response = auth_client.post(ADD_URL, data=VALID, follow_redirects=True)
    html = response.get_data(as_text=True)
    assert "Saving added successfully." in html
    block = section(html, "saving-heading")
    assert "June SIP" in block
    assert "₹5,000.50" in block
    assert "SIP" in block
    assert "Saving added successfully." not in profile_html(auth_client)


@form_modes
@pytest.mark.parametrize(
    "field", ["description", "institution", "interest_rate", "maturity_date"]
)
@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_optional_field_is_stored_as_null(
    auth_client, saving_id, mode, field, blank
):
    response = submit(auth_client, mode, saving_id, {**VALID, field: blank})
    assert response.status_code == 302
    assert saved_savings()[-1][field] is None
    assert len(saved_savings()) == (2 if mode == "add" else 1)


@form_modes
def test_all_optional_fields_omitted_are_stored_as_null(auth_client, saving_id, mode):
    data = {k: VALID[k] for k in ("amount", "type", "date", "paid_from")}
    assert submit(auth_client, mode, saving_id, data).status_code == 302
    row = saved_savings()[-1]
    for column in ("description", "institution", "interest_rate", "maturity_date"):
        assert row[column] is None, column


@form_modes
@pytest.mark.parametrize(
    "field, value",
    [
        ("amount", "0.01"),
        ("amount", "10000000"),
        ("description", "x" * 200),
        ("description", "'; DROP TABLE savings;--"),
        ("institution", "x" * 100),
        ("institution", "'; DROP TABLE savings;--"),
        ("institution", "é" * 100),
        ("interest_rate", "0"),
        ("interest_rate", "100"),
        ("interest_rate", "0.01"),
        ("interest_rate", "99.99"),
        ("maturity_date", "2026-06-02"),
        ("maturity_date", "2099-12-31"),
    ],
)
def test_boundary_values_are_saved(auth_client, saving_id, mode, field, value):
    response = submit(auth_client, mode, saving_id, {**VALID, field: value})
    assert response.status_code == 302
    stored = saved_savings()[-1][field]
    if field in ("amount", "interest_rate"):
        assert stored is not None
        assert stored == float(value)
    else:
        assert stored == value
    assert len(saved_savings()) == (2 if mode == "add" else 1)


@form_modes
@pytest.mark.parametrize("type_", TYPES)
def test_every_allowed_type_is_accepted(auth_client, saving_id, mode, type_):
    response = submit(auth_client, mode, saving_id, {**VALID, "type": type_})
    assert response.status_code == 302
    assert saved_savings()[-1]["type"] == type_


@form_modes
@pytest.mark.parametrize("paid_from", PAID_FROM)
def test_every_allowed_paid_from_is_accepted(auth_client, saving_id, mode, paid_from):
    response = submit(auth_client, mode, saving_id, {**VALID, "paid_from": paid_from})
    assert response.status_code == 302
    assert saved_savings()[-1]["paid_from"] == paid_from


# ---- Validation (add and edit) ---------------------------------------- #

TYPE_MSG = "Please select a valid type."
PAID_MSG = "Please select a valid paid from option."
INST_MSG = "Institution or scheme must be 100 characters or fewer."
RATE_MSG = "Interest rate must be between 0 and 100."
MAT_FMT_MSG = "Maturity date must be a valid date (YYYY-MM-DD)."
MAT_ORDER_MSG = "Maturity date cannot be before the date."

INVALID_CASES = [
    *(
        ("amount", value, "Amount must be a positive number.")
        for value in (None, "0", "-5", "abc", "nan", "inf")
    ),
    ("amount", "0.001", "Amount must be between"),
    ("amount", "10000000.01", "Amount must be between"),
    *(("type", value, TYPE_MSG) for value in ("Food", "", "fd", "Salary", None)),
    *(
        ("paid_from", value, PAID_MSG)
        for value in ("Cash", "", "my account", "Salary deduction", None)
    ),
    *(
        ("date", value, "Date must be a valid date")
        for value in ("20260501", "2026-02-30", "")
    ),
    ("description", "x" * 201, "Description must be 200 characters"),
    ("institution", "x" * 101, INST_MSG),
    ("institution", "é" * 101, INST_MSG),
    *(
        ("interest_rate", value, RATE_MSG)
        for value in ("-0.01", "-1", "100.01", "abc", "nan", "inf", "-inf", "1e999")
    ),
    *(
        ("maturity_date", value, MAT_FMT_MSG)
        for value in ("20300101", "2030-02-30", "tomorrow", "2030-13-01")
    ),
    ("maturity_date", "2026-06-01", MAT_ORDER_MSG),
    ("maturity_date", "2020-01-01", MAT_ORDER_MSG),
]


@form_modes
@pytest.mark.parametrize("field, value, message", INVALID_CASES)
def test_invalid_input_is_rejected_and_values_preserved(
    auth_client, saving_id, mode, field, value, message
):
    before = saved_savings()
    data = {**VALID, field: value}
    data = {k: v for k, v in data.items() if v is not None}
    response = submit(auth_client, mode, saving_id, data)
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Location" not in response.headers
    assert message in html
    assert "auth-error" in html
    for flash in ("added", "updated"):
        assert f"Saving {flash} successfully." not in html
    for name in (
        "amount",
        "date",
        "description",
        "institution",
        "interest_rate",
        "maturity_date",
    ):
        if name in data:
            assert f'value="{data[name]}"' in html, f"{name} not preserved"
    if field != "type":
        assert is_chosen(html, "type", "SIP"), "type not preserved"
    else:
        assert not is_chosen(html, "type", "PPF"), "stored type leaked"
    if field != "paid_from":
        assert is_chosen(html, "paid_from", "Salary deduction/employer")
    elif mode == "edit":
        assert not is_chosen(html, "paid_from", "My account"), "stored value leaked"
    assert saved_savings() == before


@form_modes
def test_each_invalid_field_reports_its_own_error_only(auth_client, saving_id, mode):
    data = {**VALID, "type": "Food", "interest_rate": "500", "institution": "x" * 101}
    html = submit(auth_client, mode, saving_id, data).get_data(as_text=True)
    assert any(m in html for m in (TYPE_MSG, RATE_MSG, INST_MSG)), "no error shown"
    assert html.count("auth-error") >= 1
    assert saved_savings()[-1]["type"] != "Food"
    assert PAID_MSG not in html
    assert MAT_FMT_MSG not in html
    assert MAT_ORDER_MSG not in html


@form_modes
def test_posting_only_category_or_source_is_rejected(auth_client, saving_id, mode):
    before = saved_savings()
    data = {k: v for k, v in VALID.items() if k != "type"}
    data["category"] = "Food"
    data["source"] = "Salary"
    response = submit(auth_client, mode, saving_id, data)
    assert response.status_code == 200
    assert TYPE_MSG in response.get_data(as_text=True)
    assert saved_savings() == before


@form_modes
def test_validation_failure_does_not_write_expenses_or_credits(
    auth_client, user_id, saving_id, mode
):
    insert_expense(user_id)
    insert_credit(user_id)
    expenses, credits = saved_expenses(), saved_credits()
    submit(auth_client, mode, saving_id, {**VALID, "amount": "0"})
    assert saved_expenses() == expenses
    assert saved_credits() == credits


# ---- Edit ------------------------------------------------------------- #


def test_edit_form_is_prefilled(auth_client, saving_id):
    response = auth_client.get(edit_url(saving_id))
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'value="1000.00"' in html
    assert is_chosen(html, "type", "PPF")
    assert is_chosen(html, "paid_from", "My account")
    assert 'value="2026-05-01"' in html
    assert 'value="Deposit"' in html
    assert 'value="SBI"' in html
    assert 'value="7.1"' in html
    assert 'value="2030-05-01"' in html
    assert f'action="{edit_url(saving_id)}"' in html
    assert "Save Changes" in html
    assert 'href="/profile"' in html


def test_edit_form_preselects_stored_salary_deduction(auth_client, user_id):
    target = insert(user_id, paid_from="Salary deduction/employer")
    html = auth_client.get(edit_url(target)).get_data(as_text=True)
    assert is_chosen(html, "paid_from", "Salary deduction/employer")
    assert not is_chosen(html, "paid_from", "My account")


def test_edit_form_with_null_optional_fields_is_empty(auth_client, user_id):
    target = insert_bare(user_id)
    html = auth_client.get(edit_url(target)).get_data(as_text=True)
    assert 'value="None"' not in html
    assert "None" not in html
    for field in ("description", "institution", "interest_rate", "maturity_date"):
        assert re.search(
            rf'name="{field}"[^>]*value=""|value=""[^>]*name="{field}"', html
        )


def test_get_edit_changes_nothing(auth_client, saving_id):
    before = saved_savings()
    assert auth_client.get(edit_url(saving_id)).status_code == 200
    assert saved_savings() == before


def test_valid_edit_updates_only_that_row(auth_client, user_id, saving_id):
    sibling = insert(user_id, description="Sibling")
    before = {row["id"]: row for row in saved_savings()}
    response = auth_client.post(edit_url(saving_id), data=VALID)
    assert response.status_code == 302
    assert response.headers["Location"] == "/profile"
    after = {row["id"]: row for row in saved_savings()}
    assert after[sibling] == before[sibling]
    assert set(after) == set(before)
    assert after[saving_id] == {
        **before[saving_id],
        "amount": 5000.50,
        "type": "SIP",
        "date": "2026-06-02",
        "paid_from": "Salary deduction/employer",
        "description": "June SIP",
        "institution": "HDFC Fund",
        "interest_rate": 12.5,
        "maturity_date": "2030-06-02",
    }


def test_edit_keeps_user_id_and_created_at_and_ignores_forged_fields(
    auth_client, user_id, other_id, saving_id
):
    forged = {"id": "777", "user_id": str(other_id), "created_at": "2030-01-01"}
    auth_client.post(edit_url(saving_id), data={**VALID, **forged})
    [row] = saved_savings()
    assert row["id"] == saving_id
    assert row["user_id"] == user_id
    assert row["created_at"] == OLD_TIMESTAMP


def test_edit_success_flashes_updated_message(auth_client, saving_id):
    response = auth_client.post(edit_url(saving_id), data=VALID, follow_redirects=True)
    html = response.get_data(as_text=True)
    assert "Saving updated successfully." in html
    assert "June SIP" in section(html, "saving-heading")
    assert "Saving updated successfully." not in profile_html(auth_client)


def test_unchanged_edit_succeeds(auth_client, saving_id):
    before = saved_savings()
    data = {
        "amount": "1000.00",
        "type": "PPF",
        "date": "2026-05-01",
        "paid_from": "My account",
        "description": "Deposit",
        "institution": "SBI",
        "interest_rate": "7.1",
        "maturity_date": "2030-05-01",
    }
    response = auth_client.post(edit_url(saving_id), data=data, follow_redirects=True)
    assert "Saving updated successfully." in response.get_data(as_text=True)
    assert saved_savings() == before


# ---- Delete ----------------------------------------------------------- #


def test_confirmation_page_shows_details_and_changes_nothing(auth_client, user_id):
    target = insert(
        user_id,
        amount=1234567.5,
        type="Gold",
        date="2026-09-05",
        description="Coins",
    )
    before = saved_savings()
    response = auth_client.get(delete_url(target))
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "₹1,234,567.50" in html
    assert "Gold" in html
    assert "September 5, 2026" in html
    assert "Coins" in html
    assert "undone" in html.lower()
    assert "Delete Saving" in html
    assert re.search(
        r'<form[^>]*method="post"[^>]*action="%s"' % delete_url(target), html, re.I
    )
    assert "Cancel" in html
    assert 'href="/profile"' in html
    assert saved_savings() == before


def test_confirmation_page_null_description_shows_placeholder(auth_client, user_id):
    target = insert_bare(user_id)
    html = auth_client.get(delete_url(target)).get_data(as_text=True)
    assert "No description" in html
    assert "None" not in html


def test_head_and_cancel_target_delete_nothing(auth_client, saving_id):
    before = saved_savings()
    auth_client.head(delete_url(saving_id))
    assert auth_client.get("/profile").status_code == 200
    assert saved_savings() == before


def test_confirm_deletes_only_that_saving_and_flashes(
    auth_client, user_id, other_id, saving_id
):
    sibling = insert(user_id, description="Sibling")
    foreign = insert(other_id, description="Theirs")
    insert_expense(user_id)
    insert_credit(user_id)
    before = {row["id"]: row for row in saved_savings()}
    expenses_before, credits_before = saved_expenses(), saved_credits()
    response = auth_client.post(delete_url(saving_id), data={"user_id": str(other_id)})
    assert response.status_code == 302
    assert response.headers["Location"] == "/profile"
    after = {row["id"]: row for row in saved_savings()}
    assert set(after) == {sibling, foreign}
    assert after[sibling] == before[sibling]
    assert after[foreign] == before[foreign]
    assert saved_expenses() == expenses_before
    assert saved_credits() == credits_before
    assert "Saving deleted successfully." in profile_html(auth_client)
    assert "Saving deleted successfully." not in profile_html(auth_client)


def test_second_delete_submission_is_404_and_deletes_nothing_else(
    auth_client, user_id, saving_id
):
    sibling = insert(user_id, description="Sibling")
    assert auth_client.post(delete_url(saving_id)).status_code == 302
    before = saved_savings()
    assert auth_client.post(delete_url(saving_id)).status_code == 404
    assert saved_savings() == before
    assert [row["id"] for row in before] == [sibling]


def test_edit_page_for_deleted_saving_is_404(auth_client, saving_id):
    auth_client.post(delete_url(saving_id))
    assert auth_client.get(edit_url(saving_id)).status_code == 404


# ---- Expense / credit / saving isolation ------------------------------ #


@pytest.fixture()
def same_id_trio(user_id):
    expense = insert_expense(user_id, description="Expense row")
    credit = insert_credit(user_id)
    saving = insert(user_id, description="Saving row")
    assert expense == credit == saving, "precondition: shared id"
    return saving


def test_editing_saving_leaves_expense_and_credit_unchanged(auth_client, same_id_trio):
    expenses, credits = saved_expenses(), saved_credits()
    assert auth_client.post(edit_url(same_id_trio), data=VALID).status_code == 302
    assert saved_expenses() == expenses
    assert saved_credits() == credits
    assert saved_savings()[0]["description"] == "June SIP"


def test_deleting_saving_leaves_expense_and_credit_unchanged(auth_client, same_id_trio):
    expenses, credits = saved_expenses(), saved_credits()
    assert auth_client.post(delete_url(same_id_trio)).status_code == 302
    assert saved_expenses() == expenses
    assert saved_credits() == credits
    assert saved_savings() == []


def test_editing_expense_or_credit_leaves_saving_unchanged(auth_client, same_id_trio):
    before = saved_savings()
    expense = {
        "amount": "9",
        "category": "Bills",
        "date": "2026-07-01",
        "description": "x",
    }
    assert (
        auth_client.post(f"/expenses/{same_id_trio}/edit", data=expense).status_code
        == 302
    )
    credit = {
        "amount": "9",
        "source": "Gift",
        "date": "2026-07-01",
        "description": "x",
    }
    assert (
        auth_client.post(f"/credits/{same_id_trio}/edit", data=credit).status_code
        == 302
    )
    assert saved_savings() == before
    assert saved_expenses()[0]["category"] == "Bills"
    assert saved_credits()[0]["source"] == "Gift"


def test_deleting_expense_or_credit_leaves_saving_unchanged(auth_client, same_id_trio):
    before = saved_savings()
    assert auth_client.post(f"/expenses/{same_id_trio}/delete").status_code == 302
    assert auth_client.post(f"/credits/{same_id_trio}/delete").status_code == 302
    assert saved_savings() == before
    assert saved_expenses() == []
    assert saved_credits() == []


# ---- Profile: spending views unaffected ------------------------------- #


def test_saving_add_edit_delete_leave_spending_views_identical(auth_client, user_id):
    insert_expense(user_id, amount=45.5, category="Food")
    insert_expense(user_id, amount=10, category="Bills", description="Power")
    insert_credit(user_id, amount=1000)
    base = profile_html(auth_client)
    baseline = (
        spending_view(base),
        section(base, "cat-heading"),
        section(base, "credit-heading"),
    )
    assert "₹55.50" in stats_section(base)

    def current():
        html = profile_html(auth_client)
        return (
            spending_view(html),
            section(html, "cat-heading"),
            section(html, "credit-heading"),
        )

    auth_client.post(ADD_URL, data={**VALID, "amount": "99999"})
    assert current() == baseline

    target = saved_savings()[-1]["id"]
    auth_client.post(
        edit_url(target), data={**VALID, "amount": "88888", "type": "Gold"}
    )
    assert current() == baseline

    auth_client.post(delete_url(target))
    assert saved_savings() == []
    assert current() == baseline


def test_saving_amount_appears_only_in_total_saved_card(auth_client, user_id):
    insert_expense(user_id, amount=45.5)
    insert(user_id, amount=99999)
    html = profile_html(auth_client)
    text = re.sub(r"<[^>]+>", " ", stats_section(html))
    assert text.count("₹99,999.00") == 1
    assert "Total Saved" in text
    assert "₹45.50" in text


def test_stats_with_only_savings_show_no_spending(auth_client, user_id):
    insert(user_id, amount=5000)
    html = profile_html(auth_client)
    assert "₹0.00" in html
    categories = section(html, "cat-heading")
    assert "₹5,000.00" not in categories
    assert "₹5,000.00" in stats_section(html)
    assert "₹5,000.00" not in section(html, "credit-heading")


# ---- Profile: Total Saved and breakdown ------------------------------- #


def test_total_saved_card_is_zero_without_savings(auth_client):
    stats = stats_section(profile_html(auth_client))
    assert "Total Saved" in stats
    assert "₹0.00" in stats


def test_total_saved_sums_only_own_savings(auth_client, user_id, other_id):
    insert(user_id, amount=1000.25)
    insert(user_id, amount=2000, type="FD")
    insert(other_id, amount=7777)
    stats = stats_section(profile_html(auth_client))
    assert "₹3,000.25" in stats
    assert "7,777" not in stats


def test_total_saved_follows_inclusive_date_filter(auth_client, user_id):
    for date, amount in [
        ("2026-04-30", 1),
        ("2026-05-01", 10),
        ("2026-05-15", 100),
        ("2026-05-31", 1000),
        ("2026-06-01", 10000),
    ]:
        insert(user_id, amount=amount, date=date)
    html = profile_html(auth_client, "?from=2026-05-01&to=2026-05-31")
    assert "₹1,110.00" in stats_section(html)
    assert "₹11,111.00" not in stats_section(html)
    assert "₹11,111.00" in stats_section(profile_html(auth_client))
    one_side = profile_html(auth_client, "?from=2026-05-15")
    assert "₹11,100.00" in stats_section(one_side)
    other_side = profile_html(auth_client, "?to=2026-05-15")
    assert "₹111.00" in stats_section(other_side)


def test_breakdown_section_absent_without_savings(auth_client, user_id):
    insert_expense(user_id)
    html = profile_html(auth_client)
    assert "saving-type-heading" not in html
    assert "Savings by Type" not in html


def test_breakdown_section_lists_types_amounts_and_percentages(auth_client, user_id):
    insert(user_id, amount=3000, type="FD")
    insert(user_id, amount=1000, type="RD")
    insert(user_id, amount=500, type="FD", date="2026-05-02")
    html = profile_html(auth_client)
    block = section(html, "saving-type-heading")
    assert "Savings by Type" in html
    assert "FD" in block
    assert "RD" in block
    assert "₹3,500.00" in block
    assert "₹1,000.00" in block
    assert "78" in block
    assert "22" in block


def test_breakdown_follows_date_filter_and_user(auth_client, user_id, other_id):
    insert(user_id, amount=3000, type="FD", date="2026-05-01")
    insert(user_id, amount=1000, type="RD", date="2026-05-31")
    insert(user_id, amount=555, type="Gold", date="2026-06-01")
    insert(other_id, amount=444, type="Bonds", date="2026-05-10")
    block = section(
        profile_html(auth_client, "?from=2026-05-01&to=2026-05-31"),
        "saving-type-heading",
    )
    assert "FD" in block and "RD" in block
    assert "Gold" not in block
    assert "Bonds" not in block
    assert "75" in block and "25" in block
    unfiltered = section(profile_html(auth_client), "saving-type-heading")
    assert "Gold" in unfiltered
    assert "Bonds" not in unfiltered


# ---- Profile: list ---------------------------------------------------- #


def test_profile_shows_add_saving_button_after_add_credit(auth_client):
    html = profile_html(auth_client)
    assert "+ Add Saving" in html
    assert 'href="/savings/add"' in html
    assert html.index("+ Add Expense") < html.index("+ Add Credit")
    assert html.index("+ Add Credit") < html.index("+ Add Saving")
    assert html.index("+ Add Saving") - html.index("+ Add Credit") < 400


def test_savings_section_has_heading_and_rows(auth_client, user_id):
    insert(user_id, amount=1234.5, type="Gold", date="2026-05-01", description="Coins")
    block = savings_section(auth_client)
    assert "Recent Savings" in block
    assert "Coins" in block
    assert "₹1,234.50" in block
    assert "May 1, 2026" in block
    assert "Gold" in block
    for header in ("Date", "Description", "Type", "Amount", "Actions"):
        assert f">{header}</th>" in block
    assert ">Category</th>" not in block
    assert ">Source</th>" not in block


def test_savings_table_keeps_explicit_aria_roles(auth_client, user_id):
    insert(user_id)
    block = savings_section(auth_client)
    assert 'role="table"' in block
    assert block.count('role="rowgroup"') == 2
    assert 'role="row"' in block
    assert 'role="cell"' in block
    assert block.count('role="columnheader"') == 5


def test_saving_details_appear_under_description(auth_client, user_id):
    insert(
        user_id,
        description="Retirement",
        institution="Post Office",
        interest_rate=7.5,
        maturity_date="2031-03-31",
        paid_from="Salary deduction/employer",
    )
    block = savings_section(auth_client)
    assert "Retirement" in block
    assert "Post Office" in block
    assert "7.5" in block
    assert "2031" in block
    assert "Salary deduction" in block


def test_my_account_saving_shows_no_salary_note(auth_client, user_id):
    insert(user_id, paid_from="My account")
    assert "Salary deduction" not in savings_section(auth_client)


def test_saving_without_optional_details_shows_no_placeholders(auth_client, user_id):
    insert_bare(user_id, type="NPS")
    block = savings_section(auth_client)
    assert "None" not in block
    assert "NPS" in block
    assert "Salary deduction" not in block


def test_saving_action_links_have_exact_aria_labels(auth_client, user_id):
    with_desc = insert(user_id, amount=1234.5, type="Gold", description="Coins")
    no_desc = insert_bare(user_id, amount=7, type="NPS")
    html = profile_html(auth_client)
    assert 'aria-label="Edit saving Coins, ₹1,234.50, May 1, 2026"' in html
    assert 'aria-label="Delete saving Coins, ₹1,234.50, May 1, 2026"' in html
    assert 'aria-label="Edit saving NPS, ₹7.00, May 1, 2026"' in html
    assert 'aria-label="Delete saving NPS, ₹7.00, May 1, 2026"' in html
    for target in (with_desc, no_desc):
        assert 'class="tx-edit"' in action_tag(html, edit_url(target), "tx-edit")
        assert "tx-delete" in action_tag(html, delete_url(target), "tx-delete")


def test_saving_action_icons_have_no_visible_text(auth_client, user_id):
    target = insert(user_id)
    block = savings_section(auth_client)
    match = re.search(
        rf'<a\b[^>]*href="{re.escape(delete_url(target))}"[^>]*>(.*?)</a>', block, re.S
    )
    assert match
    inner = match.group(1)
    assert "<svg" in inner
    assert re.sub(r"<svg.*?</svg>", "", inner, flags=re.S).strip() == ""


def test_savings_section_has_no_inline_styles_or_category_classes(auth_client, user_id):
    for type_ in TYPES:
        insert(user_id, type=type_, description=type_)
    block = savings_section(auth_client)
    assert "style=" not in block
    assert "cat-" not in block


def test_savings_newest_first_with_id_tiebreak(auth_client, user_id):
    insert(user_id, date="2026-05-01", description="old-one")
    insert(user_id, date="2026-05-03", description="same-day-first")
    insert(user_id, date="2026-05-03", description="same-day-second")
    insert(user_id, date="2026-05-02", description="middle-one")
    block = savings_section(auth_client)
    order = [
        block.index(name)
        for name in ("same-day-second", "same-day-first", "middle-one", "old-one")
    ]
    assert order == sorted(order), "expected date DESC then id DESC"


def test_twelve_savings_listed_behind_see_more(auth_client, user_id):
    for day in range(1, 13):
        insert(user_id, date=f"2026-05-{day:02d}", description=f"entry-{day:02d}")
    block = savings_section(auth_client)
    assert block.count('class="tx-edit"') == 12
    assert "See more+" in block
    assert "entry-12" in block
    assert "entry-01" in block


def test_no_see_more_when_five_or_fewer_savings(auth_client, user_id):
    for day in range(1, 6):
        insert(user_id, date=f"2026-05-{day:02d}")
    block = savings_section(auth_client)
    assert block.count('class="tx-edit"') == 5
    assert "See more+" not in block


def test_users_see_only_their_own_savings(auth_client, user_id, other_id):
    insert(user_id, description="Mine")
    foreign = insert(
        other_id, amount=777, description="Theirs", institution="TheirBank"
    )
    html = profile_html(auth_client)
    block = section(html, "saving-heading")
    assert "Mine" in block
    assert "Theirs" not in html
    assert "TheirBank" not in html
    assert f'href="{edit_url(foreign)}"' not in html
    assert f'href="{delete_url(foreign)}"' not in html
    assert "See more+" not in block


# ---- Profile: date filter and empty states ---------------------------- #


def test_date_filter_bounds_are_inclusive_for_savings(auth_client, user_id):
    for date, name in [
        ("2026-04-30", "before-range"),
        ("2026-05-01", "first-day"),
        ("2026-05-15", "mid-month"),
        ("2026-05-31", "last-day"),
        ("2026-06-01", "after-range"),
    ]:
        insert(user_id, date=date, description=name)
    block = savings_section(auth_client, "?from=2026-05-01&to=2026-05-31")
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
def test_single_sided_date_filter_applies_to_savings(
    auth_client, user_id, query, kept, dropped
):
    for date, name in [
        ("2026-05-01", "first-day"),
        ("2026-05-15", "mid-month"),
        ("2026-05-31", "last-day"),
    ]:
        insert(user_id, date=date, description=name)
    block = savings_section(auth_client, query)
    assert all(name in block for name in kept)
    assert not any(name in block for name in dropped)


def test_date_filter_limits_the_savings_listed(auth_client, user_id):
    for day in range(1, 13):
        insert(user_id, date=f"2026-05-{day:02d}", description=f"in-{day:02d}")
    for date in ("2026-04-01", "2026-04-02", "2026-06-20"):
        insert(user_id, date=date, description="outside")
    block = savings_section(auth_client, "?from=2026-05-01&to=2026-05-31")
    assert block.count('class="tx-edit"') == 12
    assert "outside" not in block
    assert savings_section(auth_client).count('class="tx-edit"') == 15


def test_savings_empty_state_for_user_without_savings(auth_client, user_id):
    insert_expense(user_id)
    insert_credit(user_id)
    block = savings_section(auth_client)
    assert "No savings yet." in block
    assert 'href="/savings/add"' in block
    assert "<table" not in block
    assert 'role="table"' not in block


def test_savings_filtered_empty_state_links_to_all_time(auth_client, user_id):
    insert(user_id, date="2026-05-01")
    block = savings_section(auth_client, "?from=2027-01-01&to=2027-01-31")
    assert "No savings in this period." in block
    assert "Show all time" in block
    assert 'href="/profile"' in block
    assert "<table" not in block


def test_other_users_savings_do_not_hide_empty_state(auth_client, other_id):
    insert(other_id)
    assert "No savings yet." in savings_section(auth_client)


def test_credit_empty_state_unchanged_by_savings(auth_client, user_id):
    insert(user_id)
    html = profile_html(auth_client)
    assert "No credits yet." in section(html, "credit-heading")
    assert "No savings yet." not in section(html, "credit-heading")


def test_filter_excluding_all_savings_shows_zero_total_and_no_breakdown(
    auth_client, user_id
):
    insert(user_id, amount=5000, date="2026-05-01")
    html = profile_html(auth_client, "?from=2027-01-01&to=2027-01-31")
    stats = stats_section(html)
    assert "Total Saved" in stats
    assert "₹5,000.00" not in stats
    assert "saving-type-heading" not in html
    assert "Savings by Type" not in html


# ---- Escaping --------------------------------------------------------- #


def test_html_in_description_and_institution_is_displayed_as_text(auth_client, user_id):
    target = insert(
        user_id,
        description='<script>d</script>"><b>Tom & Jerry</b>',
        institution="<script>i</script><u>Bank</u>",
    )
    for path in ("/profile", edit_url(target), delete_url(target)):
        html = auth_client.get(path).get_data(as_text=True)
        assert "<script>d" not in html, path
        assert "<script>i" not in html, path
        assert "<b>Tom" not in html, path
        assert "<u>Bank" not in html, path
    block = savings_section(auth_client)
    assert "&lt;script&gt;d&lt;/script&gt;" in block
    assert "&lt;script&gt;i&lt;/script&gt;" in block


def test_aria_label_escapes_quotes_and_markup(auth_client, user_id):
    target = insert(user_id, description='<i>A&B</i>" onfocus="alert(1)')
    html = profile_html(auth_client)
    for kind, css in (("delete", "tx-delete"), ("edit", "tx-edit")):
        href = delete_url(target) if kind == "delete" else edit_url(target)
        tag = action_tag(html, href, css)
        assert ' onfocus="' not in tag
        assert "<i>" not in tag
        assert "&lt;i&gt;A&amp;B&lt;/i&gt;" in tag


@form_modes
def test_html_in_failed_submission_is_escaped_when_redisplayed(
    auth_client, saving_id, mode
):
    data = {
        **VALID,
        "amount": "0",
        "description": '"><script>y</script>',
        "institution": '"><script>z</script>',
        "interest_rate": '"><script>r</script>',
    }
    html = submit(auth_client, mode, saving_id, data).get_data(as_text=True)
    for marker in ("y", "z", "r"):
        assert f"<script>{marker}" not in html


# ---- Other pages unchanged -------------------------------------------- #


def test_add_expense_and_credit_pages_have_no_saving_fields(auth_client):
    for path in ("/expenses/add", "/credits/add"):
        html = auth_client.get(path).get_data(as_text=True)
        for field in ("paid_from", "institution", "interest_rate", "maturity_date"):
            assert f'name="{field}"' not in html, (path, field)


def test_expense_add_still_works_and_does_not_touch_savings(auth_client):
    data = {
        "amount": "10",
        "category": "Bills",
        "date": "2026-05-01",
        "description": "x",
    }
    assert auth_client.post("/expenses/add", data=data).status_code == 302
    assert len(saved_expenses()) == 1
    assert saved_savings() == []


def test_credit_add_still_works_and_does_not_touch_savings(auth_client):
    data = {
        "amount": "10",
        "source": "Gift",
        "date": "2026-05-01",
        "description": "x",
    }
    assert auth_client.post("/credits/add", data=data).status_code == 302
    assert len(saved_credits()) == 1
    assert saved_savings() == []
