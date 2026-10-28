# Payroll APA TSD validation

Date: 2026-10-28. Branch: `feat/payroll-tsd-apa`, based on `e7cfb5e`.

## Implemented in this checkpoint

Migrations 0052 and 0053 add tenant-scoped payment-type codes to component
types, frozen component rows and base-pay run items, with preset defaults and
backfills. Migration 0054 adds `pay_item_tsd_lines`. At approval, pay-run items
and absence-pay calculations freeze one line per payment type. Salary and bonus
amounts with code 10 are grouped together. The pure allocator preserves the
existing aggregate pay calculation and assigns cent residuals to the largest
record for each levy. A social-tax minimum top-up is placed on an eligible base
salary record. Exemption 610 is allocated to the base salary record first and
then by payment type, capped at each record's taxable amount.

TSD preparation reads the frozen lines. For earlier approved runs it rebuilds
the split read-only from frozen component rows and employee context when those
inputs are complete. Otherwise it retains one base-type record and displays the
warning `Legacy run: per-type split unavailable`. Export rows continue to
include payment type codes; absence-pay lines remain separate and use their
payout date. Older database snapshots without migration 0054 skip persistence
during approval until they are upgraded.

## Verification

The migration list is explicit in both `tests/test_migrations_and_tenancy.py`
and `.github/workflows/ci.yml`. Each requested test file was run individually:

```powershell
.venv\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache --basetemp=.tmp\test-tsd-repeat tests\test_tsd_export.py
# 10 passed
.venv\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache --basetemp=.tmp\test-absence-repeat tests\test_payroll_absence_pay.py
# 10 passed
.venv\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache --basetemp=.tmp\test-payouts tests\test_payroll_payouts.py
# 7 passed
.venv\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache --basetemp=.tmp\test-settlement tests\test_payroll_settlement.py
# 8 passed
.venv\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache --basetemp=.tmp\test-payroll-final2 tests\test_payroll.py
# 16 passed
.venv\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache --basetemp=.tmp\test-demo-fixes tests\test_payroll_demo_fixes.py
# 24 passed
.venv\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache --basetemp=.tmp\test-hourly tests\test_payroll_part_time_hourly.py
# 30 passed
.venv\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache --basetemp=.tmp\test-merit-final2 tests\test_merit_palk.py
# 49 passed
.venv\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache --basetemp=.tmp\test-migrations-repeat tests\test_migrations_and_tenancy.py
# 16 passed
```

Total: 170 passed. No live EMTA or other network calls were made. The full
Merit Palk suite includes the older-schema upgrade test; approval skips new
TSD-line persistence when migration 0054 has not been applied.
The PostgreSQL migration branch has a matching immutability trigger, but no
PostgreSQL server was used for integration testing.

## Remaining validation

- Verify the exact component preset codes with an Estonian accountant. Author,
  parental, non-taxable expense and deduction classifications need confirmation.
- Confirm generated XBRL GL XML and transitional CSV acceptance with EMTA before
  filing. Outputs remain review-only and are not submitted by the application.

## 4a completion

Steps 4 and 5 are implemented. The legacy Annex 1 CSV upload is separate from
the internal review CSV, UTF-8 semicolon-delimited with dot-decimal amounts to
two places, and refuses payment dates after 31 December 2027. Codes 1040 and
1050 are blank because the 2024 guide does not describe 1040 and the employee
snapshot has no A1/E101 country. This file convention needs e-MTA confirmation.
The XLSX accountant workpaper has Payments, By payment type and By recipient
sheets. The on-screen preparation view includes list/group views, payment-month
filter, frozen totals, record count and legacy-run warnings in en/et/lv/lt.

These are implemented and locally tested export formats, not live-verified e-MTA
uploads. Direct submission remains disabled.

The final requested files passed individually: `tests/test_tsd_export.py` (14),
`tests/test_workspace_payroll.py` (17), `tests/test_i18n.py` (16),
`tests/test_payroll.py` (16) and `tests/test_merit_palk.py` (49). Node syntax and
`git diff --check` passed. Python runtime was 3.14.6; no live network or
PostgreSQL tests were used.

Exact preset and legal classifications still require Estonian accountant
confirmation. XML and CSV output remain unverified against e-MTA, and direct
submission remains disabled.

## Scope 4b handoff (2026-10-28)

Vendored the official business example, cancellation example, feedback report XSD and four feedback report examples under `tests/fixtures/emta/`. Provenance and retrieval date are in that directory's README. The developer guide states that each XBRL GL file represents a single transaction (see local extract, sections 1 and 3); the target export must therefore use one file per payout transaction, not one file per organisation and payment month. The XBRL GL schema archive was not downloaded. Full XBRL GL schema validation remains pending.

Scope 4b is not complete. The current `tsd.py` exporter still emits the review-only FastAccounts namespace and does not implement the official APA extension, cancellation, export history, feedback import, offline APA business rules or declaration panel controls. No rule codes are yet claimed as implemented. Next steps: map the vendored sample and local taxonomy field-by-field; add an additive tenant-scoped export/history/result migration and both explicit migration lists; implement service logic and routes; add structural and feedback tests; wire the en/et/lv/lt declaration panel; synchronise `tsd-export.md`, this validation record, roadmap and change log; then run the requested test files individually. Do not mark 4b complete until these pass. No live network calls were made.
