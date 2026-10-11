# Estonian e-invoices

FastAccounts writes Estonian e-arve 1.2 XML for issued, part-paid and paid
sales invoices and accepts purchase XML into draft bills. Draft sales invoices
cannot be exported. UK organisations retain the existing generic XML export.
No schema migration or configuration change is required.

## Review boundary

The writer follows the e-arve 1.2 element structure, includes seller and buyer
details, item amounts and VAT groups, and uses Decimal money rounding. Payment
information is included only when an active organisation bank account has an
IBAN. Missing optional contact and bank details are omitted.

The writer is spec-faithful and review-gated, not live-verified against a
schema/XSD. Accountant review and independent schema validation are required
before production use. Passing local writer/parser round-trip tests demonstrates
internal consistency, rather than acceptance by an operator or accounting system.

## Purchase intake

Use **Import e-invoice** in Bills to upload a single purchase invoice, either
as an `Invoice` document or an `E_Invoice` file containing one invoice.
Files containing multiple invoices are explicitly rejected. Intake
checks each item's arithmetic and declared net, VAT and gross totals to two
decimal places. Invalid XML, unrecognisable documents and inconsistent totals
are rejected with an explanation. This declaration-consistency validation and
writer/parser round-trip coverage do not establish external schema conformance.

Successful intake creates a **Draft** bill and attaches the original XML as
bill evidence. Supplier creation, bill creation and evidence registration share
one transaction; a failed import rolls them back and removes newly written
evidence files. It does not approve a bill or post ledger entries. Lines default
to the organisation's EXPENSE account. Review the supplier, account allocation,
tax treatment and attachment before approval.

Supplier matching uses `contacts.registration_no` within the importing
organisation and only contacts whose `contact_type` is `supplier` or `both`.
An existing supplier with that registry number is reused without renaming it.
Registry numbers are not unique in the contacts schema; where several suppliers
match, intake chooses the earliest `created_at`, then `id`, deterministically.
Existing collisions require accountant review. Without a registry number,
intake reuses an exact supplier name/VAT match that also has no registry number.
Other organisations' contacts are ignored. If no supplier matches, intake
creates one using the seller details. A customer-only registry match creates a
separate supplier contact.

Contacts have no note column. The provenance note, `Imported from e-invoice
{number}`, is retained on the draft bill, alongside the source XML evidence and
the existing audit trail. No migration is needed to add a contact note.

Bills enforce `UNIQUE (organisation_id, contact_id, supplier_number)`.
Importing the same invoice number for the same resolved supplier returns an
already-imported conflict. This constraint does not detect duplicate invoices
under different supplier contacts, so contact collisions must be reviewed.

VAT codes are selected by numeric rate from the organisation's active tax codes
for its country, preferring standard, reduced and zero codes over reverse-charge
codes where rates overlap. Unknown rates are rejected. A zero rate can be mapped
without rejecting a foreign supplier. Numeric matching alone does not determine
the correct reverse-charge treatment, exemption or purchase tax reporting category.

Purchase credit notes require the supplier-credit workflow; negative lines and
discounts whose price times quantity differs from the declared net are outside
this intake.
Both exclusive and inclusive VAT rounding are accepted when declarations
reconcile exactly. Imported bills preserve the declared VAT and recoverable
VAT amounts, including a valid cent difference from net-based recalculation.
The writer uses `ItemDetailInfo`, nested `VAT` groups, `TotalVATSum`,
`PayToAccount` (IBAN) and `PayToName` (seller). The parser also accepts direct
item VAT/quantity tags and alternate total names used by other exporters.

## Operator delivery

`einvoice_operator` is a **Planning stub** in the integration catalogue and
connector registry. `EInvoiceOperatorProvider.submit()` raises `PermissionError`
and has no network client. Finbite/Omniva hosted delivery needs operator
contracts and a reviewed delivery adapter. Download and purchase intake do not
send, acknowledge or track operator deliveries.
