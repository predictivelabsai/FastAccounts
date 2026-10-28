# Payroll APA TSD validation

Date: 2026-10-28. Branch: `feat/payroll-tsd-apa`, based on `200c715`.

## Implemented in this checkpoint

Migrations 0052 and 0053 add tenant-scoped payment-type codes to component
types, frozen component rows and base-pay run items, with preset defaults and
backfills. Prepared records expose the base-pay code, and the editor accepts a
component code with an Estonian label. `payroll_tsd_types.py` contains a small
resident-person matrix extract and pure lookup function.

## Verification run

```powershell
.venv\Scripts\python.exe -m pytest -x -q -o cache_dir=.tmp\pytest-cache --basetemp=.tmp\test-tsd-debug2 tests\test_migrations_and_tenancy.py::test_component_catalogue_upgrade_preserves_defaults_and_posted-payroll tests\test_tsd_export.py
# 8 passed
```

The first test run found an undefined schema-capability flag in the draft item
writer; this was fixed before the passing run. The full migration suite started
but did not finish inside the short command window. No network calls or
PostgreSQL execution were performed.

## Remaining work in scope 4a

- Snapshot official payment types on base salary and board fee, and split each
  recipient's frozen run and absence-pay calculation into records per payment
  type and payment date.
- Allocate social tax, monthly-minimum top-up, UI, II pillar, shared tax-free
  amount and income tax across those records with deterministic cent residuals,
  then reconcile all record totals to the frozen payroll calculation.
- Replace the transitional review CSV with the Annex 1 legacy upload shape
  documented by the 2024 guide, including its documented-code header assumption.
- Add the APA TSD recipient/type workpaper views and XLSX export, validation
  messages, full mixed-payment/reconciliation tests and role/CSRF tests.
- Verify the exact component preset codes with an Estonian accountant. Author,
  parental, non-taxable expense and deduction classifications need confirmation.
- Confirm generated APA XML and legacy CSV acceptance with EMTA before filing.

The current exporter still has its prior one-record-per-pay-run-item calculation
logic. Therefore this checkpoint does not fulfil the full 4a acceptance scope.
