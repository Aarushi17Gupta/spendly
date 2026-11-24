"""Tests for Step 11 - profile net: Total Credits and Net cards on GET /profile
and database.queries.get_net_summary()."""

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
from database.queries import get_net_summary

EMAIL = "net@spendly.test"
OTHER_EMAIL = "other@spendly.test"
OWN_ACCOUNT = "My account"
PROFILE_CSS = Path(__file__).resolve().parent.parent / "static" / "css" / "profile.css"

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
    "amount": "700.00",
    "type": "FD",
    "date": "2026-06-02",
    "description": "Deposit",
    "paid_from": OWN_ACCOUNT,
    "institution": "",
    "interest_rate": "",
    "maturity_date": "",
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setitem(flask_app.config, "TESTING", True)
    init_db()
    create_user("Net", EMAIL, "netpass")
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


def last_id(table):
    with closing(get_db()) as conn:
        return conn.execute(f"SELECT MAX(id) FROM {table}").fetchone()[0]  # noqa: S608


def credit(user_id, amount, date="2026-05-10"):
    add_credit(user_id, amount, "Salary", date, "pay")


def expense(user_id, amount, date="2026-05-10", category="Food"):
    add_expense(user_id, amount, category, date, "spend")


def profile_html(client, query=""):
    response = client.get("/profile" + query)
    assert response.status_code == 200
    return response.get_data(as_text=True)


def net_section(html):
    match = re.search(
        r'<section class="profile-net" aria-label="Income and net">.*?</section>',
        html,
        re.S,
    )
    assert match, "profile-net section not found"
    return match.group(0)


def stats_section(html):
    match = re.search(r'<section[^>]*class="profile-stats".*?</section>', html, re.S)
    assert match, "profile-stats section not found"
    return match.group(0)


def text(fragment):
    return re.sub(r"\s+", " ", fragment).strip()


def cards(section_html):
    """Return [{'classes', 'label', 'value', 'html'}] for each stat-card."""
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


def net_cards(client, query=""):
    found = cards(net_section(profile_html(client, query)))
    assert [c["label"] for c in found] == ["Total Credits", "Net"]
    return {c["label"]: c for c in found}


def values(client, query=""):
    found = net_cards(client, query)
    return found["Total Credits"]["value"], found["Net"]["value"]


def stat_cards_by_label(html):
    return {c["label"]: c for c in cards(stats_section(html))}


# ---- get_net_summary --------------------------------------------------- #


class TestGetNetSummary:
    def test_returns_exact_totals_and_net(self, user_id):
        credit(user_id, 50000)
        expense(user_id, 12345.50)
        summary = get_net_summary(user_id)
        assert summary["total_credits"] == 50000.0
        assert summary["total_spent"] == 12345.5
        assert summary["net"] == 37654.5

    def test_net_is_negative_when_spending_exceeds_credits(self, user_id):
        credit(user_id, 100)
        expense(user_id, 250)
        summary = get_net_summary(user_id)
        assert summary["net"] == -150.0

    def test_no_data_gives_zero_everywhere(self, user_id):
        summary = get_net_summary(user_id)
        assert summary["total_credits"] == 0
        assert summary["total_spent"] == 0
        assert summary["net"] == 0

    def test_only_expenses_gives_zero_credits_and_negative_net(self, user_id):
        expense(user_id, 80)
        summary = get_net_summary(user_id)
        assert summary["total_credits"] == 0
        assert summary["total_spent"] == 80.0
        assert summary["net"] == -80.0

    def test_only_credits_gives_zero_spent_and_positive_net(self, user_id):
        credit(user_id, 80)
        summary = get_net_summary(user_id)
        assert summary["total_credits"] == 80.0
        assert summary["total_spent"] == 0
        assert summary["net"] == 80.0

    def test_float_sums_are_rounded_to_two_places(self, user_id):
        credit(user_id, 0.10)
        credit(user_id, 0.20)
        summary = get_net_summary(user_id)
        assert summary["total_credits"] == 0.3, "0.1 + 0.2 must be rounded to 0.3"

    def test_net_of_float_credits_and_matching_expense_is_exactly_zero(self, user_id):
        credit(user_id, 0.10)
        credit(user_id, 0.20)
        expense(user_id, 0.30)
        summary = get_net_summary(user_id)
        assert summary["net"] == 0
        assert math.copysign(1, summary["net"]) == 1, "net must not be negative zero"

    def test_sub_paisa_amounts_round_to_two_places(self, user_id):
        credit(user_id, 0.007)
        summary = get_net_summary(user_id)
        assert summary["total_credits"] == 0.01
        assert summary["net"] == 0.01

    def test_sub_paisa_expense_never_yields_negative_zero(self, user_id):
        expense(user_id, 0.004)
        summary = get_net_summary(user_id)
        for key in ("total_credits", "total_spent", "net"):
            assert summary[key] == 0, f"{key} should round to 0"
            assert math.copysign(1, summary[key]) == 1, f"{key} is negative zero"

    def test_equal_credits_and_expenses_net_is_positive_zero(self, user_id):
        credit(user_id, 123.45)
        expense(user_id, 123.45)
        net = get_net_summary(user_id)["net"]
        assert net == 0
        assert math.copysign(1, net) == 1

    def test_totals_are_not_multiplied_by_row_counts(self, user_id):
        for amount in (100, 200, 300):
            credit(user_id, amount)
        for amount in (10, 20, 30, 40):
            expense(user_id, amount)
        summary = get_net_summary(user_id)
        assert summary["total_credits"] == 600.0
        assert summary["total_spent"] == 100.0
        assert summary["net"] == 500.0

    def test_other_users_rows_are_ignored(self, user_id, other_id):
        credit(user_id, 500)
        expense(user_id, 200)
        credit(other_id, 9999)
        expense(other_id, 7777)
        mine = get_net_summary(user_id)
        theirs = get_net_summary(other_id)
        assert (mine["total_credits"], mine["total_spent"], mine["net"]) == (
            500.0,
            200.0,
            300.0,
        )
        assert (theirs["total_credits"], theirs["total_spent"], theirs["net"]) == (
            9999.0,
            7777.0,
            2222.0,
        )

    def test_savings_are_ignored(self, user_id):
        credit(user_id, 1000)
        expense(user_id, 300)
        add_saving(user_id, 5000, "FD", "2026-05-10", OWN_ACCOUNT)
        summary = get_net_summary(user_id)
        assert summary == {"total_credits": 1000.0, "total_spent": 300.0, "net": 700.0}

    def test_lower_bound_is_inclusive(self, user_id):
        credit(user_id, 1, "2026-04-30")
        credit(user_id, 10, "2026-05-01")
        expense(user_id, 2, "2026-04-30")
        expense(user_id, 20, "2026-05-01")
        summary = get_net_summary(user_id, date_from="2026-05-01")
        assert summary["total_credits"] == 10.0
        assert summary["total_spent"] == 20.0
        assert summary["net"] == -10.0

    def test_upper_bound_is_inclusive(self, user_id):
        credit(user_id, 10, "2026-05-31")
        credit(user_id, 1, "2026-06-01")
        expense(user_id, 4, "2026-05-31")
        expense(user_id, 2, "2026-06-01")
        summary = get_net_summary(user_id, date_to="2026-05-31")
        assert summary["total_credits"] == 10.0
        assert summary["total_spent"] == 4.0
        assert summary["net"] == 6.0

    def test_both_bounds_include_both_boundary_dates_only(self, user_id):
        for day, amount in (
            ("2026-04-30", 1),
            ("2026-05-01", 10),
            ("2026-05-15", 100),
            ("2026-05-31", 1000),
            ("2026-06-01", 10000),
        ):
            credit(user_id, amount, day)
            expense(user_id, amount / 10, day)
        summary = get_net_summary(user_id, "2026-05-01", "2026-05-31")
        assert summary["total_credits"] == 1110.0
        assert summary["total_spent"] == 111.0
        assert summary["net"] == 999.0

    def test_range_matching_nothing_gives_zero(self, user_id):
        credit(user_id, 10, "2026-05-01")
        expense(user_id, 5, "2026-05-01")
        summary = get_net_summary(user_id, "2030-01-01", "2030-12-31")
        assert summary["total_credits"] == 0
        assert summary["total_spent"] == 0
        assert summary["net"] == 0
        assert math.copysign(1, summary["net"]) == 1

    def test_credits_in_range_without_expenses(self, user_id):
        credit(user_id, 10, "2026-05-01")
        expense(user_id, 5, "2026-07-01")
        summary = get_net_summary(user_id, "2026-05-01", "2026-05-31")
        assert summary == {"total_credits": 10.0, "total_spent": 0, "net": 10.0}

    def test_expenses_in_range_without_credits(self, user_id):
        credit(user_id, 10, "2026-07-01")
        expense(user_id, 5, "2026-05-01")
        summary = get_net_summary(user_id, "2026-05-01", "2026-05-31")
        assert summary == {"total_credits": 0, "total_spent": 5.0, "net": -5.0}


# ---- Profile page values ----------------------------------------------- #


class TestProfileNetValues:
    def test_positive_net_shows_exact_amounts(self, auth_client, user_id):
        credit(user_id, 50000)
        expense(user_id, 12345.50)
        found = net_cards(auth_client)
        assert found["Total Credits"]["value"] == "₹50,000.00"
        assert found["Net"]["value"] == "₹37,654.50"
        assert "stat-card--negative" not in found["Net"]["classes"]

    def test_negative_net_has_sign_before_symbol_and_negative_class(
        self, auth_client, user_id
    ):
        credit(user_id, 100)
        expense(user_id, 250)
        found = net_cards(auth_client)
        assert found["Total Credits"]["value"] == "₹100.00"
        assert found["Net"]["value"] == "-₹150.00"
        assert "stat-card--negative" in found["Net"]["classes"]

    def test_equal_amounts_show_zero_without_negative_style(self, auth_client, user_id):
        credit(user_id, 321.10)
        expense(user_id, 321.10)
        net = net_cards(auth_client)["Net"]
        assert net["value"] == "₹0.00"
        assert "stat-card--negative" not in net["classes"]

    def test_user_with_no_data_sees_zero_in_both_cards(self, auth_client):
        found = net_cards(auth_client)
        assert found["Total Credits"]["value"] == "₹0.00"
        assert found["Net"]["value"] == "₹0.00"
        assert "stat-card--negative" not in found["Net"]["classes"]

    def test_only_expenses_shows_zero_credits_and_negative_net(
        self, auth_client, user_id
    ):
        expense(user_id, 1234.5)
        found = net_cards(auth_client)
        assert found["Total Credits"]["value"] == "₹0.00"
        assert found["Net"]["value"] == "-₹1,234.50"
        assert "stat-card--negative" in found["Net"]["classes"]

    def test_only_credits_shows_positive_net(self, auth_client, user_id):
        credit(user_id, 1234.5)
        found = net_cards(auth_client)
        assert found["Total Credits"]["value"] == "₹1,234.50"
        assert found["Net"]["value"] == "₹1,234.50"
        assert "stat-card--negative" not in found["Net"]["classes"]

    def test_several_credits_and_expenses_are_not_multiplied(
        self, auth_client, user_id
    ):
        for amount in (100, 200, 300):
            credit(user_id, amount)
        for amount in (10, 20, 30, 40):
            expense(user_id, amount)
        assert values(auth_client) == ("₹600.00", "₹500.00")

    def test_float_amounts_cancelling_show_positive_zero(self, auth_client, user_id):
        credit(user_id, 0.10)
        credit(user_id, 0.20)
        expense(user_id, 0.30)
        found = net_cards(auth_client)
        assert found["Net"]["value"] == "₹0.00"
        assert "-₹0.00" not in net_section(profile_html(auth_client))
        assert "stat-card--negative" not in found["Net"]["classes"]

    def test_sub_paisa_expense_never_shows_negative_zero(self, auth_client, user_id):
        expense(user_id, 0.004)
        found = net_cards(auth_client)
        assert found["Net"]["value"] == "₹0.00"
        assert "stat-card--negative" not in found["Net"]["classes"]

    def test_one_crore_positive_fits_with_separators(self, auth_client, user_id):
        credit(user_id, 10_000_000)
        assert values(auth_client) == ("₹10,000,000.00", "₹10,000,000.00")

    def test_one_crore_negative_keeps_sign_and_style(self, auth_client, user_id):
        expense(user_id, 10_000_000)
        found = net_cards(auth_client)
        assert found["Net"]["value"] == "-₹10,000,000.00"
        assert "stat-card--negative" in found["Net"]["classes"]

    def test_negative_class_only_when_net_below_zero(self, auth_client, user_id):
        credit(user_id, 100)
        expense(user_id, 100.01)
        assert "stat-card--negative" in net_cards(auth_client)["Net"]["classes"]

    def test_net_card_always_has_net_class(self, auth_client):
        assert "stat-card--net" in net_cards(auth_client)["Net"]["classes"]

    def test_cards_use_existing_stat_classes(self, auth_client):
        for card in net_cards(auth_client).values():
            assert "stat-card" in card["classes"]
            assert '<span class="stat-label">' in card["html"]
            assert '<span class="stat-value">' in card["html"]

    def test_twelve_credits_are_totalled_while_ten_are_listed(
        self, auth_client, user_id
    ):
        for _ in range(12):
            credit(user_id, 100)
        html = profile_html(auth_client)
        assert cards(net_section(html))[0]["value"] == "₹1,200.00"
        credits_html = re.search(
            r'<section[^>]*aria-labelledby="credit-heading".*?</section>', html, re.S
        ).group(0)
        assert len(re.findall(r'class="tx-edit"', credits_html)) == 10
        assert "Showing latest 10 of 12" in credits_html

    def test_other_users_data_never_affects_cards(self, auth_client, user_id, other_id):
        credit(user_id, 500)
        expense(user_id, 200)
        credit(other_id, 9999)
        expense(other_id, 7777)
        assert values(auth_client) == ("₹500.00", "₹300.00")

    def test_savings_do_not_affect_cards(self, auth_client, user_id):
        credit(user_id, 1000)
        expense(user_id, 300)
        add_saving(user_id, 5000, "FD", "2026-05-10", OWN_ACCOUNT)
        assert values(auth_client) == ("₹1,000.00", "₹700.00")


# ---- Date filter ------------------------------------------------------- #


class TestProfileNetDateFilter:
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
        found = net_cards(auth_client, "?from=2030-01-01&to=2030-12-31")
        assert found["Total Credits"]["value"] == "₹0.00"
        assert found["Net"]["value"] == "₹0.00"
        assert "stat-card--negative" not in found["Net"]["classes"]

    def test_filter_applies_to_negative_net(self, auth_client, user_id):
        credit(user_id, 10, "2026-05-01")
        expense(user_id, 60, "2026-05-02")
        credit(user_id, 5000, "2026-07-01")
        found = net_cards(auth_client, "?from=2026-05-01&to=2026-05-31")
        assert found["Net"]["value"] == "-₹50.00"
        assert "stat-card--negative" in found["Net"]["classes"]

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


class TestNetUpdatesThroughRoutes:
    def test_adding_a_credit_increases_credits_and_net(self, auth_client):
        assert values(auth_client) == ("₹0.00", "₹0.00")
        response = auth_client.post("/credits/add", data=CREDIT_FORM)
        assert response.status_code == 302
        assert values(auth_client) == ("₹100.00", "₹100.00")

    def test_editing_a_credit_updates_credits_and_net(self, auth_client, user_id):
        credit(user_id, 100)
        cid = last_id("credits")
        response = auth_client.post(
            f"/credits/{cid}/edit", data={**CREDIT_FORM, "amount": "250.25"}
        )
        assert response.status_code == 302
        assert values(auth_client) == ("₹250.25", "₹250.25")

    def test_deleting_a_credit_updates_credits_and_net(self, auth_client, user_id):
        credit(user_id, 100)
        credit(user_id, 30)
        cid = last_id("credits")
        response = auth_client.post(f"/credits/{cid}/delete")
        assert response.status_code == 302
        assert values(auth_client) == ("₹100.00", "₹100.00")

    def test_adding_an_expense_decreases_net(self, auth_client, user_id):
        credit(user_id, 100)
        response = auth_client.post("/expenses/add", data=EXPENSE_FORM)
        assert response.status_code == 302
        assert values(auth_client) == ("₹100.00", "₹60.00")

    def test_editing_an_expense_updates_net(self, auth_client, user_id):
        credit(user_id, 100)
        expense(user_id, 40)
        eid = last_id("expenses")
        response = auth_client.post(
            f"/expenses/{eid}/edit", data={**EXPENSE_FORM, "amount": "150.00"}
        )
        assert response.status_code == 302
        found = net_cards(auth_client)
        assert found["Total Credits"]["value"] == "₹100.00"
        assert found["Net"]["value"] == "-₹50.00"
        assert "stat-card--negative" in found["Net"]["classes"]

    def test_deleting_an_expense_updates_net(self, auth_client, user_id):
        credit(user_id, 100)
        expense(user_id, 40)
        eid = last_id("expenses")
        response = auth_client.post(f"/expenses/{eid}/delete")
        assert response.status_code == 302
        assert values(auth_client) == ("₹100.00", "₹100.00")


class TestSavingsLeaveNetSectionUntouched:
    @pytest.fixture()
    def seeded(self, user_id):
        credit(user_id, 1000)
        expense(user_id, 300)

    def test_adding_a_saving_leaves_net_section_identical(self, auth_client, seeded):
        before = net_section(profile_html(auth_client))
        response = auth_client.post("/savings/add", data=SAVING_FORM)
        assert response.status_code == 302
        assert net_section(profile_html(auth_client)) == before

    def test_editing_a_saving_leaves_net_section_identical(
        self, auth_client, user_id, seeded
    ):
        add_saving(user_id, 700, "FD", "2026-05-10", OWN_ACCOUNT)
        sid = last_id("savings")
        before = net_section(profile_html(auth_client))
        response = auth_client.post(
            f"/savings/{sid}/edit", data={**SAVING_FORM, "amount": "9999.00"}
        )
        assert response.status_code == 302
        assert net_section(profile_html(auth_client)) == before

    def test_deleting_a_saving_leaves_net_section_identical(
        self, auth_client, user_id, seeded
    ):
        add_saving(user_id, 700, "FD", "2026-05-10", OWN_ACCOUNT)
        sid = last_id("savings")
        before = net_section(profile_html(auth_client))
        response = auth_client.post(f"/savings/{sid}/delete")
        assert response.status_code == 302
        assert net_section(profile_html(auth_client)) == before
        assert values(auth_client) == ("₹1,000.00", "₹700.00")


# ---- Structure --------------------------------------------------------- #


class TestStructure:
    def test_net_section_sits_between_date_filter_and_stats(self, auth_client):
        html = profile_html(auth_client)
        filter_pos = html.index('class="date-filter"')
        net_pos = html.index('class="profile-net"')
        stats_pos = html.index('class="profile-stats"')
        assert filter_pos < net_pos < stats_pos

    def test_net_section_is_not_inside_stats_section(self, auth_client):
        html = profile_html(auth_client)
        assert "profile-net" not in stats_section(html)
        assert "Total Credits" not in stats_section(html)

    def test_net_section_has_exactly_two_cards_in_order(self, auth_client):
        found = cards(net_section(profile_html(auth_client)))
        assert [c["label"] for c in found] == ["Total Credits", "Net"]

    def test_total_credits_card_is_not_the_net_card(self, auth_client):
        found = net_cards(auth_client)
        assert "stat-card--net" not in found["Total Credits"]["classes"]
        assert "stat-card--negative" not in found["Total Credits"]["classes"]

    def test_cards_always_rendered_for_user_without_data(self, auth_client):
        section = net_section(profile_html(auth_client))
        assert "Total Credits" in section
        assert ">Net<" in section

    def test_note_is_inside_net_card_after_its_value(self, auth_client):
        net = net_cards(auth_client)["Net"]["html"]
        note = "Credits minus expenses. Savings are not included."
        assert note in net
        assert net.index('<span class="stat-value">') < net.index(note)

    def test_note_is_not_in_total_credits_card(self, auth_client):
        credits_card = net_cards(auth_client)["Total Credits"]["html"]
        assert "Savings are not included" not in credits_card

    def test_net_section_has_no_inline_styles(self, auth_client, user_id):
        expense(user_id, 500)
        section = net_section(profile_html(auth_client))
        assert "style=" not in section
        assert "<style" not in section

    def test_section_heading_ids_are_kept(self, auth_client):
        html = profile_html(auth_client)
        for heading_id in (
            "tx-heading",
            "cat-heading",
            "credit-heading",
            "saving-heading",
        ):
            assert f'id="{heading_id}"' in html, f"{heading_id} missing"

    def test_empty_state_wording_is_kept(self, auth_client):
        html = profile_html(auth_client)
        assert "No expenses yet." in html
        assert "No credits yet." in html
        assert "No savings yet." in html


# ---- Labels ------------------------------------------------------------ #


def stat_labels(html):
    return [
        text(m)
        for m in re.findall(r'<span class="stat-label">(.*?)</span>', html, re.S)
    ]


def section_titles(html):
    return [
        text(m)
        for m in re.findall(r'<h2 class="section-title"[^>]*>(.*?)</h2>', html, re.S)
    ]


class TestLabels:
    def test_stat_card_labels_in_order(self, auth_client):
        assert stat_labels(profile_html(auth_client)) == [
            "Total Credits",
            "Net",
            "Total Spent",
            "Total Saved",
            "Expenses",
            "Top Category",
        ]

    def test_section_titles_renamed(self, auth_client):
        titles = section_titles(profile_html(auth_client))
        assert "Recent Expenses" in titles
        assert "Expenses by Category" in titles
        assert "Recent Credits" in titles
        assert "Recent Savings" in titles

    def test_old_labels_are_gone(self, auth_client, user_id):
        expense(user_id, 10)
        html = profile_html(auth_client)
        assert "Transactions" not in stat_labels(html)
        assert "Recent Transactions" not in section_titles(html)
        assert "Recent Transactions" not in html
        assert "By Category" not in [t for t in section_titles(html)]
        assert not re.search(r"(?<!Expenses )By Category", html)

    def test_total_spent_total_saved_top_category_keep_labels_and_values(
        self, auth_client, user_id
    ):
        expense(user_id, 30, category="Food")
        expense(user_id, 20, category="Bills")
        add_saving(user_id, 500, "FD", "2026-05-10", OWN_ACCOUNT)
        found = stat_cards_by_label(profile_html(auth_client))
        assert found["Total Spent"]["value"] == "₹50.00"
        assert found["Total Saved"]["value"] == "₹500.00"
        assert found["Top Category"]["value"] == "Food"
        assert found["Expenses"]["value"] == "2"

    def test_stat_values_do_not_follow_credits(self, auth_client, user_id):
        expense(user_id, 30)
        before = stats_section(profile_html(auth_client))
        credit(user_id, 1000)
        assert stats_section(profile_html(auth_client)) == before

    def test_aria_label_amounts_are_unchanged(self, auth_client, user_id):
        add_expense(user_id, 45.5, "Food", "2026-05-01", "Lunch")
        add_credit(user_id, 1000, "Freelance", "2026-05-01", "Project")
        html = profile_html(auth_client)
        assert re.search(r'aria-label="Edit Lunch, ₹45\.50, [^"]+"', html)
        assert re.search(r'aria-label="Delete Lunch, ₹45\.50, [^"]+"', html)
        assert re.search(r'aria-label="Edit credit Project, ₹1,000\.00, [^"]+"', html)
        assert re.search(r'aria-label="Delete credit Project, ₹1,000\.00, [^"]+"', html)


# ---- Auth -------------------------------------------------------------- #


def test_logged_out_profile_redirects_to_login(client):
    response = client.get("/profile")
    assert response.status_code == 302
    assert response.headers["Location"].split("?")[0].endswith("/login")


# ---- CSS --------------------------------------------------------------- #


def css_rules():
    css = re.sub(r"/\*.*?\*/", "", PROFILE_CSS.read_text(encoding="utf-8"), flags=re.S)
    return re.findall(r"([^{}]+)\{([^{}]*)\}", css)


class TestCss:
    def test_net_rules_exist(self):
        selectors = [sel for sel, _ in css_rules() if "profile-net" in sel]
        assert selectors, "no .profile-net rules found in profile.css"

    def test_negative_net_uses_danger_variable(self):
        bodies = [body for sel, body in css_rules() if "stat-card--negative" in sel]
        assert bodies, "no .stat-card--negative rule found"
        assert any("var(--danger)" in body for body in bodies)

    def test_new_rules_do_not_hardcode_hex_colours(self):
        for selector, body in css_rules():
            if "profile-net" in selector or "stat-card--negative" in selector:
                assert not re.search(
                    r"#[0-9a-fA-F]{3,8}\b", body
                ), f"hex colour in rule {selector.strip()!r}"
