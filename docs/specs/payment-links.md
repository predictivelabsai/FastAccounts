# Payment links

P1 item 9 supplies local, provider-agnostic payment URL configuration. EveryPay,
LinkPay and custom are labels, not HTTP adapters or claims of provider support.
No provider calls, credentials, callbacks or ledger postings are involved.

The simpler design uses `payment_link_configs` per organisation and
`invoice_payment_links` per invoice and method. Composite tenant foreign keys
prevent links to another organisation's invoice or configuration. Organisation
row locking and a unique invoice/method constraint make generation idempotent,
including concurrent requests. Configuration changes are audited.

Owners and administrators can create and edit methods. All organisation roles
can read methods and invoice links. Writes require CSRF protection. GET invoice
detail and payment-link endpoints materialise eligible links locally; they never
initiate payment. The invoice list remains unchanged. The detail payload includes
`payment_links` and `/invoices/{invoice_id}/payment-links` returns the same list.

Templates must be absolute HTTPS URLs with a fixed host, no embedded credentials,
whitespace or backslashes. Placeholders are allowed only in the path, query or
fragment, with no format specifiers, conversions or attribute access:

- `{invoice_total}`: full invoice gross total, Decimal formatted to two places.
- `{invoice_due}`: current total less allocated payments, also two places.
- `{invoice_number}` and `{invoice_id}`: issued number and internal identifier.
- `{token}`: stable `secrets.token_urlsafe(32)` token for this invoice and method.
- `{currency}`: the invoice currency code.

Values are URL-encoded individually. For example:
`https://merchant.example.test/pay/{token}?amount={invoice_due}&reference={invoice_number}`.
The administrator must supply a URL accepted by their merchant service. This
mechanism cannot establish a payment session for a provider requiring an API call.

Only unpaid Issued or Part Paid sales invoices are eligible. Drafts, paid invoices
and credit notes return no links; direct generation refuses them. A method's
currency must match the invoice, or be empty to allow any invoice currency. There
is no conversion and no organisation base-currency restriction. Use
`{invoice_due}` for collection on part-paid invoices, rather than charging the
full `{invoice_total}` again.

Each stored URL refreshes on the next read if the template or outstanding amount
changes; its token and creation time remain stable. Disabled and incompatible
methods are hidden. Stored rows remain for preservation and re-enabling. Already
shared external URLs cannot be revoked or refreshed by FastAccounts. Their
destination must enforce current balance, expiry and duplicate-payment controls.
Tokens are globally unique and unpredictable, but grant no access to invoice
data in FastAccounts. Treat shared payment URLs as sensitive and do not log them.
Configuration contains public URL templates only; never include provider secrets.

There is no existing unauthenticated invoice/share page. The authenticated invoice
dialog exposes payment buttons, read-only URL fields and copy controls. Payment
methods appear under Settings in all four locales. A public invoice page,
EveryPay/LinkPay HTTP integration, payment verification, automatic reconciliation,
provider-side revocation and production UAT are deferred. Clicking a link does not
mark an invoice paid; existing payment allocation remains authoritative.
