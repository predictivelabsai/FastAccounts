# Payroll reports and delivery validation

## Implemented in this branch

Migrations 0065-0066 add organisation payroll email settings, employee report
language, tenant-scoped per-run delivery history and nullable PALK designations
for component types and frozen payroll lines. Employee language choices are et,
en, lv and lt, defaulting to the organisation language. Selected payslips render
as one password-free PDF per employee. Review packs include the pay-run XLSX and
optionally the payslip PDF. Both delivery flows use the configured Postmark
transport and can be exercised with an injected mock client.

`payroll_reports.py` provides tenant-scoped annual summaries, 6/9/12-month
average-pay reports, monthly PALK rows, yearly month-end headcount/FTE averages,
and pay lists with payout-derived paid status. XLSX downloads are available for
each report. Unmapped PALK component names and amounts appear as a warning and
are excluded from designated rows.

PALK output includes the due date on the 18th of the following month, moved to
the next working day when it falls on an Estonian weekend or public holiday. The
payroll declarations panel shows that date. The rule is based on the [Statistics
Estonia Palk ja tööjõud monthly reporting calendar](https://www.stat.ee/et/kusimustikud/palk-ja-toojoud-2026-kuu),
which lists monthly dates on the 18th. Confirm the working-day adjustment with
the bureau because that calendar also lists dates which fall on weekends.

The payroll screen includes report, settings, selected payslip delivery and
review-pack dialogs. The employee editor has a report-language selector. Labels
are available in en, et, lv and lt. Employee selection supports all employees
by default and can be narrowed before sending or downloading a PDF.

## Focused validation

All pytest commands use the repository's required 300-second PowerShell job
wrapper with `-p no:cacheprovider -x`. Each file was run individually.

| Command | Result |
|---|---:|
| `tests/test_payroll_reports_delivery.py` | 4 passed, 1 existing deprecation warning |
| `tests/test_payroll.py` | 16 passed, 1 existing deprecation warning |
| `tests/test_workspace_payroll.py` | 17 passed, 1 existing deprecation warning |
| `tests/test_i18n.py` | 19 passed, 1 existing deprecation warning |
| `tests/test_migrations_and_tenancy.py` | 18 passed |
| `tests/test_bulk_sending.py` | 27 passed, 1 existing deprecation warning |
| `tests/test_document_settings.py` | 42 passed, 1 existing deprecation warning |
| `tests/test_fx_rates.py` | 57 passed, 1 existing deprecation warning |
| `tests/test_mfa.py` | 52 passed, 2 existing warnings |
| `tests/test_reminder_rules.py` | 55 passed, 1 existing deprecation warning |

The route checks cover viewer/accountant/administrator/owner permissions, CSRF
on all writes, cross-organisation run and employee identifiers, and a mocked
failed delivery followed by a successful retry. Email delivery tests use a
local fake transport. No Postmark requests were made. A separate worktree is
running the full test suite and was not inspected.

## Follow-ups

- The general overview has payroll KPIs and an overdue declaration count, but no
general deadline feed. Add the PALK due date there as a dashboard follow-up.
- Confirm Latvian and Lithuanian payslip copy and report definitions with the
bureau. Unsupported catalogue strings currently fall back to English.
- Confirm the weekend and public-holiday due-date adjustment with the bureau.
- Production PostgreSQL and accountant UAT remain external checks.
- Department filtering remains deferred as requested.

## Commits

- `5d6b5a1` Add payroll reports delivery schema
- `bfc000c` Add payroll report calculations and workbook export
- `e459031` Build payroll reports and delivery flows
- `9d8678d` Add selected payslip PDF download link
- `10e9fbd` Support unmapped payroll PALK designations
- `0065b6c` Cover payroll report delivery API routes
