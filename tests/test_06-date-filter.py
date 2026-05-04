"""
Tests for Step 6 — Date Filter feature on GET /profile.

All test logic is self-contained; this file must be invoked via file path:
    pytest tests/test_06-date-filter.py
because the hyphen in the filename prevents import-based discovery.

Seed data used across tests (deterministic, belongs to 'filteruser'):
    id  amount   category       date         description
    1   100.00   Food           2026-05-01   Grocery run
    2    20.00   Transport      2026-05-05   Bus fare
    3    50.00   Bills          2026-05-10   Water bill
    4    80.00   Entertainment  2026-05-15   Concert
    5    40.00   Health         2026-05-20   Pharmacy

Date-range test window: 2026-05-01 to 2026-05-10
  -> matching rows: Food (100.00), Transport (20.00), Bills (50.00)
  -> total_spent: 170.00, transaction_count: 3, top_category: Food
  -> pct: Food ~58.82%, Transport ~11.76%, Bills ~29.41% (sum must == 100)

Out-of-range rows: Entertainment (2026-05-15), Health (2026-05-20)
"""

import sqlite3
import pytest
from werkzeug.security import generate_password_hash

from app import app as flask_app
from database.db import init_db, get_db
from database.queries import get_category_breakdown


# ------------------------------------------------------------------ #
# Fixtures                                                            #
# ------------------------------------------------------------------ #

TEST_EMAIL = "filteruser@spendly.test"
TEST_PASSWORD = "filterpass"
TEST_NAME = "Filter User"

SEED_EXPENSES = [
    (100.00, "Food",          "2026-05-01", "Grocery run"),
    ( 20.00, "Transport",     "2026-05-05", "Bus fare"),
    ( 50.00, "Bills",         "2026-05-10", "Water bill"),
    ( 80.00, "Entertainment", "2026-05-15", "Concert"),
    ( 40.00, "Health",        "2026-05-20", "Pharmacy"),
]

# Expenses that fall within the inclusive date window [2026-05-01, 2026-05-10]
IN_RANGE_DESCRIPTIONS = {"Grocery run", "Bus fare", "Water bill"}
OUT_OF_RANGE_DESCRIPTIONS = {"Concert", "Pharmacy"}

DATE_FROM = "2026-05-01"
DATE_TO = "2026-05-10"

FILTER_TOTAL = 170.00          # 100 + 20 + 50
FILTER_COUNT = 3
FILTER_TOP_CATEGORY = "Food"   # highest single-category spend in window


@pytest.fixture()
def app(tmp_path):
    """
    Isolated Flask app backed by a temporary file-based SQLite database.
    A file-based DB is used so that both the Flask app and direct get_db()
    calls within the same test process share the same data.
    """
    db_file = str(tmp_path / "test_spendly.db")

    flask_app.config.update({
        "TESTING": True,
        "SECRET_KEY": "test-secret-date-filter",
        "WTF_CSRF_ENABLED": False,
    })

    # Monkey-patch DB_PATH in database.db so every get_db() call uses our
    # temp file for the duration of this test.
    import database.db as db_module
    original_db_path = db_module.DB_PATH
    db_module.DB_PATH = db_file

    with flask_app.app_context():
        init_db()

        # Insert the test user directly so we know the exact password.
        conn = get_db()
        conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (TEST_NAME, TEST_EMAIL, generate_password_hash(TEST_PASSWORD)),
        )
        conn.commit()
        user_id = conn.execute(
            "SELECT id FROM users WHERE email = ?", (TEST_EMAIL,)
        ).fetchone()[0]

        conn.executemany(
            "INSERT INTO expenses (user_id, amount, category, date, description)"
            " VALUES (?, ?, ?, ?, ?)",
            [(user_id, amt, cat, dt, desc) for amt, cat, dt, desc in SEED_EXPENSES],
        )
        conn.commit()
        conn.close()

        yield flask_app

    # Restore original DB_PATH after the test.
    db_module.DB_PATH = original_db_path


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def auth_client(client):
    """Test client already logged in as the seeded filteruser."""
    resp = client.post(
        "/login",
        data={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert resp.status_code == 302, (
        f"Login fixture failed; expected 302 redirect, got {resp.status_code}"
    )
    return client


# ------------------------------------------------------------------ #
# Helper                                                              #
# ------------------------------------------------------------------ #

def _get_user_id(app):
    """Return the test user's DB id from within the app context."""
    with app.app_context():
        conn = get_db()
        row = conn.execute(
            "SELECT id FROM users WHERE email = ?", (TEST_EMAIL,)
        ).fetchone()
        conn.close()
        return row[0]


# ------------------------------------------------------------------ #
# 1. Auth guard                                                        #
# ------------------------------------------------------------------ #

class TestAuthGuard:
    def test_profile_unauthenticated_redirects_to_login(self, client):
        resp = client.get("/profile")
        assert resp.status_code == 302, (
            "Unauthenticated GET /profile must return 302"
        )
        assert "/login" in resp.headers["Location"], (
            "Redirect target must be /login"
        )

    def test_profile_unauthenticated_with_filter_params_redirects(self, client):
        resp = client.get(f"/profile?from={DATE_FROM}&to={DATE_TO}")
        assert resp.status_code == 302, (
            "Unauthenticated GET /profile with filter params must return 302"
        )
        assert "/login" in resp.headers["Location"]


# ------------------------------------------------------------------ #
# 2. No-filter baseline (all expenses visible)                        #
# ------------------------------------------------------------------ #

class TestNoFilterBaseline:
    def test_profile_no_params_returns_200(self, auth_client):
        resp = auth_client.get("/profile")
        assert resp.status_code == 200, "GET /profile (no params) must return 200"

    def test_profile_no_params_shows_all_expenses(self, auth_client):
        resp = auth_client.get("/profile")
        html = resp.data.decode("utf-8")
        for _, _, _, desc in SEED_EXPENSES:
            assert desc in html, (
                f"Expected description '{desc}' in unfiltered profile page"
            )

    def test_profile_no_params_stats_reflect_all_expenses(self, auth_client):
        resp = auth_client.get("/profile")
        html = resp.data.decode("utf-8")
        all_total = sum(amt for amt, *_ in SEED_EXPENSES)
        # Total spent formatted as ₹290.00
        assert f"₹{all_total:.2f}" in html, (
            f"Expected total ₹{all_total:.2f} in unfiltered stats"
        )
        # Transaction count
        assert str(len(SEED_EXPENSES)) in html, (
            "Expected transaction count of 5 in unfiltered stats"
        )

    def test_profile_no_params_rupee_symbol_present(self, auth_client):
        resp = auth_client.get("/profile")
        html = resp.data.decode("utf-8")
        assert "₹" in html, "Rupee symbol ₹ must appear on the profile page"


# ------------------------------------------------------------------ #
# 3. Filter form structure                                            #
# ------------------------------------------------------------------ #

class TestFilterFormStructure:
    def test_filter_form_uses_get_method(self, auth_client):
        resp = auth_client.get("/profile")
        html = resp.data.decode("utf-8")
        assert 'method="get"' in html.lower() or "method='get'" in html.lower(), (
            "Date filter form must use method='get'"
        )

    def test_filter_form_has_from_input(self, auth_client):
        resp = auth_client.get("/profile")
        html = resp.data.decode("utf-8")
        assert 'name="from"' in html, "Filter form must have an input with name='from'"

    def test_filter_form_has_to_input(self, auth_client):
        resp = auth_client.get("/profile")
        html = resp.data.decode("utf-8")
        assert 'name="to"' in html, "Filter form must have an input with name='to'"

    def test_filter_form_has_apply_button(self, auth_client):
        resp = auth_client.get("/profile")
        html = resp.data.decode("utf-8")
        assert "Apply" in html, "Filter form must contain an 'Apply' submit button"

    def test_filter_form_has_clear_link(self, auth_client):
        resp = auth_client.get("/profile")
        html = resp.data.decode("utf-8")
        assert "Clear" in html, "Filter form must contain a 'Clear' link"

    def test_clear_link_points_to_profile_without_params(self, auth_client):
        # When params are active, the Clear link must strip them.
        resp = auth_client.get(f"/profile?from={DATE_FROM}&to={DATE_TO}")
        html = resp.data.decode("utf-8")
        # The Clear anchor href must be /profile with no query string.
        # We look for href="/profile" without a trailing '?'.
        assert 'href="/profile"' in html, (
            "Clear link must point to /profile with no query parameters"
        )


# ------------------------------------------------------------------ #
# 4. Date inputs pre-populated when filter is active                  #
# ------------------------------------------------------------------ #

class TestDateInputPrepopulation:
    def test_from_input_prepopulated_after_filter(self, auth_client):
        resp = auth_client.get(f"/profile?from={DATE_FROM}&to={DATE_TO}")
        html = resp.data.decode("utf-8")
        assert f'value="{DATE_FROM}"' in html, (
            f"'from' input must be pre-populated with {DATE_FROM}"
        )

    def test_to_input_prepopulated_after_filter(self, auth_client):
        resp = auth_client.get(f"/profile?from={DATE_FROM}&to={DATE_TO}")
        html = resp.data.decode("utf-8")
        assert f'value="{DATE_TO}"' in html, (
            f"'to' input must be pre-populated with {DATE_TO}"
        )

    def test_inputs_empty_when_no_filter_active(self, auth_client):
        resp = auth_client.get("/profile")
        html = resp.data.decode("utf-8")
        # Neither date value should appear as a filled input value.
        assert f'value="{DATE_FROM}"' not in html, (
            "date inputs should be empty when no filter is active"
        )
        assert f'value="{DATE_TO}"' not in html, (
            "date inputs should be empty when no filter is active"
        )


# ------------------------------------------------------------------ #
# 5. Filtered transaction list (inclusive range)                      #
# ------------------------------------------------------------------ #

class TestFilteredTransactions:
    def test_filtered_profile_returns_200(self, auth_client):
        resp = auth_client.get(f"/profile?from={DATE_FROM}&to={DATE_TO}")
        assert resp.status_code == 200, (
            "GET /profile with valid date range must return 200"
        )

    def test_in_range_transactions_appear(self, auth_client):
        resp = auth_client.get(f"/profile?from={DATE_FROM}&to={DATE_TO}")
        html = resp.data.decode("utf-8")
        for desc in IN_RANGE_DESCRIPTIONS:
            assert desc in html, (
                f"Description '{desc}' is within date range and must appear"
            )

    def test_out_of_range_transactions_absent(self, auth_client):
        resp = auth_client.get(f"/profile?from={DATE_FROM}&to={DATE_TO}")
        html = resp.data.decode("utf-8")
        for desc in OUT_OF_RANGE_DESCRIPTIONS:
            assert desc not in html, (
                f"Description '{desc}' is outside date range and must NOT appear"
            )

    def test_boundary_date_from_included(self, auth_client):
        # DATE_FROM itself (2026-05-01) is inclusive — 'Grocery run' must show.
        resp = auth_client.get(f"/profile?from={DATE_FROM}&to={DATE_FROM}")
        html = resp.data.decode("utf-8")
        assert "Grocery run" in html, (
            f"Expense on exactly {DATE_FROM} must appear (inclusive lower bound)"
        )

    def test_boundary_date_to_included(self, auth_client):
        # DATE_TO itself (2026-05-10) is inclusive — 'Water bill' must show.
        resp = auth_client.get(f"/profile?from={DATE_TO}&to={DATE_TO}")
        html = resp.data.decode("utf-8")
        assert "Water bill" in html, (
            f"Expense on exactly {DATE_TO} must appear (inclusive upper bound)"
        )

    def test_rupee_symbol_in_filtered_amounts(self, auth_client):
        resp = auth_client.get(f"/profile?from={DATE_FROM}&to={DATE_TO}")
        html = resp.data.decode("utf-8")
        assert "₹" in html, (
            "Rupee symbol ₹ must appear in filtered transaction amounts"
        )

    def test_only_from_param_returns_200(self, auth_client):
        # Partial filter: only 'from', no 'to'.
        resp = auth_client.get(f"/profile?from={DATE_FROM}")
        assert resp.status_code == 200, (
            "GET /profile with only 'from' param must return 200"
        )

    def test_only_from_param_hides_earlier_expenses(self, auth_client):
        # All SEED_EXPENSES have date >= 2026-05-01 so all should appear;
        # use a later from-date to prove lower-bound filtering works.
        resp = auth_client.get("/profile?from=2026-05-15")
        html = resp.data.decode("utf-8")
        assert "Concert" in html, (
            "Expense on 2026-05-15 must appear when from=2026-05-15"
        )
        assert "Grocery run" not in html, (
            "Expense on 2026-05-01 must NOT appear when from=2026-05-15"
        )

    def test_only_to_param_returns_200(self, auth_client):
        resp = auth_client.get(f"/profile?to={DATE_TO}")
        assert resp.status_code == 200, (
            "GET /profile with only 'to' param must return 200"
        )

    def test_only_to_param_hides_later_expenses(self, auth_client):
        resp = auth_client.get(f"/profile?to={DATE_TO}")
        html = resp.data.decode("utf-8")
        # Expenses on/before 2026-05-10 should appear.
        assert "Water bill" in html, (
            "Expense on 2026-05-10 must appear when to=2026-05-10"
        )
        # Expenses after 2026-05-10 should not appear.
        assert "Concert" not in html, (
            "Expense on 2026-05-15 must NOT appear when to=2026-05-10"
        )


# ------------------------------------------------------------------ #
# 6. Filtered summary stats                                           #
# ------------------------------------------------------------------ #

class TestFilteredStats:
    def test_filtered_total_spent(self, auth_client):
        resp = auth_client.get(f"/profile?from={DATE_FROM}&to={DATE_TO}")
        html = resp.data.decode("utf-8")
        assert f"₹{FILTER_TOTAL:.2f}" in html, (
            f"Total spent within filter window must be ₹{FILTER_TOTAL:.2f}"
        )

    def test_filtered_transaction_count(self, auth_client):
        resp = auth_client.get(f"/profile?from={DATE_FROM}&to={DATE_TO}")
        html = resp.data.decode("utf-8")
        # '3' must appear somewhere in the stats area; the unfiltered count is 5,
        # which must NOT appear as the stats value.
        assert str(FILTER_COUNT) in html, (
            f"Transaction count in filter window must be {FILTER_COUNT}"
        )
        # The full dataset total 290.00 must not appear in filtered view.
        assert "₹290.00" not in html, (
            "Unfiltered total ₹290.00 must not appear in filtered stats"
        )

    def test_filtered_top_category(self, auth_client):
        resp = auth_client.get(f"/profile?from={DATE_FROM}&to={DATE_TO}")
        html = resp.data.decode("utf-8")
        assert FILTER_TOP_CATEGORY in html, (
            f"Top category '{FILTER_TOP_CATEGORY}' must appear in filtered stats"
        )


# ------------------------------------------------------------------ #
# 7. Filtered category breakdown                                      #
# ------------------------------------------------------------------ #

class TestFilteredCategoryBreakdown:
    def test_in_range_categories_appear_in_breakdown(self, auth_client):
        resp = auth_client.get(f"/profile?from={DATE_FROM}&to={DATE_TO}")
        html = resp.data.decode("utf-8")
        for cat in ("Food", "Transport", "Bills"):
            assert cat in html, (
                f"Category '{cat}' should appear in filtered breakdown"
            )

    def test_out_of_range_categories_absent_from_breakdown(self, auth_client):
        resp = auth_client.get(f"/profile?from={DATE_FROM}&to={DATE_TO}")
        html = resp.data.decode("utf-8")
        # Entertainment and Health are outside the date range.
        # We verify their category-specific amounts don't appear.
        # ₹80.00 (Entertainment) and ₹40.00 (Health) must not show.
        assert "₹80.00" not in html, (
            "Entertainment amount ₹80.00 must not appear in filtered breakdown"
        )
        assert "₹40.00" not in html, (
            "Health amount ₹40.00 must not appear in filtered breakdown"
        )

    def test_category_breakdown_pct_sum_via_direct_call(self, app):
        """
        Calls get_category_breakdown() directly to verify the pct rounding
        invariant: pct values must sum to exactly 100 for any non-empty result.
        This avoids depending on HTML rendering for a numeric invariant.
        """
        user_id = _get_user_id(app)
        with app.app_context():
            breakdown = get_category_breakdown(
                user_id, date_from=DATE_FROM, date_to=DATE_TO
            )
        assert len(breakdown) > 0, "Expected at least one category in filtered breakdown"
        total_pct = sum(row["pct"] for row in breakdown)
        assert total_pct == 100, (
            f"Category pct values must sum to 100, got {total_pct}"
        )

    def test_category_breakdown_pct_sum_all_expenses_via_direct_call(self, app):
        """Same rounding invariant holds when no date filter is applied."""
        user_id = _get_user_id(app)
        with app.app_context():
            breakdown = get_category_breakdown(user_id)
        assert len(breakdown) > 0, "Expected at least one category in unfiltered breakdown"
        total_pct = sum(row["pct"] for row in breakdown)
        assert total_pct == 100, (
            f"Unfiltered category pct values must sum to 100, got {total_pct}"
        )


# ------------------------------------------------------------------ #
# 8. Invalid / unparseable date params                                #
# ------------------------------------------------------------------ #

class TestInvalidDateParams:
    def test_invalid_from_param_returns_200_not_500(self, auth_client):
        resp = auth_client.get("/profile?from=not-a-date")
        assert resp.status_code == 200, (
            "Invalid 'from' param must not raise a 500; expected 200"
        )

    def test_invalid_to_param_returns_200_not_500(self, auth_client):
        resp = auth_client.get("/profile?to=not-a-date")
        assert resp.status_code == 200, (
            "Invalid 'to' param must not raise a 500; expected 200"
        )

    def test_both_invalid_params_returns_200(self, auth_client):
        resp = auth_client.get("/profile?from=not-a-date&to=also-bad")
        assert resp.status_code == 200, (
            "Both invalid date params must not raise a 500; expected 200"
        )

    def test_both_invalid_params_treats_as_no_filter(self, auth_client):
        """When both params are invalid, the page should show all expenses."""
        resp = auth_client.get("/profile?from=not-a-date&to=also-bad")
        html = resp.data.decode("utf-8")
        for _, _, _, desc in SEED_EXPENSES:
            assert desc in html, (
                f"Invalid params treated as None; all expenses (incl. '{desc}') must appear"
            )

    def test_invalid_from_with_valid_to_returns_200(self, auth_client):
        resp = auth_client.get(f"/profile?from=bad&to={DATE_TO}")
        assert resp.status_code == 200, (
            "Mixed invalid/valid params must not cause 500"
        )

    @pytest.mark.parametrize("bad_date", [
        "2026-13-01",   # month 13
        "2026-00-10",   # month 0
        "not-a-date",
        "2026/05/01",   # wrong separator
        "",             # empty string
        "01-05-2026",   # reversed format
    ])
    def test_various_malformed_from_dates_return_200(self, auth_client, bad_date):
        resp = auth_client.get(f"/profile?from={bad_date}")
        assert resp.status_code == 200, (
            f"Malformed from='{bad_date}' must not cause a 500"
        )


# ------------------------------------------------------------------ #
# 9. Zero-match date range — empty state                             #
# ------------------------------------------------------------------ #

class TestEmptyStateForZeroResults:
    def test_zero_match_range_returns_200(self, auth_client):
        resp = auth_client.get("/profile?from=2020-01-01&to=2020-01-31")
        assert resp.status_code == 200, (
            "A date range matching no expenses must return 200, not 500"
        )

    def test_zero_match_range_shows_empty_state_message(self, auth_client):
        resp = auth_client.get("/profile?from=2020-01-01&to=2020-01-31")
        html = resp.data.decode("utf-8")
        # The spec mandates an empty-state message, e.g. "No expenses in this period"
        assert "No expenses" in html, (
            "Zero-match filter must show an empty-state message containing 'No expenses'"
        )

    def test_zero_match_range_shows_zero_stats(self, auth_client):
        resp = auth_client.get("/profile?from=2020-01-01&to=2020-01-31")
        html = resp.data.decode("utf-8")
        assert "₹0.00" in html, (
            "Zero-match filter must show ₹0.00 for total spent"
        )

    def test_zero_match_range_no_expense_rows(self, auth_client):
        """None of the seeded expense descriptions should appear."""
        resp = auth_client.get("/profile?from=2020-01-01&to=2020-01-31")
        html = resp.data.decode("utf-8")
        for _, _, _, desc in SEED_EXPENSES:
            assert desc not in html, (
                f"Expense '{desc}' must not appear in a zero-match date range"
            )

    def test_empty_state_appears_in_categories_section(self, auth_client):
        resp = auth_client.get("/profile?from=2020-01-01&to=2020-01-31")
        html = resp.data.decode("utf-8")
        # The empty-state message should appear at least once (could cover both sections)
        assert html.count("No expenses") >= 1, (
            "Empty-state message must appear in at least one section when no results"
        )


# ------------------------------------------------------------------ #
# 10. Rupee symbol display                                            #
# ------------------------------------------------------------------ #

class TestRupeeSymbol:
    def test_rupee_in_unfiltered_view(self, auth_client):
        resp = auth_client.get("/profile")
        assert "₹" in resp.data.decode("utf-8"), (
            "Rupee symbol must appear on unfiltered profile page"
        )

    def test_rupee_in_filtered_view(self, auth_client):
        resp = auth_client.get(f"/profile?from={DATE_FROM}&to={DATE_TO}")
        assert "₹" in resp.data.decode("utf-8"), (
            "Rupee symbol must appear on filtered profile page"
        )

    def test_rupee_in_individual_transaction_amount(self, auth_client):
        resp = auth_client.get(f"/profile?from={DATE_FROM}&to={DATE_TO}")
        html = resp.data.decode("utf-8")
        # Food row: ₹100.00
        assert "₹100.00" in html, (
            "Individual transaction amount must display the ₹ symbol (₹100.00)"
        )
