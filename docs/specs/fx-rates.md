# FX booking, realised settlement and open-balance revaluation: P2 items 1 to 3

Implemented on 2026-10-12. FastAccounts maintains manual exchange rates and
converts document and payment bookings into the organisation's base currency.

## Rate direction and resolution

`exchange_rates.rate` means units of `to_currency` per **one** unit of
`from_currency`. For a USD document in an EUR organisation, USD -> EUR at 1.10
means USD 10.00 posts EUR 11.00. Either currency may be the base currency.

Resolution order is an explicit positive rate, then the organisation's latest
exact-direction table row with `rate_date <= document/payment date`, then 1.
Same-currency bookings default to 1 without lookup. There is no inverse lookup,
ECB call or other network feed. If multiple sources share the latest date,
manual takes precedence, then source and row ID provide deterministic ordering.
Invoice, credit note, bill and supplier credit drafts retain the resolved rate
in their existing `exchange_rate` column. Payment ledger entries retain the
applied rate; a payment table column is unnecessary.

## Conversion and accounting

`ledger.post` is the conversion point. A line's transaction currency is
`line.transaction_currency or batch currency`. If it differs from base currency:

```
base debit  = money(Decimal(line.debit)  * batch exchange_rate)
base credit = money(Decimal(line.credit) * batch exchange_rate)
```

`money()` quantises to Decimal 0.01 with ROUND_HALF_UP; `db_number()` serialises
the exact Decimal as fixed-point text. Original transaction amounts and currency
are retained with their existing signed amount convention. `gl_entries.currency`
is the organisation's base currency. Document and payment totals remain in the
transaction currency. Rates must be finite and greater than zero.

Both original and converted debit/credit totals must balance exactly. Rounding
that breaks balance raises a clear error and rolls back the business event. Ordinary document
bookings introduce no balancing adjustment. Settlement events use the dedicated
FX gain/loss role for historical-rate differences. Existing same-currency,
rate-1 stored values remain bit-identical. Reversals swap the stored base amounts
and negate transaction amounts without applying conversion twice.

## Maintenance and access

- GET `/organisations/{organisation_id}/exchange-rates` is readable by members,
  including viewers.
- POST and DELETE of individual rows require owner/administrator membership and
  CSRF. Input forbids extra fields. Dates use YYYY-MM-DD, currency codes use three
  uppercase letters, currencies must differ, and rates fit existing NUMERIC(20,10).
- Insert source is always `manual`. The existing uniqueness constraint refuses
  duplicate manual date/currency pairs with a clear error after rollback.
- All repository queries are organisation-scoped. Create/delete and their
  `exchange_rate.created`/`exchange_rate.deleted` audits share a transaction.
- Settings has a compact table and add form. Non-administrators have disabled
  add/delete controls. Four locale catalogues append the `fx_rates` section.

The existing 0003 table, positive-rate check, uniqueness constraint and date index
support rate maintenance. Migration `0025_fx_realised` adds the prepayment
`exchange_rate NUMERIC(20,10) NOT NULL DEFAULT 1` column and seeds `FX_GAIN_LOSS`
using the existing recursive next-free-code pattern. Existing roles and custom
accounts survive; UK and EE default charts include the role. CI and migration
expectations now include 25 migrations. The same migration adds nullable
`payment_allocations.booked_base_amount` to retain each allocation's exact share
of the aggregate control leg; existing rows remain NULL. Database migration
reruns skip applied versions; the role insertion itself is idempotent.

## Realised settlement (2026-10-12)

The effective booked rate is the stored exchange rate only when the document's
currency differs from the organisation base currency. A base-currency document
always books at 1, even if its stored explicit rate differs. `booking_rate`
continues to accept explicit rates for base-currency documents; ledger conversion
remains line-keyed. Apply the same effective-rate rule to payments, prepayments
and periodisation.

Invoice issue and bill approval trace their control legs through both
`posting_batch_id` and document source fields. Settlement reads the actual
original AR/AP entries from that batch, scoped to organisation and control
account. It does not re-convert or independently round the booked total.
Allocate that exact total cumulatively by the settled document-currency share:
`money(booked_base * new_paid / total) - money(booked_base * old_paid / total)`.
For final settlement, subtract the actual prior base relief from the original
booked total. New payment allocations retain their exact booked-base portions;
prepayment offsets and refunds are directly traceable through their batches.
Legacy payment allocations with NULL base portions apportion the stored aggregate
control amount cumulatively by allocation currency units in allocation-ID order,
including unallocated units in the payment denominator. This handles legacy
payment-rate residuals without editing old ledger lines. Legacy documents without
queryable original entries fall back to a total converted at the effective rate.
Manually represented paid units without allocation history use the proportional
booked-base fallback. Queries and history joins are organisation-scoped.

Payments retain two aggregate legs. The bank leg uses the payment's effective
rate. The trade-control leg sums booked allocation portions plus the unallocated
remainder converted at the payment's effective rate. A single aggregate FX leg
balances their net difference. A receipt at a higher rate credits FX (gain);
a supplier payment at a higher rate debits FX (loss). Lower rates reverse those
signs. All arithmetic uses Decimal and `money()` with ROUND_HALF_UP. Allocation
validation, posting, allocation records, paid totals and audits are one atomic
transaction; a failed rate or balance writes nothing.

When all effective rates equal the payment rate, retain the existing aggregate
posting path, metadata and two-line batch exactly, except when a final allocation
would strand previously rounded base cents. Rate-1 organisations remain exactly
identical, including base-currency documents carrying non-1 explicit stored rates.
The rounding exception prioritises exact clearing and recognises the remaining
cent difference in FX. For example, USD 0.02 at 1.5 books EUR 0.03; after a first
USD 0.01 instalment relieves EUR 0.02, the last USD 0.01 must relieve EUR 0.01
rather than another EUR 0.02. Preserving the old final batch and exact clearing
are mathematically incompatible. This is an explicit deviation from unconditional
equal-rate compatibility, necessary to preserve the accounting invariant. When
rates differ, the aggregate legs and FX difference are denominated in base
currency to avoid converting already booked portions twice. The payment record
retains its original amount and bank currency.

Prepayments now use the bank currency, resolve the payment-date booking rate,
and retain it alongside the original currency amount and unallocated balance.
Allocation uses the prepayment's booked control portion and the document's
booked AR/AP portion, with one net FX leg when needed. The same amount argument
continues to consume that number of units from each currency balance, including
foreign-to-base and base-to-foreign allocations; this API introduces no separate
currency-conversion quote or second allocation amount. Equal effective rates
retain the historical two-leg allocation shape without an FX leg, with the same
final-cent exception. Zero base legs are omitted because ledger lines require
exactly one positive debit or credit.

Refund FX is implemented, not deferred. Refunds preserve original batch and
entry reversal links, relieve prepayment control at its booked effective rate,
value bank movement at the refund-date rate and post one net difference to FX.
Equal rates retain two legs unless final-cent clearing requires an FX adjustment.
Partial refunds remain compensating events and do not mark the original batch
reversed.

Foreign-currency periodisation is enabled. Funding and each period posting pass
the document's effective rate explicitly. Funding retains ledger conversion;
period transfers distribute the actual funded base cents cumulatively by
object dimension and post those portions as base-currency lines. This avoids
independent period rounding and makes completed transit totals exactly zero.
Document-currency schedule portions retain equal-first/equal-last cent rules.
VAT remains fully recoverable on the original bill, and one-schedule-per-bill,
locked periods, cancellation and immutable posting semantics remain intact.

### Files and acceptance checks

Domain changes: `documents.py`, `prepayments.py`, `fx_settlement.py`,
`fx_settlement_repository.py`, `periodisation.py`,
`periodisation_repository.py`, `organisations.py` and additive
migration `0025_fx_realised.sql`. No new routes, UI screens or locale sections.
Wiring and regression changes: `.github/workflows/ci.yml`,
`tests/test_fx_realised.py`, `tests/test_fx_rates.py`, `tests/test_automation.py`,
`tests/test_cash_flow.py`, `tests/test_master_data_import.py`,
`tests/test_migrations_and_tenancy.py`, `tests/test_objects.py`,
`tests/test_payment_links.py`, `tests/test_payroll.py`,
`tests/test_payroll_part_time_hourly.py`, `tests/test_periodisation.py`,
`tests/test_postgres_optional.py`, `tests/test_prepayments.py`,
`tests/test_public.py` and `tests/test_quotes.py`. Documentation changes are
`docs/specs/fx-rates.md`, `docs/change_log.md` and `docs/product_roadmap.md`.
Existing upgrade tests append migration 0025 and default-chart counts include
FX_GAIN_LOSS. Offline pytest acceptance
checks cover gain/loss signs, mixed allocations, exact control clearing,
equal-rate posting equality, atomic rollback, prepayment cross-currency offsets,
refund reversal links, period transit clearing and idempotent role seeding.

## Periodic revaluation (2026-10-12)

Goal: revalue current open foreign-currency control balances atomically with a
manual run in Exchange rates settings. This is a current-state run using the
selected date's rate, not an as-of reconstruction of document/payment history.
The posting date must be in an unlocked configured fiscal period, including for
an empty run. Documents and settled portions remain in their transaction currency.

Scope includes issued/part-paid customer invoices (AR), approved/part-paid
supplier bills (AP), customer prepayments and supplier prepayments. Credit
documents, drafts, fully settled balances and base-currency balances are excluded.
Only a non-zero unrelieved attributable base balance participates. A document
with no original or revaluation control entries has no booked base to revalue;
the run does not invent a baseline from its stored rate.

For each document, sum its original control batch and all document-linked
`fx_revaluation` control entries with the original control's debit/credit sign.
Subtract actual relief from `settled_control`, including legacy NULL allocation
portions and prepayment allocations/refunds. Paid units represented without
tracked ledger relief affect the remaining currency portion but do not fabricate
base relief in a revaluation or in settlements after that revaluation.
Unrelieved currency units are `total - paid_total`, or `unallocated_balance` for
prepayments. Resolve the latest exact-direction currency-to-base rate on/before
the revaluation date through `booking_rate`, with fallback 1. The document's
stored rate is never used as the revaluation rate. Compute:

```
target = money(unrelieved_currency * effective_rate)
delta  = current_attributable_base - target
```

A debit control receives `-delta` and a credit control receives `delta` in signed
debit-minus-credit terms. Zero deltas produce no ledger entries. All non-zero
document control lines share one balanced base-currency batch, with one aggregate
`FX_GAIN_LOSS` line for the net difference. When the signed differences cancel,
the aggregate FX amount is zero and no zero-value FX line is emitted. An active
FX role is still required for a run with non-zero document deltas. All arithmetic
uses Decimal and `money()` with ROUND_HALF_UP. No posted lines are changed.

Each control line retains `source_line_type` (`invoice`, `bill` or `prepayment`),
`source_line_id`, contact and document due date where available. Its batch uses
`voucher_type='fx_revaluation'` and the run ID as voucher ID. Baseline queries add
only these attributable entries, keeping allocation and refund relief separate.
After a revaluation, `booked_portion` apportions the remaining attributable base
over the remaining currency units. The final settlement takes the exact remaining
base, absorbing cents. Payment, allocation and refund paths use these base amounts
even when their current rate equals the document's original rate. Prepayment
inclusion is implemented without a disclosed scope deferral.

Repeatability: migration 0026 gives each organisation/date a unique run. A second
run on the same date raises `A revaluation already exists for this date`, including
after an Empty run. Later-date runs recompute deltas from the current baseline;
they do not amortise an earlier adjustment. The organisation lock serialises run
identity and prepayment balance changes. Different organisations remain isolated.

`fx_revaluations` retains run ID, organisation, revaluation/posting date, optional
batch ID, Posted/Empty status, actor and creation timestamp. No per-line companion
table is needed: the immutable `fx_revaluation.posted` audit retains the complete
per-document result, resolved rate, portion, booked base, target, delta, base
currency and totals. Totals include the signed FX amount (debit positive, credit
negative). History reconstructs these results from the tenant-scoped audit.
Migration 0026 and its composite tenant indexes are directly rerun-safe.
Validation, ledger posting, run identity and audit are one transaction. Missing
roles, inactive accounts, locked periods or posting failures roll everything back.

GET `/organisations/{organisation_id}/fx-revaluations` is member-readable,
including viewers. POST requires owner/administrator plus CSRF and strictly
validated YYYY-MM-DD input with no extra fields. Settings adds a date/run form,
the result table and history list alongside manual rates. `canEditMappings()`
disables both date and run controls for other members. New copy is appended within
the existing trailing `fx_rates` section in en/et/lt/lv.

Implementation files: `fx_revaluation.py`, `fx_revaluation_repository.py`,
`fx_settlement.py`, `fx_settlement_repository.py`, `documents.py`, `prepayments.py`,
`api_app.py`, `static/app.js`, `migrations/sqlite/0026_fx_revaluations.sql`, CI,
four locale tails, `tests/test_fx_revaluation.py` and existing migration/browser
expectations. Acceptance covers both trade sides and gain/loss directions,
partial/fully paid and base-currency exclusions, exact later clearing, repeat
convergence, empty runs, rollback, prepayment offsets/refunds, tenant constraints,
roles, CSRF and offline owner/viewer browser flows in all locales. The roadmap
and change log record the final full-suite result after verification.

Complete changed-file inventory (33 files):

- Services and persistence: `fx_revaluation.py`, `fx_revaluation_repository.py`,
  `fx_settlement.py`, `fx_settlement_repository.py`, `documents.py`, `prepayments.py`.
- API and UI: `api_app.py`, `static/app.js`.
- Migration and CI: `migrations/sqlite/0026_fx_revaluations.sql`,
  `.github/workflows/ci.yml`.
- Locales: `web/locales/en.json`, `web/locales/et.json`, `web/locales/lt.json`,
  `web/locales/lv.json`.
- Tests: `tests/test_fx_revaluation.py`, `tests/test_fx_rates.py`,
  `tests/test_fx_realised.py`, `tests/test_automation.py`, `tests/test_cash_flow.py`,
  `tests/test_master_data_import.py`, `tests/test_migrations_and_tenancy.py`,
  `tests/test_objects.py`, `tests/test_payment_links.py`, `tests/test_payroll.py`,
  `tests/test_payroll_part_time_hourly.py`, `tests/test_periodisation.py`,
  `tests/test_postgres_optional.py`, `tests/test_prepayments.py`,
  `tests/test_public.py`, `tests/test_quotes.py`.
- Documentation: `docs/specs/fx-rates.md`, `docs/change_log.md`,
  `docs/product_roadmap.md`.

Estonian additions for copy QA (14 strings, within `fx_rates.workspace`):

| English key | Estonian addition |
| --- | --- |
| Document | Dokument |
| Revalue balances | Hinda saldod ümber |
| Revalue current open foreign balances at the selected date rate. | Hinda avatud saldod välisvaluutas ümber valitud kuupäeva kursiga. |
| Revaluation date | Ümberhindluse kuupäev |
| Run revaluation | Käivita ümberhindlus |
| Open portion | Avatud osa |
| Booked base | Arvestatud summa baasvaluutas |
| Target base | Sihtsumma baasvaluutas |
| Delta | Vahe |
| Revaluation history | Ümberhindluste ajalugu |
| Posting batch | Kandepakett |
| No posting | Kannet ei tehtud |
| Revaluation date must use YYYY-MM-DD | Ümberhindluse kuupäev peab olema kujul AAAA-KK-PP |
| A revaluation already exists for this date | Selle kuupäeva ümberhindlus on juba olemas |

Out of scope: automated schedules and rate feeds, foreign bank-account cash
revaluation, historical as-of reconstruction and automatic reversals.

## Deferred

Automated rate feeds and scheduling remain deferred.
Production accountant UAT and live PostgreSQL validation remain pending.
