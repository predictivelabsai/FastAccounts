# Payroll contracts validation

Date: 2026-10-29. Branch: `feat/payroll-contracts`, started at `3b815c3`.
Build 9 implementation is complete. External validation remains for a redacted
official e-MTA TÖR sample.

## Implemented in this checkpoint

Migration 0067 adds tenant-scoped contract, salary-agreement, position-history
and TÖR CSV staging tables. Migration 0068 adds frozen contract base lines to
pay-run items. Migration 0067 backfills one contract and one salary agreement
for each existing employee. Monthly and hourly employees become employment
contracts, board fees become board-member contracts, and income-line employees
become services contracts. The old employee records are retained unchanged.

`PayrollContractService` lists, creates and updates contracts, positions and
dated salary agreements. The employee card exposes contract terms, salary and
position history, payday override, monthly advance and future-dated agreement
entry. Contract and position APIs enforce organisation membership, payroll
write roles and CSRF checks. All new workspace copy is available in en, et, lv
and lt, including the requested Estonian labels.

TÖR CSV upload stages UTF-8 files for review, normalises supported English and
Estonian headers, records assumptions and row errors, and uses a content hash to
avoid duplicate staging. Reviewed rows match employees by personal code within
the organisation, create employees when no match exists, and create or update
contract and position history without deleting existing records. Duplicate
personal codes remain visible as conflicts. Application is retry-safe, and new
employees without a salary agreement are excluded from regular payroll until a
dated agreement is added. Upload, review and apply actions have role and CSRF
checks. No live e-MTA query or network call is used.

Reviewed Merit Palk employee and salary-agreement pulls create or update
contracts and dated monthly salary agreements. Existing employee salary fields
are not overwritten. New employee records receive an initial legacy fallback;
later Merit agreement changes update dated contract history. Existing external
employee mappings and provider source identities are retained, and repeated
pulls do not duplicate contracts or agreement dates.

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
| `tests/test_merit_palk.py` | Full file reached 300-second timeout. 32 cases passed before the earlier services-contract regression; that case passed separately after the fix, and 16 later cases passed in a filtered run. |
| `tests/test_workspace_payroll.py` | 21 passed |
| `tests/test_payroll_contracts.py` | 9 passed |
| `tests/test_payroll_tor_import.py` | 6 passed |
| `tests/test_i18n.py` | 20 passed |
| `tests/test_payroll.py` | 16 passed |
| `tests/test_migrations_and_tenancy.py` | 19 passed |

The six non-Merit requested files passed, 91 tests total. Merit Palk coverage
passed across the timed run and two focused continuation runs, 49 cases in total.
The complete Merit Palk file did not finish inside the required per-file limit.

No full test suite or network test was run. The separate worktree full test run
was left alone. `demo-guide.html` and `docs/website_review_2026-10-09.md` were
not changed.

The workspace editor failure was reproduced at detached baseline `7371730`, so
it predates Build 9. The save payload included `palk_row` from a nonexistent
form field and sent `palk_designation` as a string; the API rejected the
payload. The editor now omits the invalid field and converts the selected
designation to an integer. The workspace file passes after the fix.

## Remaining external validation

No redacted official TÖR export was supplied. The staged CSV parser currently
assumes UTF-8 and ISO dates. Confirm header aliases and contract type values
against an official sample before production use. The focused migration suite
passed against the local SQLite migration catalogue. No PostgreSQL service or
live provider connection was used.
