# Fixed assets and automatic depreciation

## Goal

Record bank-paid fixed assets for UK and Estonian organisations, depreciate them
on a reproducible calendar schedule, dispose of them through balanced ledger
entries, and expose a register and schedule through the existing API and web UI.

## Files touched

- Add `migrations/sqlite/0018_fixed_assets.sql`, `fixed_assets.py`,
  `fixed_asset_repository.py`, fixed asset accounting and browser tests.
- Extend `organisations.py`, `automation.py`, `.env.sample`,
  `.github/workflows/ci.yml` and existing migration/health expectations.
- Extend `api_app.py`, `web/public.py`, `static/app.js` and all four
  `web/locales` files using existing authentication, dialogs and translation
  patterns.
- Update `docs/product_roadmap.md` and `docs/change_log.md` together.

## Accounting rules

Acquisition debits fixed assets and credits bank. Each asset snapshots its group
percentage, frequency and accounts. Calendar month, quarter or year ends are due
dates, including a full acquisition period. Calculate each charge from the
rounded cumulative straight-line target less posted charges, capped at cost.
Record zero-cent instalments so the schedule advances without an empty batch.
One organisation/period/frequency run posts one batch across eligible assets.
Reruns return the recorded result.

Disposal catches up unpaid scheduled charges through its full disposal period in
the disposal batch. Debit accumulated depreciation and bank proceeds, credit
original cost, and post an explicit gain/loss when required. No later depreciation
is posted. Use Decimal throughout, immutable entries, tenant-scoped repository
queries and foreign keys, and one transaction for each event and ledger batch.

## Acceptance checks

- Migration applies to empty and existing databases without altering chart or
  ledger rows; code collisions and existing roles are preserved.
- `db.migrate()` matches the inline CI list exactly; rerun applies nothing.
- pytest verifies acquisition, depreciation and disposal balance, stable retries,
  final top-up, percentage caps, calendar frequency boundaries and leap February,
  tenant isolation, locked periods, rollback and worker failure isolation.
- Authorised API and mounted-web routes expose register, schedule, groups, runs,
  acquisition and disposal; exact money uses decimal strings.
- Browser checks exercise group creation, acquisition, depreciation and disposal
  dialogs in all four locales with synthetic data and intercepted requests.
- Run the full pytest suite and fix regressions before marking delivery complete.
- Append-only translation changes and the synchronised roadmap/change log pass
  diff checks. No secrets, live provider requests or real accounting data are used.

## Out of scope

Inventory, orders, manufacturing, CRM and HR remain outside FastAccounts.
Accountant UAT, acquisition reversal, VAT/foreign-currency acquisition treatment,
residual values, revaluation, impairment, tax-specific schedules, asset transfers
and dedicated disposal gain/loss roles are follow-ups. The existing automation
worker gate remains default off. No push to main or master is authorised.
