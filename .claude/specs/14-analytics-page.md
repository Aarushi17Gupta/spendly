# Spec: Analytics Page

## Overview
This feature replaces the "Analytics Coming Soon" placeholder at `/analytics` with a working page that shows how a logged-in user's money changes from month to month. The profile already answers "how much, for this period?" with totals, lists and breakdowns; it cannot show a trend. Analytics adds a month-by-month chart of credits, expenses and savings, three summary cards, and a table of spending by category and month, for the last 3, 6 or 12 calendar months. It comes now because Steps 10–13 completed the credit, expense and savings data it needs. The page is read-only, rendered on the server, and works without JavaScript.

## Depends on
- Step 03 — Login and Logout (session identifies the user)
- Steps 04–06 — Profile Page and Date Filter (card styles, inclusive date bounds)
- Step 07 — Add Expense (`_current_user_id()`, `CATEGORIES`)
- Step 10 — Credits
- Step 12 — Savings
- Step 13 — Available Balance (`get_available_summary()`, `OWN_ACCOUNT`)

## Routes
No new routes. The existing `GET /analytics` (logged-in only) is modified to read an optional parameter:
- `GET /analytics?months=3|6|12` — number of calendar months to show, ending with the current month; 6 when missing or invalid

## Database changes
No database changes. All three entry tables already hold a `YYYY-MM-DD` `date`.

New queries in `database/queries.py` (inclusive date bounds, both required):
- `get_monthly_totals(user_id, date_from, date_to)` — one dict per calendar month in the range, oldest first, with `month` (`YYYY-MM`), `credits`, `spent`, `saved_from_account` and `available`; months without entries are included with zeros
- `get_category_months(user_id, date_from, date_to)` — one dict per category that has expenses in the range, highest total first and then by name, with `name`, `total` and `months` (list of amounts, oldest first, zeros included)

## Page content
1. Heading "Analytics" and the period label, such as "Jul 2026 – Dec 2026"
2. Period links "3 months", "6 months" and "12 months"; the active one has `aria-current="true"`
3. Summary cards:

| Card | Value | When there is nothing to show |
|---|---|---|
| Average Monthly Spending | Expenses in the range divided by the number of months from the first month with any entry (credit, expense or own-account saving) to the current month | ₹0.00 |
| Highest Spending Month | Month name and its expense total; the most recent month wins a tie | — |
| Savings Rate | Own-account savings divided by credits, as a whole percentage | — when credits are 0 |

4. "Monthly Overview" — grouped bars per month for credits, expenses and savings paid from the account, with a legend, followed by a table of the same figures plus Available
5. "Spending by Category" — a table with one row per category, one column per month and a Total column

Notes shown on the page:
- "The current month is included, so its figures may be incomplete."
- "Savings include only those paid from your account."

## Templates
- **Create:** none
- **Modify:** `templates/analytics.html` — replace the placeholder and its inline `<style>` block with the content above

## Files to change
- `app.py` — fetch and render in `analytics()`; add the allowed month counts, a pure helper that returns the first and last day of the range for a given month count and today's date, and any summary calculation as a helper
- `database/queries.py` — add the two queries
- `templates/analytics.html`
- `static/css/style.css` — receive the `--tone-*` tokens, so both pages can use them
- `static/css/profile.css` — remove the moved `--tone-*` tokens; nothing else changes
- `CLAUDE.md` — add `GET /analytics` to the route table as Step 14

## Files to create
- `static/css/analytics.css`
- `tests/test_14-analytics-page.py`

## New dependencies
No new dependencies. No chart library or CDN script.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only (`?` placeholders) — never f-strings in SQL; pass `OWN_ACCOUNT` as a parameter
- Passwords hashed with werkzeug (not applicable here, but maintain convention)
- Use CSS variables — never hardcode hex values; moving the existing token definitions is the only exception
- All templates extend `base.html`
- No inline `style` attributes or `<style>` tags; every internal link uses `url_for()`
- All SQL stays in `database/`; the route only fetches and renders
- Use `_current_user_id()` as the auth guard, and scope every query by the session user's id
- Reuse `_user_date_filter()`; group by the first seven characters of `date`
- Query the three tables separately; never join them, which would multiply rows
- The range runs from the first day of the oldest month to the last day of the current month, so entries dated later this month count and entries in later months do not
- The range helper takes today's date as an argument, and must handle ranges that cross a year boundary and months of every length
- Accept only the exact values `3`, `6` and `12`; anything else, including `abc`, `0`, `-3` and `1000000`, falls back to 6 without an error
- `available` is credits minus expenses minus own-account savings, matching `get_available_summary()` for the same range
- Savings whose `paid_from` is not "My account" appear nowhere on this page
- Round amounts to two decimal places, subtract already-rounded values, and never return or display negative zero
- Compute card values from the rounded monthly totals; the Savings Rate may exceed 100%
- Show a savings rate above zero that rounds to 0 as "<1%"
- Show amounts as `₹1,234.50` and negative amounts as `-₹1,234.50`
- Draw the chart as inline SVG with geometry from attributes; scale every bar to the largest single bar in the range, and draw no bar for zero
- A non-zero value too small to see still gets a visible bar
- The chart must not depend on colour alone: the legend names each series in bar order, and the table beneath gives every value
- Give the SVG `role="img"` and an `aria-label` that points to the table; both tables need captions or labelled headings and scoped headers
- Use `--tone-credit`, `--tone-expense` and `--tone-saving`, as on the profile
- Include every stored category in the category table, even one outside `CATEGORIES`
- Wide tables scroll inside their own labelled, keyboard-focusable container; the page never scrolls sideways
- With no credits, expenses or own-account savings in the range, show "No entries in this period." with links to add an expense and a credit, in place of the chart and tables; the cards and period links remain
- With entries but no expenses, the category section shows "No expenses in this period."
- Rely on Jinja autoescaping; never use `|safe`
- Do not change any existing query helper or the profile's content or appearance
- Every existing test passes unmodified
- Out of scope: budgets and goals, recommendations, exports, custom date ranges, forecasts, savings by type, interactive charts, and syncing with any MCP server

## Definition of done
- [ ] `/analytics` shows the new page, and no "Coming Soon" content or inline `<style>` remains
- [ ] Logged-out visitors are redirected to `/login`, and a deleted user's session is cleared
- [ ] With no parameter the page shows 6 months ending with the current month, and "6 months" is marked active
- [ ] `?months=3` and `?months=12` show that many months, and the matching link is marked active
- [ ] Invalid `months` values show 6 months with no error
- [ ] A 12-month range crossing a year boundary lists its months in order, oldest first
- [ ] Entries on the first and last day of the range are included; entries a day outside it are not
- [ ] Months without entries appear with ₹0.00 and no bar
- [ ] With credits of ₹50,000.00, expenses of ₹30,000.00 and ₹5,000.00 saved from the account in one month, its row shows those figures and ₹15,000.00 available
- [ ] A month that spends more than it earns shows a negative Available with the minus sign before ₹
- [ ] Amounts such as 0.10 + 0.20 credited and 0.30 spent give ₹0.00, not -₹0.00
- [ ] Salary-deduction savings and savings made before Spendly change nothing on the page
- [ ] Average Monthly Spending does not count months before the user's first entry in the range
- [ ] Highest Spending Month shows the right month, with the most recent winning a tie
- [ ] Savings Rate shows 10% for ₹5,000.00 saved of ₹50,000.00, "—" with no credits, and "<1%" for a tiny rate
- [ ] Category rows are ordered by total, and each row's months add up to its total
- [ ] The category totals add up to the expenses in the Monthly Overview
- [ ] The chart's bars are proportional to the values and have a legend
- [ ] Several credits, expenses and savings in one month give totals that are not multiplied
- [ ] Adding, editing or deleting an entry is reflected on the next page load
- [ ] One user's entries never appear in another user's analytics
- [ ] A user with no data sees the empty state and placeholder card values, with no errors
- [ ] A user with credits but no expenses sees the chart and the category empty message
- [ ] The page is readable at desktop width, at 900px and below, and at 600px and below, for 12 months and amounts of ₹1 crore
- [ ] The page works with JavaScript disabled, and loads no external chart library
- [ ] The profile looks the same as before, and all existing tests pass unmodified
