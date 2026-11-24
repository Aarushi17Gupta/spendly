# Spec: Edit Expense

## Overview
This feature lets a logged-in user correct an expense they have already recorded. An "Edit" link on each row of the profile transactions table opens a form at `/expenses/<id>/edit`, pre-filled with the stored values. Submitting it updates the existing row and returns to the profile, where the stats and category breakdown reflect the change. It replaces the Step 8 stub, reuses the Step 7 validation rules, and is the first route that acts on a specific expense, so it also establishes the ownership check that Step 9 (Delete Expense) will need.

## Depends on
- Step 01 — Database Setup (`expenses` table must exist)
- Step 03 — Login and Logout (session identifies the user)
- Steps 04–06 — Profile Page (entry point and redirect destination)
- Step 07 — Add Expense (`_current_user_id()`, `_expense_form_error()`, `_render_expense_form()`, form styles)

## Routes
The existing stub is replaced:
- `GET /expenses/<int:id>/edit` — render the form pre-filled with the expense — logged-in owner only
- `POST /expenses/<int:id>/edit` — validate and update the expense, then redirect to profile — logged-in owner only

## Database changes
No database changes to tables, columns, or constraints.

New helpers in `database/db.py`:
- `get_expense(expense_id, user_id)` — return the row matching both `id` and `user_id`, or `None`
- `update_expense(expense_id, user_id, amount, category, date, description=None)` — update the row matching both `id` and `user_id`; return whether a row was updated

## Templates
- **Create:** `templates/edit_expense.html` — extends `base.html`; edit heading, pre-filled form, "Save Changes" button, and a link back to profile
- **Create:** `templates/_expense_fields.html` — partial holding the amount, category, date, and description fields, included by both the add and edit forms
- **Modify:** `templates/add_expense.html` — include the shared partial in place of its inline fields; no visible change
- **Modify:** `templates/profile.html` — add an "Edit" link to each transaction row, with a matching column header

## Files to change
- `app.py` — replace the `edit_expense` stub with GET and POST handling; import the new helpers and `abort`; let `_render_expense_form()` render either template
- `database/db.py` — add `get_expense()` and `update_expense()`
- `database/queries.py` — include `id` in the rows returned by `get_recent_transactions()`
- `templates/add_expense.html` — use the shared fields partial
- `templates/profile.html` — add the Edit link
- `static/css/profile.css` — style the Edit link, including in the stacked layout at 600px and below
- `CLAUDE.md` — mark `GET/POST /expenses/<id>/edit` as implemented in the route table

## Files to create
- `templates/edit_expense.html`
- `templates/_expense_fields.html`

The edit page reuses `static/css/add_expense.css`; no new stylesheet is needed.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only (`?` placeholders) — never f-strings in SQL
- Passwords hashed with werkzeug (not applicable here, but maintain convention)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html` (the `_expense_fields.html` partial is included, so it does not)
- No inline styles; every internal link uses `url_for()`
- All SQL stays in `database/`, never in the route
- Use `_current_user_id()` as the auth guard on both GET and POST, before looking up the expense; redirect to `/login` if it returns `None`
- A missing expense and one owned by another user must both return `abort(404)`, so a response never reveals that another user's expense exists
- Scope both `get_expense()` and `update_expense()` by `user_id` in the `WHERE` clause; take `user_id` from the session, never from the form or URL
- If `update_expense()` matches no row (deleted between lookup and save), return `abort(404)`
- Reuse `_expense_form_error()` and the existing constants; do not duplicate or loosen Step 7 validation
- Import the helper as `db_update_expense`, following the existing `db_add_expense` convention
- Update only `amount`, `category`, `date`, and `description`; never change `id`, `user_id`, or `created_at`
- Pre-fill the amount with two decimal places, and show a `NULL` description as an empty field, never as "None"
- A blank description is stored as `NULL`
- On validation failure, re-render the form with the submitted values (not the stored ones) and a flash error; write nothing
- On success, flash "Expense updated successfully." and redirect to `url_for('profile')`; saving without changes also counts as success
- Each Edit link needs an accessible name identifying its expense, and the table must keep its explicit ARIA roles
- Do not implement delete; `/expenses/<id>/delete` stays a stub until Step 9

## Definition of done
- [ ] GET and POST to `/expenses/<id>/edit` while logged out redirect to `/login` and change nothing
- [ ] A session for a deleted user is cleared and redirected to `/login`
- [ ] Each transaction on the profile page has an Edit link pointing to that expense
- [ ] The Edit link is visible and usable at desktop width and at 600px and below
- [ ] The edit form is pre-filled with the stored amount, category, date, and description
- [ ] An expense with no description shows an empty description field
- [ ] Submitting valid changes updates the existing row, redirects to `/profile`, and shows the success message
- [ ] The number of transactions is unchanged after an edit
- [ ] The profile totals and category breakdown reflect the edited values
- [ ] `user_id` and `created_at` are unchanged after an edit, even if the form submits a `user_id`
- [ ] Saving the form without changes succeeds
- [ ] Clearing the description saves successfully and stores `NULL`
- [ ] GET and POST for a non-existent expense id return 404
- [ ] GET and POST for another user's expense return 404 and leave it unchanged
- [ ] A missing, zero, negative, non-numeric, `nan`, or infinite amount shows a flash error and saves nothing
- [ ] An amount outside 0.01–10,000,000 shows a flash error and saves nothing
- [ ] An invalid category shows a flash error and saves nothing
- [ ] A malformed date, including `20260501`, shows a flash error and saves nothing
- [ ] A description over 200 characters shows a flash error and saves nothing
- [ ] Submitted values are preserved in the form after a validation failure
- [ ] The add-expense page looks and behaves as before, and all existing tests pass
