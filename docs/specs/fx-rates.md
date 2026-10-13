# FX foundation: P2 item 1

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
that breaks balance raises a clear error and rolls back the business event. No
balancing adjustment or gain/loss line is introduced. Existing same-currency,
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
support this feature as-is. No migration is added; the count remains 24.

## Deferred: P2 item 2

Realised FX, revaluation, gain/loss accounts, periodisation and prepayment FX
integration, and automated rate feeds are deferred to P2 item 2. Existing
periodisation/prepayment refusals of rates other than 1 are unchanged. Payment
conversion does not settle exchange differences against historical document
rates. Production accountant UAT and live PostgreSQL validation remain pending.
