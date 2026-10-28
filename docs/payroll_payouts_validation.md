# Payroll calendar and payouts validation

Date: 2026-10-28. Branch: `feat/payroll-payouts`, based on
`feat/payroll-tax-settings` at `39f9ce4`.

## Runtime and scope

Commands ran in PowerShell from the repository root. The final focused test set
passed in `.tmp\venv312` (Python 3.12.14). The default project `.venv` also ran
the same set under Python 3.14.6. No package installation, live network call, PostgreSQL test,
bank submission or e-MTA submission was performed. The full test suite was not
run. No pain.001.001.03 XSD is vendored, so payment-file checks are structural.
The untracked `demo-guide.html` and `docs/website_review_2026-10-09.md` were left
untouched.

## Commits

- `d308d6b` Add Estonian payroll working calendar
- `bae4222` Add dated payroll payday settings
- `e74ebee` Add payroll payout lifecycle
- `5842a3f` Use payment month for payroll tax settlement
- `26ff435` Calculate TSD deadlines from payment dates
- `d8a466f` Generate SEPA files for payroll payouts

## Targeted pytest commands

All commands use the ignored repository `.tmp` directory for pytest data.

1. `.venv\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache --basetemp=.tmp\pytest-temp tests\test_payroll_calendar.py`

   Result: 6 passed.

2. `.venv\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache --basetemp=.tmp\pytest-temp tests\test_payroll_payday.py tests\test_migrations_and_tenancy.py`

   Result: 24 passed at the payday unit checkpoint.

3. `.venv\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache --basetemp=.tmp\pytest-temp tests\test_payroll_payouts.py tests\test_migrations_and_tenancy.py`

   Result: 18 passed at the payout lifecycle checkpoint.

4. `.venv\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache --basetemp=.tmp\pytest-temp tests\test_payroll_settlement.py tests\test_payroll_payouts.py tests\test_payroll_rules.py tests\test_migrations_and_tenancy.py`

   Result: 29 passed at the payment-month aggregation checkpoint.

5. `.venv\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache --basetemp=.tmp\pytest-temp tests\test_payroll_settlement.py tests\test_payroll.py`

   Result: 24 passed, with one existing fastcore deprecation warning.

6. `.venv\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache --basetemp=.tmp\pytest-temp tests\test_payroll_payouts.py tests\test_payroll_payday.py tests\test_migrations_and_tenancy.py tests\test_payment_orders.py`

   Result at the SEPA checkpoint: 43 passed, with one existing fastcore
   deprecation warning. The final payout/migration rerun after adding the
   paid/pending/unpaid summaries is recorded below.

7. `.tmp\venv312\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache312 --basetemp=.tmp\pytest-temp312 tests\test_payroll_calendar.py tests\test_payroll_payday.py tests\test_payroll_payouts.py tests\test_payroll_settlement.py tests\test_payroll.py tests\test_tsd_export.py tests\test_payment_orders.py tests\test_migrations_and_tenancy.py`

   Result: 80 passed in Python 3.12.14. The same focused set with the `.venv`
   Python 3.14.6 also passed 80 tests, with one existing fastcore deprecation
   warning. Both runs include the actual TSD payout-date, payroll summary and
   SEPA structural tests.

## Other checks

- `node --check static/app.js` passed after the payroll UI changes.
- Python JSON parsing of all four `web/locales/*.json` files passed.
- `py_compile` passed for changed application modules; `git diff --check` passed.

## Remaining validation

Accountant UAT, verified payroll data against the migrating bureau's Merit Palk
records, live bank acceptance of pain.001.001.03 and PostgreSQL migration tests
remain outstanding. The test suite covers synthetic records only.
