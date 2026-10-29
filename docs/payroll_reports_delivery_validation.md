# Payroll reports and delivery validation

## Implemented in this branch

Migration 0065 adds organisation payroll email settings, employee report language,
and tenant-scoped per-run delivery history. Employee language choices are et,
en, lv and lt, defaulting to the organisation language. Selected payslips render
as one password-free PDF per employee. Review packs include the pay-run XLSX and
optionally the payslip PDF. Both delivery flows use the configured Postmark
transport and can be exercised with an injected mock client.

`payroll_reports.py` provides tenant-scoped annual summaries, 6/9/12-month
average-pay reports, monthly PALK rows, yearly month-end headcount/FTE averages,
and pay lists with payout-derived paid status. XLSX downloads are available for
each report. PALK output includes the due date on the 18th of the following
month, and the payroll declarations panel shows that date.

The payroll screen now includes report, settings, selected payslip delivery and
review-pack dialogs. The employee editor has a report-language selector. Labels
were added to the en, et, lv and lt catalogues. Employee selection supports all
employees by default and can be narrowed before sending or downloading a PDF.

## Focused validation

All pytest commands below use the repository's required 300-second PowerShell
job wrapper with `-p no:cacheprovider -x`.

| Command | Result |
|---|---:|
| `tests/test_payroll_reports_delivery.py` | 3 passed |
| `tests/test_payroll.py` | 16 passed, 1 existing deprecation warning |
| `tests/test_workspace_payroll.py` | 17 passed, 1 existing deprecation warning |
| `tests/test_i18n.py` | 19 passed, 1 existing deprecation warning |
| `tests/test_bulk_sending.py` | 27 passed, 1 existing deprecation warning |
| `tests/test_migrations_and_tenancy.py` | 18 passed |

`node --check static/app.js`, `python -m py_compile` for the changed Python
modules, and `git diff --check` passed. Email delivery tests use a local fake
transport. No Postmark requests were made.

## Remaining acceptance work

- PALK designation is non-null and constrained to supported rows by migration
  0063. The report code emits an unmapped-type warning when it encounters an
  unmapped frozen value, but the current schema cannot store that state. Add an
  explicit unmapped designation in a later additive migration and test the
  warning end to end.
- The PALK due date is shown in the payroll declarations panel and report result.
  It is not yet part of a general workspace dashboard deadline feed.
- Add explicit new-route tests for viewer/accountant/owner permissions, CSRF,
  tenant isolation, failed-delivery retry, mixed-language PDF labels and report
  XLSX contents. Existing routes retain their existing role and CSRF guards.
- Confirm Latvian and Lithuanian payslip copy and report definitions with the
  bureau. Unsupported catalogue strings currently fall back to English.
- Department filtering remains deferred as requested.
- Production PostgreSQL and accountant UAT remain external checks.

## Commits

- `5d6b5a1` Add payroll reports delivery schema
- `bfc000c` Add payroll report calculations and workbook export

- `e459031` Build payroll reports and delivery flows
- `9d8678d` Add selected payslip PDF download link
