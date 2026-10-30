# Payroll dimensions and bureau validation

Date: 2026-10-29. Branch: `feat/payroll-dimensions-bureau`. Build 10 is
implemented and verified; independent payroll bureau UAT is pending.

## Build decision and progress

Payroll uses a tenant-scoped `payroll_dimensions` register for departments,
position groups, positions and cost centres; projects remain analytical objects.
Migrations 0069 and 0070 store register links and frozen employee dimensions.
Migration 0071 adds department and cost-centre tags to analytical GL entries.
Migration 0072 adds reviewed dimension import batches and rows.

The register service, employee/contract/agreement and component dimension
writes, approval snapshots, dimension cost report API/XLSX output, split payroll
expense postings and reviewed CSV/XLSX imports are implemented. Salary, employer
social tax and employer unemployment insurance expenses use the approved
employee snapshot. Liability postings remain unsplit. Import application is
explicit after row review and scopes every read and write to the organisation.

The bureau overview API and workspace page include only the signed-in user's
active organisations. The summary includes current-month run status and unpaid
net pay, the next rule-based payday, most recent APA export, blocking APA
findings, PALK due date (18th of the following month, adjusted to a working day)
and TSD due date (10th after the payment month, adjusted to a working day).
The owner/administrator matrix lists member roles and invitation states and
opens the existing invitation API workflow. Payroll settings group the current
payday, email, leave, reserve, posting-account and dimension controls. Register
editing, reviewed imports, employee/contract/agreement/component selectors and
the dimension-cost report are wired into the workspace.

No migration was required for this final UI/API step. The explicit migration
catalogues in `tests/test_migrations_and_tenancy.py` and `.github/workflows/ci.yml`
remain at migration 0072.

## Validation commands and outcomes

All commands used the required PowerShell `Start-Job` wrapper with a 600-second timeout, `-q -p no:cacheprovider -x`, and ran individually.

- `tests/test_migrations_and_tenancy.py`: initial run exposed the CI catalogue line-format defect after 11 passed; after correcting the explicit CI list, 20 passed in 170.02s.
- `tests/test_payroll_dimensions.py`: initial run exposed a report-format expectation mismatch after 3 passed; after correcting the expected two-decimal amount, 4 passed in 36.53s.
- `tests/test_payroll.py`: 16 passed in 156.11s with one upstream `asyncio.iscoroutinefunction` deprecation warning.
- After the ledger dimension change, `tests/test_migrations_and_tenancy.py`: 20 passed in 166.88s.
- After the ledger dimension change, `tests/test_payroll_dimensions.py`: 5 passed in 47.74s.
- After the ledger dimension change, `tests/test_payroll.py`: 16 passed in 144.10s with the same upstream deprecation warning.
- `tests/test_payroll_dimension_import.py`: 5 passed in 48.68s, covering CSV/XLSX staging, review, apply/discard, position groups, project tenancy and API roles.
- After migration 0072, `tests/test_migrations_and_tenancy.py`: 20 passed in 172.86s.
- `tests/test_payroll_bureau.py`: 3 passed in 26.74s, covering membership
  filtering across two of three organisations, dimension API role protection
  and administered-company matrix isolation.
- `tests/test_workspace_payroll.py`: 21 passed in 180.43s, then 21 passed in
  173.65s after the component request schema was aligned with the dimension
  fields. One upstream `asyncio.iscoroutinefunction` deprecation warning.
- `tests/test_i18n.py`: 21 passed in 1.40s after adding the complete bureau UI
  labels to all four locales. One upstream deprecation warning.
- `tests/test_migrations_and_tenancy.py`: 20 passed in 162.55s.
- `tests/test_workspace_payroll_bureau.py`: 1 passed in 8.46s, exercising the
  overview, two-company membership matrix and invitation action in Playwright.
- `node --check static/app.js` and `git diff --check` completed successfully.

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
- Migration `0071_payroll_ledger_dimensions` stores tenant-checked department and cost-centre tags alongside analytical GL tags. Payroll salary, social-tax and employer UI expense lines now split by each approved item's frozen department, cost centre and project; liability lines remain untagged and aggregated. Corrections keep the same analytical tags when reversing line direction.
- Migration `0072_payroll_dimension_imports` adds isolated review batches. CSV and XLSX imports cover departments, positions with position groups, cost centres and projects; commits revalidate rows and apply accepted records in the tenant transaction.
- Commit `f6ae210` adds the membership-scoped bureau overview read API and
  cross-tenant test.
- Commit `2de2fec` adds owner/administrator-protected dimension register API
  endpoints without changing the migration catalogue.
- Commit `053dd08` adds bureau overview and membership matrix workspace views,
  localized labels and role-filtered membership data.
- The final Build 10 checkpoint adds settings and register/import dialogs,
  dimension selectors, APA finding and due-date summaries, invitation workflow
  and the browser-level acceptance test.

## Open validation

- Independent Estonian bureau UAT remains necessary for production approval.
- Confirm with the bureau that PALK's 18th-day working-day adjustment is
  acceptable; the existing report service and bureau overview use that rule.
