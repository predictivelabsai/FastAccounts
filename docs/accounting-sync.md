# Reviewed accounting sync

## Reviewed push pipeline

Status: **Documented contract · not live-verified**.

Bookkeepers explicitly prepare, review and execute exports to Merit Aktiva or
SmartAccounts. Preparation reads an organisation-scoped, balanced ledger batch
and freezes its exact EUR amounts as decimal strings. Payroll must be Approved
and have a posted batch. Payroll document numbers are `PAY-{period}`, matching
the local voucher; journal and reversal voucher numbers pass through unchanged.
Only Estonian organisations with EUR books qualify. Every account requires a
Confirmed provider mapping. Unmapped or merely Suggested accounts cause a hard
stop listing every missing code. Pending preparations block duplicates.

Review rebuilds the payload from the source journal and current mappings. A
changed payload is refused with `prepared payload changed; prepare again`.
The obsolete preparation is marked Failed and its review cleared, allowing a
fresh preparation without the pending-document lock.
Successful review records the reviewer and timestamp. Execution requires that
review, revalidates the source and atomically claims the run as Running. A local
export mapping for the same document, including its payroll/journal alias,
causes an already-pushed refusal. The schema calls local ownership
`fastaccounts`; exports use `object_type=gl_batch` and `direction=export`.

An acknowledged external ID completes the run and is recorded for subsequent
duplicate checks. ProviderError, connector ValueError or transport failure
marks the run Failed, stores the error and increments its conflict count.
There is no automatic retry, including HTTP posting retries. A failed run can
be executed again explicitly, subject to all gates. Inspect provider records
first after uncertain outcomes or partially accepted Merit chunks: these APIs
do not guarantee remote idempotency or atomic chunk submission. A stuck Running
run also requires reconciliation before any operational recovery.

Merit acknowledgements accept canonical `external_id` or its raw `GLBId` field.
For journals split into 500-line chunks, every acknowledgement must contain an
ID before completion. The first ID identifies the export mapping; its
`external_version` JSON retains all chunk IDs for reconciliation. Missing IDs
cause Failed rather than an unsupported assumption that the posting succeeded.

The workspace shows prepared journals, review attribution, failures and actions
on pay runs and provider detail pages. Approvers can prepare/review; only owners,
administrators and accountants can execute. Account-mapping CRUD retains its
existing owner/administrator guards. Suggestions use already staged external
accounts and existing Suggested mappings without making provider requests.
GL reconciliation reads the existing external snapshots.

Corrections are new reversal journals produced by `LedgerService.reverse`,
with `REV-...` voucher numbers. This pipeline pushes FastAccounts-approved
ledger journals to the provider. Neither provider's own records are edited,
and external GL can never be deleted through this pipeline. Local posted ledger
lines remain immutable.

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

## SmartAccounts

The company-scoped adapter uses `https://sa.smartaccounts.eu/{lang}/api`, with
`lang=et` by default or `en`. Constructor credentials are `api_key` (the public
company API key) and `secret_key` (the secret signing key). Both are encrypted
credentials. The contract is SmartAccounts API version 1.7, dated 28 April 2025.

| Object | Method and path | Parameters |
| --- | --- | --- |
| Connection check / accounts | GET `/settings/accounts:get` | Full account list, no filters |
| Clients | GET `/purchasesales/clients:get` | `pageNumber`, `fetchContacts=true`, `fetchAddresses=true` |
| Sales invoices | GET `/purchasesales/clientinvoices:get` | `dateFrom`, `dateTo`, `dateType=date`, `pageNumber`, `fetchRows=true` |
| Purchase invoices | GET `/purchasesales/vendorinvoices:get` | Same dated parameters |
| Payments | GET `/purchasesales/payments:get` | Same dated parameters |
| Manual ledger entries | GET `/general/entries:get` | Same dated parameters, `docType=LEDGER_ENTRY` |
| GL batch | POST `/general/entries:add` | `docType=LEDGER_ENTRY`, `date`, `document`, `currency=EUR`, `comment`, `rows` |

Every request signs the exact URL-encoded query string before `&signature=`.
Endpoint parameters appear first in insertion order, followed by `timestamp`
and `apikey`. POST appends the exact compact UTF-8 JSON body immediately, with
no separator. GET signs only the query string. The server URL is never signed.
HMAC-SHA256 uses the secret key and produces lowercase hexadecimal; the
URL-encoded signature is the final query parameter. The official example input is:

```text
codes=kood1%2Ckood2%2Ckood3&timestamp=14022013133802&apikey=a066f7de6042458da916
```

Timestamps use `ddMMyyyyHHmmss` in Europe/Tallinn, including DST conversion
from an aware injected clock. On Windows, install `tzdata` (`pip install tzdata`)
to supply the IANA timezone database. Date filters use `dd.MM.yyyy`, following
the official filter examples; canonical dates remain ISO. GL add uses the
requested ISO `yyyy-mm-dd` date. Its field table specifies Date without an
explicit encoding; confirm this with the test company before live acceptance.

Each pull makes one request. Accounts have no cursor. Clients use compact
`{"page":2}` cursors and end only when `hasMoreEntries=false`. Dated objects
use inclusive 90-day windows starting 365 days before today by default. While
paging, `{"from":"2026-01-01","to":"2026-03-31","page":2}` freezes the
window; after its last page the cursor is `{"from":"2026-04-01"}`. Once the
last window reaches today the cursor is `None`. Page size is never assumed.
The document does not specify every collection envelope name: the adapter
accepts its named collection or a single unambiguous array, excluding `deleted`.
Malformed pagination fails explicitly. Date filtering uses document dates;
historical edits require replaying the relevant date window. Remote deletions
are not applied to local books.

Client email comes from `contacts` entries with `type=EMAIL`; `dateUpdated`
(or `dateCreated`) supplies the external version. Invoice counterparties come
from nested `client` / `vendor`, totals from `amount`, `vatAmount`, `totalAmount`
and paid status from `outstandingAmount`. Remote invoice rows are retained as
`smartaccounts_rows`; applying drafts requires reviewed local lines, accounts
and tax codes, as for Merit headers. Payment invoice allocations become separate
records with IDs `{payment_id}:{row_index}` and allocation amounts, avoiding
duplicating the entire payment per invoice. Bank accounts need local review.
Unsupported allocations and payments without allocations remain review records
without a linked document. Ledger row IDs are `{entry_id}:{row_index}`;
`objectId` is preserved in `dims`. External GL is reconciliation data only.

GL push validates all batches and lines before the first request: EUR only,
finite two-decimal amounts, accounts, dates, document numbers, non-negative
single-sided lines and a positive balanced total. Wire rows use `account`,
`description`, `debitAmount` and `creditAmount`, never OriginalCurrency fields.
Decimal arithmetic is retained until the JSON numeric wire boundary. One batch
is one request, with no row chunking: the document specifies no add row cap.
The returned `id` is captured as `external_id`. SmartAccounts supports
`entries:delete`, but this adapter never calls delete or edit. Corrections are
new linked reversal entries. Multiple batches are not remotely atomic and no
provider idempotency token is documented; inspect provider state before retrying
an uncertain or partially completed push.

Limits are 60 requests/minute and 1000 requests/24 hours, exceeded with HTTP
503. Shared HTTP retry/backoff honours `Retry-After`; 503 can also indicate a
billing problem. Offline fixtures exercise the contract without vendor access.

### Live verification status

| Capability | Status |
| --- | --- |
| Connection check and accounts | Documented contract · not live-verified |
| Clients | Documented contract · not live-verified |
| Sales and purchase invoices | Documented contract · not live-verified |
| Payments and allocations | Documented contract · not live-verified |
| Ledger entries | Documented contract · not live-verified |
| EUR GL batch push | Documented contract · not live-verified |

Acceptance with a SmartAccounts test company, including collection envelopes,
date encoding and fetch flags, remains pending. The synthetic encrypted demo
connection performs no live check.
