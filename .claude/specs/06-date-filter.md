# Spec: Date Filter

## Overview
Step 6 adds a date range filter to the profile page so users can narrow the
transaction list, summary stats, and category breakdown to a specific period.
Currently the page always shows all expenses; this step wires up `?from=` and
`?to=` query-string parameters on `GET /profile` so the user can select any
start and end date and see filtered results. The filter form lives directly on
the profile page — no new routes are needed.

## Depends on
- Step 1: Database setup (tables and `get_db()` exist)
- Step 2: Registration (users are stored in the database)
- Step 3: Login / Logout (`session["user_id"]` is set on login)
- Step 4: Profile page static UI (template already renders all four sections)
- Step 5: Backend connection (`database/queries.py` with live query helpers)

## Routes
No new routes. The existing `GET /profile` route is modified to read optional
`from` and `to` query parameters:
- `GET /profile` — no params — shows all expenses (existing behavior)
- `GET /profile?from=YYYY-MM-DD&to=YYYY-MM-DD` — filters all data sections to
  the given inclusive date range — logged-in only

## Database changes
No database changes. The `expenses.date` column (TEXT, ISO-8601 `YYYY-MM-DD`)
is already present and lexicographically sortable.

## Templates
- **Modify**: `templates/profile.html`
  - Add a date filter form above the "Recent Transactions" section
  - The form uses `method="get"` and `action="{{ url_for('profile') }}"` so it
    appends `from` and `to` to the URL as query parameters
  - Two `<input type="date">` fields: `name="from"` and `name="to"`
  - A submit button labelled "Apply"
  - A "Clear" link that points to `url_for('profile')` (strips all params)
  - Pre-populate both inputs from the current query params so the selected range
    persists after the page reloads
  - All three data sections (stats, transactions, categories) already use Jinja
    variables — no structural changes needed beyond the new form

## Files to change
- `app.py` — update `profile()` to read `request.args.get("from")` and
  `request.args.get("to")` and forward both to the query helpers
- `database/queries.py` — update the four query helpers to accept optional
  `date_from` and `date_to` parameters and filter results accordingly:
  - `get_summary_stats(user_id, date_from=None, date_to=None)`
  - `get_recent_transactions(user_id, limit=10, date_from=None, date_to=None)`
  - `get_category_breakdown(user_id, date_from=None, date_to=None)`
  - `get_user_by_id` does not need date params — user info is never filtered

## Files to create
- `static/css/date-filter.css` — styles for the filter form only; linked from
  `profile.html` via `url_for`

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only via `get_db()`
- Parameterised queries only — never string-format values into SQL
- Date comparison must use SQL `BETWEEN ? AND ?` with the `expenses.date` column
- When `date_from` is `None`, do not add a lower-bound clause; same for `date_to`
- Invalid or unparseable date strings from query params must be silently ignored
  (treat as `None`) — never let a bad param raise an exception or 500
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- No inline styles — all filter-form styles go in `static/css/date-filter.css`
- The "Clear" link must use `url_for('profile')` — never a hardcoded path
- `pct` rounding invariant from Step 5 must still hold after filtering
- If the filter returns zero expenses, stats should show zeros and the
  transactions/categories sections show an empty-state message (e.g. "No
  expenses in this period") rather than a blank table

## Definition of done
- [ ] Visiting `/profile` without filter params shows all expenses (unchanged behavior)
- [ ] Submitting the date filter form appends `from` and `to` to the URL
- [ ] With `?from=2026-05-01&to=2026-05-10` the transaction list shows only
      expenses whose date falls within that range (inclusive)
- [ ] The summary stats (total spent, transaction count, top category) reflect
      only the filtered expenses, not all expenses
- [ ] The category breakdown reflects only the filtered expenses
- [ ] The date inputs are pre-populated with the currently active `from`/`to` values
- [ ] Clicking "Clear" returns to `/profile` with no query params and shows all data
- [ ] Providing an invalid date (e.g. `?from=not-a-date`) does not cause a 500 error
- [ ] A date range that matches zero expenses shows an empty-state message instead
      of a blank table
- [ ] All amounts continue to display the ₹ symbol
- [ ] `pct` values in the filtered category breakdown sum to 100
