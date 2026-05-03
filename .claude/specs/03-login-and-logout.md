# Spec: Login and Logout

## Overview
Implement session-based login and logout so registered users can authenticate with Spendly. This step upgrades the `/login` route to handle POST requests (validate credentials, start a Flask session), implements `/logout` to clear that session, and adds a `get_user_by_id()` helper to `database/db.py`. After this step, the app has a working auth loop: register → login → logout.

## Depends on
- Step 1 (Database Setup) — `users` table and `get_db()` must exist.
- Step 2 (Registration) — `get_user_by_email()` and `create_user()` must exist; users must be able to register before they can log in.

## Routes
- `POST /login` — validate credentials, set `session['user_id']`, redirect to `/` on success — public
- `GET /logout` — clear session, redirect to `/` — public (no login required to hit this)

## Database changes
No new tables or columns. The existing `users` table has all required fields (`id`, `email`, `password_hash`).

## Templates
- **Modify:** `templates/login.html` — add `<form method="POST" action="{{ url_for('login') }}">` with `email` and `password` fields; render flash messages for errors.
- **Modify:** `templates/base.html` — update nav links so "Login" shows when logged out and "Logout" shows when logged in, using `session.get('user_id')` as the guard.

## Files to change
- `app.py` — update `login()` to handle POST (verify password, set session); implement `logout()` to clear session and redirect; import `session` from Flask; import `get_user_by_id` from `database/db.py`.
- `database/db.py` — add `get_user_by_id(user_id)` helper.
- `templates/login.html` — add form markup and flash message display.
- `templates/base.html` — add conditional nav links based on session state.

## Files to create
No new files.

## New dependencies
No new dependencies. `werkzeug.security.check_password_hash` is already available via the existing `werkzeug` install.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only — never use f-strings in SQL
- Verify passwords with `werkzeug.security.check_password_hash` — never compare plaintext
- Use CSS variables — never hardcode hex values in any template or stylesheet
- All templates extend `base.html`
- Store only `user_id` (integer) in the session — never store the full user row or password hash
- Use `flash()` for all error messages — never return raw error strings
- Use `redirect(url_for(...))` after every successful POST — never render a template on POST success
- `logout()` must call `session.clear()` — do not selectively pop keys
- Do not redirect to `/profile` after logout — redirect to `/`

## Definition of done
- [ ] Visiting `GET /login` renders the login form
- [ ] Submitting valid credentials sets `session['user_id']` and redirects to `/`
- [ ] Submitting with a wrong password re-renders the login form with a flash error
- [ ] Submitting with an unregistered email re-renders the login form with a flash error
- [ ] Submitting with a missing field re-renders the login form with a flash error
- [ ] Visiting `GET /logout` clears the session and redirects to `/`
- [ ] After logout, `session.get('user_id')` is `None`
- [ ] The nav in `base.html` shows "Logout" when logged in and "Login" when logged out
