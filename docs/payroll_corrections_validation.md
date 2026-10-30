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
  validation, frozen absence lineage, support for correction zero values, and
  compatibility with the partial regular-period unique index.
- Approval/API/test commit: `f239f91` adds supplementary runs with zero starting
  pay, correction delta calculation against the last approved snapshot, balanced
  delta-only GL posting, immutable per-payment-type TSD delta lines, and
  organisation-scoped create routes protected by role and CSRF dependencies.
- Follow-up commits: `82c746e` adds the receivable base schema, `b7e70f5` adds
  offset/account and APA history schema, and `503b770` implements correction
  payouts, offsets, workpaper changes and APA operation versioning.
- Backend payout/history work adds migrations 0057-0059. Positive correction net
  deltas use the ordinary payout batch with a correction run reference and
  partial-payment caps against the net delta. Negative deltas create a tenant-
  scoped employee receivable with a balanced debit to receivable and credit to
  salary payable. Open receivables are listed; salary payout creation proposes
  offsets in FIFO order, and an accountant confirms them before posting the
  payable/receivable offset. Offset confirmation reduces the bank line and an
  offset-only payout creates no bank line.
- A same-month correction updates the affected transaction with APA operation
  `M`, carrying a full replacement under the existing line number. The guide's
  section 4 cancellation example uses `T` with only the existing line number and
  operation code. Cancelling a version is recorded with its XML; the line number
  is retired, so any later replacement uses `R` and a fresh line number. A paid
  correction in a later month exports under its own payout ID and actual payout
  date as a new `R` transaction. This follows the vendored cancellation example
  at `tests/fixtures/emta/APA_TSD_lahteandmed_ariuhingule_naide_tuhistamine_XML_20251017.xml`.
- Same-month corrected deltas feed the original workpaper and legacy CSV. A
  later-month correction remains a separate workpaper transaction. APA history
  retains `R`/`M` operation values, immutable payloads, cancellation XML, actor
  and tenant data.
- Correction tests cover salary increases and decreases, successive corrections,
  full reversal, supplementary exemption sharing, tenant boundaries and route
  authorisation/CSRF dependency. Targeted results:
  - `pytest tests/test_payroll.py -q`: 16 passed, 1 dependency deprecation warning.
  - `pytest tests/test_payroll_corrections.py -q`: 5 passed.
  - `pytest tests/test_payroll_settlement.py -q`: 8 passed.
  - `pytest tests/test_migrations_and_tenancy.py -q`: 17 passed.
- Follow-up commits: `0f34db7` adds SQLite and PostgreSQL tenant-lineage guards
  for `original_run_id`; `58fde23` adds payroll correction UI actions and
  translations; `65d74fc` recalculates later-month positive corrections, freezes
  payout-specific TSD lines and posts balanced tax adjustments; `75e788b` adds
  payout date selection and verifies the later-month APA workpaper values;
  `0d5d8a2` prevents deletion or reassignment of a run with related runs.
- Later-month positive correction payouts use the selected payment month and the
  remaining employee exemption for that month. The run item keeps its immutable
  approved values; the recalculated net delta, TSD snapshot and tax-liability
  adjustment are associated with the payout. A negative correction creates an
  employee receivable and remains an `M` amendment of the original period. It
  does not create a negative payout.
- Migrations 0060 and 0062 use SQLite triggers and PostgreSQL trigger
  substitutions to reject cross-organisation original-run references and to
  protect referenced original runs. Migration 0061 stores payout-specific TSD
  rows with update/delete guards.

### Final requested test pass

Each requested file was run individually with the repository venv:

- `.venv\Scripts\python.exe -m pytest tests/test_payroll_corrections.py -q`: 9 passed.
- `.venv\Scripts\python.exe -m pytest tests/test_payroll_payouts.py -q`: 7 passed, 1 existing fastcore deprecation warning.
- `.venv\Scripts\python.exe -m pytest tests/test_tsd_apa_history.py -q`: 6 passed, 1 existing fastcore deprecation warning.
- `.venv\Scripts\python.exe -m pytest tests/test_tsd_apa_xml.py -q`: 6 passed.
- `.venv\Scripts\python.exe -m pytest tests/test_tsd_export.py -q`: 14 passed.
- `.venv\Scripts\python.exe -m pytest tests/test_workspace_payroll.py -q`: 17 passed, 1 existing fastcore deprecation warning.
- `.venv\Scripts\python.exe -m pytest tests/test_i18n.py -q`: 18 passed, 1 existing fastcore deprecation warning.
- `.venv\Scripts\python.exe -m pytest tests/test_migrations_and_tenancy.py -q`: 18 passed.

Total: 95 passed and 4 existing deprecation warnings. No full suite, browser
test, live network test or PostgreSQL integration run was performed. Build 5 is
implemented; accountant UAT and e-MTA acceptance remain external validation.
