# Accounting and security invariants

These are release requirements, not implementation suggestions.

1. Every posted batch has at least two lines and exact equal debits and credits.
2. Posted ledger entries cannot be updated or deleted at either service or database level.
3. Corrections create a new, linked reversal; the original remains readable.
4. Duplicate voucher keys and duplicate statement fingerprints cannot post twice.
5. Locked periods reject new normal postings.
6. Money and tax use `Decimal`/`NUMERIC`, with line-level half-up currency rounding.
7. Every business record and query is organisation-scoped; API access is membership-scoped.
8. Invoice numbers are allocated atomically only at issue, separately for invoices and credits.
9. Bank downloads never post by themselves; a person confirms reconciliation.
10. VAT/KMD exports require an accountant review state. Direct filing additionally requires
    provider approval, an explicit legal declaration, and a production enable switch.
11. Provider credentials are encrypted with a versioned Fernet key and never returned by
    ordinary connection endpoints or included in audit details.
12. Provider calls happen outside document/ledger database transactions through retryable,
    idempotent adapters/outbox records.

The pytest suite exercises these invariants with synthetic UK and Estonian fixtures.
