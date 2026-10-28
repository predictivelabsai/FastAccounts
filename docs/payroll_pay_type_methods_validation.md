# Payroll pay-type methods validation

## Scope and status

Build 6 adds calculation method/default metadata to component types, frozen
quantity/rate/coefficient/percentage inputs, net targets for gross-up lines,
and Statistics Estonia PALK row snapshots. Existing types and lines default to
`fixed_sum`, preserving their stored amounts and historic calculation behaviour.
The run editor previews calculations; the service recalculates them before save.

## Individual acceptance commands

| Command | Result |
|---|---:|
| `python -m pytest -q tests/test_payroll.py` | 16 passed |
| `python -m pytest -q tests/test_payroll_demo_fixes.py` | 24 passed |
| `python -m pytest -q tests/test_payroll_part_time_hourly.py` | 30 passed |
| `python -m pytest -q tests/test_payroll_pay_type_methods.py` | 26 passed |
| `python -m pytest -q tests/test_tsd_export.py` | 14 passed |
| `python -m pytest -q tests/test_workspace_payroll.py` | 17 passed |
| `python -m pytest -q tests/test_i18n.py` | 18 passed |
| `python -m pytest -q tests/test_migrations_and_tenancy.py -x` | 18 passed |

Additional checks: `python -m pytest -q tests/test_payroll_rules.py` (3 passed),
`python -m compileall -q payroll.py payroll_components.py payroll_rules.py api_app.py`,
and `node --check static/app.js` passed. The requested pytest files ran one at a
time. Browser checks were capped at two minutes per invocation.

## Follow-up review

- Confirm care-leave and child-leave TSD types and PALK rows against the bureau's
  vendored Merit payment-type extract and the PALK form version in use.
- Confirm private-car eligibility, mileage records, EUR 0.30/km and EUR 335 per
  month limits, and the treatment of any excess with the accountant. The limits
  are parameters in `payroll_rules.py`; the preset does not split taxable and
  exempt amounts. See the [Income Tax Act](https://www.riigiteataja.ee/en/akt/515052024003) and [EMTA guidance](https://www.emta.ee/en/node/168/main_chapter/11656/pdf).
- Gross-up tests cover exact cent results with 0%, 2%, 4% and 6% pension and with
  or without exemption. Accountant UAT remains needed for shared exemptions and
  any rate changes beyond the configured 2026 rules.
- Production UAT and PostgreSQL runtime validation remain external checks.
