"""Tests for Step 14 - the analytics page: GET /analytics, the range and summary
helpers in app, and database.queries.get_monthly_totals() / get_category_months().

Unless a test says otherwise, "today" is frozen at 2026-12-15, so the default
six-month view runs from Jul 2026 to Dec 2026."""

import datetime
import html as html_lib
import math
import re
from contextlib import closing
from pathlib import Path

import pytest

import app as app_module
import database.db as db_module
from app import app as flask_app
from database.db import (
    add_credit,
    add_expense,
    add_saving,
    create_user,
    delete_credit,
    delete_expense,
    get_db,
    get_user_by_email,
    init_db,
    update_expense,
)
from database.queries import (
    _month_keys,
    get_available_summary,
    get_category_months,
    get_monthly_totals,
)

EMAIL = "analytics@spendly.test"
OTHER_EMAIL = "other@spendly.test"
OWN_ACCOUNT = "My account"
SALARY = "Salary deduction/employer"
OLD = "Already saved before Spendly"
TODAY = datetime.date(2026, 12, 15)
RANGE_6 = ("2026-07-01", "2026-12-31")
MONTHS_6 = ["2026-07", "2026-08", "2026-09", "2026-10", "2026-11", "2026-12"]
LABELS_6 = ["Jul 2026", "Aug 2026", "Sep 2026", "Oct 2026", "Nov 2026", "Dec 2026"]

STATIC = Path(__file__).resolve().parent.parent / "static" / "css"
ANALYTICS_CSS = STATIC / "analytics.css"
STYLE_CSS = STATIC / "style.css"
PROFILE_CSS = STATIC / "profile.css"

CARD_LABELS = ["Average Monthly Spending", "Highest Spending Month", "Savings Rate"]
NOTE_CURRENT = "The current month is included, so its figures may be incomplete."
NOTE_SAVINGS = "Savings include only those paid from your account."
EMPTY_ENTRIES = "No entries in this period."
EMPTY_EXPENSES = "No expenses in this period."


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setitem(flask_app.config, "TESTING", True)
    monkeypatch.setattr(app_module, "_today", lambda: TODAY)
    init_db()
    create_user("Tester", EMAIL, "analyticspass")
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


def credit(uid, amount, date="2026-12-05"):
    add_credit(uid, amount, "Salary", date, "pay")


def expense(uid, amount, date="2026-12-05", category="Food"):
    add_expense(uid, amount, category, date, "spend")


def saving(uid, amount, date="2026-12-05", paid_from=OWN_ACCOUNT):
    add_saving(uid, amount, "FD", date, paid_from)


def last_id(sql):
    # Only literal statements are passed in: table names are never interpolated.
    with closing(get_db()) as conn:
        return conn.execute(sql).fetchone()[0]


def page(client, query=""):
    response = client.get("/analytics" + query)
    assert (
        response.status_code == 200
    ), f"GET /analytics{query} gave {response.status_code}"
    return response.get_data(as_text=True)


def text_of(fragment):
    stripped = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html_lib.unescape(stripped)).strip()


def rupees(value):
    sign = "-" if value < 0 else ""
    return f"{sign}₹{abs(value):,.2f}"


def parse_money(cell):
    match = re.fullmatch(r"(-?)₹([\d,]+\.\d{2})", cell)
    assert match, f"not a money cell: {cell!r}"
    value = float(match.group(2).replace(",", ""))
    return -value if match.group(1) else value


def table(html, heading_id):
    """Return (header cells, body rows) of the table labelled by heading_id."""
    match = re.search(
        r'<table\b[^>]*aria-labelledby="%s"[^>]*>(.*?)</table>' % heading_id,
        html,
        re.S,
    )
    assert match, f"table labelled by {heading_id} not found"
    body = match.group(1)
    head = re.search(r"<thead\b.*?</thead>", body, re.S)
    assert head, "table has no thead"
    header = [
        text_of(c) for c in re.findall(r"<th\b[^>]*>(.*?)</th>", head.group(0), re.S)
    ]
    tbody = re.search(r"<tbody\b.*?</tbody>", body, re.S)
    assert tbody, "table has no tbody"
    rows = [
        [text_of(c) for c in re.findall(r"<t[hd]\b[^>]*>(.*?)</t[hd]>", row, re.S)]
        for row in re.findall(r"<tr\b.*?</tr>", tbody.group(0), re.S)
    ]
    return header, rows


def monthly_rows(html):
    return table(html, "monthly-heading")[1]


def category_rows(html):
    return table(html, "category-heading")[1]


def attr(tag, name):
    match = re.search(r'(?<![\w-])%s="([^"]*)"' % name, tag)
    return match.group(1) if match else None


def svg_tag(html):
    match = re.search(r"<svg\b[^>]*analytics-chart[^>]*>", html)
    assert match, "svg.analytics-chart not found"
    return match.group(0)


def bars(html):
    result = []
    for attrs, inner in re.findall(r"<rect\b([^>]*?)(?<!/)>(.*?)</rect>", html, re.S):
        classes = (attr(attrs, "class") or "").split()
        if "chart-bar" not in classes:
            continue
        tone = [c for c in classes if c.startswith("tone-")]
        title = re.search(r"<title>(.*?)</title>", inner, re.S)
        result.append(
            {
                "tone": tone[0] if tone else None,
                "height": float(attr(attrs, "height")),
                "y": float(attr(attrs, "y")),
                "title": text_of(title.group(1)) if title else None,
            }
        )
    return result


def cards(html):
    match = re.search(
        r'<section[^>]*class="[^"]*analytics-cards[^"]*"[^>]*>.*?</section>', html, re.S
    )
    assert match, "section.analytics-cards not found"
    content = text_of(match.group(0))
    values = {}
    for label in CARD_LABELS:
        start = content.index(label) + len(label)
        ends = [
            content.index(other, start)
            for other in CARD_LABELS
            if other != label and other in content[start:]
        ]
        values[label] = content[start : min(ends) if ends else len(content)].strip()
    return values


def period_links(html):
    match = re.search(
        r'<nav[^>]*class="[^"]*period-links[^"]*"[^>]*>.*?</nav>', html, re.S
    )
    assert match, "nav.period-links not found"
    return [
        (text_of(inner), attr(attrs, "aria-current"))
        for attrs, inner in re.findall(r"<a\b([^>]*)>(.*?)</a>", match.group(0), re.S)
    ]


def m(month, credits=0.0, spent=0.0, saved=0.0):
    return {
        "month": month,
        "credits": credits,
        "spent": spent,
        "saved_from_account": saved,
        "available": 0.0,
    }


def seed_example(uid):
    credit(uid, 50000)
    expense(uid, 30000)
    saving(uid, 5000)


# ---- Range, label and summary helpers ------------------------------------ #


class TestMonthRange:
    @pytest.mark.parametrize(
        "months, today, expected",
        [
            (6, "2026-12-15", ("2026-07-01", "2026-12-31")),
            (3, "2026-07-01", ("2026-05-01", "2026-07-31")),
            (12, "2026-12-31", ("2026-01-01", "2026-12-31")),
            (12, "2026-03-10", ("2025-04-01", "2026-03-31")),
            (12, "2026-01-05", ("2025-02-01", "2026-01-31")),
            (6, "2026-02-10", ("2025-09-01", "2026-02-28")),
            (3, "2026-01-31", ("2025-11-01", "2026-01-31")),
            (3, "2026-02-10", ("2025-12-01", "2026-02-28")),
            (3, "2028-02-10", ("2027-12-01", "2028-02-29")),
            (3, "2026-04-30", ("2026-02-01", "2026-04-30")),
            (3, "2026-06-01", ("2026-04-01", "2026-06-30")),
        ],
        ids=[
            "six-in-december",
            "three-in-july-31-days",
            "twelve-in-one-calendar-year",
            "twelve-crossing-year",
            "twelve-from-january",
            "six-ending-february",
            "three-crossing-year-from-31st",
            "february-28-days",
            "february-29-days",
            "april-30-days",
            "june-30-days",
        ],
    )
    def test_range_covers_whole_calendar_months(self, months, today, expected):
        result = app_module._month_range(months, datetime.date.fromisoformat(today))
        assert result == expected, f"{months} months to {today}: {result}"

    def test_range_ignores_the_day_of_today(self):
        first = app_module._month_range(6, datetime.date(2026, 12, 1))
        last = app_module._month_range(6, datetime.date(2026, 12, 31))
        assert first == last == RANGE_6


class TestMonthKeys:
    @pytest.mark.parametrize(
        "date_from, date_to, expected",
        [
            ("2026-01-01", "2026-01-31", ["2026-01"]),
            ("2026-01-15", "2026-01-20", ["2026-01"]),
            ("2025-11-01", "2026-02-28", ["2025-11", "2025-12", "2026-01", "2026-02"]),
            ("2026-07-01", "2026-12-31", MONTHS_6),
        ],
    )
    def test_keys_list_every_month_oldest_first(self, date_from, date_to, expected):
        assert _month_keys(date_from, date_to) == expected

    def test_twelve_month_range_has_twelve_keys(self):
        keys = _month_keys("2025-04-01", "2026-03-31")
        assert len(keys) == 12 and keys == sorted(keys)


class TestMonthLabel:
    @pytest.mark.parametrize(
        "month, label",
        [
            ("2026-07", "Jul 2026"),
            ("2026-01", "Jan 2026"),
            ("2025-12", "Dec 2025"),
            ("2028-02", "Feb 2028"),
        ],
    )
    def test_label_is_short_month_and_year(self, month, label):
        assert app_module._month_label(month) == label


class TestSavingsRateLabel:
    @pytest.mark.parametrize(
        "credits, saved, expected",
        [
            (50000, 5000, "10%"),
            (100, 150, "150%"),
            (3, 1, "33%"),
            (8, 1, "13%"),
            (200, 1, "1%"),
            (1000, 5, "1%"),
            (1000, 4, "<1%"),
            (100000, 1, "<1%"),
            (100, 0, "0%"),
            (0, 100, "—"),
            (0, 0, "—"),
        ],
        ids=[
            "ten-percent",
            "above-100",
            "rounds-down",
            "twelve-and-half-rounds-up",
            "half-percent-rounds-up",
            "half-percent-large",
            "just-under-half-is-tiny",
            "tiny-rate",
            "credits-without-savings",
            "savings-without-credits",
            "nothing",
        ],
    )
    def test_label(self, credits, saved, expected):
        assert app_module._savings_rate_label(credits, saved) == expected


class TestAnalyticsSummary:
    def test_empty_months_give_placeholders(self):
        summary = app_module._analytics_summary([m(k) for k in MONTHS_6])
        assert summary["average"] == 0
        assert summary["highest"] is None
        assert summary["rate"] == "—"
        assert summary["has_entries"] is False

    def test_average_starts_at_first_month_with_any_entry(self):
        monthly = [
            m("2026-09"),
            m("2026-10"),
            m("2026-11", spent=300),
            m("2026-12", spent=100),
        ]
        assert app_module._analytics_summary(monthly)["average"] == 200

    @pytest.mark.parametrize(
        "first",
        [m("2026-10", credits=10), m("2026-10", spent=10), m("2026-10", saved=10)],
        ids=["credit", "expense", "saving"],
    )
    def test_any_entry_type_starts_the_average(self, first):
        spent = first["spent"]
        monthly = [m("2026-09"), first, m("2026-11", spent=60), m("2026-12")]
        average = app_module._analytics_summary(monthly)["average"]
        assert average == round((spent + 60) / 3, 2)

    def test_average_is_rounded_to_paise(self):
        monthly = [m("2026-10", spent=100), m("2026-11"), m("2026-12")]
        assert app_module._analytics_summary(monthly)["average"] == 33.33

    def test_highest_is_the_row_with_most_spent(self):
        monthly = [
            m("2026-10", spent=5),
            m("2026-11", spent=50),
            m("2026-12", spent=20),
        ]
        assert app_module._analytics_summary(monthly)["highest"]["month"] == "2026-11"

    def test_most_recent_month_wins_a_tie(self):
        monthly = [
            m("2026-10", spent=50),
            m("2026-11", spent=50),
            m("2026-12", spent=1),
        ]
        assert app_module._analytics_summary(monthly)["highest"]["month"] == "2026-11"

    def test_entries_without_expenses_have_no_highest(self):
        summary = app_module._analytics_summary(
            [m("2026-11", credits=100), m("2026-12")]
        )
        assert summary["highest"] is None
        assert summary["has_entries"] is True
        assert summary["rate"] == "0%"

    def test_rate_uses_totals_across_months(self):
        monthly = [
            m("2026-11", credits=100, saved=10),
            m("2026-12", credits=100, saved=10),
        ]
        assert app_module._analytics_summary(monthly)["rate"] == "10%"


# ---- Queries ---------------------------------------------------------------- #


class TestMonthlyTotals:
    def test_every_month_is_listed_oldest_first_with_zeros(self, user_id):
        result = get_monthly_totals(user_id, *RANGE_6)
        assert [r["month"] for r in result] == MONTHS_6
        for row in result:
            for key in ("credits", "spent", "saved_from_account", "available"):
                assert row[key] == 0, f"{row['month']} {key} should be zero"

    def test_spec_example_figures(self, user_id):
        seed_example(user_id)
        december = get_monthly_totals(user_id, *RANGE_6)[-1]
        assert december["credits"] == 50000
        assert december["spent"] == 30000
        assert december["saved_from_account"] == 5000
        assert december["available"] == 15000

    def test_available_can_be_negative(self, user_id):
        credit(user_id, 100)
        expense(user_id, 250)
        assert get_monthly_totals(user_id, *RANGE_6)[-1]["available"] == -150

    def test_several_entries_are_summed_not_multiplied(self, user_id):
        for _ in range(3):
            credit(user_id, 100)
        for _ in range(2):
            expense(user_id, 10)
        for _ in range(4):
            saving(user_id, 5)
        december = get_monthly_totals(user_id, *RANGE_6)[-1]
        assert (
            december["credits"],
            december["spent"],
            december["saved_from_account"],
        ) == (
            300,
            20,
            20,
        )
        assert december["available"] == 260

    @pytest.mark.parametrize("paid_from", [SALARY, OLD])
    def test_other_paid_from_values_are_excluded(self, user_id, paid_from):
        saving(user_id, 999, paid_from=paid_from)
        december = get_monthly_totals(user_id, *RANGE_6)[-1]
        assert december["saved_from_account"] == 0
        assert december["available"] == 0

    def test_no_negative_zero(self, user_id):
        credit(user_id, 0.1)
        credit(user_id, 0.2)
        expense(user_id, 0.3)
        december = get_monthly_totals(user_id, *RANGE_6)[-1]
        assert december["available"] == 0
        assert math.copysign(1, december["available"]) == 1, "available is -0.0"

    def test_empty_months_are_not_negative_zero(self, user_id):
        for row in get_monthly_totals(user_id, *RANGE_6):
            for key in ("credits", "spent", "saved_from_account", "available"):
                assert math.copysign(1, row[key]) == 1, f"{row['month']} {key} is -0.0"

    @pytest.mark.parametrize(
        "date, included",
        [
            ("2026-06-30", False),
            ("2026-07-01", True),
            ("2026-12-31", True),
            ("2027-01-01", False),
            ("2026-12-28", True),
        ],
        ids=["day-before", "first-day", "last-day", "day-after", "later-this-month"],
    )
    def test_range_boundaries_are_inclusive(self, user_id, date, included):
        credit(user_id, 10, date)
        expense(user_id, 20, date)
        saving(user_id, 30, date)
        result = get_monthly_totals(user_id, *RANGE_6)
        assert sum(r["credits"] for r in result) == (10 if included else 0)
        assert sum(r["spent"] for r in result) == (20 if included else 0)
        assert sum(r["saved_from_account"] for r in result) == (30 if included else 0)

    def test_entries_land_in_their_own_month(self, user_id):
        expense(user_id, 5, "2026-08-31")
        expense(user_id, 7, "2026-09-01")
        spent = {r["month"]: r["spent"] for r in get_monthly_totals(user_id, *RANGE_6)}
        assert spent["2026-08"] == 5 and spent["2026-09"] == 7

    def test_only_the_given_users_entries_count(self, user_id, other_id):
        expense(other_id, 500)
        credit(other_id, 900)
        saving(other_id, 70)
        result = get_monthly_totals(user_id, *RANGE_6)
        assert all(
            r["credits"] == r["spent"] == r["saved_from_account"] == 0 for r in result
        )

    @pytest.mark.parametrize(
        "amounts",
        [
            (0.1, 0.2, 0.3, 0.07),
            (10.01, 20.02, 0.07, 5.55),
            (1234.56, 0.01, 99.99, 0.10),
        ],
    )
    def test_matches_get_available_summary_for_paise_amounts(self, user_id, amounts):
        c, e, s, extra = amounts
        credit(user_id, c)
        credit(user_id, extra)
        expense(user_id, e)
        saving(user_id, s)
        date_from, date_to = "2026-12-01", "2026-12-31"
        [row] = get_monthly_totals(user_id, date_from, date_to)
        summary = get_available_summary(user_id, date_from, date_to)
        assert row["credits"] == summary["total_credits"]
        assert row["spent"] == summary["total_spent"]
        assert row["saved_from_account"] == summary["saved_from_account"]
        assert row["available"] == summary["available"]

    def test_rows_are_rounded_to_paise_before_summing(self, user_id):
        expense(user_id, 10.004)
        expense(user_id, 10.004)
        december = get_monthly_totals(user_id, *RANGE_6)[-1]
        assert december["spent"] == 20.0, "each row rounds to 10.00 before summing"

    def test_malformed_dates_do_not_break_the_totals(self, user_id):
        with closing(get_db()) as conn:
            for bad in ("2026-12-15x", "garbage", "2026-13-05", "2026-7-15"):
                conn.execute(
                    "INSERT INTO expenses (user_id, amount, category, date, description) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (user_id, 11, "Food", bad, "bad date"),
                )
            conn.commit()
        expense(user_id, 4)
        result = get_monthly_totals(user_id, *RANGE_6)
        assert [r["month"] for r in result] == MONTHS_6
        categories = get_category_months(user_id, *RANGE_6)
        assert round(sum(r["spent"] for r in result), 2) == round(
            sum(c["total"] for c in categories), 2
        ), "monthly and category totals must treat bad dates the same way"


class TestCategoryMonths:
    def test_no_expenses_gives_no_categories(self, user_id):
        credit(user_id, 100)
        assert get_category_months(user_id, *RANGE_6) == []

    def test_each_category_lists_every_month_oldest_first(self, user_id):
        expense(user_id, 10, "2026-07-03")
        expense(user_id, 5, "2026-12-03")
        expense(user_id, 2, "2026-12-04")
        [food] = get_category_months(user_id, *RANGE_6)
        assert food["name"] == "Food"
        assert food["months"] == [10, 0, 0, 0, 0, 7]
        assert food["total"] == 17

    def test_categories_are_ordered_by_total_then_name(self, user_id):
        expense(user_id, 10, category="Food")
        expense(user_id, 50, category="Transport")
        expense(user_id, 10, category="Bills")
        names = [c["name"] for c in get_category_months(user_id, *RANGE_6)]
        assert names == ["Transport", "Bills", "Food"]

    def test_totals_add_up_to_monthly_expenses(self, user_id):
        expense(user_id, 10.004, category="Food")
        expense(user_id, 10.004, category="Food", date="2026-10-01")
        expense(user_id, 0.006, category="Bills")
        expense(user_id, 0.006, category="Bills", date="2026-11-30")
        expense(user_id, 3.33, category="Health", date="2026-08-08")
        categories = get_category_months(user_id, *RANGE_6)
        monthly = get_monthly_totals(user_id, *RANGE_6)
        assert round(sum(c["total"] for c in categories), 2) == round(
            sum(r["spent"] for r in monthly), 2
        )
        for index, row in enumerate(monthly):
            column = round(sum(c["months"][index] for c in categories), 2)
            assert column == row["spent"], f"{row['month']} column differs from monthly"
        for category in categories:
            assert round(sum(category["months"]), 2) == category["total"]

    def test_unknown_category_is_included(self, user_id):
        expense(user_id, 9, category="Pet snacks")
        assert [c["name"] for c in get_category_months(user_id, *RANGE_6)] == [
            "Pet snacks"
        ]

    def test_boundaries_and_isolation(self, user_id, other_id):
        expense(user_id, 1, "2026-06-30")
        expense(user_id, 2, "2026-07-01")
        expense(user_id, 3, "2026-12-31")
        expense(user_id, 4, "2027-01-01")
        expense(other_id, 100)
        [food] = get_category_months(user_id, *RANGE_6)
        assert food["total"] == 5

    def test_savings_and_credits_never_appear(self, user_id):
        credit(user_id, 100)
        saving(user_id, 100)
        assert get_category_months(user_id, *RANGE_6) == []


# ---- Access ------------------------------------------------------------------ #


class TestAccess:
    def test_logged_out_visitor_is_redirected_to_login(self, client):
        response = client.get("/analytics")
        assert response.status_code == 302
        assert response.headers["Location"].split("?")[0].endswith("/login")

    def test_logged_in_user_sees_the_page(self, auth_client):
        html = page(auth_client)
        assert "Analytics" in html
        assert "Coming Soon" not in html

    def test_deleted_user_is_sent_to_login_and_session_cleared(
        self, auth_client, user_id
    ):
        with closing(get_db()) as conn:
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
        response = auth_client.get("/analytics")
        assert response.status_code == 302
        assert response.headers["Location"].split("?")[0].endswith("/login")
        with auth_client.session_transaction() as sess:
            assert "user_id" not in sess, "stale session should be cleared"


# ---- The months parameter ----------------------------------------------------- #


class TestMonthsParameter:
    @pytest.mark.parametrize(
        "query, shown",
        [
            ("", 6),
            ("?months=3", 3),
            ("?months=6", 6),
            ("?months=12", 12),
            ("?months=abc", 6),
            ("?months=0", 6),
            ("?months=-3", 6),
            ("?months=1000000", 6),
            ("?months=", 6),
            ("?months=03", 6),
            ("?months=%203", 6),
            ("?months=3.0", 6),
            ("?months=7", 6),
            ("?months=12&months=3", 12),
            ("?months=3&months=12", 3),
            ("?months=abc&months=3", 6),
        ],
    )
    def test_months_shown_and_active_link(
        self, auth_client, user_id, query, shown
    ):
        credit(user_id, 100)
        html = page(auth_client, query)
        assert len(monthly_rows(html)) == shown
        active = [label for label, current in period_links(html) if current == "true"]
        assert active == [f"{shown} months"], f"active links: {active}"

    def test_period_links_are_in_order(self, auth_client):
        links = period_links(page(auth_client))
        assert [label for label, _ in links] == ["3 months", "6 months", "12 months"]

    def test_period_links_point_at_analytics_with_months(self, auth_client):
        html = page(auth_client)
        nav = re.search(r"<nav[^>]*period-links[^>]*>.*?</nav>", html, re.S).group(0)
        hrefs = re.findall(r'href="([^"]*)"', nav)
        assert [("months=%s" % n) in h for h, n in zip(hrefs, (3, 6, 12))] == [True] * 3

    def test_heading_and_period_label(self, auth_client):
        html = page(auth_client)
        assert re.search(r"<h1[^>]*>\s*Analytics\s*</h1>", html)
        assert "Jul 2026 – Dec 2026" in html

    @pytest.mark.parametrize(
        "query, label",
        [("?months=3", "Oct 2026 – Dec 2026"), ("?months=12", "Jan 2026 – Dec 2026")],
    )
    def test_period_label_follows_months(self, auth_client, query, label):
        assert label in page(auth_client, query)

    def test_default_months_are_listed_oldest_first(self, auth_client, user_id):
        credit(user_id, 100)
        assert [r[0] for r in monthly_rows(page(auth_client))] == LABELS_6

    def test_twelve_months_crossing_a_year_boundary_are_in_order(
        self, auth_client, user_id, monkeypatch
    ):
        monkeypatch.setattr(app_module, "_today", lambda: datetime.date(2026, 3, 10))
        credit(user_id, 100, "2026-03-05")
        html = page(auth_client, "?months=12")
        labels = [r[0] for r in monthly_rows(html)]
        assert labels[0] == "Apr 2025" and labels[-1] == "Mar 2026"
        assert labels[8:10] == ["Dec 2025", "Jan 2026"]
        assert "Apr 2025 – Mar 2026" in html


# ---- Monthly Overview table ------------------------------------------------------ #


class TestMonthlyTable:
    def test_table_is_labelled_with_scoped_headers(self, auth_client, user_id):
        credit(user_id, 100)
        credit_html = page(auth_client)
        assert re.search(r'id="monthly-heading"[^>]*>\s*Monthly Overview', credit_html)
        header, rows = table(credit_html, "monthly-heading")
        assert header[0] == "Month"
        assert header[1:] == ["Credits", "Expenses", "Savings", "Available"]
        assert 'scope="col"' in credit_html and 'scope="row"' in credit_html

    def test_empty_months_show_zero_without_bars(self, auth_client, user_id):
        credit(user_id, 100, "2026-12-05")
        rows = monthly_rows(page(auth_client))
        for row in rows[:-1]:
            assert row[1:] == ["₹0.00"] * 4, f"{row[0]} should be all zero"

    def test_spec_example_row(self, auth_client, user_id):
        seed_example(user_id)
        row = monthly_rows(page(auth_client))[-1]
        assert row == [
            "Dec 2026",
            "₹50,000.00",
            "₹30,000.00",
            "₹5,000.00",
            "₹15,000.00",
        ]

    def test_negative_available_has_minus_before_rupee(self, auth_client, user_id):
        credit(user_id, 100)
        expense(user_id, 250)
        row = monthly_rows(page(auth_client))[-1]
        assert row[4] == "-₹150.00"

    def test_no_negative_zero_shown(self, auth_client, user_id):
        credit(user_id, 0.1)
        credit(user_id, 0.2)
        expense(user_id, 0.3)
        html = page(auth_client)
        assert monthly_rows(html)[-1] == [
            "Dec 2026",
            "₹0.30",
            "₹0.30",
            "₹0.00",
            "₹0.00",
        ]
        assert "-₹0.00" not in html

    def test_large_amounts_use_grouping(self, auth_client, user_id):
        credit(user_id, 10000000)
        assert monthly_rows(page(auth_client))[-1][1] == "₹10,000,000.00"

    def test_totals_are_not_multiplied(self, auth_client, user_id):
        for _ in range(3):
            credit(user_id, 100)
        for _ in range(2):
            expense(user_id, 10)
        for _ in range(4):
            saving(user_id, 5)
        assert monthly_rows(page(auth_client))[-1][1:] == [
            "₹300.00",
            "₹20.00",
            "₹20.00",
            "₹260.00",
        ]

    @pytest.mark.parametrize("paid_from", [SALARY, OLD])
    def test_other_savings_change_nothing(self, auth_client, user_id, paid_from):
        credit(user_id, 100)
        before = page(auth_client)
        saving(user_id, 4000, paid_from=paid_from)
        after = page(auth_client)
        assert monthly_rows(after) == monthly_rows(before)
        assert cards(after) == cards(before)
        assert bars(after) == bars(before)

    @pytest.mark.parametrize(
        "date, shown",
        [
            ("2026-06-30", False),
            ("2026-07-01", True),
            ("2026-12-31", True),
            ("2027-01-01", False),
            ("2026-12-28", True),
        ],
    )
    def test_boundary_dates(self, auth_client, user_id, date, shown):
        credit(user_id, 100)  # keeps the table visible when the expense is outside
        expense(user_id, 12.5, date)
        html = page(auth_client)
        total = sum(parse_money(r[2]) for r in monthly_rows(html))
        assert total == (12.5 if shown else 0)

    def test_other_users_entries_never_appear(self, auth_client, other_id):
        credit(other_id, 777)
        expense(other_id, 555)
        saving(other_id, 333)
        html = page(auth_client)
        assert "777" not in html and "555" not in html
        assert EMPTY_ENTRIES in html

    @pytest.mark.parametrize("paid", [OWN_ACCOUNT])
    def test_saving_alone_counts_as_an_entry(self, auth_client, user_id, paid):
        saving(user_id, 50, paid_from=paid)
        html = page(auth_client)
        assert EMPTY_ENTRIES not in html
        assert monthly_rows(html)[-1][3] == "₹50.00"


# ---- Summary cards ------------------------------------------------------------------ #


class TestCards:
    def test_card_labels_present(self, auth_client):
        assert set(cards(page(auth_client))) == set(CARD_LABELS)

    def test_no_data_shows_placeholders(self, auth_client):
        values = cards(page(auth_client))
        assert values["Average Monthly Spending"] == "₹0.00"
        assert values["Highest Spending Month"] == "—"
        assert values["Savings Rate"] == "—"

    def test_average_skips_months_before_first_entry(self, auth_client, user_id):
        credit(user_id, 1000, "2026-10-02")
        expense(user_id, 300, "2026-11-02")
        expense(user_id, 600, "2026-12-02")
        values = cards(page(auth_client))
        assert values["Average Monthly Spending"].split()[0] == "₹300.00"

    def test_average_counts_current_month(self, auth_client, user_id):
        expense(user_id, 90, "2026-12-02")
        assert (
            cards(page(auth_client))["Average Monthly Spending"].split()[0] == "₹90.00"
        )

    def test_highest_month_shows_name_and_total(self, auth_client, user_id):
        expense(user_id, 300, "2026-09-02")
        expense(user_id, 600.5, "2026-11-02")
        value = cards(page(auth_client))["Highest Spending Month"]
        assert "Nov 2026" in value and "₹600.50" in value

    def test_highest_tie_goes_to_most_recent_month(self, auth_client, user_id):
        expense(user_id, 500, "2026-09-02")
        expense(user_id, 500, "2026-11-02")
        value = cards(page(auth_client))["Highest Spending Month"]
        assert "Nov 2026" in value and "Sep 2026" not in value

    def test_entries_without_expenses_have_no_highest(self, auth_client, user_id):
        credit(user_id, 100)
        value = cards(page(auth_client))["Highest Spending Month"]
        assert value == "—"

    @pytest.mark.parametrize(
        "credit_amount, saved_amount, expected_html, expected_text",
        [
            (50000, 5000, "10%", "10%"),
            (8, 1, "13%", "13%"),
            (100, 150, "150%", "150%"),
            (100, 0, "0%", "0%"),
            (100000, 1, "&lt;1%", "<1%"),
        ],
        ids=["ten", "half-up", "above-100", "no-savings", "tiny"],
    )
    def test_savings_rate(
        self,
        auth_client,
        user_id,
        credit_amount,
        saved_amount,
        expected_html,
        expected_text,
    ):
        credit(user_id, credit_amount)
        if saved_amount:
            saving(user_id, saved_amount)
        html = page(auth_client)
        assert cards(html)["Savings Rate"].split()[0] == expected_text
        assert expected_html in html, "tiny rate must be HTML-escaped"
        assert "<1%" not in html

    def test_savings_rate_without_credits_is_dash(self, auth_client, user_id):
        saving(user_id, 100)
        assert cards(page(auth_client))["Savings Rate"] == "—"

    def test_cards_use_rounded_monthly_totals(self, auth_client, user_id):
        expense(user_id, 10.004)
        expense(user_id, 10.004)
        value = cards(page(auth_client))["Average Monthly Spending"]
        assert value.split()[0] == "₹20.00"

    def test_notes_shown_with_data(self, auth_client, user_id):
        expense(user_id, 10)
        html = page(auth_client)
        assert NOTE_CURRENT in html and NOTE_SAVINGS in html

    def test_notes_shown_when_empty(self, auth_client):
        html = page(auth_client)
        assert NOTE_CURRENT in html and NOTE_SAVINGS in html


# ---- Category table --------------------------------------------------------------------- #


class TestCategoryTable:
    def test_table_is_labelled_with_header_row(self, auth_client, user_id):
        expense(user_id, 10)
        html = page(auth_client)
        assert re.search(r'id="category-heading"[^>]*>\s*Spending by Category', html)
        header, _ = table(html, "category-heading")
        assert header == ["Category", *LABELS_6, "Total"]

    def test_rows_are_ordered_by_total_then_name(self, auth_client, user_id):
        expense(user_id, 10, category="Food")
        expense(user_id, 50, category="Transport")
        expense(user_id, 10, category="Bills")
        assert [r[0] for r in category_rows(page(auth_client))] == [
            "Transport",
            "Bills",
            "Food",
        ]

    def test_each_row_months_add_up_to_total(self, auth_client, user_id):
        expense(user_id, 10.25, "2026-07-03")
        expense(user_id, 5.5, "2026-12-03")
        expense(user_id, 7.01, "2026-09-03", category="Health")
        for row in category_rows(page(auth_client)):
            months = [parse_money(c) for c in row[1:-1]]
            assert len(months) == 6
            assert round(sum(months), 2) == parse_money(row[-1]), row

    def test_category_totals_add_up_to_monthly_expenses(self, auth_client, user_id):
        expense(user_id, 10.004)
        expense(user_id, 10.004, "2026-10-01")
        expense(user_id, 0.006, category="Bills")
        expense(user_id, 0.006, "2026-11-30", category="Bills")
        expense(user_id, 3.33, "2026-08-08", category="Health")
        html = page(auth_client)
        category_total = round(sum(parse_money(r[-1]) for r in category_rows(html)), 2)
        monthly_total = round(sum(parse_money(r[2]) for r in monthly_rows(html)), 2)
        assert category_total == monthly_total

    def test_unknown_category_is_listed(self, auth_client, user_id):
        expense(user_id, 9, category="Pet snacks")
        assert [r[0] for r in category_rows(page(auth_client))] == ["Pet snacks"]

    def test_hostile_category_is_escaped(self, auth_client, user_id):
        hostile = "<script>alert(1)</script>"
        expense(user_id, 9, category=hostile)
        html = page(auth_client)
        assert hostile not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html

    def test_sql_in_category_is_stored_as_text(self, auth_client, user_id):
        name = "x'); DROP TABLE expenses;--"
        expense(user_id, 9, category=name)
        rows = category_rows(page(auth_client))
        assert rows[0][0] == name
        assert last_id("SELECT COUNT(*) FROM expenses") == 1

    def test_no_expenses_shows_message_and_no_table(self, auth_client, user_id):
        credit(user_id, 100)
        html = page(auth_client)
        assert EMPTY_EXPENSES in html
        assert not re.search(r'<table[^>]*aria-labelledby="category-heading"', html)

    def test_with_expenses_no_empty_message(self, auth_client, user_id):
        expense(user_id, 10)
        assert EMPTY_EXPENSES not in page(auth_client)

    def test_other_users_expenses_are_not_listed(self, auth_client, user_id, other_id):
        expense(other_id, 99, category="Travel")
        expense(user_id, 1, category="Food")
        assert [r[0] for r in category_rows(page(auth_client))] == ["Food"]


# ---- Chart ----------------------------------------------------------------------------------- #


class TestChart:
    def test_svg_attributes(self, auth_client, user_id):
        credit(user_id, 100)
        tag = svg_tag(page(auth_client))
        assert attr(tag, "role") == "img"
        assert attr(tag, "height") == "264"
        assert attr(tag, "aria-label"), "svg needs an aria-label pointing at the table"

    def test_legend_names_series_in_bar_order(self, auth_client, user_id):
        credit(user_id, 100)
        html = page(auth_client)
        legend = re.search(r"<ul[^>]*chart-legend[^>]*>.*?</ul>", html, re.S)
        assert legend, "ul.chart-legend not found"
        items = [
            text_of(i) for i in re.findall(r"<li\b.*?</li>", legend.group(0), re.S)
        ]
        assert items == ["Credits", "Expenses", "Savings"]

    def test_bars_are_proportional_to_the_largest_bar(self, auth_client, user_id):
        credit(user_id, 1000)
        expense(user_id, 500)
        saving(user_id, 250)
        expense(user_id, 250, "2026-11-05")
        found = bars(page(auth_client))
        by_tone = {}
        for bar in found:
            by_tone.setdefault(bar["tone"], []).append(bar)
        assert by_tone["tone-credit"][0]["height"] == pytest.approx(200)
        assert by_tone["tone-expense"][-1]["height"] == pytest.approx(100)
        assert by_tone["tone-saving"][0]["height"] == pytest.approx(50)
        assert by_tone["tone-expense"][0]["height"] == pytest.approx(50)
        assert len(found) == 4

    def test_scale_is_shared_across_months(self, auth_client, user_id):
        credit(user_id, 400, "2026-08-05")
        expense(user_id, 100, "2026-12-05")
        heights = sorted(b["height"] for b in bars(page(auth_client)))
        assert heights == [pytest.approx(50), pytest.approx(200)]

    def test_bars_sit_on_the_baseline(self, auth_client, user_id):
        seed_example(user_id)
        for bar in bars(page(auth_client)):
            assert bar["y"] + bar["height"] == pytest.approx(220), bar

    def test_tiny_value_still_gets_a_visible_bar(self, auth_client, user_id):
        credit(user_id, 10000000)
        expense(user_id, 0.01)
        found = {b["tone"]: b for b in bars(page(auth_client))}
        assert found["tone-expense"]["height"] == pytest.approx(2)
        assert found["tone-credit"]["height"] == pytest.approx(200)

    def test_zero_values_draw_no_bar(self, auth_client, user_id):
        credit(user_id, 100)
        found = bars(page(auth_client))
        assert [b["tone"] for b in found] == ["tone-credit"]

    def test_each_bar_has_a_tone_class_and_title(self, auth_client, user_id):
        seed_example(user_id)
        found = bars(page(auth_client))
        assert {b["tone"] for b in found} == {
            "tone-credit",
            "tone-expense",
            "tone-saving",
        }
        for bar in found:
            assert bar["title"], f"bar {bar['tone']} has no <title>"

    def test_bar_order_is_credit_expense_saving(self, auth_client, user_id):
        seed_example(user_id)
        assert [b["tone"] for b in bars(page(auth_client))] == [
            "tone-credit",
            "tone-expense",
            "tone-saving",
        ]

    def test_other_savings_draw_no_bar(self, auth_client, user_id):
        saving(user_id, 100, paid_from=SALARY)
        saving(user_id, 100, paid_from=OLD)
        credit(user_id, 100)
        assert [b["tone"] for b in bars(page(auth_client))] == ["tone-credit"]

    def test_bar_count_follows_entries_in_twelve_months(self, auth_client, user_id):
        for month in ("2026-01-05", "2026-06-05", "2026-12-05"):
            expense(user_id, 10, month)
        assert len(bars(page(auth_client, "?months=12"))) == 3

    def test_scroll_containers_are_labelled_and_focusable(self, auth_client, user_id):
        expense(user_id, 10)
        html = page(auth_client)
        containers = re.findall(r"<div\b[^>]*analytics-scroll[^>]*>", html)
        assert len(containers) >= 2, "each table needs its own scroll region"
        for tag in containers:
            assert attr(tag, "role") == "region"
            assert attr(tag, "tabindex") == "0"
            assert attr(tag, "aria-label") or attr(tag, "aria-labelledby"), tag

    def test_tables_have_scoped_headers(self, auth_client, user_id):
        expense(user_id, 10)
        html = page(auth_client)
        for table_html in re.findall(r"<table\b.*?</table>", html, re.S):
            assert "analytics-table" in table_html.split(">", 1)[0]
            assert 'scope="col"' in table_html and 'scope="row"' in table_html


# ---- Empty states ---------------------------------------------------------------------------------- #


class TestEmptyStates:
    def test_no_entries_shows_message_and_links(self, auth_client):
        html = page(auth_client)
        with flask_app.test_request_context():
            from flask import url_for

            add_expense_url = url_for("add_expense")
            add_credit_url = url_for("add_credit")
        assert EMPTY_ENTRIES in html
        assert f'href="{add_expense_url}"' in html
        assert f'href="{add_credit_url}"' in html

    def test_no_entries_replaces_chart_and_tables(self, auth_client):
        html = page(auth_client)
        assert "analytics-chart" not in html
        assert 'aria-labelledby="monthly-heading"' not in html
        assert 'aria-labelledby="category-heading"' not in html

    def test_no_entries_keeps_cards_and_period_links(self, auth_client):
        html = page(auth_client)
        assert set(cards(html)) == set(CARD_LABELS)
        assert len(period_links(html)) == 3

    def test_entries_outside_range_are_still_empty(self, auth_client, user_id):
        expense(user_id, 10, "2026-06-30")
        assert EMPTY_ENTRIES in page(auth_client)

    def test_only_other_savings_is_still_empty(self, auth_client, user_id):
        saving(user_id, 10, paid_from=OLD)
        assert EMPTY_ENTRIES in page(auth_client)

    def test_credits_only_shows_chart_and_category_message(self, auth_client, user_id):
        credit(user_id, 100)
        html = page(auth_client)
        assert EMPTY_ENTRIES not in html
        assert svg_tag(html)
        assert EMPTY_EXPENSES in html
        values = cards(html)
        assert values["Highest Spending Month"] == "—"
        assert values["Savings Rate"].split()[0] == "0%"


# ---- Changes show on the next load ---------------------------------------------------------------------- #


class TestChangesAreReflected:
    def test_added_entries_appear(self, auth_client, user_id):
        assert EMPTY_ENTRIES in page(auth_client)
        expense(user_id, 42, category="Food")
        html = page(auth_client)
        assert EMPTY_ENTRIES not in html
        assert monthly_rows(html)[-1][2] == "₹42.00"

    def test_edited_expense_is_updated(self, auth_client, user_id):
        expense(user_id, 42, "2026-12-05", "Food")
        expense_id = last_id("SELECT MAX(id) FROM expenses")
        update_expense(expense_id, user_id, 60, "Transport", "2026-11-05", "moved")
        html = page(auth_client)
        rows = monthly_rows(html)
        assert rows[-1][2] == "₹0.00" and rows[-2][2] == "₹60.00"
        assert [r[0] for r in category_rows(html)] == ["Transport"]

    def test_deleted_expense_disappears(self, auth_client, user_id):
        expense(user_id, 42)
        delete_expense(last_id("SELECT MAX(id) FROM expenses"), user_id)
        assert EMPTY_ENTRIES in page(auth_client)

    def test_deleted_credit_disappears_from_totals(self, auth_client, user_id):
        credit(user_id, 100)
        expense(user_id, 10)
        delete_credit(last_id("SELECT MAX(id) FROM credits"), user_id)
        assert monthly_rows(page(auth_client))[-1][1] == "₹0.00"


# ---- Page hygiene ------------------------------------------------------------------------------------------ #


class TestPageHygiene:
    @pytest.fixture(params=["empty", "full"])
    def html(self, request, auth_client, user_id):
        if request.param == "full":
            seed_example(user_id)
        return page(auth_client)

    def test_no_style_tags_or_attributes(self, html):
        assert "<style" not in html.lower()
        assert not re.search(r"<[^>]+\sstyle\s*=", html, re.I), "inline style attribute"

    def test_no_placeholder_text(self, html):
        assert "Coming Soon" not in html

    def test_no_external_scripts(self, html):
        sources = re.findall(r'<script\b[^>]*\ssrc="([^"]*)"', html, re.I)
        for src in sources:
            assert not src.startswith(
                ("http:", "https:", "//")
            ), f"external script {src}"
            assert "chart" not in src.lower(), f"chart library {src}"

    def test_page_links_analytics_stylesheet(self, html):
        assert "analytics.css" in html


class TestStylesheets:
    def test_analytics_css_has_no_hex_colours(self):
        css = re.sub(
            r"/\*.*?\*/", "", ANALYTICS_CSS.read_text(encoding="utf-8"), flags=re.S
        )
        declarations = " ".join(re.findall(r"\{([^}]*)\}", css))
        assert not re.search(
            r"#[0-9a-fA-F]{3,8}\b", declarations
        ), "hex colour in analytics.css"

    def test_analytics_css_does_not_define_tones(self):
        css = ANALYTICS_CSS.read_text(encoding="utf-8")
        assert not re.search(r"--tone-[\w-]+\s*:", css)

    @pytest.mark.parametrize(
        "token", ["--tone-credit", "--tone-expense", "--tone-saving"]
    )
    def test_tone_tokens_defined_in_style_css_only(self, token):
        pattern = re.escape(token) + r"\s*:"
        assert re.search(
            pattern, STYLE_CSS.read_text(encoding="utf-8")
        ), f"{token} missing"
        assert not re.search(
            pattern, PROFILE_CSS.read_text(encoding="utf-8")
        ), f"{token} still defined in profile.css"

    @pytest.mark.parametrize("tone", ["tone-credit", "tone-expense", "tone-saving"])
    def test_each_tone_class_sets_its_token(self, tone):
        css = PROFILE_CSS.read_text(encoding="utf-8")
        assert re.search(r"\.%s\s*\{\s*--tone:\s*var\(--%s\)" % (tone, tone), css)

    def test_chart_bars_use_the_tone(self):
        css = ANALYTICS_CSS.read_text(encoding="utf-8")
        assert re.search(r"\.chart-bar\s*\{\s*fill:\s*var\(--tone\)", css)
