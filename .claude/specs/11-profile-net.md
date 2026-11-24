# Spec: Profile Net

## Overview
This feature shows a logged-in user how their income compares with their spending. The profile gains a Total Credits card and a Net card (credits minus expenses) that follow the existing date filter, and the labels that became ambiguous once credits were added are renamed to say "expenses". Step 10 recorded credits without totalling them and reserved this step for the totals; Step 12 (Savings) was built first. Net is the flow of money for the selected period, not a bank balance, because Spendly holds no opening balance. Savings do not affect Net; an Available figure that subtracts them is left for a later step.

## Depends on
- Steps 04–06 — Profile Page and Date Filter (stats cards and filtering)
- Steps 07–09 — Add, Edit and Delete Expense (expense amounts)
- Step 10 — Credits (`credits` table)
- Step 12 — Savings, already built (stats layout and the Total Saved card, which must not change)

## Routes
No new routes. `GET /profile` is modified to fetch the net summary; its URL and parameters do not change.

## Database changes
No database changes. The `credits` and `expenses` tables already hold everything needed.

New query in `database/queries.py`:
- `get_net_summary(user_id, date_from=None, date_to=None)` — return a dict with `total_credits`, `total_spent` and `net`, where `net` is `total_credits - total_spent`

## Templates
- **Create:** none
- **Modify:** `templates/profile.html`
  - Add a `<section class="profile-net" aria-label="Income and net">` between the date filter and the existing `profile-stats` section, holding two cards: "Total Credits", then "Net"
  - Each card uses the existing `stat-card`, `stat-label` and `stat-value` classes; the Net card also has `stat-card--net`
  - Show the note "Credits minus expenses. Savings are not included." inside the Net card, after its value
  - Rename the labels below
  - Show negative amounts with the sign before the symbol

| Current label | New label |
|---|---|
| Transactions (stat card) | Expenses |
| Recent Transactions | Recent Expenses |
| By Category | Expenses by Category |

"Total Spent", "Total Saved" and "Top Category" keep their labels; only expenses have categories, so "Top Category" is not ambiguous.

## Files to change
- `app.py` — call `get_net_summary()` in `profile()` with the active date range and pass it to the template
- `database/queries.py` — add `get_net_summary()`
- `templates/profile.html` — new section, renamed labels, negative amounts
- `static/css/profile.css` — layout for the net section and the negative Net style, at all existing breakpoints
- `tests/test_08-edit-expense.py` — look up the "Expenses" label where "Transactions" was used
- `tests/test_09-delete-expense.py` — look up the "Expenses" label where "Transactions" was used

## Files to create
- `tests/test_11-profile-net.py`

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only (`?` placeholders) — never f-strings in SQL
- Passwords hashed with werkzeug (not applicable here, but maintain convention)
- Use CSS variables — never hardcode hex values; use `--danger` for a negative Net
- All templates extend `base.html`
- No inline styles; every internal link uses `url_for()`
- All SQL stays in `database/`; the route only fetches and renders
- Scope both totals by the session user's id and reuse `_user_date_filter()` for inclusive date bounds
- Sum credits and expenses in separate queries or subqueries; never join the tables, which would multiply rows
- Round `total_credits`, `total_spent` and `net` to two decimal places, and never return or display negative zero
- With no matching credits or expenses, every value is 0
- Show a positive or zero Net as `₹1,234.50` and a negative Net as `-₹1,234.50`; always use ₹, thousands separators and two decimal places
- Mark a negative Net with the `stat-card--negative` class; the minus sign must carry the meaning, so colour is never the only cue
- Net never reads the `savings` table
- Do not change `get_summary_stats()`, `get_category_breakdown()`, the credits queries or the savings queries
- Keep the two new cards outside the `profile-stats` section, which must stay identical when credits change (Step 10)
- Keep the section heading ids `tx-heading`, `cat-heading`, `credit-heading` and `saving-heading`, and the existing empty-state wording
- Both cards are always rendered, including for a user with no data
- No JavaScript is required
- In `tests/test_08-edit-expense.py` and `tests/test_09-delete-expense.py`, change only the label lookups; every other existing test passes unmodified
- Out of scope: Available balance, opening balance, charts, trends between periods, analytics page changes, and merging the lists

## Definition of done
- [ ] The profile shows Total Credits and Net cards above the existing summary cards
- [ ] With credits of ₹50,000.00 and expenses of ₹12,345.50, Net shows ₹37,654.50
- [ ] With credits of ₹100.00 and expenses of ₹250.00, Net shows -₹150.00 and has the negative style
- [ ] With equal credits and expenses, Net shows ₹0.00 without the negative style
- [ ] A user with no credits or expenses sees ₹0.00 in both cards, with no errors
- [ ] A user with only expenses sees ₹0.00 credits and a negative Net
- [ ] A user with several credits and several expenses sees totals that are not multiplied
- [ ] Amounts such as 0.10 + 0.20 credited and 0.30 spent give a Net of ₹0.00, not -₹0.00
- [ ] Adding, editing or deleting a credit or an expense updates Net immediately
- [ ] Adding, editing or deleting a saving does not change Total Credits or Net
- [ ] The date filter applies to both cards, including both boundary dates and one-sided ranges
- [ ] A filter that matches nothing shows ₹0.00 in both cards
- [ ] An invalid date parameter is ignored and does not cause an error
- [ ] One user's credits and expenses never affect another user's cards
- [ ] Total Credits covers all matching credits, not just the 10 listed
- [ ] The renamed labels are shown, and "Recent Transactions", "By Category" on its own and the "Transactions" card label are gone from the profile
- [ ] Total Spent, Total Saved and Top Category keep their labels and values
- [ ] The Net card states that savings are not included
- [ ] The cards are readable at desktop width, at 900px and below, and at 600px and below, including for amounts of ₹1 crore
- [ ] Logged-out visitors to `/profile` are still redirected to `/login`
- [ ] All tests pass, with only the "Transactions" label lookups in Steps 8 and 9 updated (three lines)
