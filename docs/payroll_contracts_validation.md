# Payroll contracts validation

Date: 2026-10-29. Branch: `feat/payroll-contracts`, based on
`7371730` (`feat/payroll-reports-delivery`). Build 9 is in progress.

## Implemented in this checkpoint

Migration 0067 adds tenant-scoped contract, salary-agreement, position-history
and TÖR CSV staging tables. Migration 0068 adds frozen contract base lines to
pay-run items. Migration 0067 backfills one contract and one salary agreement
for each existing employee. Monthly and hourly employees become employment
contracts, board fees become board-member contracts, and income-line employees
become services contracts. The old employee records are retained unchanged.

`PayrollContractService` lists and creates contracts, positions and dated salary
agreements. The API exposes list/create contract and add agreement endpoints
with organisation membership, payroll write-role and CSRF checks. Agreement
history remains dated and supports all requested base-pay types. TÖR CSV upload
stages UTF-8 files for review, normalises the supported English and Estonian
headers, records parse assumptions and row errors, and uses a content hash to
avoid duplicate staging. No live e-MTA query or network call is used.

The run model now selects each active contract's salary agreements effective during the
period and prorates monthly rates across the working days from `payroll_calendar`.
For an agreement change during a month, each agreement segment receives its
share of the period's working days. Contracts are frozen as base lines within
the employee's pay-run item, preserving the one-item-per-employee constraint.
Employment, board-member, services and other contracts use TSD payment codes 10,
21, 17 and 16 respectively. Aggregate payroll taxes remain on the employee run
item and are allocated to those frozen lines when the run is approved.
Employees without contract records continue to use the legacy salary fields.

On approval, a positive monthly net advance on an active contract creates a
draft advance payout dated the 15th of the earning month, capped at the
employee's calculated net. Only a paid advance reduces the salary payout amount.
Advances do not change gross pay or payroll taxes. Existing employees with a
single backfilled contract retain the same payroll amounts as the legacy
employee-level calculation.

## Validation commands and outcomes

Every pytest command used the requested PowerShell `Start-Job` wrapper with
`-q -p no:cacheprovider -x` and a 300-second job timeout.

| File | Result |
|---|---:|
| `tests/test_workspace_payroll.py` | 17 passed |
| `tests/test_payroll.py` | 16 passed |
| `tests/test_payroll_demo_fixes.py` | 24 passed |
| `tests/test_payroll_part_time_hourly.py` | 30 passed |
| `tests/test_payroll_payouts.py` | 7 passed |
| `tests/test_tsd_export.py` | 14 passed |
| `tests/test_payroll_contracts.py` | 8 passed |
| `tests/test_payroll_tor_import.py` | 2 passed |
| `tests/test_migrations_and_tenancy.py` | 19 passed |

The nine requested files passed, 137 tests total.

No full test suite or network test was run. The separate worktree full test run
was left alone. `demo-guide.html` and `docs/website_review_2026-10-09.md` were
not changed.

The workspace editor failure was reproduced at detached baseline `7371730`, so
it predates Build 9. The save payload included `palk_row` from a nonexistent
form field and sent `palk_designation` as a string; the API rejected the
payload. The editor now omits the invalid field and converts the selected
designation to an integer. The workspace file passes after the fix.

## Remaining Build 9 work

- Map reviewed Merit Palk contract and salary data into the history tables.
- Add TÖR import apply/review actions, including tenant-local personal-code
  matching, employee/contract upsert, per-row failure reporting and retry-safe
  application.
- Add the employee-card Contracts UI and payroll TÖR entry. Add and verify the
  requested en/et/lv/lt labels, including `Lepingud` and `TÖR import failist`.
- Add TÖR apply/idempotency and employee/payroll UI tests for roles, CSRF and
  the requested en/et/lv/lt labels.
- Add and execute a PostgreSQL migration path check if the available CI or
  optional local PostgreSQL test environment supports it.

No accountant or production e-MTA export layout was supplied. The staged CSV
parser currently assumes UTF-8 and ISO dates; exact export aliases and contract
type translations need validation against a redacted official sample.
