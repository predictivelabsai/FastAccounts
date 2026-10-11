# Reviewed accounting sync

## Merit Aktiva

The adapter stages accounts, contacts, sales and purchase invoice headers,
payments and external GL entries for accountant review. External GL entries are
reconciliation snapshots, not local ledger postings. Invoice list responses do
not include document lines: an accountant must enrich headers with reviewed
lines and local account mappings before applying them as drafts. Payments need
an existing mapped local document and a reviewed bank account. Directions 3/4
carry `merit_payment_note` and `import_warning` for manual handling.

The base is `https://aktiva.merit.ee/api`; company context is implicit in each
API key. All endpoints are signed.

| Path | Method | Version | Parameters/body | Period cap |
| --- | --- | --- | --- | --- |
| `/v2/accounts` | GET | v2 | `UsageFilter=0` | None |
| `/v1/getcustomers` | GET | v1 | Optional `ChangedDate` (yyyymmdd) | None |
| `/v1/getvendors` | GET | v1 | Optional `ChangedDate` (yyyymmdd) | None |
| `/v2/getinvoices` | POST | v2 | `PeriodStart`, `PeriodEnd` (yyyymmdd) | Three months; adapter uses 90 inclusive days |
| `/v2/getpurchorders` | POST | v2 | `PeriodStart`, `PeriodEnd`, `UnPaid=false`, `DateType=0` | Adapter uses 90 inclusive days |
| `/v2/getpayments` | POST | v2 | `PeriodStart`, `PeriodEnd`, `DateType=0` | Three months; adapter uses 90 inclusive days |
| `/v1/GetGLBatchesFull` | POST | v1 | `PeriodStart`, `PeriodEnd`, `WithLines=1`, `DateType=0` | 31 inclusive days |
| `/v1/sendglbatch` | POST | v1 | `DocNo`, `BatchDate`, `CurrencyCode=EUR`, `EntryRow` | 500 rows per request |
| `/v2/sendinvoice` | POST | v2 | Existing invoice payload via `create_invoice` | Existing invoice contract |
| `/v2/getpayments` | GET | v2 | Existing empty-body `check` probe | None |

Query parameters are `apiId`, UTC `timestamp` in `%Y%m%d%H%M%S` format and
`signature`. The signature is Base64 of HMAC-SHA256 with the API key over
`apiId + timestamp + exact body`. GET signs an empty body, including filtered
GETs. POST signs UTF-8 compact JSON with `ensure_ascii=False` and separators
`(',', ':')`. The existing signing helper remains unchanged.

Merit permits 100 requests/minute. The shared HTTP provider handles 429 and
`Retry-After` backoff. Pull JSON numbers are parsed as `Decimal`. Monetary
values remain `Decimal` in canonical records; GL pushes convert to numeric
floats only at the wire boundary as required by the supplied Merit contract.

Each date-based pull performs one bounded window. With no cursor it starts
365 days before the injected UTC clock's current date. GL windows end at
start + 30 days; invoice/payment windows end at start + 89 days. Both are capped
at today. The returned cursor is compact JSON `{"from":"YYYY-MM-DD"}` for
the day after the window end, or `None` when today is reached. ISO date input
cursors are also accepted. Invalid/reversed/oversized periods raise `ValueError`.

Unfiltered full customer/vendor lists have a documented server-side failure.
With a cursor the adapter always sends `ChangedDate` in yyyymmdd format. With
no cursor it attempts each unfiltered list and, after a server error, falls back
to `ChangedDate=today-365 days`. Authentication, transport and malformed-response
failures are raised, never hidden. Contacts return no next cursor because each
filtered response is a full list. The fallback is deliberately a recent-year
subset, so older unchanged contacts require a supplied earlier cursor.

GL pushes accept canonical batches with `doc_no`, `posting_date`, `currency`
and `lines`. Lines use `account_code` (or `external_account_code`), `debit`,
`credit` and `memo` (or `description`). All batches are validated before the
first GL request. Batches over 500 rows are split into requests with suffixes
`-2`, `-3`, etc.; the base number is shortened so each `DocNo` stays within
35 characters. Accounts allow 8 characters, memos 150. Splitting does not make
the requests atomic: a later failure can leave earlier chunks accepted. Review
the provider state before retrying to avoid duplicate or incomplete journals.

GL cannot be deleted via API: corrections are reversal journals. The adapter
does not change local ledger lines or implement provider deletion.

### Live verification status

| Capability | Status |
| --- | --- |
| Accounts pull (`accounts`) | Documented contract · not live-verified |
| Customers/vendors pull (`getcustomers`, `getvendors`) | Documented contract · not live-verified |
| Sales invoice headers pull (`getinvoices`) | Documented contract · not live-verified |
| Purchase invoice headers pull (`getpurchorders`) | Documented contract · not live-verified |
| Canonical reviewed payment pull | Documented contract · not live-verified |
| GL entries pull (`GetGLBatchesFull`) | Documented contract · not live-verified |
| GL batches push (`sendglbatch`) | Documented contract · not live-verified |
| Existing sales invoice API (`sendinvoice`) | In production use |
| Existing payment API (`getpayments`) | In production use |
| Existing connection probe (`check`, GET `getpayments`) | In production use |

These statuses follow the supplied verified contracts and existing production
usage. This change is verified with synthetic fixtures only, with no live calls.
