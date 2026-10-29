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

Every attempted pytest command used the requested PowerShell `Start-Job` wrapper,
a 300-second timeout, and `-q -p no:cacheprovider -x`. The `test_payroll.py`
timeout from the previous session must not be repeated.

- `tests/test_payroll_dimensions.py`: earlier checkpoint had 2 passed. New
  acceptance coverage was added for employee/contract validation and frozen
  report tenant scope. The latest invocation returned no captured pytest output,
  so the new coverage is not counted as passed.
- `tests/test_migrations_and_tenancy.py`: the prior checkpoint had 20 passed
  before migration 0070. Subsequent runs found old-schema compatibility defects
  in employee approval and component edits. Fixes were committed; the latest
  invocation returned no captured output. It needs a surfaced process result
  before it can be counted as passing.
- `tests/test_payroll.py`: timed out in the previous session and must not be run
  again.

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

- Split salary and employer-levy ledger postings by frozen dimensions through
  the analytical-object mechanism, preserve balanced totals, and leave payout
  postings unchanged.
- Verify the dimension cost report and finish period grouping and XLSX output.
- Add reviewed CSV/XLSX imports for departments, positions, cost centres and
  projects.
- Add the bureau overview, read-only organisation membership matrix, and
  grouped payroll settings page with owner/admin protections.
- Complete UI flows and tests for imports, overview tenant isolation, matrix
  access, settings grouping, report output and frozen ledger dimensions.
- Run the requested test files individually, except `tests/test_payroll.py`
  which must remain unrun due to its recorded timeout. Record the exact results.
