# Spec: Registration

## Overview
Implement user registration so new visitors can create a Spendly account. This step adds a `POST /register` route that validates form input, hashes the password, inserts a new row into the `users` table, and redirects to the login page on success. It also adds a `create_user()` helper to `database/db.py` and wires up Flask's secret key and flash messaging so errors surface cleanly in the template.

## Depends on
- Step 1 (Database Setup) — `users` table and `get_db()` must already exist.

## Routes
- `POST /register` — process registration form, insert user, redirect to `/login` — public

## Database changes
No new tables or columns. The `users` table from Step 1 already has all required columns (`name`, `email`, `password_hash`, `created_at`).

## Templates
- **Modify:** `templates/register.html` — add a `<form method="POST" action="{{ url_for('register') }}">` with fields for `name`, `email`, `password`, and `confirm_password`; render flash messages for validation errors and success.

## Files to change
- `app.py` — set `app.secret_key`, update `register()` to handle both GET and POST, import `create_user` and `get_user_by_email` from `database/db.py`, use `flash()` and `redirect()`.
- `database/db.py` — add `create_user(name, email, password)` and `get_user_by_email(email)`.
- `templates/register.html` — add form markup and flash message display.

## Files to create
No new files.

## New dependencies
No new dependencies. `werkzeug.security` is already installed.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only — never use f-strings in SQL
- Hash passwords with `werkzeug.security.generate_password_hash` — never store plaintext
- Use CSS variables — never hardcode hex values in any template or stylesheet
- All templates extend `base.html`
- Set `app.secret_key` using `os.environ.get('SECRET_KEY', 'dev-secret')` — never hardcode a production secret
- Validate all fields server-side: name, email, password required; passwords must match; email must not already exist
- Use `flash()` for all error and success messages — never return raw error strings
- Use `abort(400)` only for truly malformed requests; use flash+redirect for user-correctable errors
- On duplicate email, show a user-friendly message — do not expose raw DB exceptions

## Definition of done
- [ ] Visiting `GET /register` renders the registration form
- [ ] Submitting the form with valid data creates a new user in the `users` table
- [ ] The stored password is a bcrypt hash, not plaintext
- [ ] Submitting with a missing field re-renders the form with a flash error
- [ ] Submitting with mismatched passwords re-renders the form with a flash error
- [ ] Submitting with an already-registered email re-renders the form with a flash error
- [ ] Successful registration redirects to `/login`
- [ ] A success flash message is visible on the login page after redirect
- [ ] `get_user_by_email()` returns `None` for unknown emails and a Row for known ones
