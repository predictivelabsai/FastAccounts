# Payroll tax settings validation

Date: 2026-10-28. Branch: `feat/payroll-tax-settings`, based on `c8a5d2c`.

## Runtime and scope

The existing `.venv` runs Python 3.14. A separate ignored `.tmp/venv312` runs
Python 3.12.14 with repository requirements and Playwright 1.63.0, matching the
already installed Chromium. Package installation was separate from pytest.
Provider tests use fakes and browser tests intercept all requests locally.
No live provider, e-MTA or PostgreSQL integration test was run. The whole suite
was not run. Other feature tests changed only to extend migration expectations.

The first test commands used pytest's default temporary directory. Later
commands explicitly locate test data under the repository's ignored `.tmp`.
The two protected untracked files were neither edited nor staged. No push ran.

## Exact pytest commands and outcomes

Commands ran from the repository root in PowerShell. Counts below include initial
failures and their subsequent corrections, rather than omitting failed attempts.

1. `.venv\Scripts\python.exe -m pytest tests/test_tsd_export.py -q`

   Result: 6 passed

2. `.venv\Scripts\python.exe -m pytest tests/test_payroll_rules.py tests/test_payroll.py tests/test_payroll_part_time_hourly.py -q`

   Result: Initial attempt: 3 collection errors (missing parenthesis); second attempt: 48 passed, 1 failed (session access in year-error handler). Corrected before focused rerun.

3. `.venv\Scripts\python.exe -m pytest tests/test_payroll.py::test_api tests/test_payroll_rules.py -q`

   Result: 4 passed

4. `.venv\Scripts\python.exe -m pytest tests/test_payroll_rules.py tests/test_tsd_export.py -q`

   Result: 9 passed

5. `.venv\Scripts\python.exe -m pytest tests/test_migrations_and_tenancy.py -q -x`

   Result: 1 failed (historical fixture used current-schema services); fixture corrected.

6. `.venv\Scripts\python.exe -m pytest tests/test_migrations_and_tenancy.py -q -x --basetemp=.tmp/test-unit3-migrations`

   Result: 15 passed

7. `.venv\Scripts\python.exe -m pytest tests/test_employee_tax_settings.py -q --basetemp=.tmp/test-unit3-history`

   Result: 13 passed

8. `.venv\Scripts\python.exe -m pytest tests/test_merit_palk.py -q --basetemp=.tmp/test-unit3-merit`

   Result: 45 passed, 4 errors. This process loaded the service before its new error class was added and the API afterwards. Clean reruns pass.

9. `.venv\Scripts\python.exe -m pytest tests/test_payroll.py tests/test_payroll_part_time_hourly.py -q --basetemp=.tmp/test-unit3-payroll`

   Result: 46 passed

10. `.venv\Scripts\python.exe -m pytest tests/test_employee_tax_settings.py -q --basetemp=.tmp/test-unit3-history-final`

   Result: 13 passed

11. `.venv\Scripts\python.exe -m pytest tests/test_employee_tax_settings.py tests/test_migrations_and_tenancy.py -q --basetemp=.tmp/test-unit4-migrations`

   Result: 28 passed

12. `.venv\Scripts\python.exe -m pytest tests/test_employee_details.py -q --basetemp=.tmp/test-unit4-details`

   Result: 8 passed, 1 failed (test used the wrong audit column); corrected to object_id.

13. `.venv\Scripts\python.exe -m pytest tests/test_employee_details.py -q --basetemp=.tmp/test-unit4-details-final`

   Result: 9 passed

14. `.venv\Scripts\python.exe -m pytest tests/test_i18n.py -q --basetemp=.tmp/test-unit5-i18n`

   Result: 14 passed

15. `.venv\Scripts\python.exe -m pytest tests/test_employee_tax_settings_api.py -q --basetemp=.tmp/test-unit5-api`

   Result: 3 passed

16. `.venv\Scripts\python.exe -m pytest tests/test_workspace_employee_tax_settings.py -q --basetemp=.tmp/test-unit5-browser`

   Result: 2 passed, 4 failed (select locator in the new test).

17. `.venv\Scripts\python.exe -m pytest tests/test_merit_palk.py -q --basetemp=.tmp/test-merit-final`

   Result: 49 passed

18. `.venv\Scripts\python.exe -m pytest tests/test_workspace_employee_tax_settings.py -q -x --basetemp=.tmp/test-unit5-browser-debug`

   Result: 1 failed (same select locator); corrected to the combobox accessible name.

19. `.venv\Scripts\python.exe -m pytest tests/test_workspace_payroll.py -q --basetemp=.tmp/test-workspace-final`

   Result: 13 passed

20. `.venv\Scripts\python.exe -m pytest tests/test_workspace_employee_tax_settings.py -q -x --basetemp=.tmp/test-unit5-browser-fixed`

   Result: 6 passed

21. `.venv\Scripts\python.exe -m pytest tests/test_workspace_employee_tax_settings.py -q --basetemp=.tmp/test-unit5-browser-final`

   Result: 6 passed after the mobile table adjustment

22. `.tmp\venv312\Scripts\python.exe -m pytest tests/test_payroll_rules.py tests/test_employee_tax_settings.py tests/test_employee_tax_settings_api.py tests/test_employee_details.py tests/test_migrations_and_tenancy.py -q --basetemp=.tmp/test-final-domain-312`

   Result: 49 passed

23. `.tmp\venv312\Scripts\python.exe -m pytest tests/test_payroll.py tests/test_payroll_part_time_hourly.py -q --basetemp=.tmp/test-final-payroll-312`

   Result: 46 passed

24. `.tmp\venv312\Scripts\python.exe -m pytest tests/test_payroll_demo_fixes.py tests/test_tsd_export.py -q --basetemp=.tmp/test-final-tsd-312`

   Result: 30 passed

25. `.tmp\venv312\Scripts\python.exe -m pytest tests/test_merit_palk.py -q --basetemp=.tmp/test-final-merit-312`

   Result: 49 passed

26. `.tmp\venv312\Scripts\python.exe -m pytest tests/test_workspace_payroll.py tests/test_workspace_employee_tax_settings.py tests/test_i18n.py -q --basetemp=.tmp/test-final-browser-i18n-312`

   Result: 14 passed, 16 failed, 3 skipped: Playwright 1.64.1 expected an absent browser binary. Matched the installed browser with Playwright 1.63.0.

27. `.tmp\venv312\Scripts\python.exe -m pytest tests/test_workspace_payroll.py tests/test_workspace_employee_tax_settings.py tests/test_i18n.py -q --basetemp=.tmp/test-final-browser-i18n-312-fixed`

   Result: 33 passed

28. `.tmp\venv312\Scripts\python.exe -m pytest tests/test_employee_tax_settings.py tests/test_employee_tax_settings_api.py tests/test_payroll_demo_fixes.py::test_settlement_lock_rolls_back_and_concurrent_requests_post_once tests/test_tsd_export.py -q --basetemp=.tmp/test-final-freeze-312`

    Result: 29 passed, after the final approval/election lock changes and the
    additional database tenant-foreign-key test.

## Final coverage and other checks

The passing Python 3.12 runs cover 208 distinct tests. Repeated tests between
commands are not counted twice in that figure. All originally failing cases have
passing reruns; no final targeted failure or skip remains. Browser verification
covers English, Estonian, Latvian and Lithuanian, mobile and desktop, including
viewer read-only access. The Estonian mobile render was visually inspected and
adjusted so history actions fit without horizontal scrolling.

These additional commands also passed:

```powershell
.tmp\venv312\Scripts\python.exe -m compileall -q api_app.py payroll.py payroll_rules.py payroll_tax_settings.py payroll_tax_repository.py employee_details.py tsd.py excel_export.py
.tmp\venv312\Scripts\python.exe -m pytest --collect-only -q tests/test_payroll_rules.py tests/test_employee_tax_settings.py tests/test_employee_tax_settings_api.py tests/test_employee_details.py tests/test_migrations_and_tenancy.py tests/test_payroll.py tests/test_payroll_part_time_hourly.py tests/test_payroll_demo_fixes.py tests/test_tsd_export.py tests/test_merit_palk.py tests/test_workspace_payroll.py tests/test_workspace_employee_tax_settings.py tests/test_i18n.py | Select-Object -Last 1
git diff --check
```

Collection result: 208 tests. Compilation and whitespace validation: pass.
Changed text files were also checked for valid UTF-8. The services-contract
Estonian description in the TSD document was corrected to UTF-8 during review.

## Open questions and deferred verification

- Official e-MTA services-contract payment-code mapping and production accountant
  UAT remain pending. Exports continue to use explicit internal labels.
- Actual payout-date selection is deliberately deferred. Settlement means month
  end in this change. No rates beyond 2026 are configured.
- PostgreSQL migration/trigger substitutions are included but were not executed
  against a live server, in keeping with the offline test scope. A PostgreSQL
  smoke run remains an integration verification step.
- Employee unemployment exclusions leave the employer contribution payable for
  ordinary employees. Legacy employee fields expose stored master values rather
  than projecting histories; the precise compatibility contract is documented
  in `payroll_rules.md`.

## Files changed

The manifest includes implementation, new tests, documentation, locales and the
older tests whose expected migration catalogues/counts required extension.

```text
.github/workflows/ci.yml
api_app.py
database.py
docs/change_log.md
docs/payroll_rules.md
docs/payroll_tax_settings_validation.md
docs/product_roadmap.md
docs/tsd-export.md
employee_details.py
excel_export.py
migrations/sqlite/0037_employee_tax_settings.sql
payroll.py
payroll_rules.py
payroll_tax_repository.py
payroll_tax_settings.py
static/app.css
static/app.js
tests/conftest.py
tests/test_automation.py
tests/test_cash_flow.py
tests/test_contact_groups.py
tests/test_copilot.py
tests/test_document_settings.py
tests/test_employee_details.py
tests/test_employee_tax_settings.py
tests/test_employee_tax_settings_api.py
tests/test_exports_everywhere.py
tests/test_fx_rates.py
tests/test_fx_realised.py
tests/test_fx_revaluation.py
tests/test_master_data_import.py
tests/test_master_data_maintenance.py
tests/test_merit_palk.py
tests/test_mfa.py
tests/test_migrations_and_tenancy.py
tests/test_objects.py
tests/test_payment_links.py
tests/test_payroll.py
tests/test_payroll_part_time_hourly.py
tests/test_payroll_rules.py
tests/test_periodisation.py
tests/test_postgres_optional.py
tests/test_prepayments.py
tests/test_public.py
tests/test_quotes.py
tests/test_tsd_export.py
tests/test_workspace_employee_tax_settings.py
tsd.py
web/locales/en.json
web/locales/et.json
web/locales/lt.json
web/locales/lv.json
```
