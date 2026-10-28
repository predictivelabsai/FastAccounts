# Payroll corrections validation

Date: 2026-10-28. Branch: `feat/payroll-corrections`, based on `15be8ce`.

## Design decision

Approved regular payroll remains immutable. A correction is a separate pay run
linked to one approved original run. It starts as a copy of the original frozen
items and components, with editable draft values. Approval compares the correction
snapshot with the original plus all earlier approved corrections for each
employee and component, and posts only the net delta. The correction ledger batch
uses the correction run as its voucher and links its source lines to the original
run. A zero-valued correction item is permitted for a full reversal. Neither the
original nor prior corrections are rewritten.

A supplementary run is an independent run linked to a regular run and carries
its own items. It is intended for separately earned amounts such as a bonus, not
a repeated base salary. It is included in the existing employee/payment-month
exemption aggregation. Its approval posts its own full payroll batch.

## Run uniqueness and payment dates

The unique organisation/month rule remains for `kind='regular'`. Additive
migration replaces the old index with a partial unique index for regular runs;
correction and supplementary runs may coexist for the same period and retain
`original_run_id` for navigation and tenant-safe lineage. A correction's payment
date is selected on its own payout and determines tax/payment month. A correction
paid in a later month is taxed in that later payment month. Before declaration,
a correction with the original payment month supersedes the corrected payment
for that month; the original snapshot remains immutable and the correction ledger
records only the delta. Tax-free exemption is recalculated using the payment-month
aggregation and any earlier approved payroll payments.

## Payouts, receivables and TSD

A positive net correction delta creates an additional payout. A negative net
delta is recorded as an employee receivable and may be offset against a future
positive payout with an explicit, accountant-visible allocation. It must never
create a negative bank payment. Zero net delta creates no payout.

TSD lines are frozen per approved run/payment. Corrections create new frozen TSD
line versions for the affected payment. The APA developer guide, section 4,
defines operation `M` as a complete replacement for the existing transaction;
operation `T` cancels a transaction by referring to its existing line number
without repeating its details. A cancelled line number is final and cannot be
reused. If another replacement is subsequently needed, it receives a new line
number and operation `R`. The APA history therefore retains all immutable
versions and cancellation events. Before declaration, the affected original
payout transaction is replaced with `M`; where the correction is represented as
a distinct payout transaction, it is emitted as `R` and any superseded
transaction is cancelled with `T` as required by the APA transaction model.
Export history is tenant-scoped and preserves prior XML, hashes and actor data.

## API and user interface

Approved run detail exposes `Create correction` and `Add supplementary run`.
Correction detail shows original, corrected and delta values per employee,
provides draft edits and approval, and links both directions between runs. All
endpoints remain organisation-scoped and use existing role and CSRF protections.
The UI strings are translated in English, Estonian, Latvian and Lithuanian.
Estonian labels include `Parandus`, `Täiendav palgaleht`, `Algne`,
`Parandatud` and `Vahe`.

## Acceptance and validation

Targeted tests cover increasing and decreasing salary corrections, negative
receivable handling, full reversal, successive corrections, supplementary runs
sharing exemption, balanced delta GL batches, APA replacement and cancellation
history, original immutability, tenant and role isolation, and CSRF. Run the
requested pytest files individually with local fixtures only. Add each numbered
migration to both the explicit catalogue in `tests/test_migrations_and_tenancy.py`
and `.github/workflows/ci.yml`; other tests derive from the migration catalogue.
Update payroll, TSD and payout documentation, the roadmap and change log. Record
commands, counts, commits and unresolved acceptance items here.

## 2026-10-28 implementation checkpoint

- Design and migration commits: `7afc5fe`, `170ac1b`.
- Service/API commit: `7788af3` adds tenant-safe correction cloning, one-draft
  validation, support for correction zero values, and compatibility with the
  partial regular-period unique index.
- Approval/API/test commit: `f239f91` adds supplementary runs with zero starting
  pay, correction delta calculation against the last approved snapshot, balanced
  delta-only GL posting, immutable per-payment-type TSD delta lines, and
  organisation-scoped create routes protected by role and CSRF dependencies.
- Correction tests cover salary increases and decreases, successive corrections,
  full reversal, supplementary exemption sharing, tenant boundaries and route
  authorisation/CSRF dependency. Targeted results:
  - `pytest tests/test_payroll.py -q`: 16 passed, 1 dependency deprecation warning.
  - `pytest tests/test_payroll_corrections.py -q`: 5 passed.
  - `pytest tests/test_payroll_settlement.py -q`: 8 passed.
  - `pytest tests/test_migrations_and_tenancy.py -q`: 17 passed.
- Remaining: negative net receivables and visible offsets; additional payouts and
  correction payment-date handling; TSD/APA declaration versioning including
  replacement `M`, cancellation `T` and later `R` line identifiers; payroll UI
  and en/et/lv/lt strings. The migration records `original_run_id` without a
  composite foreign key, so tenant-safe lineage depends on the service checks.
