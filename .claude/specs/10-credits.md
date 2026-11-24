# Spec: Credits

## Overview
This feature lets a logged-in user record money coming in, such as salary, alongside their expenses. A credit has an amount, a source, a date, and an optional description, and can be added, edited, and deleted through the same flow as an expense. Credits are stored in their own table and shown in their own "Recent Credits" list on the profile page, so every existing expense total and breakdown stays correct. This step delivers the records and the list only; Step 11 (Profile Net) will add the Total Credits and Net cards and rename the expense-specific labels.

## Depends on
- Step 01 — Database Setup (`users` table and `get_db()`)
- Step 03 — Login and Logout (session identifies the user)
- Steps 04–06 — Profile Page and Date Filter (entry point, list location, and redirect destination)
- Step 07 — Add Expense (validation rules, form helpers, form styles)
- Step 08 — Edit Expense (ownership rules, shared fields partial, per-row actions)
- Step 09 — Delete Expense (confirmation page pattern)

## Routes
- `GET /credits/add` — render the add-credit form — logged-in only
- `POST /credits/add` — validate and save the credit, then redirect to profile — logged-in only
- `GET /credits/<int:id>/edit` — render the form pre-filled with the credit — logged-in owner only
- `POST /credits/<int:id>/edit` — validate and update the credit, then redirect to profile — logged-in owner only
- `GET /credits/<int:id>/delete` — render the confirmation page without changing anything — logged-in owner only
- `POST /credits/<int:id>/delete` — delete the credit, then redirect to profile — logged-in owner only

The existing `GET /profile` route is modified to fetch credits; its URL and parameters do not change.

## Database changes
New table, created in `init_db()` with `CREATE TABLE IF NOT EXISTS`, so it is added to existing databases automatically:

| Column | Definition |
|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT |
| `user_id` | INTEGER NOT NULL, FOREIGN KEY to `users(id)` |
| `amount` | REAL NOT NULL |
| `source` | TEXT NOT NULL |
| `date` | TEXT NOT NULL |
| `description` | TEXT |
| `created_at` | TEXT DEFAULT (datetime('now')) |

The `users` and `expenses` tables do not change. No credits are seeded.

New helpers in `database/db.py`:
- `add_credit(user_id, amount, source, date, description=None)`
- `get_credit(credit_id, user_id)` — return the row matching both, or `None`
- `update_credit(credit_id, user_id, amount, source, date, description=None)` — return whether a row was updated
- `delete_credit(credit_id, user_id)` — return whether a row was deleted

New queries in `database/queries.py`:
- `get_recent_credits(user_id, limit=10, date_from=None, date_to=None)` — newest first, ordered by `date DESC, id DESC`
- `count_credits(user_id, date_from=None, date_to=None)` — total matching credits, for the "Showing latest N of M" note

## Templates
- **Create:** `templates/add_credit.html` — add form with an "Add Credit" button and a link back to profile
- **Create:** `templates/edit_credit.html` — pre-filled form with a "Save Changes" button and a link back to profile
- **Create:** `templates/delete_credit.html` — credit details, warning, POST form with a "Delete Credit" button, and a "Cancel" link
- **Create:** `templates/_entry_fields.html` — `_expense_fields.html` renamed, with the dropdown's field name, label, placeholder, and options supplied by the caller
- **Modify:** `templates/add_expense.html`, `templates/edit_expense.html` — include the renamed partial; no visible change
- **Modify:** `templates/profile.html` — add a "+ Add Credit" button beside "+ Add Expense", and a "Recent Credits" section below the existing grid

## Files to change
- `app.py` — add `CREDIT_SOURCES`, the three credit routes, and credits on the profile; generalise the form helpers so validation and rendering take the dropdown field and its options
- `database/db.py` — add the `credits` table and helpers
- `database/queries.py` — add the two credit queries
- `templates/add_expense.html`
- `templates/edit_expense.html`
- `templates/profile.html`
- `static/css/profile.css` — hero button group and credits section, including at 600px and below
- `CLAUDE.md` — add the credit routes to the route table

## Files to create
- `templates/add_credit.html`
- `templates/edit_credit.html`
- `templates/delete_credit.html`
- `templates/_entry_fields.html` (replaces `templates/_expense_fields.html`)
- `tests/test_10-credits.py`

The credit pages reuse `static/css/add_expense.css` and `static/css/delete_expense.css`; no new stylesheet is needed.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only (`?` placeholders) — never f-strings in SQL
- Passwords hashed with werkzeug (not applicable here, but maintain convention)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html` (the `_entry_fields.html` partial is included, so it does not)
- No inline styles; every internal link uses `url_for()`
- All SQL stays in `database/`, never in a route
- Allowed sources: Salary, Freelance, Interest, Refund, Gift, Other
- The credit form submits the dropdown as `source`; the expense form keeps submitting `category`
- Apply the Step 7 amount, date, and description rules through shared code; do not duplicate or loosen them
- An invalid source flashes "Please select a valid source."; all existing expense messages stay the same
- Use `_current_user_id()` as the auth guard on GET and POST, before looking up the credit; redirect to `/login` if it returns `None`
- A missing credit and one owned by another user must both return `abort(404)`
- Scope `get_credit()`, `update_credit()`, and `delete_credit()` by `user_id` in the `WHERE` clause; take `user_id` from the session, never from the form or URL
- If an update or delete matches no row, return `abort(404)`
- Use the bounded converter `<int(max=9223372036854775807):id>`
- Never delete on GET; this is a hard delete of exactly one row
- Import colliding helpers as `db_add_credit` and `db_delete_credit`, and `db_update_credit` for consistency
- An edit changes only `amount`, `source`, `date`, and `description`
- A blank description is stored as `NULL`, shown as an empty form field, and shown as "No description" elsewhere
- On validation failure, re-render with the submitted values and a flash error; write nothing
- On success, flash "Credit added successfully.", "Credit updated successfully.", or "Credit deleted successfully." and redirect to `url_for('profile')`
- Show amounts with ₹, thousands separators, and two decimal places; rely on Jinja autoescaping and never use `|safe`
- Keep credits separate from expenses: no existing expense query, stat, or breakdown may read the `credits` table
- The date filter applies to the credits list with the same inclusive bounds as expenses
- Render the credits table only when there are credits, with the same explicit ARIA roles, five columns (Date, Description, Source, Amount, Actions), and action icons as the expenses table
- Give each action link an `aria-label` in the form `Edit credit <description or source>, <amount>, <date>` or `Delete credit <description or source>, <amount>, <date>`
- The credits empty state must use credit wording, with a filtered variant that links to all time
- Source badges must not use the `cat-*` expense category colour classes
- No JavaScript is required; CSRF tokens remain out of scope, as no existing form has them
- Out of scope: Total Credits and Net cards, renaming existing profile labels, recurring credits, and merging the two lists

## Definition of done
- [ ] Starting the app with an existing database adds the `credits` table and keeps all users and expenses
- [ ] GET and POST to all three credit routes while logged out redirect to `/login` and change nothing
- [ ] A session for a deleted user is cleared and redirected to `/login`
- [ ] The profile shows "+ Add Credit" beside "+ Add Expense", both usable at desktop width and at 600px and below
- [ ] The add form shows amount, source, date, and description, with exactly the six allowed sources
- [ ] Submitting valid data saves one credit for the logged-in user, redirects to `/profile`, and shows the success message
- [ ] The new credit appears in "Recent Credits" immediately
- [ ] Total Spent, Transactions, Top Category, and By Category are unchanged after adding, editing, or deleting a credit
- [ ] A missing, zero, negative, non-numeric, `nan`, infinite, or out-of-range amount shows a flash error and saves nothing
- [ ] An invalid source, including an expense-only category such as "Food", shows a flash error and saves nothing
- [ ] A malformed date, including `20260501`, shows a flash error and saves nothing
- [ ] A description over 200 characters shows a flash error and saves nothing
- [ ] Submitted values are preserved after a validation failure on both add and edit
- [ ] The edit form is pre-filled, and saving updates the existing row without changing `user_id` or `created_at`
- [ ] Clearing the description stores `NULL`
- [ ] The delete confirmation shows the credit's details, and opening or cancelling it deletes nothing
- [ ] Confirming deletes only that credit, and a second submission returns 404
- [ ] With an expense and a credit sharing the same id, editing or deleting one leaves the other unchanged
- [ ] GET and POST for a missing, oversized, or other user's credit id return 404 and change nothing
- [ ] Users see only their own credits
- [ ] Credits are listed newest first, at most 10, with "Showing latest 10 of N" when there are more
- [ ] The date filter limits the credits list and its count, including both boundary dates
- [ ] A user with no credits sees the credits empty state, and a filter with no matches shows its filtered variant
- [ ] A description containing HTML is displayed as text
- [ ] The expense pages look and behave as before, and all existing tests pass unmodified
