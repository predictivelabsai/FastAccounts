# Payroll dimensions and bureau validation

Date: 2026-10-29. Branch: `feat/payroll-dimensions-bureau`, at the current
Build 10 implementation commits.

## Build decision and progress

The existing `objects` table is tenant-scoped, but its object-type check and
ledger dimension schema only cover project, location, person and generic object.
Payroll uses a separate tenant-scoped `payroll_dimensions` register for
`department`, `position_group`, `position` and `cost_centre`, while projects
continue to use the analytical-object register. Migration 0069 adds register
storage and optional references on employees, contracts, salary agreements,
component lines and frozen contract-run records. Migration 0070 adds frozen
employee-level dimensions to payroll run items.

Build 10 remains in progress. The register service, employee/contract/agreement
dimension writes, component-line dimension writes, approval snapshots on payroll
items, and a dimension cost report API/XLSX route have been started. The report
uses frozen payroll item values. Department and cost-centre dimensions are not
yet represented on GL entries, so the analytical posting split is outstanding.

## Validation commands and outcomes

All commands used the required PowerShell `Start-Job` wrapper with a 600-second timeout, `-q -p no:cacheprovider -x`, and ran individually.

- `tests/test_migrations_and_tenancy.py`: initial run exposed the CI catalogue line-format defect after 11 passed; after correcting the explicit CI list, 20 passed in 170.02s.
- `tests/test_payroll_dimensions.py`: initial run exposed a report-format expectation mismatch after 3 passed; after correcting the expected two-decimal amount, 4 passed in 36.53s.
- `tests/test_payroll.py`: 16 passed in 156.11s with one upstream `asyncio.iscoroutinefunction` deprecation warning.

## Completed implementation checkpoints

- Commit `2408204` wires employee, contract and salary-agreement dimensions and
  validates IDs against active, same-organisation register values. Component
  updates accept department, cost-centre and project IDs. The checkpoint's
  dimensions suite passed 3 tests before subsequent additions.
- Commit `0cd13f4` adds migration 0070 for frozen payroll item dimensions and
  updates the explicit migration catalogues in the test and CI files.
- Commit `191d111` keeps approval compatible with schemas older than migration
  0070.
- Commit `6f5ad78` keeps component edits compatible with schemas predating
  migration 0069.
- Commit `63e78a1` adds a dimension cost API, report selector and en/et/lv/lt
  locale labels, plus frozen-value tenant-scope coverage.

## Remaining work

- Split salary and employer levy ledger postings by frozen department, cost centre and project dimensions through the analytical-object mechanism, preserve balanced totals, and leave payout postings unchanged.
- Add reviewed CSV/XLSX imports for departments, positions (with position group), cost centres and projects.
- Add the bureau overview, read-only organisation membership matrix, and grouped payroll settings page with owner/admin protections and required UI/locales.
- Run each touched test file individually with the required timeout wrapper and record exact outcomes.
