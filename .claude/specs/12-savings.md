# Spec: Savings

## Overview
A logged-in user can record deposits into savings and investments (FD, RD, SIP, EPF, PPF and others), alongside expenses and credits. Each record is one dated deposit, not a holding. Savings live in their own table and never affect spending totals. Step 11 (Profile Net) is still reserved; this step records savings and shows Total Saved only. Available balance is left until after Step 11.

## Depends on
- Step 10 — Credits (form helpers, shared partial, entry table, confirmation page)

## Routes
All are logged-in only; edit and delete are owner only.
- `GET/POST /savings/add`
- `GET/POST /savings/<int:id>/edit`
- `GET/POST /savings/<int:id>/delete` — GET shows a confirmation page and deletes nothing

`GET /profile` also fetches savings.

## Database changes
New `savings` table, created in `init_db()` with `CREATE TABLE IF NOT EXISTS`:

| Column | Definition |
|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT |
| `user_id` | INTEGER NOT NULL, FOREIGN KEY to `users(id)` |
| `amount` | REAL NOT NULL |
| `type` | TEXT NOT NULL |
| `date` | TEXT NOT NULL |
| `description` | TEXT |
| `institution` | TEXT |
| `interest_rate` | REAL |
| `maturity_date` | TEXT |
| `paid_from` | TEXT NOT NULL |
| `created_at` | TEXT DEFAULT (datetime('now')) |

Helpers in `database/db.py`:
- `add_saving(user_id, amount, type, date, paid_from, description=None, institution=None, interest_rate=None, maturity_date=None)`
- `get_saving(saving_id, user_id)` — row or `None`
- `update_saving(saving_id, user_id, amount, type, date, paid_from, description=None, institution=None, interest_rate=None, maturity_date=None)` — bool
- `delete_saving(saving_id, user_id)` — bool

Queries in `database/queries.py` (inclusive date bounds):
- `get_recent_savings(user_id, limit=10, date_from=None, date_to=None)` — `date DESC, id DESC`
- `get_savings_summary(user_id, date_from=None, date_to=None)` — dict with `total` and `count`
- `get_savings_breakdown(user_id, date_from=None, date_to=None)` — list of `name`, `amount`, `pct`, like `get_category_breakdown`

## Form fields and validation
- `amount`, `date`, `description`: the existing shared rules
- `type`: one of FD, RD, SIP, EPF, VPF, PPF, NPS, Mutual Fund, Stocks/ETF, Bonds, Sukanya Samriddhi, NSC, KVP, SCSS, Post Office MIS, Gold, Emergency Fund, Other; error "Please select a valid type."
- `paid_from`: "My account" (preselected on add) or "Salary deduction/employer"; error "Please select a valid paid from option."
- `institution`: optional, at most 100 characters; error "Institution or scheme must be 100 characters or fewer."
- `interest_rate`: optional, finite, 0 to 100 inclusive; error "Interest rate must be between 0 and 100."
- `maturity_date`: optional, `YYYY-MM-DD`; error "Maturity date must be a valid date (YYYY-MM-DD)."; not before `date`; error "Maturity date cannot be before the date."
- Blank optional fields are stored as `NULL`

## Profile
- "+ Add Saving" button after "+ Add Credit"
- "Total Saved" stat card, in the existing stats section, following the date filter
- "Recent Savings" section (heading id `saving-heading`), same table as credits with a Type column; institution, rate, maturity date and a salary deduction note appear under the description
- "Savings by Type" section (heading id `saving-type-heading`), rendered only when there are savings
- Empty state uses saving wording, with the filtered variant
- Action labels: `Edit saving <description or type>, <amount>, <date>` and the `Delete saving` equivalent
- At most 10 rows, with "Showing latest 10 of N"

## Rules for implementation
- Same auth, ownership (404), bounded id, hard delete, escaping, parameterised SQL and no-inline-style rules as Step 10
- Total Spent, Transactions, Top Category, By Category and Recent Credits must not change when savings change
- Success flashes: "Saving added successfully.", "Saving updated successfully.", "Saving deleted successfully."
- Out of scope: Available balance, withdrawals and maturity payouts, current value and returns, recurring entries, converting existing expenses, syncing with any MCP server

## Definition of done
- [ ] Existing databases gain the table and keep their data
- [ ] Add, edit and delete work, and are protected against logged-out and other users
- [ ] Every invalid field shows its error, preserves input and saves nothing
- [ ] Profile shows the total, list and breakdown, all obeying the date filter
- [ ] All existing tests pass unmodified
