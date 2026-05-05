# Spec: Add Expense

## Overview
This feature lets a logged-in user add a new expense record through a form at `GET/POST /expenses/add`. The form collects amount, category, date, and an optional description, then writes the row to the `expenses` table. This is the first user-facing write path in Spendly — without it, the profile dashboard remains read-only and relies solely on seeded data.

## Depends on
- Step 01 — Database Setup (`expenses` table must exist)
- Step 03 — Login and Logout (session must be established to identify the user)
- Step 04/05 — Profile Page (redirect destination after a successful add)

## Routes
- `GET /expenses/add` — render the add-expense form — logged-in only
- `POST /expenses/add` — validate and save the new expense, then redirect to profile — logged-in only

## Database changes
No new tables or columns. The `expenses` table already exists with all required columns:
`id`, `user_id`, `amount`, `category`, `date`, `description`, `created_at`.

A new DB helper `add_expense(user_id, amount, category, date, description)` must be added to `database/db.py`.

## Templates
- **Create:** `templates/add_expense.html` — form with fields: amount, category (dropdown), date, description (optional)
- **Modify:** none required (profile already links to this route via stub)

## Files to change
- `app.py` — replace the stub `add_expense` route with real GET + POST handlers
- `database/db.py` — add `add_expense()` helper

## Files to create
- `templates/add_expense.html` — the expense form template
- `static/css/add_expense.css` — page-specific styles

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only (`?` placeholders) — never f-strings in SQL
- Passwords hashed with werkzeug (not applicable here, but maintain convention)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Redirect unauthenticated users to `/login` — do not render the form
- Amount must be a positive number; reject zero or negative values with a flash error
- Date must be a valid ISO date string (`YYYY-MM-DD`); reject malformed dates
- Category must be one of the allowed values: Food, Transport, Bills, Health, Entertainment, Shopping, Other
- On successful POST, redirect to `url_for('profile')` with a success flash message
- On validation failure, re-render the form with the user's input preserved and a flash error
- `add_expense()` in `db.py` must accept `description=None` as default (field is optional)

## Definition of done
- [ ] Visiting `/expenses/add` while logged out redirects to `/login`
- [ ] Visiting `/expenses/add` while logged in renders a form with amount, category, date, and description fields
- [ ] Submitting the form with valid data saves a row to `expenses` and redirects to `/profile`
- [ ] The new expense appears in the transactions list on the profile page immediately after adding
- [ ] Submitting with a missing or zero amount shows a flash error and re-renders the form
- [ ] Submitting with an invalid date shows a flash error and re-renders the form
- [ ] Submitting with an invalid category shows a flash error and re-renders the form
- [ ] Description field is optional — form submits successfully when left blank
- [ ] Previously entered values are preserved in the form after a validation failure
