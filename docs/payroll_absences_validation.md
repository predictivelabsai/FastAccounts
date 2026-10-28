# Payroll absences validation

Date: 2026-10-28. Branch: `feat/payroll-absences`, based on `de88d0f`.

## Unit 1: Payment-type wage and active metadata

Migration 0042 adds organisation payment-type `is_wage` and `active` flags, and
snapshots wage eligibility on saved component rows. Historical wage flags are
backfilled from the migrated preset metadata while temporarily allowing only
that migration backfill through the existing component immutability guard; the
guard is restored immediately. Existing posting data and custom type settings
are retained. New types default to wage and active. Seeded defaults and inactive
history behaviour are documented in `payroll_rules.md`.

Targeted validation command:

```powershell
.tmp\venv312\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache312 --basetemp=.tmp\test-meta-commit tests\test_migrations_and_tenancy.py::test_component_catalogue_upgrade_preserves_defaults_and_posted_payroll tests\test_payroll_demo_fixes.py::test_full_catalogue_defaults_and_descriptions
```

Result: 2 passed. This covers the migration against an approved historical run,
preset metadata and component catalogue defaults. CI migration catalogue and
migration preservation expectations were updated. PostgreSQL SQL substitution
was added but no PostgreSQL server was used.

## Needs accountant confirmation

- Confirm custom payment-type wage eligibility against contracts and source
  documents during bureau setup. The seeded preset mapping is a default only.
- Confirm the statutory average-pay and absence rules against production
  accountant practice before UAT. Items not yet implemented are recorded here
  as the remaining units are developed.

## Unit 2: Absence register

Migration 0043 adds tenant-scoped absence records, per-type paid-salary settings
and a relation for later frozen payroll snapshots. The service validates dates,
rejects overlaps, calculates inclusive calendar days, excludes public holidays
from annual and extended leave days, and uses `payroll_calendar` for working
days. Collective annual leave validates every employee before inserting any
rows. Writes are audited and require payroll write roles plus CSRF at the API.
The workspace dialog supports month/type filters, add/edit/delete, collective
leave, and the permitted-absence salary setting in en/et/lv/lt. Approved-run
snapshots are not created until the day-based payroll calculation unit.

Commands and results:

```powershell
.tmp\venv312\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache312 --basetemp=.tmp\test-absence-final tests\test_payroll_absences.py tests\test_migrations_and_tenancy.py::test_empty_migration_is_idempotent tests\test_migrations_and_tenancy.py::test_historical_migration_catalogue_does_not_affect_other_databases
# 7 passed
.tmp\venv312\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache312 --basetemp=.tmp\test-absence-browser3 tests\test_workspace_payroll.py::test_payroll_absences_register_can_create_localised_leave
# 4 passed
node --check static\app.js
# passed
```

The application uses portable SQLite/PostgreSQL DDL; no PostgreSQL server was
available for an execution check. No live network calls were made.

## Unit 3: Day-based monthly salary

Migration 0044 adds frozen `worked_days`, `norm_days` and
`absence_working_days` to run items and snapshots the salary-interruption
decision on each run/absence relation. Monthly salary base pay and its run-level
minimum wage threshold use the same worked/norm ratio. Every absence type
interrupts salary except `permitted_absence` when its organisation setting says
salary continues. Hourly gross remains rate multiplied by entered hours. The
run breakdown and PDF payslip show the monthly worked/norm ratio.

Targeted command and result:

```powershell
.tmp\venv312\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache312 --basetemp=.tmp\test-absence-unit3-final tests\test_payroll_absences.py tests\test_payroll_part_time_hourly.py
# 39 passed
.tmp\venv312\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache312 --basetemp=.tmp\test-payroll-day-pdf tests\test_payroll.py::test_workflow_snapshot_balance_pdf_and_delete tests\test_payroll_absences.py::test_monthly_salary_is_prorated_by_frozen_absence_workdays tests\test_payroll_absences.py::test_hourly_pay_is_not_reduced_for_absences_and_approved_freeze_protects_record
# 3 passed
.tmp\venv312\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache312 --basetemp=.tmp\test-parttime-absence tests\test_payroll_absences.py::test_monthly_salary_is_prorated_by_frozen_absence_workdays tests\test_payroll_absences.py::test_part_time_monthly_minimum_and_absence_proration_use_fte tests\test_payroll_absences.py::test_hourly_pay_is_not_reduced_for_absences_and_approved_freeze_protects_record
# 3 passed
.tmp\venv312\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache312 --basetemp=.tmp\test-paid-permitted tests\test_payroll_absences.py::test_paid_permitted_absence_does_not_reduce_monthly_salary
# 1 passed
.tmp\venv312\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache312 --basetemp=.tmp\test-meta-unit3 tests\test_migrations_and_tenancy.py::test_empty_migration_is_idempotent tests\test_migrations_and_tenancy.py::test_component_catalogue_upgrade_preserves_defaults_and_posted_payroll
# 2 passed
```

## Unit 7: Liability calculation core

`payroll_leave_liability.py` calculates entitlement pro rata by calendar day,
supports both requested expiry-date policies and no expiry, consumes available
leave FIFO, and values remaining days with average daily pay plus employer
social tax and unemployment insurance. Four focused tests cover accrual, expiry,
consumption and valuation. Persistent entitlement lots, organisation settings,
employee reports, XLSX output, account mapping and balanced monthly reserve
posting are not implemented.

```powershell
.tmp\venv312\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache312 --basetemp=.tmp\test-liability-core2 tests\test_payroll_leave_liability.py
# 4 passed
```

### Needs accountant confirmation

- Confirm whether entitlement precision is four decimal days and how rounding
  occurs when a leave event consumes a fractional day.
- Confirm the exact inclusive expiry boundary and FIFO ordering across basic,
  extended and opening-balance lots. The pure functions currently treat a lot
  as expired on its expiry date and order by accrual date.

The fixture covers the 21/22 October example (EUR 2,200 becomes EUR 2,100),
minimum-wage ratio, hourly pay unchanged, and approved-run absence protection.
Employee-specific weekly schedules are not represented by this demo; an
accountant must confirm that the standard calendar/FTE assumption is suitable
for the bureau's part-time cases.

## Unit 4: Average-pay engine

`payroll_average.py` is a pure Decimal module. `EE-AVG-2026-v1` selects the six
full calendar months before the event month, includes only approved frozen run
items and reviewed historical earnings in those earning periods, and sums base
monthly/hourly wages with component lines whose frozen `is_wage` is true. The
calendar-day denominator removes public holidays and unpaid absence dates as a
union. Working-day and hourly variants use available payroll-calendar workdays
and recorded worked hours. If no non-zero wage history exists, the breakdown
records a fallback using the current agreed monthly salary projected over six
months, or the current hourly rate over six standard norm-hour totals.

Command and result:

```powershell
.tmp\venv312\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache312 --basetemp=.tmp\test-average-unit4-final2 tests\\test_payroll_average.py
# 6 passed
```

### Needs accountant confirmation

- Confirm the working-day and hourly variants. The hourly version currently
  divides the selected wage total by recorded worked hours; the regulation's
  average-hour method can depend on the agreed daily schedule.
- Confirm the six-month current-salary fallback against the regulation's
  unchanged-salary vacation-pay rule, short-service calculation and first
  pay-date case. These are distinct statutory cases and are not silently
  inferred by this pure engine.
- Confirm that every absence passed to this module has the correct explicit
  `wage_paid` status, including employer-paid sick leave and paid annual leave.
- Confirm the treatment of TLS § 19 unpaid absence, the 2024 sick-leave day
  exclusions and TLS § 37 reduced-pay periods for the applicable event type.

## Unit 5: Absence-pay wiring

`payroll_absence_pay.py` implements Decimal calculations for average,
unchanged-salary, best-of and fixed-sum vacation pay, employer sick benefit,
unused leave compensation and the default payout date. `EE-SICK-2026-v1` uses
days 2–5 at 70%, day 1 unpaid and Tervisekassa from day 6. Migration 0046 adds
tenant-scoped absence-pay snapshots. The absences API can persist a pending
vacation-pay method, amount and reviewable average-pay breakdown. Pending
snapshots can be recalculated; snapshots already marked in a payout or paid
cannot be recalculated.

Unit 5 is complete for the requested demo scope. Migration 0048 adds a nullable
breakdown snapshot to payroll component rows. Draft payroll runs generate an
employer sick benefit for qualifying days 2–5 overlapping the run period, using
the existing income-tax-only preset. They also generate unused annual-leave
compensation when the employment end date is in the run period. The component
stores its calculation basis and average-pay breakdown. Editing a draft
recalculates generated values and permits an accountant-entered override;
approved runs remain immutable. Until leave lots are applied, the termination
balance is current-year entitlement minus annual leave taken in the year plus
the latest reviewed opening unused-day balance effective by termination.
Extended and study leave are not deducted from annual entitlement.

The Absences tab shows the method selector, fixed-amount input, calculation
table and status for annual, extended and study leave. Pending records can be
added to an existing Draft absence-pay batch or a new batch with the default
payout date. The register is read-only for viewer and approver roles. Labels
are present in en, et, lv and lt, including the requested Estonian wording.

Validation commands and results:

```powershell
.tmp\venv312\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache312 --basetemp=.tmp\test-u5-ap-confirm tests\test_payroll_absence_pay.py
# 9 passed
.tmp\venv312\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache312 --basetemp=.tmp\test-u5-as-pass tests\test_payroll_absences.py
# 10 passed
.tmp\venv312\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache312 --basetemp=.tmp\test-u5-pay-final3 tests\test_payroll.py
# 16 passed
.tmp\venv312\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache312 --basetemp=.tmp\test-u5-ws-final6 tests\test_workspace_payroll.py
# 17 passed
.tmp\venv312\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache312 --basetemp=.tmp\test-u5-i18n-final3 tests\test_i18n.py
# 15 passed
.tmp\venv312\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache312 --basetemp=.tmp\test-u5-mig-final2 tests\test_migrations_and_tenancy.py
# 16 passed
node --check static\app.js
# passed
```

No live network calls or PostgreSQL execution were used. The sickness rate and
leave-balance interpretation still require Estonian accountant confirmation
before production use.

Command and result:

```powershell
.tmp\venv312\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache312 --basetemp=.tmp\test-absence-pay-unit5 tests\test_payroll_absence_pay.py
# 4 passed
```

### Needs accountant confirmation

- Confirm `EE-SICK-2026-v1` rate, covered sickness days and interaction with
  sickness-period continuation certificates before production use.
- Confirm the unchanged-salary and best-of amounts for part-time employees and
  the statutory fixed-sum agreement conditions.
- Unit 5b below implements the vacation-pay payout, payment-date tax,
  exemption aggregation, frozen values, GL postings and TSD inclusion. Sick
  benefit and termination unused-leave amounts remain outside this path.
- Unit 5 implementation is complete; see its validation and accountant review
  notes above.
- The absence-pay method selection route has role, tenant and CSRF coverage.
  The payout lifecycle and TSD reporting coverage are recorded in Unit 5b.

## Unit 6: Leave and earnings storage foundation

Migration 0045 adds tenant-scoped effective-dated entitlement rows, reviewed
opening unused-day balances and reviewed historical monthly earnings. Historical
rows have unique source keys for idempotency. The upload adapter, staging review
and apply handlers, entitlement UI/API and reviewed Merit snapshot application
have not yet been implemented, so this unit is incomplete.

```powershell
.tmp\venv312\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache312 --basetemp=.tmp\test-payroll-unit6b tests\test_migrations_and_tenancy.py::test_empty_migration_is_idempotent tests\test_migrations_and_tenancy.py::test_historical_migration_catalogue_does_not_affect_other_databases
# 2 passed
```
## Unit 8: Payslip and dashboard

Payslips show absences frozen into the run, including date range and leave-day
count. The dashboard shows employees with annual or extended leave today and
employees on sick leave today. Labels are translated in en/et/lv/lt. Remaining
leave balance display is not implemented because entitlement and leave-lot
application are not yet connected.

```powershell
node --check static\app.js
.tmp\venv312\Scripts\python.exe -c "import json,pathlib; [json.loads(p.read_text(encoding='utf-8')) for p in pathlib.Path('web/locales').glob('*.json')]"
.tmp\venv312\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache312 --basetemp=.tmp\test-payroll-unit8 tests\test_payroll.py::test_workflow_snapshot_balance_pdf_and_delete tests\test_workspace_payroll.py::test_payroll_absences_register_can_create_localised_leave
# 5 passed; JavaScript syntax and locale JSON checks passed
```

## Unit 9: Regression and delivery record

The final core regression command below passed. Earlier targeted commands
covered the four-language absence register browser flow, payslip PDF rendering,
day-based and hourly payroll, permitted paid absence, and schema migration.

```powershell
.tmp\venv312\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache312 --basetemp=.tmp\test-payroll-absence-final tests\test_payroll_absences.py tests\test_payroll_average.py tests\test_payroll_absence_pay.py tests\test_payroll_leave_liability.py tests\test_migrations_and_tenancy.py::test_empty_migration_is_idempotent tests\test_migrations_and_tenancy.py::test_historical_migration_catalogue_does_not_affect_other_databases
# 25 passed
```

Outstanding requested work before the absence series can be considered
complete: persist and pay generated vacation/sick/termination components through
approved payroll and absence-pay payout batches; implement the reviewed
CSV/XLSX historical import and apply the Merit vacation snapshot; connect leave
entitlement/opening balances to annual accrual and expiry; add liability reports
and optional mapped reserve journals; and display remaining leave balances.
Migration 0045 storage alone does not make the import workflow available.
PostgreSQL execution was not performed. The date-based and statutory parameters
listed above still need Estonian accountant review.

## Unit 5b: Absence-pay payout and tax integration

Migration 0047 adds tenant-scoped absence-pay payout batches with Draft,
Approved, Paid and Cancelled states. Pending vacation-pay records can be added
to a new batch or an existing Draft batch. On addition, the service freezes a
`calculate_pay` result for the payout-date month, using the employee's effective
tax elections and the remaining exemption after approved payroll and other
approved absence payments in that payment month. A payment defaults to the
working day immediately before leave starts. Approval posts the gross expense,
withholdings, employer taxes and net payable in a balanced ledger batch. Paid
posts the net payable to bank. Cancellation releases records back to pending
and reverses posted batches.

TSD workpapers, CSV and XBRL GL exports include each absence payment as its own
payment record for the payout month, with the frozen payout date and employee
details. The salary-run payment-month calculation sees exemption already used
by approved absence payouts. Tests cover an October salary paid on 10 November
and vacation pay paid on 20 November sharing one EUR 700 exemption, balanced
postings, TSD inclusion, cancellation, tenant scoping, roles and CSRF.

Commands and results, Python 3.12.14:

```powershell
.tmp\venv312\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache312 --basetemp=.tmp\test-absence-pay-final6 tests\test_payroll_absence_pay.py
# 7 passed
.tmp\venv312\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache312 --basetemp=.tmp\test-payouts-final tests\test_payroll_payouts.py
# 7 passed
.tmp\venv312\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache312 --basetemp=.tmp\test-settlement-final tests\test_payroll_settlement.py
# 8 passed
.tmp\venv312\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache312 --basetemp=.tmp\test-tsd-final2 tests\test_tsd_export.py
# 7 passed
.tmp\venv312\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache312 --basetemp=.tmp\test-payroll-final2 tests\test_payroll.py
# 16 passed
.tmp\venv312\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache312 --basetemp=.tmp\test-migrations-final2 tests\test_migrations_and_tenancy.py
# 16 passed
```

No live network calls or PostgreSQL execution were performed. Statutory
calculation assumptions remain subject to Estonian accountant confirmation.

## Unit 5b design note (recorded before implementation)

A pending vacation-pay snapshot becomes taxable payroll when it is added to an
`absence_pay` payout batch. Batch creation freezes one payroll calculation per
employee and payment: gross equals the saved vacation-pay amount, and the
calculation period is the payout date month. The calculation uses the employee's
frozen tax settings, including II pillar, unemployment insurance, income tax and
social tax settings. The tax-free exemption is calculated with
`calculate_pay` after subtracting exemption already consumed by frozen payroll
payments for that employee in the same payment month. This makes a later salary
run in the month eligible only for the remaining exemption.

Approval posts the frozen payroll amounts once as a balanced general-ledger
batch, debiting vacation-pay expense (or the configured payroll gross role) and
crediting net payable and the applicable employee and employer tax liabilities.
Marking the payout Paid posts a second balanced batch, debiting net payable and
crediting the selected bank account. The month's TSD workpaper treats each
frozen absence-pay calculation as its own payment record, dated with the payout
date, alongside salary payments. Cancelled batches release their absence-pay
records to pending; any posted accounting entries are reversed with linked
reversal batches. Status and posting changes are tenant-scoped and transactional,
so a snapshot can only enter one live payout and its gross is included once in
payroll tax aggregation and reporting.
