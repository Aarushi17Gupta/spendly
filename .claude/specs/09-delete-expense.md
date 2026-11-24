# Spec: Delete Expense

## Overview
This feature lets a logged-in user permanently remove an expense they have recorded. A trash-can delete icon on each row of the profile transactions table opens a confirmation page at `/expenses/<id>/delete` showing the expense's details. Confirming removes the row and returns to the profile, where the stats and category breakdown reflect the change. It replaces the Step 9 stub, reuses the ownership check established in Step 8, and completes the add, view, edit, and delete cycle for expenses. Deletion happens only on POST, so following a link, prefetching, or crawling can never remove data, and the flow works without JavaScript.

## Depends on
- Step 01 — Database Setup (`expenses` table must exist)
- Step 03 — Login and Logout (session identifies the user)
- Steps 04–06 — Profile Page (entry point and redirect destination)
- Step 07 — Add Expense (`_current_user_id()`, card and form styles)
- Step 08 — Edit Expense (`get_expense()`, ownership rules, per-row action cell)

## Routes
The existing stub is replaced:
- `GET /expenses/<int:id>/delete` — render the confirmation page without changing anything — logged-in owner only
- `POST /expenses/<int:id>/delete` — delete the expense, then redirect to profile — logged-in owner only

## Database changes
No database changes to tables, columns, or constraints.

New helper in `database/db.py`:
- `delete_expense(expense_id, user_id)` — delete the row matching both `id` and `user_id`; return whether a row was deleted

## Templates
- **Create:** `templates/delete_expense.html` — extends `base.html`; heading, the expense's amount, category, date, and description, a warning that this cannot be undone, a POST form with a "Delete Expense" button, and a "Cancel" link back to profile
- **Modify:** `templates/profile.html` — add a delete icon link (inline SVG trash can, no visible text) beside the "Edit" text link in each row's action cell, and rename the "Edit" column header to "Actions"

## Files to change
- `app.py` — replace the `delete_expense` stub with GET and POST handling; import the new helper
- `database/db.py` — add `delete_expense()`
- `templates/profile.html` — add the delete icon and rename the column header
- `static/css/profile.css` — style the delete icon, including hover and focus states and in the stacked layout at 600px and below
- `tests/test_08-edit-expense.py` — remove `test_delete_route_remains_a_stub`, which this step makes obsolete
- `CLAUDE.md` — mark `GET/POST /expenses/<id>/delete` as implemented in the route table

## Files to create
- `templates/delete_expense.html`
- `static/css/delete_expense.css` — styles specific to the confirmation page (expense summary, danger button, cancel link)

The confirmation page also links `static/css/add_expense.css` for the shared page and card layout.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only (`?` placeholders) — never f-strings in SQL
- Passwords hashed with werkzeug (not applicable here, but maintain convention)
- Use CSS variables — never hardcode hex values; use `--danger` and `--danger-light` for destructive styling
- All templates extend `base.html`
- No inline styles; every internal link uses `url_for()`
- All SQL stays in `database/`, never in the route
- Never delete on GET; the only state change is on POST
- Use `_current_user_id()` as the auth guard on both GET and POST, before looking up the expense; redirect to `/login` if it returns `None`
- A missing expense and one owned by another user must both return `abort(404)`, so a response never reveals that another user's expense exists
- Scope `delete_expense()` by `user_id` in the `WHERE` clause; take `user_id` from the session, never from the form or URL
- If `delete_expense()` matches no row (already deleted, including a double submit), return `abort(404)`
- Use the same bounded converter as the edit route, `<int(max=9223372036854775807):id>`, so oversized ids return 404 rather than 500
- Import the helper as `db_delete_expense`, following the `db_add_expense` and `db_update_expense` convention
- This is a hard delete of exactly one row; no soft delete, undo, or bulk delete
- Show the amount with ₹, thousands separators, and two decimal places; show a `NULL` description as "No description", never as "None"
- Rely on Jinja autoescaping for the description; do not use `|safe`
- On success, flash "Expense deleted successfully." and redirect to `url_for('profile')`
- The delete icon is an inline SVG trash can inside an `<a>` to the confirmation page; no icon font, image file, emoji, or external library
- The SVG uses `stroke="currentColor"` so its colour comes from CSS variables, and has `aria-hidden="true"` and `focusable="false"`
- Give the icon link a `title="Delete"` tooltip for mouse users
- Each delete icon link needs an `aria-label` identifying its expense, in the same form as Edit (`Delete <description or category>, <amount>, <date>`)
- The table must keep its explicit ARIA roles and its five columns; the Edit link and delete icon share the action cell
- The Edit link and delete icon must remain separate, easily tappable targets (icon at least 32×32px on desktop; both at least 44×44px at 600px and below)
- No JavaScript is required; do not use `confirm()` dialogs
- CSRF tokens are out of scope, as no existing form has them and no new packages are allowed

## Definition of done
- [ ] GET and POST to `/expenses/<id>/delete` while logged out redirect to `/login` and delete nothing
- [ ] A session for a deleted user is cleared and redirected to `/login` on both GET and POST
- [ ] Each transaction on the profile page has a trash-can delete icon linking to that expense's confirmation page, beside its Edit link, with no visible "Delete" text
- [ ] Each delete icon has an accessible name identifying its expense
- [ ] The delete icon is visible, keyboard-focusable, and usable at desktop width and at 600px and below
- [ ] The confirmation page shows the expense's amount, category, date, and description
- [ ] An expense with no description shows "No description" on the confirmation page
- [ ] A description containing HTML is displayed as text, not rendered
- [ ] Opening the confirmation page deletes nothing
- [ ] Cancel returns to `/profile` and deletes nothing
- [ ] Confirming deletes the expense, redirects to `/profile`, and shows "Expense deleted successfully."
- [ ] Only the chosen expense is deleted; the user's other expenses and all other users' expenses are unchanged
- [ ] The profile total, transaction count, top category, and category breakdown reflect the deletion
- [ ] Deleting the user's last expense shows the profile's empty state without errors
- [ ] GET and POST for a non-existent expense id return 404
- [ ] GET and POST for another user's expense return 404 and leave it unchanged, even if the form submits that user's `user_id`
- [ ] Submitting the same deletion twice returns 404 the second time and deletes nothing else
- [ ] An id larger than SQLite's maximum integer returns 404
- [ ] The edit page for a deleted expense returns 404
- [ ] The add and edit pages behave as before, and all tests pass once the obsolete stub test is removed
