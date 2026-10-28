# Payroll APA TSD validation

Date: 2026-10-28. Branch: `feat/payroll-tsd-apa`, based on `0be4197`.

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
.venv\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache --basetemp=.tmp\test-payroll tests\test_payroll.py
# 16 passed
.venv\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache --basetemp=.tmp\test-demo-fixes tests\test_payroll_demo_fixes.py
# 24 passed
.venv\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache --basetemp=.tmp\test-hourly tests\test_payroll_part_time_hourly.py
# 30 passed
.venv\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache --basetemp=.tmp\test-merit-final tests\test_merit_palk.py
# 49 passed
.venv\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache --basetemp=.tmp\test-migrations-repeat tests\test_migrations_and_tenancy.py
# 16 passed
```

Total: 170 passed. No live EMTA or other network calls were made. The full
Merit Palk suite includes the older-schema upgrade test; approval skips new
TSD-line persistence when migration 0054 has not been applied.

## Remaining validation

- Verify the exact component preset codes with an Estonian accountant. Author,
  parental, non-taxable expense and deduction classifications need confirmation.
- Confirm generated XBRL GL XML and transitional CSV acceptance with EMTA before
  filing. Outputs remain review-only and are not submitted by the application.

Exact preset and legal classifications still require Estonian accountant
confirmation. XML and CSV output remain unverified against e-MTA, and direct
submission remains disabled.
