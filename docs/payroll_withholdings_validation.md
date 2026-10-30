# Payroll withholdings validation

Date: 2026-10-28. Branch: `feat/payroll-withholdings`, based on
`feat/payroll-pay-type-methods` at `f4ae2dc`.

## Implemented checkpoint

- Migration `0064_payroll_withholdings` adds tenant-keyed recipient, agreement,
  draft-line and payout-line tables. The expected migration list in
  `tests/test_migrations_and_tenancy.py` and CI is updated.
- Recipient and agreement services validate and normalise IBANs, enforce
  organisation-scoped employee/recipient lookups, support archive and audit
  writes, and provide a period summary query.
- Decimal helpers cover fixed sums, gross percentages, quantity times rate,
  third-pillar contributions, net availability, a total cap and a supplied
  garnishable limit.
- Read and CSRF-protected recipient/agreement CRUD plus an on-screen JSON report
  endpoint are registered in the public API.

## Commands and results

- `.venv\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache --basetemp=.tmp\pytest-temp tests\test_migrations_and_tenancy.py` — 18 passed.
- `.venv\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache --basetemp=.tmp\pytest-temp tests\test_payroll_withholdings.py` — 7 passed.
- `tests\test_payroll.py` — 16 passed, one existing fastcore deprecation warning.
- `tests\test_payroll_payouts.py` — 7 passed, one existing fastcore deprecation warning.
- `tests\test_tsd_export.py` — 14 passed.
- `tests\test_workspace_payroll.py` — 17 passed, one existing fastcore deprecation warning.
- `tests\test_i18n.py` — 18 passed, one existing fastcore deprecation warning.
- `py_compile api_app.py payroll_withholdings.py` and `git diff --check` passed.

All pytest files ran separately using the ignored `.tmp` cache and basetemp.
No new locale keys or workspace flows are included yet, so the passing locale
and workspace suites do not validate the requested withholding UI.

Commits: `01938f2` Add payroll withholding schema; `b52b850` Add withholding
recipient and agreement services.

## Remaining work before the feature is complete

- Add recipient payouts and SEPA pain.001 integration, including liability-to-bank
  posting and recipient aggregation.
- Add reports, payroll workspace preview and payout actions, plus en/et/lv/lt
  labels.
- Confirm garnishment handling for order-specific exceptions, dependants,
  partial months and multiple orders with an accountant. The 2026 estimate uses
  the minimum monthly wage as the ordinary protected amount and uses half that
  amount as the protected portion for qualifying child-maintenance cases under
  Code of Enforcement Procedure §132(1¹). Both estimates are marked for
  accountant confirmation. [Riigi Teataja, English translation](https://www.riigiteataja.ee/en/akt/523012025002).
- Confirm third-pillar tax treatment with an accountant before implementing TSD
  type 25 or exemption 640. The current feature records this only as a net
  withholding and does not change TSD lines.
- Add API role-check and CSRF coverage, report and payout tests, and rerun the
  migration/tenancy suite after schema changes.

## Integration checkpoint (2026-10-29)

- Draft payroll runs create active agreement withholding lines using the
  agreement method, remaining cap and available net. Recalculation regenerates
  agreement lines while retaining manually entered payroll components and
  withholding lines.
- Bailiff and child-maintenance lines use year-configured §132 garnishable
  estimates, are reduced when required and expose an item warning. Order-specific
  legal exceptions remain pending accountant confirmation.
- Third-pillar entries remain net withholdings and show the pending TSD type 25 /
  exemption 640 note. TSD calculation lines are unchanged.
- Approval updates agreement withheld-to-date and closes capped agreements in
  the approval transaction. Withholdings post to the existing liability roles.
- Added offline integration tests for methods, limits, warnings, recalculation,
  approval and tenant isolation. Individually run: `test_payroll_withholding_integration.py`
  (6 passed), `test_payroll_withholdings.py` (7 passed), `test_payroll.py`
  (16 passed, 1 existing deprecation warning), `test_payroll_demo_fixes.py`
  (24 passed) and `test_payroll_absence_pay.py` (10 passed, 1 existing
  deprecation warning).
- No migration was needed: the run-line schema already carries the generated
  flag, agreement link, amount and description used by this integration.

## Build 7 completion (2026-10-29)

- Added recipient and agreement CRUD in the payroll workspace, including
  withheld-to-date and cap values, period reports and Excel exports.
- Draft pay-run rows show generated withholding lines and reduced-to-limit
  warnings. The payout dialog can create a recipient payout, mark it paid,
  cancel it and download SEPA pain.001 files.
- Added en/et/lv/lt labels and browser coverage for the Withholdings tab. The
  browser request mock now preserves query strings, which the period report
  endpoints require. Dialog loading feedback appears while report data loads.
- Pay-run reads tolerate pre-0064 databases that do not yet have the new run
  lines table; this preserves historical migration backfill test coverage.
- Requested focused suites passed individually: workspace payroll (17), i18n
  (19), withholding methods (7), withholding integration (6), withholding
  payouts (5), withholding reports (2), salary payouts (7), and migrations and
  tenancy (18). One existing fastcore deprecation warning appeared in the
  workspace, i18n and payout suites.

Build 7 implementation is complete. Accountant confirmation remains for
order-specific garnishment exceptions, dependants and partial months; the 2026
protected-income estimates; and third-pillar TSD treatment. Third-pillar entries
remain net withholdings and do not change TSD lines pending that confirmation.
No live network or production accounting data was used. PostgreSQL migration
execution remains unverified in this environment.
