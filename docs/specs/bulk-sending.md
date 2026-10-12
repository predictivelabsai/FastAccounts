# Bulk invoice PDF sending

P1 item 12, 12 October 2026. Send selected sales invoices using the established
Postmark delivery path in `DocumentService.send_invoice_email` (`documents.py`).
`AutomationService.send_reminder` uses that same sender. The existing PDF
renderer, subject, body, attachment filename and outbound stream are reused.
No parallel mailer, dependency or migration is added.

## API and eligibility

`POST /organisations/{organisation_id}/invoices/send-bulk` accepts
`{"invoice_ids": ["..."]}` with extra fields forbidden. Owner, administrator
and accountant membership (`WRITE_ROLES`) and CSRF are required. The service
checks each invoice in the requested organisation, including its contact join.
Only document type `invoice` with status `Issued` or `Part Paid` is eligible.
Drafts, paid invoices, credit notes, missing/foreign IDs and contacts without
an email address fail independently. Missing email configuration and provider
errors also produce failed rows. No ledger entries or payment status change.

`MAX_BULK_INVOICES` in `bulk_sending.py` caps a request at 50 entries, including
duplicates. Empty and oversized requests fail validation before any sending.
Results preserve input order and contain `invoice_id`, `status` (`sent` or
`failed`), `reason`, `delivery_id` and `attachment_id`. Duplicate IDs produce a
failed row without a second email. Eligibility failures have no delivery ID.

## Transactions, retries and evidence

Each eligible invoice reserves a `Prepared` row in existing `invoice_deliveries`
and an `invoice.delivery` audit event before HTTP. The exact PDF is stored using
`attach_evidence` in the existing `attachments` store in that same transaction;
the audit details link its ID. Identical existing invoice evidence can be reused.
An organisation lock serialises reservations using the existing database lock
convention. No database transaction remains open during the provider request.
The sender then commits the final `Sent` or `Failed` status and audit event in
an independent transaction. Failed provider attempts retain their PDF evidence.

An optional `Idempotency-Key` header (1 to 180 characters) scopes retries to the
organisation, actor and invoice. Its hash is stored in the delivery audit details.
Reusing a key returns an existing outcome without another provider call. A
`Prepared` outcome, for example after interruption between provider acceptance
and final persistence, fails with an explicit review instruction rather than
resending. A new key is an intentional resend. Callers should retain the same
key for the same selection on a retry. Without a key, separate requests are
intentional sends. Provider-side exactly-once delivery cannot be guaranteed
across network timeouts; review the delivery/provider history before retrying an
uncertain outcome with a new key.

Invoice detail includes tenant-scoped delivery history with retained attachment
IDs. Existing attachment download checks verify ownership and file integrity.
No storage paths or idempotency hashes are exposed through the detail payload.

## Workspace and checks

The invoices list has labelled row checkboxes, a Send emails action, confirmation
and per-invoice results. Only eligible rows are selectable by write roles.
Selection lasts for the current list rendering and is cleared after results.
Invoice detail shows email history and PDF download links. Copy is appended in
`bulk_sending` in English, Estonian, Lithuanian and Latvian and merged through
`APPEND_SECTIONS`. Existing status words are reused.

`tests/test_bulk_sending.py` uses the reminders' `HTTP_CLIENT_FACTORY` boundary
and `httpx.MockTransport`, with a network guard. It covers both countries,
independent outcomes, eligibility, role/CSRF gates, tenant isolation, duplicate
IDs, cap and payload validation, retries, interrupted persistence, audit/PDF
readback, unchanged ledger entries and offline four-language browser flows.
Run the full `python -m pytest -q` suite and `node --check static/app.js`.

## Deferred scope

Background queues, automatic retries, provider webhooks/delivery confirmation,
template editing, subject overrides in the bulk UI/API, saved selections,
column configuration, large batches, credit-note/paid-invoice bulk sending and
production accountant UAT are deferred. PostgreSQL execution remains opt-in.
