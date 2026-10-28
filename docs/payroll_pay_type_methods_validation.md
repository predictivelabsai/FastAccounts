# Payroll pay-type methods validation

## Scope and status

Build 6 adds calculation metadata to component types and frozen inputs to payroll
component lines. Existing types and lines default to `fixed_sum`; their amounts
remain unchanged. This document records the acceptance commands and known gaps.

## Commands run

- `python -m pytest -q tests/test_payroll_pay_type_methods.py`: 19 passed.
- `python -m pytest -q tests/test_migrations_and_tenancy.py -x`: 18 passed.
- `python -m compileall -q payroll.py payroll_components.py api_app.py`: passed.

## Remaining validation

Run individually: `tests/test_payroll.py`, `tests/test_payroll_demo_fixes.py`,
`tests/test_payroll_part_time_hourly.py`, `tests/test_tsd_export.py`,
`tests/test_workspace_payroll.py`, `tests/test_i18n.py`. Add integration coverage
for every method through `PayrollService`, approved line freezing, TSD lines,
and unchanged legacy fixtures. Confirm live PostgreSQL migration behaviour and
accountant UAT before treating the preset tax classifications as production
validated. The PALK classification is stored for a later report only.

## Open review points

- Confirm whether care-leave and child-leave preset TSD codes and PALK rows match
the vendored Merit extract and the PALK form version used by the bureau.
- Confirm 2026 private-car eligibility, records, limits and treatment of excess.
- Gross-up uses integer-cent binary search with deterministic lowest-gross
  selection; validate against accountant examples for exemption sharing.
- UI live previews are indicative; server calculations remain authoritative.
