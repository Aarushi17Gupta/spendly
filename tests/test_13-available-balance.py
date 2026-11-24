"""Tests for Step 13 - available balance: the Total Credits and Available cards on
GET /profile, database.queries.get_available_summary() and the third
"Paid from" option, "Already saved before Spendly"."""

import math
import re
from contextlib import closing
from pathlib import Path

import pytest

import database.db as db_module
from app import app as flask_app
from database.db import (
    add_credit,
    add_expense,
    add_saving,
    create_user,
    get_db,
    get_user_by_email,
    init_db,
)
from database.queries import get_available_summary

EMAIL = "available@spendly.test"
OTHER_EMAIL = "other@spendly.test"
OWN_ACCOUNT = "My account"
SALARY = "Salary deduction/employer"
OLD = "Already saved before Spendly"
PAID_FROM = [OWN_ACCOUNT, SALARY, OLD]
STATIC = Path(__file__).resolve().parent.parent / "static" / "css"
PROFILE_CSS = STATIC / "profile.css"
ADD_EXPENSE_CSS = STATIC / "add_expense.css"

BASE_NOTE = "Credits minus expenses and savings paid from your account."
EXPLAIN_SAVINGS = (
    "Your expenses and savings are more than your credits for this period. "
    "Money from before this period, or not recorded here, is not included. "
    "If a saving is older than your records, edit it and choose "
    "Already saved before Spendly."
)
EXPLAIN_SPENT = "You spent more than your credits for this period."
HINT = "Only savings paid from my account reduce your available balance."
PAID_MSG = "Please select a valid paid from option."
OLD_NOTE = "Credits minus expenses. Savings are not included."

CREDIT_FORM = {
    "amount": "100.00",
    "source": "Salary",
    "date": "2026-06-02",
    "description": "June pay",
}
EXPENSE_FORM = {
    "amount": "40.00",
    "category": "Food",
    "date": "2026-06-02",
    "description": "Dinner",
}
SAVING_FORM = {
    "amount": "5000.00",
    "type": "SIP",
    "date": "2026-06-02",
    "description": "Monthly SIP",
    "paid_from": OWN_ACCOUNT,
    "institution": "",
    "interest_rate": "",
    "maturity_date": "",
}

# Literal statements only: table names are never interpolated into SQL.
SELECT_ALL = {
    "credits": "SELECT * FROM credits ORDER BY id",
    "expenses": "SELECT * FROM expenses ORDER BY id",
    "savings": "SELECT * FROM savings ORDER BY id",
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setitem(flask_app.config, "TESTING", True)
    init_db()
    create_user("Tester", EMAIL, "availablepass")
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
        return [dict(r) for r in conn.execute(SELECT_ALL[table])]


def last_id(table):
    return rows(table)[-1]["id"]


def credit(user_id, amount, date="2026-05-10"):
    add_credit(user_id, amount, "Salary", date, "pay")


def expense(user_id, amount, date="2026-05-10", category="Food"):
    add_expense(user_id, amount, category, date, "spend")


def saving(user_id, amount, paid_from=OWN_ACCOUNT, date="2026-05-10", type="FD"):
    add_saving(user_id, amount, type, date, paid_from)
    return last_id("savings")


def profile_html(client, query=""):
    response = client.get("/profile" + query)
    assert response.status_code == 200
    return response.get_data(as_text=True)


def available_section(html):
    match = re.search(
        r'<section class="profile-available" '
        r'aria-label="Income and available balance">.*?</section>',
        html,
        re.S,
    )
    assert match, "profile-available section not found"
    return match.group(0)


def stats_section(html):
    match = re.search(r'<section[^>]*class="profile-stats".*?</section>', html, re.S)
    assert match, "profile-stats section not found"
    return match.group(0)


def section(html, heading_id):
    match = re.search(
        rf'<section[^>]*aria-labelledby="{heading_id}".*?</section>', html, re.S
    )
    assert match, f"section {heading_id!r} not found"
    return match.group(0)


def text(fragment):
    return re.sub(r"\s+", " ", fragment).strip()


def plain(fragment):
    return text(re.sub(r"<[^>]+>", " ", fragment))


def cards(section_html):
    """Return [{'classes', 'label', 'value', 'html'}] for each stat-card.

    The pattern stops at the first closing div, so a card must not nest one."""
    result = []
    for classes, body in re.findall(
        r'<div class="([^"]*stat-card[^"]*)">(.*?)</div>', section_html, re.S
    ):
        label = re.search(r'<span class="stat-label">(.*?)</span>', body, re.S)
        value = re.search(r'<span class="stat-value">(.*?)</span>', body, re.S)
        result.append(
            {
                "classes": classes.split(),
                "label": text(label.group(1)) if label else None,
                "value": text(value.group(1)) if value else None,
                "html": body,
            }
        )
    return result


def available_cards(client, query=""):
    found = cards(available_section(profile_html(client, query)))
    assert [c["label"] for c in found] == ["Total Credits", "Available"]
    return {c["label"]: c for c in found}


def values(client, query=""):
    found = available_cards(client, query)
    return found["Total Credits"]["value"], found["Available"]["value"]


def stat_cards_by_label(html):
    return {c["label"]: c for c in cards(stats_section(html))}


def spending_view(html):
    """Stats text with the Total Saved card (label and value) removed."""
    tokens = plain(stats_section(html)).split()
    for i in range(len(tokens) - 2):
        if tokens[i] == "Total" and tokens[i + 1] == "Saved":
            assert tokens[i + 2].startswith("₹"), "Total Saved value not found"
            del tokens[i : i + 3]
            return tokens
    pytest.fail("Total Saved card not found")


def stat_labels(html):
    return [
        text(m)
        for m in re.findall(r'<span class="stat-label">(.*?)</span>', html, re.S)
    ]


def available_card_text(client, query=""):
    return plain(available_cards(client, query)["Available"]["html"])


def paid_from_select(html):
    match = re.search(r'<select\b[^>]*\bid="paid_from"[^>]*>.*?</select>', html, re.S)
    assert match, "paid_from select not found"
    return match.group(0)


def paid_from_options(html):
    """Return [(value, selected)] for the non-placeholder options, in order."""
    result = []
    for attrs, label in re.findall(
        r"<option\b([^>]*)>(.*?)</option>", paid_from_select(html), re.S
    ):
        value = re.search(r'value="([^"]*)"', attrs).group(1)
        if value == "":
            continue
        assert text(label) == value, "option label differs from its value"
        result.append((value, bool(re.search(r"\bselected\b", attrs))))
    return result


def edit_saving_url(saving_id):
    return f"/savings/{saving_id}/edit"


def delete_saving_url(saving_id):
    return f"/savings/{saving_id}/delete"


# ---- get_available_summary --------------------------------------------- #


class TestGetAvailableSummary:
    def test_returns_exact_dict(self, user_id):
        credit(user_id, 50000)
        expense(user_id, 12345.50)
        saving(user_id, 5000)
        assert get_available_summary(user_id) == {
            "total_credits": 50000.0,
            "total_spent": 12345.5,
            "saved_from_account": 5000.0,
            "available": 32654.5,
        }

    def test_returns_exactly_the_four_keys(self, user_id):
        assert set(get_available_summary(user_id)) == {
            "total_credits",
            "total_spent",
            "saved_from_account",
            "available",
        }

    @pytest.mark.parametrize(
        "paid_from, saved, available",
        [
            (OWN_ACCOUNT, 700.0, 300.0),
            (SALARY, 0, 1000.0),
            (OLD, 0, 1000.0),
        ],
    )
    def test_each_paid_from_option_effect(self, user_id, paid_from, saved, available):
        credit(user_id, 1000)
        saving(user_id, 700, paid_from)
        summary = get_available_summary(user_id)
        assert summary["total_credits"] == 1000.0
        assert summary["total_spent"] == 0
        assert summary["saved_from_account"] == saved
        assert summary["available"] == available

    @pytest.mark.parametrize(
        "near",
        [
            "my account",
            "My account ",
            " My account",
            "MY ACCOUNT",
            "My  account",
            "My account.",
            "Myaccount",
        ],
    )
    def test_near_matches_of_my_account_are_ignored(self, user_id, near):
        credit(user_id, 1000)
        saving(user_id, 700, near)
        summary = get_available_summary(user_id)
        assert summary["saved_from_account"] == 0
        assert summary["available"] == 1000.0

    def test_mixed_options_only_my_account_reduces(self, user_id):
        credit(user_id, 10000)
        saving(user_id, 1000, OWN_ACCOUNT)
        saving(user_id, 200, SALARY)
        saving(user_id, 30, OLD)
        saving(user_id, 4, "my account")
        saving(user_id, 5, OWN_ACCOUNT)
        summary = get_available_summary(user_id)
        assert summary["saved_from_account"] == 1005.0
        assert summary["available"] == 8995.0

    def test_totals_are_not_multiplied_by_row_counts(self, user_id):
        for amount in (100, 200, 300):
            credit(user_id, amount)
        for amount in (10, 20, 30, 40):
            expense(user_id, amount)
        for amount in (1, 2, 3, 4, 5):
            saving(user_id, amount)
        summary = get_available_summary(user_id)
        assert summary == {
            "total_credits": 600.0,
            "total_spent": 100.0,
            "saved_from_account": 15.0,
            "available": 485.0,
        }

    def test_other_users_rows_are_ignored(self, user_id, other_id):
        credit(user_id, 500)
        expense(user_id, 200)
        saving(user_id, 50)
        credit(other_id, 9999)
        expense(other_id, 7777)
        saving(other_id, 1111)
        assert get_available_summary(user_id) == {
            "total_credits": 500.0,
            "total_spent": 200.0,
            "saved_from_account": 50.0,
            "available": 250.0,
        }
        assert get_available_summary(other_id) == {
            "total_credits": 9999.0,
            "total_spent": 7777.0,
            "saved_from_account": 1111.0,
            "available": 1111.0,
        }

    def test_other_users_savings_never_change_my_available(self, user_id, other_id):
        credit(user_id, 500)
        before = get_available_summary(user_id)
        saving(other_id, 400)
        assert get_available_summary(user_id) == before

    def test_float_credit_expense_and_saving_cancel_to_positive_zero(self, user_id):
        credit(user_id, 0.30)
        expense(user_id, 0.10)
        saving(user_id, 0.20)
        summary = get_available_summary(user_id)
        assert summary["total_credits"] == 0.3
        assert summary["total_spent"] == 0.1
        assert summary["saved_from_account"] == 0.2
        assert summary["available"] == 0
        assert math.copysign(1, summary["available"]) == 1, "negative zero"

    def test_float_credits_and_saving_cancel_to_positive_zero(self, user_id):
        credit(user_id, 0.10)
        credit(user_id, 0.20)
        saving(user_id, 0.30)
        summary = get_available_summary(user_id)
        assert summary["available"] == 0
        assert math.copysign(1, summary["available"]) == 1

    def test_float_savings_are_rounded_to_two_places(self, user_id):
        saving(user_id, 0.10)
        saving(user_id, 0.20)
        assert get_available_summary(user_id)["saved_from_account"] == 0.3

    def test_equal_credits_and_savings_give_positive_zero(self, user_id):
        credit(user_id, 123.45)
        saving(user_id, 123.45)
        available = get_available_summary(user_id)["available"]
        assert available == 0
        assert math.copysign(1, available) == 1

    def test_sub_paisa_saving_alone_never_yields_negative_zero(self, user_id):
        saving(user_id, 0.004)
        summary = get_available_summary(user_id)
        for key in summary:
            assert summary[key] == 0, f"{key} should round to 0"
            assert math.copysign(1, summary[key]) == 1, f"{key} is negative zero"

    def test_sub_paisa_saving_rounds_up_to_one_paisa(self, user_id):
        saving(user_id, 0.007)
        summary = get_available_summary(user_id)
        assert summary["saved_from_account"] == 0.01
        assert summary["available"] == -0.01

    def test_negative_available_is_not_capped_at_zero(self, user_id):
        credit(user_id, 50000)
        expense(user_id, 30000)
        saving(user_id, 35000)
        assert get_available_summary(user_id)["available"] == -15000.0

    def test_no_data_gives_positive_zero_everywhere(self, user_id):
        summary = get_available_summary(user_id)
        assert summary == {
            "total_credits": 0,
            "total_spent": 0,
            "saved_from_account": 0,
            "available": 0,
        }
        for key, value in summary.items():
            assert math.copysign(1, value) == 1, f"{key} is negative zero"

    def test_total_credits_and_spent_match_net_summary_inputs(self, user_id):
        credit(user_id, 80)
        expense(user_id, 30)
        saving(user_id, 900)
        summary = get_available_summary(user_id)
        assert summary["total_credits"] == 80.0
        assert summary["total_spent"] == 30.0


class TestGetAvailableSummaryRanges:
    @pytest.fixture()
    def spread(self, user_id):
        # credits n, expenses n/10, savings n/100 on each date
        for day, amount in (
            ("2026-04-30", 1),
            ("2026-05-01", 10),
            ("2026-05-15", 100),
            ("2026-05-31", 1000),
            ("2026-06-01", 10000),
        ):
            credit(user_id, amount, day)
            expense(user_id, amount / 10, day)
            saving(user_id, amount / 100, date=day)

    def test_no_range_covers_everything(self, user_id, spread):
        assert get_available_summary(user_id) == {
            "total_credits": 11111.0,
            "total_spent": 1111.1,
            "saved_from_account": 111.11,
            "available": 9888.79,
        }

    def test_lower_bound_is_inclusive(self, user_id, spread):
        assert get_available_summary(user_id, date_from="2026-05-01") == {
            "total_credits": 11110.0,
            "total_spent": 1111.0,
            "saved_from_account": 111.1,
            "available": 9887.9,
        }

    def test_upper_bound_is_inclusive(self, user_id, spread):
        assert get_available_summary(user_id, date_to="2026-05-31") == {
            "total_credits": 1111.0,
            "total_spent": 111.1,
            "saved_from_account": 11.11,
            "available": 988.79,
        }

    def test_both_bounds_include_both_boundary_dates_only(self, user_id, spread):
        assert get_available_summary(user_id, "2026-05-01", "2026-05-31") == {
            "total_credits": 1110.0,
            "total_spent": 111.0,
            "saved_from_account": 11.1,
            "available": 987.9,
        }

    def test_single_day_range(self, user_id, spread):
        assert get_available_summary(user_id, "2026-05-15", "2026-05-15") == {
            "total_credits": 100.0,
            "total_spent": 10.0,
            "saved_from_account": 1.0,
            "available": 89.0,
        }

    def test_range_matching_nothing_gives_positive_zero(self, user_id, spread):
        summary = get_available_summary(user_id, "2030-01-01", "2030-12-31")
        assert summary == {
            "total_credits": 0,
            "total_spent": 0,
            "saved_from_account": 0,
            "available": 0,
        }
        for key, value in summary.items():
            assert math.copysign(1, value) == 1, f"{key} is negative zero"

    def test_saving_outside_period_does_not_reduce_available(self, user_id):
        credit(user_id, 1000, "2026-05-10")
        saving(user_id, 400, date="2026-01-01")
        saving(user_id, 30, date="2026-05-20")
        saving(user_id, 7000, date="2026-07-01")
        summary = get_available_summary(user_id, "2026-05-01", "2026-05-31")
        assert summary["saved_from_account"] == 30.0
        assert summary["available"] == 970.0

    def test_saving_is_filtered_by_its_own_date_not_created_at(self, user_id):
        saving(user_id, 400, date="2020-01-01")
        summary = get_available_summary(user_id, "2026-01-01", "2026-12-31")
        assert summary["saved_from_account"] == 0

    def test_credits_in_range_without_savings_or_expenses(self, user_id):
        credit(user_id, 10, "2026-05-01")
        saving(user_id, 5, date="2026-07-01")
        assert get_available_summary(user_id, "2026-05-01", "2026-05-31") == {
            "total_credits": 10.0,
            "total_spent": 0,
            "saved_from_account": 0,
            "available": 10.0,
        }

    def test_only_savings_in_range_give_negative_available(self, user_id):
        credit(user_id, 10, "2026-07-01")
        saving(user_id, 5, date="2026-05-01")
        assert get_available_summary(user_id, "2026-05-01", "2026-05-31") == {
            "total_credits": 0,
            "total_spent": 0,
            "saved_from_account": 5.0,
            "available": -5.0,
        }


# ---- Profile page values (moved from the Net tests) -------------------- #


class TestProfileAvailableValues:
    def test_positive_available_shows_exact_amounts(self, auth_client, user_id):
        credit(user_id, 50000)
        expense(user_id, 12345.50)
        found = available_cards(auth_client)
        assert found["Total Credits"]["value"] == "₹50,000.00"
        assert found["Available"]["value"] == "₹37,654.50"
        assert "stat-card--negative" not in found["Available"]["classes"]

    def test_negative_available_has_sign_before_symbol_and_negative_class(
        self, auth_client, user_id
    ):
        credit(user_id, 100)
        expense(user_id, 250)
        found = available_cards(auth_client)
        assert found["Total Credits"]["value"] == "₹100.00"
        assert found["Available"]["value"] == "-₹150.00"
        assert "stat-card--negative" in found["Available"]["classes"]

    def test_equal_amounts_show_zero_without_negative_style(self, auth_client, user_id):
        credit(user_id, 321.10)
        expense(user_id, 321.10)
        available = available_cards(auth_client)["Available"]
        assert available["value"] == "₹0.00"
        assert "stat-card--negative" not in available["classes"]

    def test_user_with_no_data_sees_zero_in_both_cards(self, auth_client):
        found = available_cards(auth_client)
        assert found["Total Credits"]["value"] == "₹0.00"
        assert found["Available"]["value"] == "₹0.00"
        assert "stat-card--negative" not in found["Available"]["classes"]

    def test_only_expenses_shows_zero_credits_and_negative_available(
        self, auth_client, user_id
    ):
        expense(user_id, 1234.5)
        found = available_cards(auth_client)
        assert found["Total Credits"]["value"] == "₹0.00"
        assert found["Available"]["value"] == "-₹1,234.50"
        assert "stat-card--negative" in found["Available"]["classes"]

    def test_only_credits_shows_positive_available(self, auth_client, user_id):
        credit(user_id, 1234.5)
        found = available_cards(auth_client)
        assert found["Total Credits"]["value"] == "₹1,234.50"
        assert found["Available"]["value"] == "₹1,234.50"
        assert "stat-card--negative" not in found["Available"]["classes"]

    def test_several_credits_and_expenses_are_not_multiplied(
        self, auth_client, user_id
    ):
        for amount in (100, 200, 300):
            credit(user_id, amount)
        for amount in (10, 20, 30, 40):
            expense(user_id, amount)
        assert values(auth_client) == ("₹600.00", "₹500.00")

    def test_several_savings_are_not_multiplied(self, auth_client, user_id):
        for amount in (100, 200, 300):
            credit(user_id, amount)
        for amount in (1, 2, 3, 4, 5):
            saving(user_id, amount)
        assert values(auth_client) == ("₹600.00", "₹585.00")

    def test_float_amounts_cancelling_show_positive_zero(self, auth_client, user_id):
        credit(user_id, 0.10)
        credit(user_id, 0.20)
        expense(user_id, 0.30)
        found = available_cards(auth_client)
        assert found["Available"]["value"] == "₹0.00"
        assert "-₹0.00" not in available_section(profile_html(auth_client))
        assert "stat-card--negative" not in found["Available"]["classes"]

    def test_float_credit_expense_and_saving_cancelling_show_positive_zero(
        self, auth_client, user_id
    ):
        credit(user_id, 0.30)
        expense(user_id, 0.10)
        saving(user_id, 0.20)
        found = available_cards(auth_client)
        assert found["Available"]["value"] == "₹0.00"
        assert "-₹0.00" not in available_section(profile_html(auth_client))
        assert "stat-card--negative" not in found["Available"]["classes"]

    def test_sub_paisa_credit_rounds_to_one_paisa(self, auth_client, user_id):
        credit(user_id, 0.007)
        assert values(auth_client) == ("₹0.01", "₹0.01")

    def test_sub_paisa_expense_never_shows_negative_zero(self, auth_client, user_id):
        expense(user_id, 0.004)
        found = available_cards(auth_client)
        assert found["Available"]["value"] == "₹0.00"
        assert "stat-card--negative" not in found["Available"]["classes"]

    def test_sub_paisa_saving_never_shows_negative_zero(self, auth_client, user_id):
        saving(user_id, 0.004)
        found = available_cards(auth_client)
        assert found["Available"]["value"] == "₹0.00"
        assert "stat-card--negative" not in found["Available"]["classes"]

    def test_one_crore_positive_fits_with_separators(self, auth_client, user_id):
        credit(user_id, 10_000_000)
        assert values(auth_client) == ("₹10,000,000.00", "₹10,000,000.00")

    def test_one_crore_negative_keeps_sign_and_style(self, auth_client, user_id):
        expense(user_id, 10_000_000)
        found = available_cards(auth_client)
        assert found["Available"]["value"] == "-₹10,000,000.00"
        assert "stat-card--negative" in found["Available"]["classes"]

    def test_one_crore_negative_from_savings_keeps_sign_and_style(
        self, auth_client, user_id
    ):
        saving(user_id, 10_000_000)
        found = available_cards(auth_client)
        assert found["Total Credits"]["value"] == "₹0.00"
        assert found["Available"]["value"] == "-₹10,000,000.00"
        assert "stat-card--negative" in found["Available"]["classes"]

    def test_negative_class_only_when_available_below_zero(self, auth_client, user_id):
        credit(user_id, 100)
        expense(user_id, 100.01)
        assert (
            "stat-card--negative"
            in available_cards(auth_client)["Available"]["classes"]
        )

    def test_available_card_always_has_available_class(self, auth_client):
        assert (
            "stat-card--available"
            in available_cards(auth_client)["Available"]["classes"]
        )

    def test_available_class_is_kept_when_negative(self, auth_client, user_id):
        expense(user_id, 5)
        classes = available_cards(auth_client)["Available"]["classes"]
        assert "stat-card--available" in classes
        assert "stat-card--negative" in classes

    def test_other_users_data_never_affects_cards(self, auth_client, user_id, other_id):
        credit(user_id, 500)
        expense(user_id, 200)
        credit(other_id, 9999)
        expense(other_id, 7777)
        saving(other_id, 1234)
        assert values(auth_client) == ("₹500.00", "₹300.00")

    def test_other_users_savings_do_not_change_available(
        self, auth_client, user_id, other_id
    ):
        credit(user_id, 500)
        saving(user_id, 100)
        saving(other_id, 400)
        assert values(auth_client) == ("₹500.00", "₹400.00")


# ---- Date filter (moved) ------------------------------------------------ #


class TestProfileAvailableDateFilter:
    @pytest.fixture()
    def spread(self, user_id):
        for day, amount in (
            ("2026-04-30", 1),
            ("2026-05-01", 10),
            ("2026-05-15", 100),
            ("2026-05-31", 1000),
            ("2026-06-01", 10000),
        ):
            credit(user_id, amount, day)
            expense(user_id, amount / 10, day)

    @pytest.fixture()
    def spread_with_savings(self, user_id, spread):
        for day, amount in (
            ("2026-04-30", 0.01),
            ("2026-05-01", 0.1),
            ("2026-05-15", 1),
            ("2026-05-31", 10),
            ("2026-06-01", 100),
        ):
            saving(user_id, amount, date=day)

    def test_both_boundary_dates_are_included(self, auth_client, spread):
        assert values(auth_client, "?from=2026-05-01&to=2026-05-31") == (
            "₹1,110.00",
            "₹999.00",
        )

    def test_from_only_range(self, auth_client, spread):
        # credits 10+100+1000+10000, expenses 1+10+100+1000
        assert values(auth_client, "?from=2026-05-01") == ("₹11,110.00", "₹9,999.00")

    def test_to_only_range(self, auth_client, spread):
        # credits 1+10+100+1000, expenses 0.1+1+10+100
        assert values(auth_client, "?to=2026-05-31") == ("₹1,111.00", "₹999.90")

    def test_single_day_range(self, auth_client, spread):
        assert values(auth_client, "?from=2026-05-15&to=2026-05-15") == (
            "₹100.00",
            "₹90.00",
        )

    def test_range_matching_nothing_shows_zero_in_both(self, auth_client, spread):
        found = available_cards(auth_client, "?from=2030-01-01&to=2030-12-31")
        assert found["Total Credits"]["value"] == "₹0.00"
        assert found["Available"]["value"] == "₹0.00"
        assert "stat-card--negative" not in found["Available"]["classes"]

    def test_range_matching_nothing_with_savings_shows_zero_in_both(
        self, auth_client, spread_with_savings
    ):
        found = available_cards(auth_client, "?from=2030-01-01&to=2030-12-31")
        assert found["Total Credits"]["value"] == "₹0.00"
        assert found["Available"]["value"] == "₹0.00"
        assert "stat-card--negative" not in found["Available"]["classes"]

    def test_filter_applies_to_negative_available(self, auth_client, user_id):
        credit(user_id, 10, "2026-05-01")
        expense(user_id, 60, "2026-05-02")
        credit(user_id, 5000, "2026-07-01")
        found = available_cards(auth_client, "?from=2026-05-01&to=2026-05-31")
        assert found["Available"]["value"] == "-₹50.00"
        assert "stat-card--negative" in found["Available"]["classes"]

    @pytest.mark.parametrize(
        "query, expected",
        [
            ("", ("₹11,111.00", "₹9,888.79")),
            ("?from=2026-05-01&to=2026-05-31", ("₹1,110.00", "₹987.90")),
            ("?from=2026-05-01", ("₹11,110.00", "₹9,887.90")),
            ("?to=2026-05-31", ("₹1,111.00", "₹988.79")),
            ("?from=2026-05-15&to=2026-05-15", ("₹100.00", "₹89.00")),
        ],
    )
    def test_savings_follow_the_filter_with_inclusive_bounds(
        self, auth_client, spread_with_savings, query, expected
    ):
        assert values(auth_client, query) == expected

    def test_saving_outside_period_does_not_reduce_available(
        self, auth_client, user_id
    ):
        credit(user_id, 1000, "2026-05-10")
        saving(user_id, 400, date="2026-01-01")
        assert values(auth_client) == ("₹1,000.00", "₹600.00")
        assert values(auth_client, "?from=2026-05-01&to=2026-05-31") == (
            "₹1,000.00",
            "₹1,000.00",
        )

    @pytest.mark.parametrize(
        "query",
        [
            "?from=garbage",
            "?to=garbage",
            "?from=2026-13-45&to=2026-99-99",
            "?from=20260501",
            "?to=2026-W20-1",
            "?from=&to=",
            "?from=2026-02-30",
            "?from=%27%3B+DROP+TABLE+credits%3B--",
        ],
    )
    def test_invalid_date_params_are_ignored(self, auth_client, spread, query):
        assert values(auth_client, query) == ("₹11,111.00", "₹9,999.90")
        response = auth_client.get("/profile" + query)
        assert response.status_code == 200

    def test_invalid_from_with_valid_to_applies_only_valid_bound(
        self, auth_client, spread
    ):
        assert values(auth_client, "?from=junk&to=2026-05-31") == values(
            auth_client, "?to=2026-05-31"
        )


# ---- Mutations through routes ------------------------------------------ #


class TestAvailableUpdatesThroughRoutes:
    def test_adding_a_credit_increases_credits_and_available(self, auth_client):
        assert values(auth_client) == ("₹0.00", "₹0.00")
        response = auth_client.post("/credits/add", data=CREDIT_FORM)
        assert response.status_code == 302
        assert values(auth_client) == ("₹100.00", "₹100.00")

    def test_editing_a_credit_updates_credits_and_available(self, auth_client, user_id):
        credit(user_id, 100)
        cid = last_id("credits")
        response = auth_client.post(
            f"/credits/{cid}/edit", data={**CREDIT_FORM, "amount": "250.25"}
        )
        assert response.status_code == 302
        assert values(auth_client) == ("₹250.25", "₹250.25")

    def test_deleting_a_credit_updates_credits_and_available(
        self, auth_client, user_id
    ):
        credit(user_id, 100)
        credit(user_id, 30)
        cid = last_id("credits")
        response = auth_client.post(f"/credits/{cid}/delete")
        assert response.status_code == 302
        assert values(auth_client) == ("₹100.00", "₹100.00")

    def test_adding_an_expense_decreases_available(self, auth_client, user_id):
        credit(user_id, 100)
        response = auth_client.post("/expenses/add", data=EXPENSE_FORM)
        assert response.status_code == 302
        assert values(auth_client) == ("₹100.00", "₹60.00")

    def test_editing_an_expense_updates_available(self, auth_client, user_id):
        credit(user_id, 100)
        expense(user_id, 40)
        eid = last_id("expenses")
        response = auth_client.post(
            f"/expenses/{eid}/edit", data={**EXPENSE_FORM, "amount": "150.00"}
        )
        assert response.status_code == 302
        found = available_cards(auth_client)
        assert found["Total Credits"]["value"] == "₹100.00"
        assert found["Available"]["value"] == "-₹50.00"
        assert "stat-card--negative" in found["Available"]["classes"]

    def test_deleting_an_expense_updates_available(self, auth_client, user_id):
        credit(user_id, 100)
        expense(user_id, 40)
        eid = last_id("expenses")
        response = auth_client.post(f"/expenses/{eid}/delete")
        assert response.status_code == 302
        assert values(auth_client) == ("₹100.00", "₹100.00")

    def test_total_credits_does_not_change_when_an_expense_changes(
        self, auth_client, user_id
    ):
        credit(user_id, 100)
        before = available_cards(auth_client)["Total Credits"]
        assert auth_client.post("/expenses/add", data=EXPENSE_FORM).status_code == 302
        eid = last_id("expenses")
        auth_client.post(
            f"/expenses/{eid}/edit", data={**EXPENSE_FORM, "amount": "70.00"}
        )
        auth_client.post(f"/expenses/{eid}/delete")
        assert available_cards(auth_client)["Total Credits"] == before


# ---- Savings through routes -------------------------------------------- #


class TestSavingsThroughRoutes:
    @pytest.fixture()
    def funded(self, user_id):
        credit(user_id, 50000)
        expense(user_id, 30000)

    def test_funded_user_sees_twenty_thousand_available(self, auth_client, funded):
        assert values(auth_client) == ("₹50,000.00", "₹20,000.00")

    def test_sip_from_my_account_lowers_available_only(self, auth_client, funded):
        response = auth_client.post("/savings/add", data=SAVING_FORM)
        assert response.status_code == 302
        html = profile_html(auth_client)
        found = {c["label"]: c for c in cards(available_section(html))}
        assert found["Total Credits"]["value"] == "₹50,000.00"
        assert found["Available"]["value"] == "₹15,000.00"
        stats = stat_cards_by_label(html)
        assert stats["Total Spent"]["value"] == "₹30,000.00"
        assert stats["Total Saved"]["value"] == "₹5,000.00"
        [row] = rows("savings")
        assert row["paid_from"] == OWN_ACCOUNT

    def test_old_fd_raises_total_saved_and_leaves_available(self, auth_client, funded):
        response = auth_client.post(
            "/savings/add",
            data={
                **SAVING_FORM,
                "amount": "200000",
                "type": "FD",
                "paid_from": OLD,
            },
        )
        assert response.status_code == 302
        html = profile_html(auth_client)
        assert stat_cards_by_label(html)["Total Saved"]["value"] == "₹200,000.00"
        found = {c["label"]: c for c in cards(available_section(html))}
        assert found["Total Credits"]["value"] == "₹50,000.00"
        assert found["Available"]["value"] == "₹20,000.00"
        assert rows("savings")[0]["paid_from"] == OLD

    def test_epf_by_salary_deduction_raises_total_saved_and_leaves_available(
        self, auth_client, funded
    ):
        response = auth_client.post(
            "/savings/add",
            data={
                **SAVING_FORM,
                "amount": "1800.00",
                "type": "EPF",
                "paid_from": SALARY,
            },
        )
        assert response.status_code == 302
        html = profile_html(auth_client)
        assert stat_cards_by_label(html)["Total Saved"]["value"] == "₹1,800.00"
        found = {c["label"]: c for c in cards(available_section(html))}
        assert found["Available"]["value"] == "₹20,000.00"
        assert "stat-card--negative" not in found["Available"]["classes"]

    def test_saving_more_than_credits_minus_expenses_shows_negative_with_explanation(
        self, auth_client, funded
    ):
        response = auth_client.post(
            "/savings/add", data={**SAVING_FORM, "amount": "35000.00"}
        )
        assert response.status_code == 302
        found = available_cards(auth_client)
        assert found["Available"]["value"] == "-₹15,000.00"
        assert "stat-card--negative" in found["Available"]["classes"]
        assert plain(found["Available"]["html"]) == (
            f"Available -₹15,000.00 {BASE_NOTE} {EXPLAIN_SAVINGS}"
        )

    def test_editing_from_my_account_to_old_and_back(
        self, auth_client, user_id, funded
    ):
        sid = saving(user_id, 5000)
        html = profile_html(auth_client)
        assert available_cards(auth_client)["Available"]["value"] == "₹15,000.00"
        assert stat_cards_by_label(html)["Total Saved"]["value"] == "₹5,000.00"

        response = auth_client.post(
            edit_saving_url(sid), data={**SAVING_FORM, "paid_from": OLD}
        )
        assert response.status_code == 302
        html = profile_html(auth_client)
        assert available_cards(auth_client)["Available"]["value"] == "₹20,000.00"
        assert stat_cards_by_label(html)["Total Saved"]["value"] == "₹5,000.00"
        assert rows("savings")[0]["paid_from"] == OLD

        response = auth_client.post(
            edit_saving_url(sid), data={**SAVING_FORM, "paid_from": OWN_ACCOUNT}
        )
        assert response.status_code == 302
        html = profile_html(auth_client)
        assert available_cards(auth_client)["Available"]["value"] == "₹15,000.00"
        assert stat_cards_by_label(html)["Total Saved"]["value"] == "₹5,000.00"
        assert rows("savings")[0]["paid_from"] == OWN_ACCOUNT

    def test_old_saving_keeps_its_real_date_when_edited_to_old(
        self, auth_client, user_id, funded
    ):
        sid = saving(user_id, 5000, date="2019-03-04")
        auth_client.post(
            edit_saving_url(sid),
            data={**SAVING_FORM, "date": "2019-03-04", "paid_from": OLD},
        )
        assert rows("savings")[0]["date"] == "2019-03-04"
        period = "?from=2019-01-01&to=2019-12-31"
        stats = stat_cards_by_label(profile_html(auth_client, period))
        assert stats["Total Saved"]["value"] == "₹5,000.00"
        other = stat_cards_by_label(profile_html(auth_client, "?from=2026-01-01"))
        assert other["Total Saved"]["value"] == "₹0.00"

    def test_deleting_a_saving_from_my_account_raises_available(
        self, auth_client, user_id, funded
    ):
        sid = saving(user_id, 5000)
        assert available_cards(auth_client)["Available"]["value"] == "₹15,000.00"
        response = auth_client.post(delete_saving_url(sid))
        assert response.status_code == 302
        html = profile_html(auth_client)
        assert available_cards(auth_client)["Available"]["value"] == "₹20,000.00"
        assert stat_cards_by_label(html)["Total Saved"]["value"] == "₹0.00"

    def test_deleting_an_old_saving_leaves_available(
        self, auth_client, user_id, funded
    ):
        sid = saving(user_id, 5000, OLD)
        response = auth_client.post(delete_saving_url(sid))
        assert response.status_code == 302
        assert available_cards(auth_client)["Available"]["value"] == "₹20,000.00"

    def test_saving_larger_than_available_is_added_without_error(
        self, auth_client, funded
    ):
        response = auth_client.post(
            "/savings/add", data={**SAVING_FORM, "amount": "90000.00"}
        )
        assert response.status_code == 302
        assert response.headers["Location"] == "/profile"
        assert [r["amount"] for r in rows("savings")] == [90000.0]
        html = profile_html(auth_client)
        assert "auth-error" not in html
        assert available_cards(auth_client)["Available"]["value"] == "-₹70,000.00"

    def test_saving_larger_than_available_is_edited_without_error(
        self, auth_client, user_id, funded
    ):
        sid = saving(user_id, 100)
        response = auth_client.post(
            edit_saving_url(sid), data={**SAVING_FORM, "amount": "200000.00"}
        )
        assert response.status_code == 302
        assert [r["amount"] for r in rows("savings")] == [200000.0]
        html = profile_html(auth_client)
        assert "auth-error" not in html
        assert available_cards(auth_client)["Available"]["value"] == "-₹180,000.00"

    def test_saving_larger_than_available_is_deleted_without_error(
        self, auth_client, user_id, funded
    ):
        sid = saving(user_id, 90000)
        assert available_cards(auth_client)["Available"]["value"] == "-₹70,000.00"
        page = auth_client.get(delete_saving_url(sid))
        assert page.status_code == 200
        response = auth_client.post(delete_saving_url(sid))
        assert response.status_code == 302
        assert rows("savings") == []
        assert "auth-error" not in profile_html(auth_client)
        assert available_cards(auth_client)["Available"]["value"] == "₹20,000.00"

    def test_savings_never_change_total_credits(self, auth_client, user_id, funded):
        before = available_cards(auth_client)["Total Credits"]
        assert auth_client.post("/savings/add", data=SAVING_FORM).status_code == 302
        assert available_cards(auth_client)["Total Credits"] == before
        sid = last_id("savings")
        auth_client.post(
            edit_saving_url(sid), data={**SAVING_FORM, "amount": "99999.00"}
        )
        assert available_cards(auth_client)["Total Credits"] == before
        auth_client.post(delete_saving_url(sid))
        assert available_cards(auth_client)["Total Credits"] == before

    @pytest.mark.parametrize("paid_from", PAID_FROM)
    def test_savings_change_only_total_saved_among_stats(
        self, auth_client, user_id, funded, paid_from
    ):
        before = spending_view(profile_html(auth_client))
        assert (
            auth_client.post(
                "/savings/add", data={**SAVING_FORM, "paid_from": paid_from}
            ).status_code
            == 302
        )
        assert spending_view(profile_html(auth_client)) == before
        sid = last_id("savings")
        auth_client.post(
            edit_saving_url(sid),
            data={**SAVING_FORM, "amount": "123.00", "paid_from": paid_from},
        )
        assert spending_view(profile_html(auth_client)) == before
        auth_client.post(delete_saving_url(sid))
        assert spending_view(profile_html(auth_client)) == before


# ---- Notes and explanations -------------------------------------------- #


class TestNotes:
    @pytest.mark.parametrize(
        "setup",
        ["none", "positive", "zero", "negative_spent", "negative_saved"],
    )
    def test_base_note_is_always_in_available_card_after_the_value(
        self, auth_client, user_id, setup
    ):
        if setup == "positive":
            credit(user_id, 100)
        elif setup == "zero":
            credit(user_id, 100)
            expense(user_id, 100)
        elif setup == "negative_spent":
            expense(user_id, 100)
        elif setup == "negative_saved":
            saving(user_id, 100)
        html = profile_html(auth_client)
        found = {c["label"]: c for c in cards(available_section(html))}
        card = found["Available"]["html"]
        assert BASE_NOTE in card
        assert card.index('<span class="stat-value">') < card.index(BASE_NOTE)
        assert html.count(BASE_NOTE) == 1, "base note must appear exactly once"

    def test_base_note_is_not_in_total_credits_card(self, auth_client, user_id):
        expense(user_id, 100)
        found = available_cards(auth_client)
        assert BASE_NOTE not in found["Total Credits"]["html"]
        assert plain(found["Total Credits"]["html"]) == "Total Credits ₹0.00"

    @pytest.mark.parametrize(
        "credit_amount, expense_amount, saving_amount",
        [
            (None, None, None),
            (100, None, None),
            (100, 40, None),
            (100, 40, 60),
            (100, 100, None),
            (100, None, 100),
            (100, 10, 20),
        ],
    )
    def test_no_explanation_when_available_is_zero_or_above(
        self, auth_client, user_id, credit_amount, expense_amount, saving_amount
    ):
        if credit_amount:
            credit(user_id, credit_amount)
        if expense_amount:
            expense(user_id, expense_amount)
        if saving_amount:
            saving(user_id, saving_amount)
        found = available_cards(auth_client)["Available"]
        assert "stat-card--negative" not in found["classes"]
        assert plain(found["html"]).endswith(BASE_NOTE)
        html = profile_html(auth_client)
        assert EXPLAIN_SAVINGS not in plain(html)
        assert EXPLAIN_SPENT not in plain(html)

    def test_float_zero_shows_no_explanation(self, auth_client, user_id):
        credit(user_id, 0.30)
        expense(user_id, 0.10)
        saving(user_id, 0.20)
        found = available_cards(auth_client)["Available"]
        assert plain(found["html"]) == f"Available ₹0.00 {BASE_NOTE}"
        assert "stat-card--negative" not in found["classes"]

    def test_spent_more_explanation_only_when_nothing_saved(self, auth_client, user_id):
        credit(user_id, 100)
        expense(user_id, 250)
        found = available_cards(auth_client)["Available"]
        assert plain(found["html"]) == (
            f"Available -₹150.00 {BASE_NOTE} {EXPLAIN_SPENT}"
        )
        assert EXPLAIN_SAVINGS not in plain(profile_html(auth_client))

    def test_spent_more_explanation_when_only_expenses_exist(
        self, auth_client, user_id
    ):
        expense(user_id, 80)
        found = available_cards(auth_client)["Available"]
        assert plain(found["html"]) == f"Available -₹80.00 {BASE_NOTE} {EXPLAIN_SPENT}"

    @pytest.mark.parametrize("paid_from", [SALARY, OLD])
    def test_savings_not_from_account_keep_the_spent_more_explanation(
        self, auth_client, user_id, paid_from
    ):
        credit(user_id, 100)
        expense(user_id, 250)
        saving(user_id, 500, paid_from)
        found = available_cards(auth_client)["Available"]
        assert plain(found["html"]) == (
            f"Available -₹150.00 {BASE_NOTE} {EXPLAIN_SPENT}"
        )
        assert EXPLAIN_SAVINGS not in plain(profile_html(auth_client))

    def test_savings_explanation_when_savings_push_below_zero(
        self, auth_client, user_id
    ):
        credit(user_id, 50000)
        expense(user_id, 30000)
        saving(user_id, 35000)
        found = available_cards(auth_client)["Available"]
        assert plain(found["html"]) == (
            f"Available -₹15,000.00 {BASE_NOTE} {EXPLAIN_SAVINGS}"
        )
        assert EXPLAIN_SPENT not in plain(profile_html(auth_client))

    def test_savings_explanation_when_expenses_alone_exceed_credits(
        self, auth_client, user_id
    ):
        credit(user_id, 100)
        expense(user_id, 250)
        saving(user_id, 10)
        found = available_cards(auth_client)["Available"]
        assert plain(found["html"]) == (
            f"Available -₹160.00 {BASE_NOTE} {EXPLAIN_SAVINGS}"
        )
        assert EXPLAIN_SPENT not in plain(profile_html(auth_client))

    def test_savings_explanation_when_only_a_saving_exists(self, auth_client, user_id):
        saving(user_id, 0.01)
        found = available_cards(auth_client)["Available"]
        assert plain(found["html"]) == (
            f"Available -₹0.01 {BASE_NOTE} {EXPLAIN_SAVINGS}"
        )

    def test_explanations_are_only_in_the_available_card(self, auth_client, user_id):
        credit(user_id, 100)
        saving(user_id, 500)
        html = profile_html(auth_client)
        found = {c["label"]: c for c in cards(available_section(html))}
        assert plain(found["Total Credits"]["html"]) == "Total Credits ₹100.00"
        assert plain(html).count(EXPLAIN_SAVINGS) == 1

    def test_explanation_follows_the_date_filter(self, auth_client, user_id):
        credit(user_id, 1000, "2026-05-10")
        expense(user_id, 200, "2026-05-11")
        saving(user_id, 5000, date="2026-06-15")
        in_may = available_cards(auth_client, "?from=2026-05-01&to=2026-05-31")
        assert plain(in_may["Available"]["html"]) == (f"Available ₹800.00 {BASE_NOTE}")
        in_june = available_cards(auth_client, "?from=2026-06-01&to=2026-06-30")
        assert plain(in_june["Available"]["html"]) == (
            f"Available -₹5,000.00 {BASE_NOTE} {EXPLAIN_SAVINGS}"
        )

    def test_explanation_vanishes_after_marking_saving_as_old(
        self, auth_client, user_id
    ):
        credit(user_id, 100)
        sid = saving(user_id, 500)
        assert EXPLAIN_SAVINGS in plain(profile_html(auth_client))
        auth_client.post(
            edit_saving_url(sid),
            data={**SAVING_FORM, "amount": "500.00", "paid_from": OLD},
        )
        found = available_cards(auth_client)["Available"]
        assert plain(found["html"]) == f"Available ₹100.00 {BASE_NOTE}"
        assert EXPLAIN_SAVINGS not in plain(profile_html(auth_client))


# ---- Savings form ------------------------------------------------------- #


class TestPaidFromForm:
    def test_add_form_has_exactly_three_options_in_order(self, auth_client):
        html = auth_client.get("/savings/add").get_data(as_text=True)
        assert [value for value, _ in paid_from_options(html)] == PAID_FROM

    def test_add_form_preselects_my_account_only(self, auth_client):
        html = auth_client.get("/savings/add").get_data(as_text=True)
        selected = [value for value, chosen in paid_from_options(html) if chosen]
        assert selected == [OWN_ACCOUNT]

    @pytest.mark.parametrize("stored", PAID_FROM)
    def test_edit_form_has_three_options_and_preselects_stored_value(
        self, auth_client, user_id, stored
    ):
        sid = saving(user_id, 100, stored)
        html = auth_client.get(edit_saving_url(sid)).get_data(as_text=True)
        options = paid_from_options(html)
        assert [value for value, _ in options] == PAID_FROM
        assert [value for value, chosen in options if chosen] == [stored]

    @pytest.mark.parametrize("mode", ["add", "edit"])
    def test_hint_is_shown_and_linked_with_aria_describedby(
        self, auth_client, user_id, mode
    ):
        if mode == "add":
            html = auth_client.get("/savings/add").get_data(as_text=True)
        else:
            sid = saving(user_id, 100)
            html = auth_client.get(edit_saving_url(sid)).get_data(as_text=True)
        assert html.count(HINT) == 1
        select_tag = re.search(r'<select\b[^>]*\bid="paid_from"[^>]*>', html).group(0)
        described = re.search(r'aria-describedby="([^"]+)"', select_tag)
        assert described, "paid_from select has no aria-describedby"
        hint_id = described.group(1)
        assert hint_id != "paid_from"
        target = re.search(
            rf'<(\w+)\b[^>]*\bid="{re.escape(hint_id)}"[^>]*>(.*?)</\1>', html, re.S
        )
        assert target, f"no element with id {hint_id!r}"
        assert text(target.group(2)) == HINT

    def test_hint_sits_under_the_select(self, auth_client):
        html = auth_client.get("/savings/add").get_data(as_text=True)
        assert html.index("</select>") < html.index(HINT)
        assert html.index(HINT) < html.index('id="institution"')

    def test_hint_uses_the_form_hint_class(self, auth_client):
        html = auth_client.get("/savings/add").get_data(as_text=True)
        assert re.search(r'<p[^>]*class="form-hint"[^>]*>\s*' + re.escape(HINT), html)

    def test_hint_is_not_on_the_expense_or_credit_forms(self, auth_client, user_id):
        expense(user_id, 10)
        credit(user_id, 10)
        urls = [
            "/expenses/add",
            f"/expenses/{last_id('expenses')}/edit",
            "/credits/add",
            f"/credits/{last_id('credits')}/edit",
        ]
        for url in urls:
            response = auth_client.get(url)
            assert response.status_code == 200
            html = response.get_data(as_text=True)
            assert HINT not in html, f"hint found on {url}"
            assert "paid-from-hint" not in html, f"hint id found on {url}"
            assert "available balance" not in html, f"hint wording found on {url}"

    @pytest.mark.parametrize("mode", ["add", "edit"])
    @pytest.mark.parametrize("option", PAID_FROM)
    def test_each_option_is_accepted_and_stored(
        self, auth_client, user_id, mode, option
    ):
        data = {**SAVING_FORM, "paid_from": option}
        if mode == "add":
            response = auth_client.post("/savings/add", data=data)
        else:
            sid = saving(user_id, 100, SALARY if option != SALARY else OWN_ACCOUNT)
            response = auth_client.post(edit_saving_url(sid), data=data)
        assert response.status_code == 302
        assert rows("savings")[-1]["paid_from"] == option

    @pytest.mark.parametrize(
        "invalid",
        [
            "Cash",
            "",
            "my account",
            "already saved before spendly",
            "Already saved",
        ],
    )
    def test_invalid_option_is_rejected_on_add_and_nothing_is_saved(
        self, auth_client, invalid
    ):
        response = auth_client.post(
            "/savings/add", data={**SAVING_FORM, "paid_from": invalid}
        )
        assert response.status_code == 200
        assert PAID_MSG in response.get_data(as_text=True)
        assert rows("savings") == []

    @pytest.mark.parametrize("invalid", ["Cash", "my account", "Already saved"])
    def test_invalid_option_is_rejected_on_edit_and_row_is_unchanged(
        self, auth_client, user_id, invalid
    ):
        sid = saving(user_id, 100, OLD)
        before = rows("savings")
        response = auth_client.post(
            edit_saving_url(sid), data={**SAVING_FORM, "paid_from": invalid}
        )
        assert response.status_code == 200
        assert PAID_MSG in response.get_data(as_text=True)
        assert rows("savings") == before

    def test_missing_option_is_rejected_and_nothing_is_saved(self, auth_client):
        data = {k: v for k, v in SAVING_FORM.items() if k != "paid_from"}
        response = auth_client.post("/savings/add", data=data)
        assert response.status_code == 200
        assert PAID_MSG in response.get_data(as_text=True)
        assert rows("savings") == []


# ---- Where the new option is shown ------------------------------------- #


class TestOldOptionDisplay:
    def saving_details(self, client):
        block = section(profile_html(client), "saving-heading")
        return re.findall(r'<span class="tx-details">(.*?)</span>', block, re.S)

    def test_old_option_is_shown_in_details_under_the_description(
        self, auth_client, user_id
    ):
        add_saving(user_id, 100, "FD", "2026-05-10", OLD, "Old FD")
        block = section(profile_html(auth_client), "saving-heading")
        cell = re.search(r'<td[^>]*class="tx-desc[^"]*">(.*?)</td>', block, re.S)
        assert cell, "description cell not found"
        description, details = re.match(
            r'(.*?)<span class="tx-details">(.*?)</span>', cell.group(1), re.S
        ).groups()
        assert text(description) == "Old FD"
        assert text(details) == OLD

    def test_old_option_follows_the_other_details(self, auth_client, user_id):
        add_saving(user_id, 100, "FD", "2026-05-10", OLD, "Old FD", "SBI", 7.1)
        assert [text(d) for d in self.saving_details(auth_client)] == [
            f"SBI · 7.1% · {OLD}"
        ]

    def test_salary_option_is_still_shown_in_details(self, auth_client, user_id):
        add_saving(user_id, 100, "EPF", "2026-05-10", SALARY, "PF")
        assert [text(d) for d in self.saving_details(auth_client)] == [SALARY]

    def test_my_account_is_not_shown_in_details(self, auth_client, user_id):
        add_saving(user_id, 100, "FD", "2026-05-10", OWN_ACCOUNT, "Plain FD")
        assert self.saving_details(auth_client) == []

    def test_old_saving_follows_date_filter_in_every_savings_view(
        self, auth_client, user_id
    ):
        add_saving(user_id, 250, "PPF", "2019-03-04", OLD, "Ancient")
        html = profile_html(auth_client, "?from=2019-01-01&to=2019-12-31")
        assert stat_cards_by_label(html)["Total Saved"]["value"] == "₹250.00"
        recent = section(html, "saving-heading")
        assert "Ancient" in recent
        assert "₹250.00" in recent
        by_type = section(html, "saving-type-heading")
        assert "PPF" in by_type
        assert "₹250.00" in by_type
        later = profile_html(auth_client, "?from=2026-01-01")
        assert stat_cards_by_label(later)["Total Saved"]["value"] == "₹0.00"
        assert "Ancient" not in later

    def test_old_option_is_on_the_delete_confirmation_page(self, auth_client, user_id):
        sid = saving(user_id, 100, OLD)
        response = auth_client.get(delete_saving_url(sid))
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        match = re.search(r"<dt>Paid from</dt>\s*<dd>(.*?)</dd>", html, re.S)
        assert match, "Paid from row not found on delete page"
        assert text(match.group(1)) == OLD

    def test_salary_option_is_on_the_delete_confirmation_page(
        self, auth_client, user_id
    ):
        sid = saving(user_id, 100, SALARY)
        html = auth_client.get(delete_saving_url(sid)).get_data(as_text=True)
        match = re.search(r"<dt>Paid from</dt>\s*<dd>(.*?)</dd>", html, re.S)
        assert text(match.group(1)) == SALARY

    def test_loading_profile_leaves_existing_rows_unchanged(self, auth_client, user_id):
        add_saving(user_id, 10, "FD", "2018-01-01", OWN_ACCOUNT, "Old row", "SBI", 7.1)
        add_saving(user_id, 20, "EPF", "2026-05-01", SALARY, "Pay")
        add_saving(
            user_id, 30, "PPF", "2024-01-01", OLD, None, None, None, "2030-01-01"
        )
        add_saving(user_id, 40, "SIP", "2020-02-02", OWN_ACCOUNT)
        before = rows("savings")
        assert len(before) == 4
        profile_html(auth_client)
        profile_html(auth_client, "?from=2026-01-01&to=2026-12-31")
        assert rows("savings") == before
        assert [r["paid_from"] for r in before] == [
            OWN_ACCOUNT,
            SALARY,
            OLD,
            OWN_ACCOUNT,
        ]


# ---- Structure ----------------------------------------------------------- #


class TestStructure:
    def test_available_section_sits_between_date_filter_and_stats(self, auth_client):
        html = profile_html(auth_client)
        filter_pos = html.index('class="date-filter"')
        available_pos = html.index('class="profile-available"')
        stats_pos = html.index('class="profile-stats"')
        assert filter_pos < available_pos < stats_pos

    def test_section_has_the_spec_aria_label(self, auth_client):
        html = profile_html(auth_client)
        assert (
            '<section class="profile-available" '
            'aria-label="Income and available balance">'
        ) in html

    def test_section_has_exactly_two_cards_in_order(self, auth_client):
        found = cards(available_section(profile_html(auth_client)))
        assert [c["label"] for c in found] == ["Total Credits", "Available"]

    def test_cards_always_rendered_for_user_without_data(self, auth_client):
        section_html = available_section(profile_html(auth_client))
        assert ">Total Credits<" in section_html
        assert ">Available<" in section_html

    def test_available_section_is_not_inside_stats_section(self, auth_client):
        html = profile_html(auth_client)
        assert "profile-available" not in stats_section(html)
        assert "Available" not in stats_section(html)

    def test_total_credits_card_has_no_available_or_negative_class(
        self, auth_client, user_id
    ):
        expense(user_id, 5)
        classes = available_cards(auth_client)["Total Credits"]["classes"]
        assert classes == ["stat-card"]

    def test_available_card_uses_stat_label_and_value_classes(self, auth_client):
        card = available_cards(auth_client)["Available"]
        assert card["classes"][0] == "stat-card"
        assert '<span class="stat-label">' in card["html"]
        assert '<span class="stat-value">' in card["html"]

    def test_stat_card_labels_in_order(self, auth_client):
        assert stat_labels(profile_html(auth_client)) == [
            "Total Credits",
            "Available",
            "Total Spent",
            "Total Saved",
            "Expenses",
            "Top Category",
        ]

    def test_no_inline_styles_in_section(self, auth_client, user_id):
        expense(user_id, 500)
        section_html = available_section(profile_html(auth_client))
        assert "style=" not in section_html
        assert "<style" not in section_html

    def test_logged_out_profile_redirects_to_login(self, client):
        response = client.get("/profile")
        assert response.status_code == 302
        assert response.headers["Location"].split("?")[0].endswith("/login")


class TestNoNetLeftovers:
    @pytest.mark.parametrize("setup", ["empty", "positive", "negative", "savings"])
    def test_no_net_label_note_or_class_on_page(self, auth_client, user_id, setup):
        if setup == "positive":
            credit(user_id, 100)
        elif setup == "negative":
            expense(user_id, 100)
        elif setup == "savings":
            credit(user_id, 100)
            saving(user_id, 20)
        html = profile_html(auth_client)
        assert "Net" not in stat_labels(html)
        assert ">Net<" not in html
        assert OLD_NOTE not in html
        assert "Savings are not included" not in html
        assert "profile-net" not in html
        assert "stat-card--net" not in html
        assert 'aria-label="Income and net"' not in html

    def test_no_net_rules_remain_in_profile_css(self):
        css = PROFILE_CSS.read_text(encoding="utf-8")
        assert "profile-net" not in css
        assert "stat-card--net" not in css


# ---- CSS ----------------------------------------------------------------- #


def css_rules(path):
    css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
    return re.findall(r"([^{}]+)\{([^{}]*)\}", css)


class TestCss:
    def test_available_rules_exist_in_profile_css(self):
        selectors = [s for s, _ in css_rules(PROFILE_CSS) if "profile-available" in s]
        assert selectors, "no .profile-available rules found in profile.css"

    def test_available_rules_do_not_hardcode_hex_colours(self):
        for selector, body in css_rules(PROFILE_CSS):
            if "profile-available" in selector or "stat-card--available" in selector:
                assert not re.search(
                    r"#[0-9a-fA-F]{3,8}\b", body
                ), f"hex colour in rule {selector.strip()!r}"

    def test_form_hint_rule_exists_in_add_expense_css(self):
        bodies = [b for s, b in css_rules(ADD_EXPENSE_CSS) if ".form-hint" in s]
        assert bodies, "no .form-hint rule found in add_expense.css"

    def test_form_hint_rule_does_not_hardcode_hex_colours(self):
        for selector, body in css_rules(ADD_EXPENSE_CSS):
            if ".form-hint" in selector:
                assert not re.search(
                    r"#[0-9a-fA-F]{3,8}\b", body
                ), f"hex colour in rule {selector.strip()!r}"
