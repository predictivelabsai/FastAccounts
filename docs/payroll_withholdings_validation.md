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

- Connect agreements to draft-run generation, preserve manual deductions, and
  freeze generated lines and warnings in the run. Apply the year-parameterised
  protected-wage calculation only after an accountant confirms how order-specific
  exceptions and partial months should be represented.
- Implement the annual third-pillar allowance and EMTA TSD payment type 25 with
  exemption type 640. EMTA's TSD handbook describes an employer contribution as
  a separate type 25 payment and tracks exemption type 640 cumulatively; this is
  not the same as ordinary employee income tax exemption 610. See the
  [EMTA TSD handbook](https://emta.ee/node/330/handbook/20/pdf). The limits are
  15% of qualifying annual taxable payments and EUR 6,000, pending accountant
  confirmation of the qualifying base and excess treatment.
- Add a withholding payout lifecycle after salary payment, recipient
  aggregation, pain.001 integration, balanced liability-to-bank posting and
  approval-time cap updates.
- Add an XLSX report, payroll workspace tab and preview/payout actions; add the
  requested en/et/lv/lt labels.
- Add API tests for role checks and CSRF, report and payout tests, generated vs
  manual line preservation, and run the remaining requested files individually:
  `test_payroll.py`, `test_payroll_payouts.py`, `test_tsd_export.py`,
  `test_workspace_payroll.py`, `test_i18n.py` and final migration/tenancy rerun.
- Add a year-versioned garnishment rule and accountant-confirmed warnings.
  Relevant law is Code of Enforcement Procedure §132, including the protected
  minimum-wage amount and distinct periodic child-maintenance exceptions:
  [Riigi Teataja, English translation](https://www.riigiteataja.ee/en/akt/523012025002).

No full test run, live network operation or PostgreSQL migration run was done.
The full suite running in the separate worktree was not inspected or changed.
