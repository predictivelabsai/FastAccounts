# Payroll contracts validation

Date: 2026-10-29. Branch: `feat/payroll-contracts`, based on
`7371730` (`feat/payroll-reports-delivery`). Build 9 is in progress.

## Implemented in this checkpoint

Migration 0067 adds tenant-scoped contract, salary-agreement, position-history
and TÖR CSV staging tables. It backfills one contract and one salary agreement
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

The current run model is not yet contract-aware. Existing salary fields still
drive payroll calculations. Multiple contracts, effective agreement selection,
working-day proration, per-contract TSD snapshots and recurring net advances
are not connected to run creation or payouts.

## Validation commands and outcomes

Every pytest command used the requested PowerShell `Start-Job` wrapper with
`-q -p no:cacheprovider -x` and a 300-second job timeout.

| File | Result |
|---|---:|
| `tests/test_payroll.py` | 16 passed |
| `tests/test_payroll_demo_fixes.py` | 24 passed |
| `tests/test_payroll_part_time_hourly.py` | 30 passed |
| `tests/test_merit_palk.py` | 49 passed |
| `tests/test_tsd_export.py` | 14 passed |
| `tests/test_payroll_contracts.py` | 3 passed |
| `tests/test_payroll_tor_import.py` | 2 passed |
| `tests/test_i18n.py` | 19 passed |
| `tests/test_migrations_and_tenancy.py` | 19 passed |
| `tests/test_workspace_payroll.py` | failed twice on the first payment-type editor browser assertion (1 failed, stopped by `-x`) |

No full test suite or network test was run. The separate worktree full test run
was left alone. `demo-guide.html` and `docs/website_review_2026-10-09.md` were
not changed.

The workspace failure is in the existing custom payment-type editor flow:
after Save, the expected row is absent. The same failure occurred on the
immediate rerun, before any new contracts UI is reached. It remains unresolved.

## Remaining Build 9 work

- Make employee salary field writes update the effective salary agreement while
  preserving the legacy employee API response.
- Link contracts and agreements to run items. Support multiple contracts per
  employee, select the effective agreement, and prorate mid-month changes by
  payroll working days. Review the run-item uniqueness constraint before
  choosing separate items or multiple base TSD lines.
- Generate contract-type TSD payment codes and per-type lines; create recurring
  net-advance payout proposals and deduct them from the salary run.
- Map reviewed Merit Palk contract and salary data into the history tables.
- Add TÖR import apply/review actions, including tenant-local personal-code
  matching, employee/contract upsert, per-row failure reporting and retry-safe
  application.
- Add the employee-card Contracts UI and payroll TÖR entry. Add and verify the
  requested en/et/lv/lt labels, including `Lepingud` and `TÖR import failist`.
- Add integration tests for run selection and proration, concurrent contracts
  with TSD lines, advances, Merit mapping, TÖR apply/idempotency, UI roles and
  CSRF. Existing salary/run fixtures must remain bit-identical.
- Add and execute a PostgreSQL migration path check if the available CI or
  optional local PostgreSQL test environment supports it.

No accountant or production e-MTA export layout was supplied. The staged CSV
parser currently assumes UTF-8 and ISO dates; exact export aliases and contract
type translations need validation against a redacted official sample.
