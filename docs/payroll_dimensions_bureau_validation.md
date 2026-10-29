# Payroll dimensions and bureau validation

Date: 2026-10-29. Branch: `feat/payroll-dimensions-bureau`, based on
`feat/payroll-contracts` at `1a9646b`.

## Build decision and progress

The existing `objects` table is tenant-scoped, but its object-type check and
ledger dimension schema only cover project, location, person and generic object.
Payroll uses a separate tenant-scoped `payroll_dimensions` register for
`department`, `position_group`, `position` and `cost_centre`, while projects
continue to use the analytical-object register. Migration 0069 currently adds
register storage and optional dimension references on employee, contract,
salary-agreement, component and frozen contract-run records.

Build 10 is in progress. This migration has not yet been validated, and no
acceptance criteria should be treated as complete.

## Validation commands and outcomes

No pytest command run yet. Per requested procedure, each pytest invocation will
use the PowerShell `Start-Job` wrapper, a 300-second timeout, and
`-q -p no:cacheprovider -x`.

## Remaining work

- Add the payroll-dimension repository/service with kind validation, CRUD,
  relationship checks and tenant isolation.
- Freeze resolved department, cost centre and project values on approved lines;
  split salary and employer-levy ledger postings by dimensions and keep batches
  balanced. Payout postings remain unchanged.
- Add period cost report on screen and XLSX.
- Add reviewed CSV/XLSX dimension import for departments, positions, cost centres
  and projects.
- Add bureau overview, organisation membership matrix, payroll settings page,
  locale strings in en/et/lv/lt, and role/CSRF protections.
- Add focused coverage, update both migration catalogues in
  `tests/test_migrations_and_tenancy.py` and `.github/workflows/ci.yml`, run the
  requested per-file test list, and update roadmap/change log when complete.

Migration checkpoint validation:

- `tests/test_migrations_and_tenancy.py`: 20 passed in 156.49 seconds using
  the required PowerShell wrapper. The first attempt exposed a SQLite lock in
  the new test because it created a second organisation inside an open write
  transaction; organisation creation was moved before that transaction.
- Migration 0069 is included in the explicit expected migration list in both
  `tests/test_migrations_and_tenancy.py` and `.github/workflows/ci.yml`.

The tenant-scoped payroll dimension service now supports listing, create/update,
deactivation, active filtering, code uniqueness, and position-to-group validation.
`tests/test_payroll_dimensions.py` passed (2 tests) using the required wrapper.
This checkpoint does not yet wire employee/contracts into the service or add
approval freezing and the remaining Build 10 features.
