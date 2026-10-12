# Purchase periodisation

## Goal and scope

Spread a whole purchase bill's net expense over 1 to 120 monthly accounting
periods. Use a tenant-scoped schedule and one immutable balanced journal batch
per portion. This is purchase bookkeeping, with no inventory, orders or HR scope.

## Deferred-cost ledger model

The full bill retains its supplier, amounts, payment workflow, evidence and VAT
treatment. A schedule created before approval redirects the original net debit
to the Asset role `PERIODISED_PURCHASES`, called "Periodised expenses in transit"
in the UK chart. The original bill still credits AP for its full gross amount.
No expense is recognised twice on confirmation.

For an already approved, partly paid or paid bill, create an additional balanced
reclassification on its bill date: debit deferred cost and credit the original
expense accounts for their net amounts. Keep the original journal and bill
unchanged. This operation requires an open bill period and an unreversed source
batch. Each scheduled portion then debits the chosen real expense account and
credits deferred cost. All bill lines must be expense lines; multiple original
expense accounts can be consolidated into the chosen destination account.

Example: insurance with net cost 1,200.01 and recoverable VAT of 288.00 creates
deferred cost of 1,200.01, input VAT of 288.00 and AP of 1,488.01 at approval.
Twelve portions transfer 100.00 each, with the residual 0.01 added to the first
or last portion. After all portions, deferred cost is zero and total expense is
1,200.01. AP, payment allocation and input VAT do not change during transfers.

## VAT timing and validation

Deduct input VAT in full on the original purchase bill, following the app's
existing Estonian and UK accrual treatment. Period portions contain zero VAT and
never repost input VAT. This feature supports base-currency bills with fully
recoverable VAT or no VAT. Partial VAT recovery, foreign currency and supplier
credit-note schedules remain follow-ups, rather than silently changing tax
treatment. Existing tax reporting continues to read the full original bill.

The schedule total must equal the real bill's net subtotal. Validate finite
Decimal values with four-place precision and require whole cents, then store
with `db_number`. Divide into equal whole-cent amounts and assign the entire
remainder deterministically to the selected first or last period. Reject
zero-cent portions. Anchor monthly dates to the start day, clamping only short
months, so 31 January, 28 February and 31 March retain the original anchor.
Dates cannot precede the bill or leave configured fiscal periods. Locked periods
block creation and posting.

## Lifecycle, safety and cancellation

Draft schedules reserve deferred cost at bill approval, but generate no expense
until explicitly activated. Active schedules wait for source-bill approval and
post all due portions, or one selected due portion. Future posting is rejected.
Completion means every portion has a linked posted journal. Schedule creation,
approval, activation, cancellation and posting acquire the organisation row
lock, following the quote pattern. All ledger operations and schedule links use
the same transaction. Per-period status/journal checks, uniqueness and ledger
voucher idempotency protect retries and concurrent workers.

Cancellation changes only future Pending periods. Post any due periods first.
Posted journal links and immutable ledger lines remain intact. Cancelling an
unapproved bill's future schedule restores normal expense treatment on approval.
Cancelling after approval leaves the unrecognised balance in deferred cost for
accountant review and an explicit adjustment or reversal. Cancellation never
silently writes off an asset or reverses posted expense. Source or funding batch
reversals block further posting. Coordinated bill, deferral and portion reversal
workflows are deferred.

The existing gated automation worker checks Active schedules daily, catches up
due portions and isolates schedule and organisation failures. A schedule catch-up
is atomic: a locked period or failed journal link rolls back the entire attempt.

## Files and acceptance checks

Add migration `0021_periodisation`, tenant-scoped repository and service,
Pydantic API models, viewer GET routes and write-role/CSRF-protected create,
activation, posting and cancellation. Extend bill approval, both country charts,
the automation tick, inline CI migration list and explicit migration tests.
Add a Periodised view under Documents with creation, progress, period details
and posting/cancellation confirmation dialogs. Append a feature translation
bundle at the end of all four locale files, merging its new keys into existing
sections at load time without changing existing keys or translations.

Verify original-bill preservation, balanced batches, net-only transfers, VAT/AP
stability, cent remainder, date anchors, locked periods, rollback, cancellation,
concurrent retries, tenant isolation and composite foreign keys. Check additive
upgrade preservation, custom chart code collisions and raw migration reruns.
Exercise API roles, mounted-web CSRF and offline browser flows in all four
locales, including escaped values and mobile layout. Run the full pytest suite
with Python 3.12.14 before marking the synchronised roadmap/change log complete.

## Follow-ups

Production accountant UAT, partial VAT recovery, foreign currency, explicit
irregular period lists, schedule editing after creation and coordinated reversal
or cancellation settlement remain outside this implementation.
