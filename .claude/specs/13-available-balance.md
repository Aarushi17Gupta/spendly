# Spec: Available Balance

## Overview
This feature shows a logged-in user what is left of their income after both spending and saving, in one figure. An Available card replaces the Net card from Step 11: Available is credits minus expenses minus the savings paid from the user's own account, and it follows the existing date filter. Not every saving reduces what is left: salary deductions never reached the account, and savings made before the user started using Spendly were paid from income it has no record of. A third "Paid from" option, "Already saved before Spendly", lets the user mark those old savings so that they still count in Total Saved but do not reduce Available. Available can be negative; it is shown as it is, with an explanation, and never blocks or changes a saving. It describes the money recorded for the selected period, not a bank balance, because Spendly holds no opening balance.

## Depends on
- Step 06 — Date Filter (period selection)
- Step 10 — Credits
- Step 11 — Profile Net (`get_net_summary()`, Total Credits card, negative amounts); its Net card and note are removed by this step
- Step 12 — Savings (`savings` table, `paid_from`, savings form)

## Routes
No new routes. `GET /profile` is modified to fetch the available summary. `GET/POST /savings/add` and `GET/POST /savings/<int:id>/edit` offer and accept the new option. URLs and parameters do not change.

## Database changes
No database changes. `savings.paid_from` is already `TEXT NOT NULL` with no CHECK constraint, so it can hold the new value. Existing rows are never rewritten.

New query in `database/queries.py`:
- `get_available_summary(user_id, date_from=None, date_to=None)` — return a dict with `total_credits`, `total_spent`, `saved_from_account` and `available`. `saved_from_account` sums only savings whose `paid_from` is "My account", and `available` is `total_credits - total_spent - saved_from_account`

`get_net_summary()` stays as the helper that supplies the credit and expense totals, but its `net` value is no longer displayed.

## Paid from options

| Option | In Total Saved and Savings by Type | Reduces Available |
|---|---|---|
| My account (default on add) | Yes | Yes |
| Salary deduction/employer | Yes | No |
| Already saved before Spendly (new) | Yes | No |

## Templates
- **Create:** none
- **Modify:** `templates/profile.html` — replace the `profile-net` section, in the same place, with `<section class="profile-available" aria-label="Income and available balance">` holding two cards: "Total Credits" (unchanged), then "Available"
  - Remove the Net card and its note "Credits minus expenses. Savings are not included."
  - Cards use `stat-card`, `stat-label` and `stat-value`; the Available card also has `stat-card--available`, plus `stat-card--negative` when it is below zero
  - The Available card always shows the note "Credits minus expenses and savings paid from your account."
  - When Available is below zero, it also shows one explanation (see Rules)
- **Modify:** `templates/_saving_fields.html` — add a hint under "Paid from", linked with `aria-describedby`: "Only savings paid from my account reduce your available balance."

## Files to change
- `app.py` — add the new option to `PAID_FROM_OPTIONS`; in `profile()`, replace the `get_net_summary()` call and `net_summary` with `get_available_summary()` and `available_summary`
- `database/queries.py` — add `get_available_summary()` and correct the comment on `OWN_ACCOUNT`
- `templates/profile.html` — replace the Net card and section
- `templates/_saving_fields.html` — hint
- `static/css/profile.css` — rename the `profile-net` rules to `profile-available`; no Net rules remain
- `static/css/add_expense.css` — hint style, if no existing class fits
- `tests/test_11-profile-net.py` — keep the `get_net_summary()` query tests; update the section, label order and CSS lookups to the new section; move tests that assert the Net card to `tests/test_13-available-balance.py` as Available tests, and remove the ones that contradict this step (savings must not change the section, and the old note). Total Credits, renamed-label, date-filter and auth coverage must not be lost
- `tests/test_12-savings.py` — add the new option to the `PAID_FROM` list; nothing else

## Files to create
- `tests/test_13-available-balance.py`

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only (`?` placeholders) — never f-strings in SQL, including in tests; pass the "My account" value as a parameter using `OWN_ACCOUNT`
- Passwords hashed with werkzeug (not applicable here, but maintain convention)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html` (the `_saving_fields.html` partial is included, so it does not)
- No inline styles; every internal link uses `url_for()`
- All SQL stays in `database/`; the route only fetches and renders
- `get_available_summary()` calls `get_net_summary()` for the credit and expense totals instead of summing them again
- Reuse `_user_date_filter()`; the same inclusive bounds apply to credits, expenses and savings, using each saving's own `date`
- Scope every total by the session user's id
- Round `saved_from_account` and `available` to two decimal places, subtract already-rounded values, and never return or display negative zero
- With no matching data, every value is 0
- Only an exact "My account" value reduces Available
- Show a negative Available as `-₹1,234.50`; never cap it at zero, and never use colour as the only cue
- When Available is below zero, show exactly one explanation, after the first note:
  - if `saved_from_account` is above zero: "Your expenses and savings are more than your credits for this period. Money from before this period, or not recorded here, is not included. If a saving is older than your records, edit it and choose Already saved before Spendly."
  - otherwise: "You spent more than your credits for this period."
- Never block, warn on, reorder or change a saving because of Available; entries may be added in any order
- Do not change existing savings automatically, whatever their date; the user edits old ones
- A saving marked "Already saved before Spendly" keeps its real date and follows the date filter in Total Saved, Recent Savings and Savings by Type
- That option appears in the saving's details under its description and on the delete confirmation page, as other non-default values already do
- "My account" stays first and stays the default on the add form; the invalid-option error stays "Please select a valid paid from option."
- Do not change `get_net_summary()`, `get_summary_stats()`, `get_category_breakdown()`, the credits queries, `get_savings_summary()` or `get_savings_breakdown()`
- No "Net" card, label or note remains anywhere on the profile
- Total Credits must not change when a saving or expense changes, and the `profile-stats` section must not change when a saving changes, except for Total Saved
- Both cards are always rendered, including for a user with no data
- No JavaScript is required
- Every existing test passes unmodified apart from the edits listed under Files to change
- Out of scope: opening balance, withdrawals and maturity payouts, interest, recurring entries, bulk editing of old savings, analytics, and syncing with any MCP server

## Definition of done
- [ ] The profile shows Total Credits and Available cards above the existing summary cards, and no Net card, label or note
- [ ] With credits of ₹50,000.00, expenses of ₹30,000.00 and no savings, Available shows ₹20,000.00
- [ ] Adding a ₹5,000.00 SIP paid from my account changes Available to ₹15,000.00 and leaves Total Credits and Total Spent unchanged
- [ ] Adding a ₹2,00,000 FD marked "Already saved before Spendly" raises Total Saved by ₹200,000.00 and leaves Available unchanged
- [ ] Adding an EPF saving by salary deduction raises Total Saved and leaves Available unchanged
- [ ] With credits of ₹50,000.00, expenses of ₹30,000.00 and ₹35,000.00 saved from my account, Available shows -₹15,000.00 with the negative style and the expenses-and-savings explanation
- [ ] With expenses above credits and nothing saved from my account, Available is negative and shows the spent-more explanation only
- [ ] With Available at ₹0.00 or above, neither explanation nor the negative style is shown
- [ ] Expenses and savings that add up to exactly the credits show ₹0.00, not -₹0.00, including with amounts such as 0.10 + 0.20
- [ ] A saving larger than what is available can be added, edited and deleted without any error or warning
- [ ] Editing an old saving from "My account" to "Already saved before Spendly" raises Available by its amount and leaves Total Saved unchanged
- [ ] Editing it back lowers Available again, and deleting a saving paid from my account raises it
- [ ] Adding, editing or deleting a credit or an expense updates Available
- [ ] The add form offers exactly the three options, with "My account" selected
- [ ] The edit form preselects "Already saved before Spendly" when stored
- [ ] The new option is shown under the saving's description and on its delete confirmation page
- [ ] An invalid option is still rejected with the existing error and saves nothing
- [ ] Savings recorded before this step keep their stored option and all other values
- [ ] The date filter applies to both cards, including boundary dates and one-sided ranges
- [ ] A saving outside the filtered period does not reduce Available for that period
- [ ] A filter that matches nothing shows ₹0.00 in both cards
- [ ] A user with no data sees ₹0.00 in both cards, with no errors
- [ ] One user's savings never affect another user's Available
- [ ] Several credits, expenses and savings give totals that are not multiplied
- [ ] The hint is shown on the savings add and edit forms and is not on the expense or credit forms
- [ ] The cards are readable at desktop width, at 900px and below, and at 600px and below, including for amounts of ₹1 crore
- [ ] Logged-out visitors to `/profile` are still redirected to `/login`
- [ ] All tests pass, with only the listed edits to existing tests
