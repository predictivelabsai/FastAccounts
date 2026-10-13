# FastAccounts Change Log

Keep this file synchronized with `docs/product_roadmap.md`. Entries describe
implemented and verified product changes; planning status alone is not marked as
delivered.

## 2026-10-12: Sales quotes

- Added tenant-scoped quotes and quote lines with migration `0020_quotes`,
  base-currency and exact decimal guards, and a separate `QUO-` series using the
  existing document sequences. CI and upgrade migration expectations include
  the new migration, preserving existing records and sequence counters.
- Quotes have no voucher or ledger posting. Draft offers can be edited, marked
  sent, accepted or declined after sending, or expired after their inclusive
  validity date. Stale acceptance is refused. A tenant-scoped daily-worker
  helper expires overdue Draft and Sent offers without affecting accepted ones.
- Accepted offers convert atomically through the existing invoice service into
  issued invoices with balanced postings, original lines, tax codes, amount type
  and notes. Invoices use the quote date, customer payment terms and the invoice
  series. Failed posting rolls back the invoice, numbering and conversion link;
  repeated and concurrent conversion returns the same invoice.
- Added viewer-readable and write-role, CSRF-protected API routes, a Documents
  Quotes view, multiple-line draft editing, status actions and confirmation of
  invoice posting on conversion. All four locales have append-only additions.
- Verified with offline service, API, migration and all-four-locale browser
  checks. Python 3.12.14, `python -m pytest -q`:
  `832 passed, 4 skipped in 595.30s (0:09:55)`. The four skips are existing
  opt-in PostgreSQL checks. No live provider calls were made.
- Quote email delivery, scheduling the daily expiry helper and production UAT
  remain deferred. Mark sent records status only, with explicit interface copy.

## 2026-10-12: Staged contact and item CSV import

- Added a shared master-data CSV pipeline with contact and item validators,
  tenant-scoped batches and rows, row-level errors and warnings, explicit commit
  and discard, created entity ids and audit events. Discard retains staged rows
  for audit. Existing records are skipped without updating local data.
- Commits apply valid rows atomically and serialise per organisation, preventing
  duplicate natural keys across concurrent batches and rejecting double commits.
  Contacts match by name or registry/personal code; items match by code.
- Migration `0019_master_data_import` adds staging tables, item unit and purchase
  price fields. The existing item unit price stores the imported sale price.
  Prices are exact decimals in the organisation's base currency; missing item
  accounts default to the standard sales and cost-of-sales roles.
- Added viewer-readable, write-role and CSRF-protected API routes, a settings
  import entry and a contact import action. Upload or paste CSV, inspect all
  row issues, then commit valid rows or discard. All four locales are updated.
- Verified with offline pytest service, API, migration and browser regressions,
  including rollback, concurrent batches, tenant isolation, malformed CSV,
  idempotency and all four locales. Python 3.12.14, `python -m pytest -q`:
  `764 passed, 4 skipped in 528.45s (0:08:48)`. The four skips are opt-in
  PostgreSQL checks. Production UAT remains pending.

## 2026-10-12: Cash-flow statement and comparative reports

- Added a read-only, tenant-scoped direct-method cash-flow service and authorised
  API route. Base-currency opening and closing liquid balances reconcile to
  external inflows/outflows. Classifications cover trade receipts, supplier
  payments, payroll roles, VAT, revenue, expenses, financing and Other. Account
  details retain journal memos, contact ids and per-bucket allocated amounts.
- Internal liquid transfers have equal gross inflows/outflows and zero net
  effect, and are excluded from headline totals. Ambiguous mixed journals match
  liquid sides first and allocate the remaining cash proportionally across
  opposite non-liquid contra amounts, with deterministic cent rounding.
- Added optional previous-period, prior-year and YTD comparisons to existing
  P&L and balance-sheet reports, keeping single-period callers compatible.
  Whole calendar periods use preceding calendar periods; custom ranges use equal
  day counts. Full prior-year periods honour leap-year month ends. YTD covers
  January through the selected end month against the prior calendar year.
  Balance-sheet columns remain cumulative snapshots at the two period ends.
- Added a cash-flow accounting view, liquid-account details, period presets and
  comparison selectors and columns. Appended translations in English, Estonian,
  Lithuanian and Latvian. No schema or configuration change is required.
- Scope and follow-up: only BANK-role accounts are liquid. Existing migrations
  preserve that role, and fresh charts seed it. The schema permits one account
  per role per organisation, while payment-service-created bank accounts have
  no BANK role. Including those accounts or storing multiple BANK roles needs a
  separate account-role/schema decision. The UI states the report's scope.
- Validation: Python 3.12.14, `python -m pytest -q`: `724 passed, 4 skipped in 482.16s (0:08:02)`. The four skipped tests
  are opt-in PostgreSQL checks. Service arithmetic, boundary and status tests,
  tenant isolation, split allocations, transfer netting, calendar/leap-year
  comparatives, upgrade preservation and browser views in all four locales
  passed. Existing translation keys and values are preserved; JavaScript
  syntax and diff checks passed. No live provider calls were made.

## 2026-10-12: Fixed assets and automatic depreciation

### Added

- Added additive migration `0018_fixed_assets` with tenant-scoped asset groups,
  acquired assets, reproducible depreciation runs and per-asset amounts. Added
  CI migration-list parity and migration expectations. Seeded charts and existing
  organisations receive fixed asset, accumulated depreciation and depreciation
  expense roles without repurposing custom accounts or existing roles. The
  service creates equipment 20%, computers 25% and other 10% default groups at
  first use with locale-appropriate names and monthly depreciation.
- Added atomic, immutable and balanced acquisition, depreciation and disposal
  events. Paid acquisition debits the fixed asset account and credits bank.
  Each acquired asset snapshots its policy and accounts; stable voucher keys
  make retries idempotent. Runs post one expense/accumulated-depreciation batch
  across eligible assets, tagged by asset id. Recorded zero-cent instalments
  advance the schedule without posting an empty batch.
- Added authorised tenant-scoped API routes for groups, acquisitions, disposal,
  runs, register and schedule through the existing web API mount. Added a fixed
  assets page with per-asset/group costs, accumulated depreciation and carrying
  values, run and schedule lists, and group, acquisition, disposal and manual-run
  dialogs. Added append-only copy in all four locales, using Estonian põhivarad,
  põhivara grupp and kulumi arvutus.
- Extended the existing default-off automation worker with due depreciation.
  Organisation failures are isolated and expose safe error messages, retaining
  the existing `FASTACCOUNTS_AUTOMATION_WORKER` gate.

### Accounting rules and boundaries

- Calendar month, quarter and year ends define due dates. The full acquisition
  period counts, without daily prorating. Each charge is the rounded cumulative
  straight-line target less prior charges, capped at acquisition cost, so the
  final period tops up exactly and accumulated depreciation never exceeds cost.
  One organisation/period/frequency run is reproducible and reruns return the
  stored result. Completed runs cannot absorb assets acquired afterwards.
- Disposal catches up every unpaid scheduled charge through the disposal calendar
  period in the same disposal batch, using full periods. It debits accumulated
  depreciation and bank proceeds, credits original cost, and posts any explicit
  gain to sales or loss to operating expenses. Acquisition and run records remain
  intact; disposed assets receive no further depreciation.
- Accountant UAT, acquisition reversal, tax-specific depreciation, residual values,
  revaluation, impairment, asset transfers and VAT/foreign-currency acquisitions
  remain follow-ups. Acquisitions require a bank payment in the organisation base
  currency. Dedicated disposal gain/loss accounts remain a follow-up; the current
  implementation uses existing sales and operating-expense roles.
- Validation: full pytest suite on Python 3.12.14 passed: 677 passed and four
  opt-in PostgreSQL tests skipped because `TEST_POSTGRES_URL` was not set.
  Critical acquisition, group, depreciation and disposal browser flows passed
  in all four locales. All 18 migrations match CI exactly and an immediate
  rerun is empty. Compilation, JavaScript syntax, append-only locale and
  staged diff/secret-pattern checks passed.

## 2026-10-12: Customer and supplier prepayments

### Added

- Added additive migration `0017_prepayments` with tenant-scoped prepayments,
  allocations and refunds, per-contact indexes, event idempotency keys and
  posting-batch links. Added the same migration to CI and migration expectations.
  Both seeded charts now contain supplier prepayments as an asset and customer
  prepayments as a liability. Existing organisations receive missing roles;
  custom accounts and existing roles are preserved, including code collisions.
- Added a repository and service for creating, listing, allocating and refunding
  prepayments, with an outstanding view per contact. Each event posts one balanced
  immutable batch in the same transaction as its records and balances. Customer
  receipts debit bank and credit customer prepayments; supplier advances debit
  supplier prepayments and credit bank. Allocation offsets the prepayment against
  contact-tagged AR/AP, without another bank movement, and updates document paid
  totals and Part Paid/Paid status. Refunds compensate only the unallocated amount
  through the original bank account, with links to the original batch and entries.
- Added authorised list/create/get/allocate/refund API routes and a contact
  outstanding route through the existing web API mount. Exact monetary responses
  use decimal strings. Sales and purchases have prepayment tables and dialogs;
  Contacts has an outstanding-prepayments dialog. Added append-only English,
  Estonian, Lithuanian and Latvian workspace copy.

### Validation and boundaries

- Tests cover both sides and country charts, balanced events and retries,
  concurrent allocation, status transitions, over-allocation, draft/credit/closed
  documents, locked periods, transaction rollback after posting, tenant/contact
  isolation, exact amounts, refunds and preservation of existing charts and books.
  Statement tests confirm allocation-only AR/AP movements and matching current
  ageing balances. Browser tests intercept every request and cover all four
  languages, validation errors, stable retry keys, refreshes and mobile dialogs.
- Prepayments currently require the organisation base currency. Reversing an
  allocation, foreign-currency advances/FX differences, bank-feed matching and
  VAT-on-advance/cash-VAT treatment remain follow-ups for accountant UAT. Refunds
  cannot consume an allocated amount. Existing historical document-ageing
  behaviour is unchanged; contact statements use dated immutable ledger entries.
- Validation: `python -m pytest tests/ -q --tb=short` passed with 627 tests,
  four optional PostgreSQL skips and five dependency deprecation warnings.
  The focused run passed 77 tests; the final eight browser cases passed, including
  the contact outstanding view. Fresh `db.migrate()` matches CI's 17 migrations
  exactly and reruns apply nothing. Compilation, JavaScript syntax, diff checks
  and append-only locale verification passed. Tests use synthetic data and
  intercepted browser requests. PostgreSQL checks require `TEST_POSTGRES_URL`;
  local validation used Python 3.14.6 because Python 3.12 is unavailable.

## 2026-10-12: Daily GoCardless bank feed worker

### Added

- Added additive migration `0016_bank_feed_schedules`, per-organisation/account
  daily schedules, last attempt/result, safe errors and timestamps. Updated the
  inline CI migration list, health migration count and all affected migration
  expectations, with an exact CI-list regression and a data-preserving upgrade
  check.
- Extended the existing opt-in automation worker to discover valid bank mappings
  and pull due accounts as `system`. Atomic claims prevent concurrent daily
  pulls. Discovery preserves inactive schedules until explicitly linked again.
  Missed days require one overlapping 90-day import; success, failure and
  interrupted attempts next become due tomorrow. Dates use the server calendar
  and timestamps use UTC. Existing imports remain idempotent and review-first.
- Isolated feed/account/organisation errors and recheck transient Error
  connections' consent on the next daily run. Reauth Required connections make
  no bank requests until consent and account mappings are restored. The worker
  retains its default-off switch and 60-second poll interval.
- Added a local authorised status GET route and a small integration-card section
  with last scheduled pull, result and renewal warnings, including when account
  loading fails. Added append-only copy in all four locales, using Estonian
  pangafeed and "Impordi kohe". Updated the worker description in `.env.sample`.

### Validation and boundaries

- Validation: `python -m pytest tests/ -q` passed with 582 tests, three optional
  PostgreSQL skips and one existing dependency warning. The final focused run
  passed 101 tests, including 12 intercepted browser cases across four languages
  covering mobile layout, manual pull refresh and expiry during account loading.
  Fresh `db.migrate()` matches CI exactly; reruns and preservation checks passed.
  Python compilation, JavaScript syntax and diff checks passed.
- Tests used synthetic feeds and blocked or intercepted HTTP. Live bank consent
  UAT, GB/EE coverage and legal/commercial acceptance remain pending. No automatic
  ledger reconciliation or payment initiation is added. Local validation used
  Python 3.14.6 because Python 3.12 is unavailable; optional PostgreSQL checks
  still require an explicit test database.

## 2026-10-12: Customer and supplier statements of account (PR6)

### Added

- Added `statements.py` for historical contact AR/AP statements with opening,
  chronological movements and closing balances. Include ledger-only opening
  receivables/payables and original/reversal batches; filter every ledger join
  by organisation. Customer and supplier statements remain separate.
- Added Decimal base and per-transaction-currency balances, plus EUR presentation
  amounts. For non-EUR base currencies, require an explicit positive rate per
  base unit and show it on the PDF. Amounts are rounded per movement so opening
  plus movements equals closing. No historical rate is inferred or fetched.
- Added authorised JSON and PDF GET routes under organisation contacts. The
  existing web API mount serves the Contacts download button and date/side/rate
  dialog using session authentication. PDFs use country-specific Estonian or
  English labels, embedded Unicode fonts, wrapping and repeated table headers.
  Added UI and validation copy to all four locales without changing old keys.
  No migration or configuration change is required.

### Validation and boundaries

- Targeted pytest checks cover historical arithmetic, reversals, opening imports,
  real invoices/bills/payments, currencies, tenant/contact isolation, empty
  statements, invalid inputs and authorised mounted web downloads. Playwright
  checks English/GBP and Estonian/EUR dialogs, error recovery, downloads and
  mobile layout using intercepted requests. A synthetic nine-page PDF was
  rendered and visually checked for wrapping, Unicode text and closing totals.
- Validation: the statement, browser, document, ledger, opening-balance, locale
  and API pytest files passed with 106 tests and one existing dependency
  deprecation warning. Python compilation, JavaScript syntax and diff checks
  passed. Tests used synthetic data and no live provider calls.
- Statements reproduce recorded control-account amounts. The explicit EUR rate
  is a presentation conversion, not historical valuation or FX revaluation.
  Accountant UAT and historical EUR rate sourcing remain pending; upstream
  currency posting, ageing and opening-item allocation changes are outside this
  task. Python 3.14.6 was used locally because Python 3.12 is unavailable.

## 2026-10-11: Estonian e-invoice export and purchase inbox (PR3)

### Added

- Added an isolated e-arve 1.2 XML writer with seller/buyer details, invoice
  lines, grouped VAT totals and optional organisation IBAN payment information.
  XML export accepts Issued, Part Paid and Paid invoices; drafts are rejected.
  The UK generic XML branch remains available. No migration or configuration
  change is required.
- Added namespace-independent purchase parsing with Decimal item arithmetic
  and declared net/VAT/gross consistency checks. Purchase upload creates a Draft
  bill with supplier resolution, tax-code matching by rate and original XML
  evidence. Duplicate supplier invoice numbers return an already-imported
  conflict. The Bills dialog has English, Estonian, Lithuanian and Latvian copy.
- Added the `einvoice_operator` Planning stub to the connector registry and
  integration catalogue. Its submission boundary raises `PermissionError`;
  Finbite/Omniva hosted delivery needs operator contracts.

### Validation and boundaries

- Verified `python -m pytest tests/ -q`: 510 passed, three optional PostgreSQL
  integration tests skipped, with only existing dependency deprecation warnings.
  English and Estonian import-dialog browser regressions ran with intercepted
  requests. `python -m compileall -q .`, JavaScript syntax and staged diff checks
  passed on local Python 3.14.6. No live provider calls were made.
- Synthetic writer/parser round trips and purchase fixtures verify internal
  declaration consistency. The writer is spec-faithful and review-gated, not
  live-verified against a schema/XSD. Accountant UAT and external schema/operator
  acceptance remain pending. No live operator delivery is implemented.
- Supplier matching uses tenant-scoped `registration_no` and `contact_type`
  supplier/both. Existing matched contacts retain their names. Contacts have no
  note column, so import provenance is stored on the draft bill and source XML
  evidence. Registry collisions and numeric zero-rate/reverse-charge tax-code
  choices require review. Bills already enforce uniqueness by organisation,
  supplier contact and supplier invoice number. Details are in
  [`e-invoices.md`](e-invoices.md), synchronised with roadmap section 35.
- Preserve valid inclusive VAT rounding during purchase intake, including
  recoverable VAT and subsequent balanced bill approval. Ordinary bill creation
  retains its existing net-based calculation unless validated VAT is supplied.

## 2026-10-11: Opening balances and opening receivables/payables (PR2)

### Added

- Added `opening_balances.py` with monthly period creation, balance-sheet
  snapshots and immutable opening postings. Only active Asset, Liability and
  Equity accounts are allowed; signed differences post to RETAINED_EARNINGS.
  Existing fiscal periods are preserved, including locked periods. No migrations
  or configuration changes are needed.
- Added CSV validation with row-numbered errors and customer/supplier totals.
  Imports create ledger-only AR debits/AP credits with contact IDs, due dates
  and original references, balanced by per-side retained-earnings lines.
  Contacts are reused within the tenant; invoice and bill documents are not
  fabricated. Contact creation and ledger posting share one transaction.
- Added viewer snapshots/previews and write-role, CSRF-protected posting APIs.
  Decimal preview amounts are returned as strings. A POST preview supplements
  the GET preview so file contents do not need to fit in a URL.
- Added Accounting dialogs with snapshots, per-account inputs, exact running
  totals, retained-earnings indicators, file preview/confirmation and copy in
  English, Estonian, Lithuanian and Latvian. File changes invalidate previews.

### Validation and boundaries

- `LedgerService.post` returns an existing batch for its organisation/type/ID
  key without checking changed inputs. The opening service compares submitted
  per-account debit/credit totals and dates before delegation, identifying input
  lines separately from generated offsets. Changed or reversed opening batches
  require a correcting journal; equivalent and empty no-op retries return the
  existing batch.
- Raw CSV voucher IDs are the first 16 SHA-256 hex characters of the exact UTF-8
  text. Different content creates a new batch; same-file retries return before
  creating contacts. Parsed-row API submissions hash canonical JSON of validated
  rows as a separate identity. Retry file uploads consistently as raw CSV.
  Organisation locks serialise concurrent imports; period rows are locked on
  PostgreSQL while validating a new posting.
- The plan's automatic retained-earnings remainder is implemented. Unequal
  input totals are balanced by that offset; invalid, negative, non-finite,
  sub-penny or two-sided lines are rejected, and the final batch must balance.
- Added synthetic pytest coverage for both countries, month extents and locks,
  offsets, retries, CSV errors, contact balances, rollback, tenant isolation,
  route shapes and access/CSRF, plus an intercepted desktop/mobile Playwright
  flow. No live provider calls are used.
- Accountant UAT, Estonian copy proofreading and settlement/ageing support for
  these ledger-only items remain follow-ups. Existing ageing and payment flows
  use invoice/bill documents. Imported AR/AP amounts must be excluded from the
  main opening journal to avoid double counting; both dialogs explain this.
- Verified `python -m pytest tests/ -q`: 457 passed, 3 optional PostgreSQL tests
  skipped, with 5 dependency deprecation warnings. The 44 opening-balance tests
  include concurrent retries, valid session-CSRF submissions and one-sided
  imports. JavaScript syntax, locale coverage and whitespace checks passed.
  Local validation uses Python 3.14.6 because Python 3.12 is not installed.

## 2026-10-11: Payment orders, supplier IBANs and attachments (PR1)

### Added

- Added migration `0015_payment_orders` and the payment-order service and API:
  eligible bill preview, exclusion reasons, currency totals, audited creation,
  history and pain.001.001.03 XML downloads with fixed two-decimal amounts.
- Added full bank and supplier IBAN storage alongside the existing bank mask,
  and IBAN inputs on existing contact and bank-account creation paths.
- Froze amounts, currencies, payer/payee names and IBANs, and remittance
  references, so later document or contact changes do not change the export.
- Added payment-order controls and history to bills, evidence sections in
  invoice and bill dialogs, and workspace copy in English, Estonian, Lithuanian
  and Latvian. No new standalone view is required.
- Wired invoice, bill and manual journal evidence upload, listing and download,
  with owner validation, duplicate refusal, bounded upload reads, safe filenames
  and SHA-256/size verification. Stored paths remain server-side.

### Validation and boundaries

- Added synthetic pytest coverage for candidates, transaction and ledger
  invariants, frozen XML, currency groups, tenant isolation, route shapes,
  evidence round trips, access roles and CSRF, plus a Playwright browser flow.
- Updated all migration-list and count assertions to the actual 15 migrations.
- Migration 0001 already stored masked bank IBANs; migrations 0011–0014 supplied
  no full IBANs or payment details. The shared audit helper, database transaction
  layer, Decimal money helper and existing evidence table are reused.
- Contact and bank-account update routes remain follow-up work. Bank acceptance
  testing is pending. Instructions do not record payments or post ledger entries.
- XML identifiers use UUIDs without hyphens: repository bill UUIDs are 36
  characters, exceeding pain.001's 35-character identifier limit. The stored
  bill ID remains unchanged; this is a reversible export representation.
- Verified `python -m pytest tests/ -q`: 413 passed, 3 optional PostgreSQL tests
  skipped, on local Python 3.14.6. Python 3.12 is not installed locally; CI
  remains configured for 3.12. JavaScript syntax and whitespace checks passed.

## 2026-10-11: Open sign-up switch

### Added

- Added the `FASTACCOUNTS_OPEN_SIGNUP` switch to the shared sign-in policy, so
  any verified address may create an account by mail or Google while production
  is early-stage. When absent or false, the v0.4.0 access rules apply unchanged.
- Documented the switch in the environment samples and the roadmap.

### Data and boundaries

- Existing throttles, confirmation-before-session, hashed single-use tokens and
  identical public outcomes are unchanged; the flag only widens access, never
  weakens throttling. A live production sign-up test remains follow-up work.

## 2026-10-11: Reviewed push pipeline

### Added

- Added migration `0014_sync_push`, prepared payloads and source references,
  with explicit review and execution for approved payroll and ledger journals.
- Added confirmed account-mapping coverage, exact Decimal amounts, tenant and
  EE/EUR gates, duplicate export refusal and manual retry after failure.
- Added thin API routes, payroll push history, provider mapping controls and GL
  reconciliation, with English, Estonian, Latvian and Lithuanian workspace copy.
- Added one offline synthetic SmartAccounts journal preparation and confirmed
  mappings, using all seven lines of the seeded payroll batch for exact review.

### Verification

- Offline pytest covers source gates, mappings, exact payloads, review changes,
  success, failures, explicit retry, listing, role/tenant isolation and reversals.
- Browser regression exercises prepare, review, execution permissions, mappings
  and reconciliation with intercepted requests and synthetic data.
- Documented contract · not live-verified. Production provider acceptance remains
  pending. Local export ownership uses the existing schema value `fastaccounts`.

## 2026-10-11: SmartAccounts reviewed accounting adapter

### Added

- Added company-key HMAC-signed accounts, clients, invoices, payments and manual
  ledger pulls, metadata-based pagination and bounded dated cursors. Added
  validated balanced EUR GL batch pushes, without row splitting or deletion.
- Registered SmartAccounts with encrypted key fields, language configuration,
  an original text logo and a synthetic encrypted Estonian demo connection.
- Added offline signature vectors, Tallinn DST, dispatch, pagination, validation,
  normaliser and connection tests; documented the contract in accounting-sync.

### Data and boundaries

- Documented contract only, not live-verified. Invoice rows require local
  account/tax review; payments require mapped invoices and bank accounts.
  External GL remains reconciliation data. Corrections use new reversal entries.
- No schema changes, local ledger changes or MeritProvider changes. Test-company
  acceptance and uncertain push reconciliation remain follow-up work.

## 2026-10-11: Merit reviewed accounting adapter

### Added

- Added signed, bounded Merit pulls for accounts, customers/vendors, sales and
  purchase invoice headers, payments and external GL entries, with next-window
  JSON cursors and Decimal amounts. Added GL batch pushes with 500-row chunks
  and sales invoice pushes through the existing invoice API.
- Added synthetic fixture tests and [accounting-sync contracts](accounting-sync.md).
  GL and accounting pulls remain documented contracts, not live-verified;
  existing invoice/payment/check APIs retain their production-use status.

### Data and boundaries

- Invoice headers require reviewed line/account enrichment; external GL remains
  read-only reconciliation data. Other income/expense payments carry a manual
  review warning. Customer/vendor server errors fall back to ChangedDate-filtered
  recent-year lists; older unchanged contacts need an earlier supplied cursor.
- No schema, local posting, credentials or configuration changes. GL corrections
  use reversal journals; provider GL deletion is unavailable. Chunked pushes are
  separate requests and require reconciliation before retry after partial failure.

## 2026-10-11: General reviewed-import data model

- Added migrations `0011_account_mappings`, `0012_external_gl`, and
  `0013_sync_review` for reviewed account suggestions, read-only external GL
  snapshots, generalized staged-record matches, and sync-review attribution.
- Generalized the reviewed pipeline for contacts, purchase and sales invoices,
  payments, accounts, and GL entries while retaining the existing employee
  import behavior. Applied invoices remain drafts, and payments are refused
  unless their local invoice or bill is already mapped.
- Added tenant-scoped account-mapping CRUD and GL reconciliation endpoints.
  Pulled GL rows remain external reconciliation data and are never posted to
  the FastAccounts ledger.

## 2026-10-11 — Excel workbook export pack

### Added

- Added native `.xlsx` downloads for payroll pay runs, the general ledger,
  invoices, employees and VAT returns. Payroll workbooks include summary and
  frozen-item reconciliation sheets, plus accounting lines when the run has a
  posted batch.
- Added the pay-run **Export workbook** action in English, Estonian, Latvian and
  Lithuanian, and authenticated report download routes with optional validated
  general-ledger date bounds.

### Data and boundaries

- These workbooks are rendered reports only. Exporting does not post, update or
  delete accounting data, and this change adds no database migration.
- Accounting calculations remain Decimal-based. Two-decimal EUR values are
  converted from `Decimal` to numeric Excel cells as float values so spreadsheet
  totals and filters work normally; cells use the `#,##0.00` number format.

### Verification

- `pytest -q tests/test_excel_export.py` — 6 passed in 1.68s.
- `pytest -q` — 325 passed, 3 skipped in 148.77s.

## 2026-10-09 — Accountant-reviewed Estonian TSD file export

### Added

- Added a tenant-scoped TSD preparation and review workflow for approved
  Estonian EUR pay runs, with one immutable payment record per employee.
- Added XBRL GL XML and transitional CSV downloads for reviewed manual upload.
  Gross, net and employer-cost totals must reconcile to the approved run before
  either format is serialized; all money remains `Decimal`-based.
- Added payroll-run actions and English, Estonian, Latvian and Lithuanian copy.
  The workspace labels the output **not live-verified against e-MTA** and keeps
  direct filing disabled.
- Added [`docs/tsd-export.md`](tsd-export.md), documenting every field, XBRL GL
  envelope element, classification label, assumption and current resident-only
  limit.

### Data and boundaries

- Added migration `0010_tsd_export`, which snapshots the employee personal ID
  on each pay-run item and backfills existing runs once. No posted ledger data is
  changed.
- TSD preparation uses `sync_runs` export records with an explicit accountant
  review gate. `EMTATSDExportProvider.submit()` always raises `PermissionError`;
  no X-tee, SOAP, e-MTA upload or other network client was added.
- The XML/CSV mapping is structurally tested but has not been uploaded to or
  accepted by e-MTA. Production accountant UAT remains pending.

### Verification

- Added offline tests for per-payment XBRL GL structure, CSV fields, Decimal
  total reconciliation, frozen personal IDs, EE/EUR and review gates, API file
  downloads, and the export-only provider boundary.
- The full suite passed: 324 passed and three optional PostgreSQL tests skipped;
  no live network calls were made.

## 2026-10-09 — Public-site audience and availability polish

- Split the landing into explicit paths for accounting bureaus managing payroll,
  payables and separate client books, and small businesses keeping their own
  books. Both paths now deep-link to their corresponding feature sections.
- Replaced the undifferentiated Fast* name strip with six localized product
  summaries, each with a distinct purpose and one link to the FastSME product
  catalogue.
- Standardized public availability language on **Available**, **Review
  required**, **Pilot** and **Planned** in English, Estonian, Latvian and
  Lithuanian. The public roadmap and integration cards use the same labels;
  VAT capability remains workpapers plus export, with direct filing Planned,
  and Estonian bureau payroll remains Review required pending production UAT.
- Reduced trust-page button competition to one primary and one secondary action
  at most, with any further contact paths rendered as quieter text links. Public
  page tests cover audience links, product-card differentiation, status mapping
  and CTA hierarchy.

## 2026-10-09 — Demo integration connections and employee imports

- Fresh local demo data now includes encrypted, synthetic Connected fixtures for
  QuickBooks and Xero on Northstar Studio Ltd, plus Merit and FastHR on
  Põhjatäht Teenused OÜ. Seed setup uses the normal connection and status
  services without making provider health checks or live network calls.
- The Põhjatäht integration workspace now includes a completed three-employee
  offline file import and a second import left at Review Required with pending
  rows, ready for the review-and-apply demo flow.

## 2026-10-09 — Local account email development links

- The local sign-up verification link is printed to the server log when test
  auth is enabled and mail is not configured; password-reset links use the same
  local-only behavior.

## 2026-10-09 — Website trust pages and roadmap

- Added localized first-party `/security`, `/privacy`, `/about`, `/contact` and
  draft `/terms` pages with evidence-based hosting, encryption, backup, access,
  incident, disclosure, controller/processor, subprocessor, retention, transfer,
  analytics, company, team, product-boundary and contact copy. The pages name
  unfinished production controls instead of implying unsupported assurance.
- Added localized `/roadmap` and `/changelog` pages with Now / Next / Later /
  Shipped sections, UK/Estonia market tags and release dates taken from this
  change log. The public history states that no 0.1.x release is recorded rather
  than manufacturing one; it lists the 0.2.0, 0.2.1, 0.3.0 and merged 0.4.0
  milestones.
- Reworked the public navigation and footer around Product, bureaus, trust and
  release-history destinations. Roadmap is now first-party; GitHub moved to the
  footer as Source. The footer identifies Predictive Labs Ltd and the working
  `info@predictivelabs.ai` sales/support contact.
- Clarified the bureau tax copy in English, Estonian, Latvian and Lithuanian to
  distinguish Estonian VAT (KMD) from UK VAT and state that export is available
  while direct filing is not. Added route, localized-copy and shared-shell tests
  for the complete change; no live network calls or accounting behavior changed.
## 2026-10-09 — v0.4.0: email and password sign-in beside Google SSO

- Added sign-up, sign-in and forgot/reset password with email and password on
  `/login`, next to **Continue with Google**, in English, Estonian, Latvian and
  Lithuanian. The forms reuse the existing sign-in card, buttons and design
  tokens; reset and email-confirmation pages use the same card.
- Ported the shared FastSME local-account pattern (FastHRM and FastClinic
  `web/account_auth.py`) into `web/account_auth.py`, storing accounts, hashed
  tokens and throttles in the main database through migration
  `0009_local_accounts` (SQLite and PostgreSQL).
- Security: scrypt password hashes (N=2^14, r=8, p=5; sister-format hashes
  still verify and are upgraded on sign-in); CSRF tokens on every auth form;
  per-email lockout after 10 failed sign-ins in 15 minutes plus per-address
  throttles for sign-in, sign-up, reset requests and token forms; identical
  responses and comparable timing whether or not an address exists; single-use
  reset links stored as SHA-256 digests and valid for one hour; email
  confirmation that re-asks the chosen password; session rotation on every
  sign-in (Google, email and test sign-in); and a password reset that signs the
  account out of every other session through a per-account session version.
- Linking: a Google login maps to the same account as the verified email
  address (and discards any unconfirmed password); Google-only members,
  including those who signed in before this release, can set a password with
  **Forgot password?**. Membership and invitation rules are unchanged and shared
  between both sign-in methods.
- Email goes through Postmark with the sister products' `POSTMARK_API_TOKEN` and
  `FROM_EMAIL`; links are built from `FASTACCOUNTS_PUBLIC_URL`, never from the
  request host. Without mail configuration, requests log a warning and show the
  generic message.
- Signing out now keeps the chosen interface language.
- Tests: unit, integration and security tests for every flow, a PostgreSQL
  account-flow test, and a Playwright register → confirm → sign out → reset →
  sign in run in English and Estonian. The user guide gains sign-in, account
  creation, forgotten-password and new-password pages (43 pages and 31
  screenshots per language).
## 2026-10-09 — User guide (English and Estonian) and regression walk-through

- Added a bilingual user guide covering every workspace area, with payroll for
  accounting bureaus in depth: part-time, hourly and board-member pay, the
  social tax minimum, pay runs, payslips, ledger postings, the reviewed FastHR
  import and the employee file import. 40 pages per language, text left and
  screenshot right, as PDF, HTML and PowerPoint
  (`docs/fastaccounts_user_guide_2026-10-09*.{pdf,html,pptx}`; sources
  `docs/USER_GUIDE.md` and `docs/USER_GUIDE_et.md`).
- Added `scripts/capture_user_guide.py`: 28 screenshots per language from an
  isolated, seeded local instance with a mocked FastHR API, doubling as a
  Playwright click-through of the whole workspace. Added
  `scripts/build_user_guide.py`, `scripts/build_guide_pptx.py` and
  `docs/assets/guide.css`, copied from FastShop's guide tooling (FastClinic
  pattern; bilingual editions as in FastERP). Rebuild steps are in
  `docs/USER_GUIDE_BUILD.md`.
- Regression pass on 0.3.0 (after #11 and #12): full suite on Python 3.13
  (PostgreSQL and Playwright) and 3.12, the workspace walk-through in English
  and Estonian, and a read-only smoke test of the public pages on
  fastaccounts.org found no regressions. No application code, design or
  migration changed, so the app version stays 0.3.0; `screenshots/` is excluded
  from the Docker image.

## 2026-10-09 — Personio and BambooHR documented-contract adapters

- Added pull-only Personio and BambooHR employee adapters against their published
  HTTP contracts, including Personio JSON body token exchange and complete offset
  pagination, and BambooHR API-key Basic authentication and whole-directory reads.
- Mapped names, email and source status without inventing payroll data. Gross
  salary remains absent unless a tenant supplies a reviewed `salary_attribute`
  or `salary_field_id` alias, so the existing per-row review pipeline reports
  `Gross salary is required` and continues the batch when no mapping exists.
- Registered both as `Documented contract · not live-verified`, with encrypted
  credential metadata, localized catalogue copy and mocked contract, connection,
  staging and failure-path tests. No vendor credential or live network was used;
  production import remains gated on customer credential verification and
  accountant review.

## 2026-10-09 — Universal employee file import

- Added an offline `file_import` connector for employee CSV and TSV exports from
  any payroll or HR system, with English and Estonian header aliases, delimiter
  detection, exact Decimal salary parsing and deterministic row identifiers.
- Added a connection-free owner/administrator import endpoint and workspace file
  picker with paste fallback. Parsed records enter the existing tenant-scoped
  review/apply pipeline; raw upload contents are not stored or written to audit
  payloads.
- Added four-locale catalogue and workspace copy plus parser, deduplication,
  idempotent apply, refusal, tenant workflow and browser coverage. Native Excel
  workbooks remain out of scope and must be exported as CSV first.

## 2026-10-09 — Release 0.3.0: recurring invoices, integrations and FastHR import

Release 0.3.0 bundles Joosep Laats' (jeeqe) merged work since 0.2.1, detailed in
the entries below, plus one connector fix:

- #5 recurring invoices and the payment-reminder ladder (migration
  `0007_automation`, renumbered after payroll's `0006`).
- #7 integration connection lifecycle: encrypted per-client credentials,
  configure/test/disconnect.
- #8 reviewed employee-import pipeline (migration `0008_import_staging`).
- #9 FastHR employee connector (pull-only).
- #10 integrations workspace UI with staged employee review.
- Fix: FastHR `base_salary` is an annual amount (FastHR shows it "/aastas" and
  its own payroll divides by 12). The connector now imports monthly gross =
  base_salary / 12, rounded half-up to cents (30,000 → 2,500.00); previously
  the annual figure was stored as monthly pay. FastHR `working_time_ratio` maps
  to the work-time fraction (FTE, default 1) and `personal_code` (isikukood)
  to the personal ID, which also improves employee matching. Staff with no
  salary but an hourly rate import as hourly pay. A record with neither, or
  with a work-time ratio outside 0–1, is staged with a translated review note
  and skipped on apply instead of failing the sync; an already linked employee
  keeps its local pay terms. No migration and no UI change.
- Version chip `v0.3.0 · 2026-10-09`; the public footer version link carries
  `data-testid="app-version"` again (attribute only, no markup or style change).

## 2026-10-09 — Integration workspace

- Added the signed-in Integrations workspace for owner/administrator connection
  setup without command-line calls: adapter-ready providers are prioritised,
  credential fields come from the connector registry, secret inputs are never
  prefilled, and users can configure, test and disconnect each client connection.
- Added the FastHR employee-import workflow from sync through tenant-scoped staged
  review. Reviewers can approve, reject or retry failed rows, inspect source data
  and local employee matches, apply a mixed batch, see per-outcome counts and
  reasons, and return to recent import runs.
- Localized the complete workspace flow in English, Estonian, Latvian and
  Lithuanian and covered the server-rendered workspace entry and locale-key
  parity. No migration or live provider test was added.

## 2026-10-09 — Finance connector health checks

- Wired the QuickBooks, Xero and Merit registry entries to their real provider
  classes so adapter-ready connection tests now make credentialed, company-scoped
  health requests instead of returning no-network planning-stub results.
- Added redacted success, authentication-failure and timeout handling for all three
  providers, including QuickBooks sandbox selection, Xero tenant authorization and
  Merit HMAC signing. HMRC, e-MTA and open banking remain planning stubs, and no
  finance connector was added to the reviewed import pipeline.
- Verified request shapes, real-provider registry construction, credential
  redaction and tenant connection status transitions using mocked HTTP transports;
  automated tests make no live provider calls.

## 2026-10-09 — FastHR employee connector

- Added the first live HR adapter: a pull-only FastHR employee-master import for
  accounting-bureau payroll, with bearer authentication, connection checks and
  complete offset pagination over the FastHR employee API.
- Normalized names, active status and exact two-decimal base salary values for
  the reviewed employee-import pipeline, while preserving selected FastHR source
  fields in staged payloads. FastHR does not supply isikukood, funded-pension or
  board-member settings, so the adapter does not invent them.
- Registered tenant-configurable base URL and encrypted token credentials, added
  localized catalogue copy and a neutral placeholder mark, and verified mocked
  success, authentication, connection, pagination, staging and idempotent apply
  paths without live provider calls.

## 2026-10-09 — Reviewed employee-import pipeline

- Added a tenant-scoped staging area for connector employee records. Pulls use
  stored encrypted connection credentials, preserve provider cursors, deduplicate
  repeated external IDs within a run, and suggest unique employee matches by
  email or personal ID without writing payroll data.
- Added owner/administrator review APIs to inspect staged payloads, apply or
  reject selected rows, and triage recent sync runs. Employee creation and updates
  reuse payroll validation and exact Decimal quantization; invalid rows become
  reviewable conflicts while the rest of the batch continues.
- Added idempotent external mappings, audited row outcomes without payload blobs,
  tenant/role/CSRF coverage, and no-network connector tests including roadmap-stub
  and failure paths.

## 2026-10-09 — Integration connection lifecycle

- Added one connector registry covering all 26 public catalogue providers, with
  ordered configure-dialog credential metadata and explicit adapter-readiness
  labels. The 20 HR/payroll entries use no-network roadmap stubs until their
  reviewed adapters are built.
- Added owner/administrator APIs to list tenant-scoped connections, test
  payload credentials without persisting them, record tested connection status
  with an audit trail when a connection exists, and disconnect a provider.
- Kept credential values and encrypted material out of every API response;
  provider checks remain fake/stubbed in automated tests and make no live
  network calls.

## 2026-10-09 — HR and payroll software catalogue

- Added 20 global and Estonian HR/payroll providers to the public integration
  catalogue as potential employee-master-data and payroll-input sources for
  accounting-bureau payroll.
- Labelled every provider `Roadmap · no adapter yet`, with reviewed import-first
  direction and per-object ownership; no adapter readiness or live connection
  is claimed.
- Added complete English, Estonian, Latvian and Lithuanian catalogue copy and
  landing FAQ scope wording, plus neutral placeholder marks that are explicitly
  documented as non-official artwork.
- Added catalogue and four-locale rendering coverage. Provider network access
  is not exercised by tests.

## 2026-10-08 — FastSME public landing presentation

- Ported the FastHRM public design system with self-hosted Bricolage Grotesque
  and Hanken Grotesk fonts, ink/lime colours, pill buttons, a sticky navigation
  bar and a plain F brand tile. The existing favicon is unchanged.
- Rebuilt the landing with a dark hero, inert synthetic accounting dashboard,
  suite band, numbered features, accounting-bureau split, two pricing cards,
  five FAQs, closing CTA and product/resource footer. The dashboard overlaps
  the hero on desktop and is hidden at widths of 680px or less.
- Localized the new content in English, Estonian, Latvian and Lithuanian,
  including the payroll demo/UAT and integration limitations. Translated the
  existing Latvian/Lithuanian bureau, pricing and navigation placeholders.
- Applied the shared shell to integrations and sign-in, retaining routes,
  language selection and authentication behaviour. A single language dropdown
  moves into the mobile menu without duplicate IDs. Workspace rendering and
  accounting workflows are unchanged; roadmap scope and status are unchanged.
- Verified 30 public/i18n tests, render smoke checks for all 12 page/language
  combinations, and Chromium desktop/mobile screenshots and menu interactions.
  The repository virtual environment uses Python 3.14.6; Python 3.12 runtime
  verification was not performed. Preview servers were stopped after checks.

## 2026-10-08 — Payroll 0.2.1: part-time, hourly pay and social tax minimum

- Migration `0006_payroll_part_time_hourly` (SQLite rebuilds `employees` to
  relax the pension CHECK; PostgreSQL uses an ALTER-based equivalent in
  `database.py`). Employees gain `pay_basis` (monthly | hourly | board_fee), `fte`,
  `hourly_rate`, `social_tax_minimum_exemption` and employment start/end dates;
  pay-run items freeze pay basis, FTE, rate, hours, the applied minimum wage,
  social tax base, minimum top-up and exemption reason. Existing items are
  backfilled with `social_tax_base = gross`; posted ledger lines are untouched.
- Part-time: the minimum wage is pro-rated by FTE (EUR 946 × FTE from
  01.04.2026, EUR 886 × FTE before; Vabariigi Valitsuse määrus nr 36), which
  stops part-time staff being rejected wrongly.
- Hourly pay: gross = hourly rate × hours entered in the "Run payroll" wizard
  or API `hours`; minimum hourly rate EUR 5.67 from 01.04.2026 (EUR 5.31 before).
- II pillar 0% is allowed for anyone who has not joined it, not only board members.
- Social tax minimum obligation: social tax is charged on at least EUR 886/month
  (EUR 292.38) in 2026, with the shortfall posted as a separate employer-cost line
  on 6120/2240 ("Sotsiaalmaksu miinimumkohustuse lisamakse"). Pro-rated by
  calendar days when employment starts or ends mid-month; never applied to board
  fees; per-employee exemption reasons cover the EMTA list (state pension, partial or
  no work ability, child care, student, previously unemployed, shortened working
  time, council member, ship crew, foreign-service spouse, working on long-term sick
  leave, absent the whole month, multiple employers). Sources: EMTA "Sotsiaalmaks"
  (updated 20.07.2026) and "Maksumäärad", SMS § 2 lg 2–4, määrus nr 17. Details
  and the items still out of scope are in `docs/payroll_rules.md`.
- The basic exemption shown on items and payslips is now the amount actually used,
  capped at the taxable pay (income tax is unchanged).
- Employee form, payroll wizard (hours per hourly employee), run breakdown (social
  tax with top-up, hours, part-time) and payslips (rate × hours, FTE, social tax
  base, top-up, exemption) updated. All new labels, errors and the top-up memo are
  in the en/et catalogues (lv/lt carry English fallbacks); named server errors are
  translated in the browser.
- Demo seed adds a "Demo OÜ (sample payroll)" organisation with the seven sample
  employees (full-time, part-time 0.5 FTE, hourly, II pillar 0/2/4/6%, board fee),
  an approved September 2026 run and an October 2026 draft (gross 16,254.00, net
  12,480.00, employer cost 21,797.23). Existing demo books are unchanged.
- Tests: the seven sample employees match the earlier October 2026 calculations to
  the cent. Added coverage for pro-rated and hourly minimum wages, hours validation,
  exemptions, partial months, ledger posting of the top-up, API, the SQLite and
  PostgreSQL 0006 upgrades, translations and seed repeatability. 110 passed on
  Python 3.13 with PostgreSQL 17 and Playwright enabled; on Python 3.12 (the Docker
  runtime) 107 passed, with the 3 browser tests skipped because Playwright was not installed.
- Version 0.2.1; the `VERSION` file now has the release date on line 2, and the
  workspace sidebar shows the `v0.2.1 · 2026-10-08` chip (`data-testid=app-version`).
- Added `docs/payroll-plan.md` (bureau payroll discovery and plan).

## 2026-10-08 — Estonian accounting-bureau payroll demo

- Added tenant-scoped employee and monthly payroll APIs, frozen calculations,
  minimum-wage validation, conflict handling, and multi-page payslip PDFs.
- Added payroll migration and EE expense/liability accounts for existing and
  future books; approval posts one balanced batch atomically at month-end.
- Extended the EE seed with six named synthetic employees, three approved
  runs (July, August, September 2026), and an October draft. Reruns preserve
  existing records and immutable posted snapshots.
- Added payroll math, workflow, isolation, PDF, migration and seed tests.
- Localized EE payslips with Unicode font embedding, employer registration,
  TSD review/UAT wording and the following-month tax deadline; Docker installs
  DejaVu and fontless environments use transliteration.
- Enriched each fresh UK/EE book with five customers, five suppliers, 18 invoices,
  eight bills and 28 bank transactions, including reconciled and pending matches.
- Gated payroll requests and navigation to EE/EUR books, added a localized
  scope notice and neutral KPI, and consolidated payroll error handling.
- Added browser regression checks for both languages, non-EE/non-EUR books,
  organisation switching and a single toast on payroll request failure.
- Completed the demo locale pass: country-specific contact/bank names and
  references, Demo Kasutaja test-login identity, Estonian payroll account names,
  and translated unmatched-bank status in all Baltic workspace catalogues.
  Verified seeded Estonian tax names through the API and browser; seed amounts,
  dates, balances and tax mappings are unchanged. The full suite passed (78
  passed, one optional PostgreSQL test skipped), including browser regressions,
  on local Python 3.14; Python 3.12 was not installed for target-runtime verification.
  Existing-database account names are not migrated; fresh books use the seed
  constants. Backend validation errors and stored payroll memos can still be English.
- Accounting-bureau payroll is in demo scope; production accountant UAT pending.

## 2026-08-10 — Engineering pilot 0.2 completed

### Added

- Added the FastHTML bookkeeping workspace and typed FastAPI/OpenAPI workflows
  for multi-organisation setup, contacts/items, invoices/credits/PDF/email/XML,
  bills/credits/evidence/approvals, bank accounts, payments and allocations.
- Added portable SQLite/PostgreSQL migrations for core accounting, coexistence,
  operational governance, and database-level document immutability.
- Added exact `Decimal` tax calculations, atomic sequences, balanced immutable
  posting batches, reversals, period locks, audit events, manual journals,
  general ledger, trial balance, P&L, balance sheet, cash and AR/AP aging.
- Added idempotent CSV/CAMT.053 import, explainable suggestions, single/split
  reconciliation, month-end checklists, retention holds, and hashed exports.
- Added UK accrual/cash VAT workpapers and Estonian KMD/VD preparation with an
  accountant-review gate before export.
- Added encrypted integration connections, explicit ownership/direction,
  mappings, cursors, conflicts, outbox/webhook replay records, QuickBooks/Xero
  OAuth adapters, Merit HMAC/retry adapter, guarded HMRC VAT adapter, export-only
  e-MTA boundary, and read-only GoCardless Bank Account Data adapter.
- Added synthetic UK/EE demo books, CI, Docker persistence, FastDevOps/Coolify
  registration, accounting invariants, threat model, and accountant UAT pack.

### Security and configuration

- Added CSRF and cross-tenant API checks, invite tokens stored only as hashes,
  key-versioned Fernet credential encryption, attachment size/path/hash checks,
  provider submission gates, and database/identity health reporting.
- Added `FASTACCOUNTS_ENCRYPTION_KEY`, data-directory, CORS, attachment-size,
  and test-auth settings to `.env.sample`. Test auth is hard-disabled by default.
- Registered `fastaccounts.org` in FastDevOps with its own PostgreSQL schema,
  generated secrets, persistent evidence storage, Google callback and health check.

### Verification

- Passed 48 synthetic pytest checks (plus an opt-in real PostgreSQL check),
  Python compilation, migration rerun/data-preservation checks, provider mock
  contracts, Docker configuration/build checks, and secret-pattern scans.
- Browser-verified authenticated dashboard, invoice draft/issue workflow, PDF/XML
  links, zero console errors, and responsive 390px navigation using Chrome.

### Release gates

- Engineering tasks through the connector/open-banking candidate slice are
  implemented. UK and Estonian accountant sign-off, provider test-company
  credentials, HMRC production approval, e-MTA X-Road access, and open-banking
  legal/commercial approval remain external gates and are still labelled unavailable.

## 2026-08-10 — Public foundation and integration catalogue

### Added

- Added the responsive FastAccounts landing page, top-right Sign In control,
  public `/integrations` catalogue, `/healthz`, version identity, and a guarded
  foundation workspace.
- Added QuickBooks, Xero, Merit Aktiva, HMRC, Estonian Tax and Customs Board,
  and open-banking cards with logos/service identifiers, markets, capabilities,
  direction, record ownership, provider documentation, and unambiguous status.
- Added typed connector contracts and explicit no-network stubs for all six
  planned providers.
- Added server-side Google OAuth start/callback routes with state validation,
  verified-email and allow-list checks, plus a useful disabled configuration
  path.
- Added Python dependencies, Docker/Coolify-shaped container files, local run
  instructions, a favicon, and integration trademark notices.

### Data and configuration

- No accounting database or migration was introduced. No connector reads a
  credential or performs a network request.
- Uses the previously documented `FASTACCOUNTS_*` and Google OAuth environment
  placeholders; `.env` remains ignored.

### Verification

- Passed 14 pytest checks covering public routes, assets, accessible logo text,
  integration status, auth guards, OAuth state rejection, health identity, and
  no-network stub behavior.
- Browser-verified landing, Integrations, and disabled sign-in flows at 1440px
  desktop and 390px mobile widths using Chrome.

### Roadmap

- Marked only the delivered public/integration slice of Phase 0 complete. The
  organization, database, ledger, invoice, RBAC, CSRF, and country-pack work
  remains open.

## 2026-08-10 — Product direction confirmed

### Changed

- Set concurrent UK and Estonia delivery rather than a country-first sequence.
- Included UK/Estonian incorporated entities and sole traders/FIEs in the core
  model.
- Made coexistence with QuickBooks Online, Xero, and Merit Aktiva an explicit
  requirement with visible ownership, direction, and conflict controls.
- Set accountant-reviewed workpapers/exports as the first compliance promise;
  direct tax filing remains a clearly labelled agent/connector plan.
- Recorded later UK and Estonian accountant UAT as the professional-validation
  gate for country packs.

### Data and configuration

- No migration or new secret was introduced by these decisions.

### Verification

- The product owner supplied the decisions directly; implementation and UAT
  remain pending.

### Roadmap

- Replaced the open product questions with confirmed decisions and retained the
  unresolved production-level ownership, hosting, banking, and payment choices.

## 2026-08-10 — Researched product baseline

### Added

- Defined the focused bookkeeping boundary, target architecture, accounting
  invariants, UK and Estonia country packs, provider-adapter strategy,
  open-banking roadmap, security gates, phased delivery plan, and product-owner
  decisions.
- Added a secret-free `.env.sample`, accounting-safe ignore rules, repository
  guidance, and a planning README.

### Data and configuration

- No database, migration, runtime application, provider credential, or real
  accounting data was added.
- Reserved local port 5012 and documented proposed environment-variable names;
  all provider integrations remain planned and disabled.

### Verification

- Cross-checked current official documentation for QuickBooks, Xero, Merit,
  HMRC, Estonian VAT/accounting rules, and open-banking candidates.

### Roadmap

- All implementation phases remain unchecked. No capability is represented as
  production-ready or compliant.


## 2026-10-08 — Violet public-site redesign

- Replaced the public ink/lime palette with violet accents, white-on-accent
  controls, deep violet ink and pale violet surfaces. Preserved self-hosted
  fonts, responsive navigation, mobile action placement, scroll locking,
  Escape handling, skip links, focus states and reduced-motion support.
- Added a gradient hero, browser-framed synthetic dashboard with three inert
  glass cards, a four-step bureau workflow, an old/new comparison, factual
  product stats and five native details/summary FAQs. Restyled the existing
  feature, bureau, pricing, CTA and footer sections, integrations and sign-in.
- Added 29 landing keys in English, Estonian, Latvian and Lithuanian. Existing
  pricing and FAQ copy is unchanged; bank connectivity and direct filing
  limitations remain explicit. Roadmap scope and status are unchanged.
- Verified the full pytest suite: 95 passed, one optional PostgreSQL test
  skipped, on local Python 3.14.6. Checked 36 offline browser renders across
  all four languages, three public pages and desktop/tablet/mobile widths,
  including overflow, FAQ keyboard operation and mobile menu behaviour.
  Inspected desktop/mobile screenshots; no external network access was used.


## 2026-10-08 — Workspace violet retheme and org switcher fix

- Rethemed the signed-in workspace (static/app.css) to the violet palette:
  a violet-600 accent with a violet-800 strong accent, deep violet ink for
  the sidebar and dark surfaces, violet-tinted neutral scale, violet-tinted
  selection and shadows. Accounting behaviour, templates and routes are
  unchanged.
- Fixed the company switcher: the org menu now opens downward from the
  trigger (8px gap) instead of upward, so it no longer collides with the
  topbar or clips mid-list, at both desktop and mobile widths.
- Verified with Playwright menu geometry at 1440x900 and 430x900, org
  selection, Escape/outside-click closing, and the full pytest suite:
  95 passed, one optional PostgreSQL test skipped, on local Python 3.14.6.
  No external network access was used.

## 2026-10-08 — Automation demo: recurring invoices and payment reminders

- Added recurring invoice schedules for UK books with weekly, monthly, quarterly
  or custom-day intervals, an optional end date and optional auto-email. Due
  schedules issue ordinary invoices through the standard sequential numbering and
  immutable balanced ledger path; catch-up covers up to 24 missed periods, one
  transaction per period. Idempotency uses a compare-and-set next-run claim plus a
  unique (schedule, period) constraint, so restarts and concurrent ticks never
  double-issue and repeated runs over the same period issue nothing.
- Added a three-stage payment-reminder ladder (3 days before due, then 7 and 14
  days overdue), derived from each invoice's due date, with per-stage send events
  (never double-sent, including on failure) and per-invoice opt-out.
- Sends use the existing Postmark delivery path only: with POSTMARK_API_TOKEN or
  FROM_EMAIL unset nothing is sent and no success is faked. The recurring view
  shows a localized "email not connected" notice, the integrations page gained an
  email-connection status card (provider and masked sender, no credentials), and
  manual sends fail with an explanatory message. A background worker is available
  for deployments via FASTACCOUNTS_AUTOMATION_WORKER (default off and never started
  in tests; FASTACCOUNTS_AUTOMATION_POLL_SECONDS, default 60s); .env.sample documents
  both. No real email is sent in the demo.
- Workspace gains a localized "Recurring & reminders" view (schedules table,
  new-schedule dialog, pause/resume, run now with history, reminders-due table with
  per-stage send and skip actions) in English, Estonian, Latvian and Lithuanian;
  Estonian copy checked with Estonian spelling/morphology tooling. The demo UK book
  gains an idempotent "Retainer – Willow Design" monthly schedule whose next run is
  7 days out; reminder stages are exercised by the existing overdue demo invoices.
- Renumbered the automation migration from `0006` to `0007` because payroll's
  `0006` shipped first in v0.2.1.
- Verified the full pytest suite: 147 passed, one optional PostgreSQL test skipped,
  on local Python 3.14.6, including service tests for issue/restart idempotency,
  catch-up, ladder boundaries, opt-out and unconnected-email failure (MockTransport;
  no live network), API tests, i18n parity and a Playwright workspace regression.
  Accountant UAT for reminder copy and real delivery remains pending. No external
  network access was used.

## 2026-10-11: GoCardless read-only bank feed (PR4)

- Added GoCardless Bank Account Data token acquisition, one-time HTTP 401 refresh,
  bank selection and consent link completion. Stored user secrets use the existing
  key-versioned Fernet vault; persisted access tokens are encrypted and excluded
  from public connection responses.
- Added tenant-scoped mapping to existing bank accounts, account balances and
  manual 90-day booked transaction imports with source-hash and row-fingerprint
  idempotency. Outgoing amounts remain negative; incoming amounts remain positive.
- Added the connectable integration card and consent, mapping and pull controls
  with English, Estonian, Lithuanian and Latvian translations.
- No migration or background worker. Consent may last around 180 days depending
  on the bank and agreement, and renewal requires re-linking. The documented
  default agreement currently gives 90 days of account access; API access tokens
  have a separate, shorter expiry. Live consent UAT remains pending.
- Verified using synthetic providers and httpx MockTransport, with no live bank
  endpoints. Roadmap scope is synchronised in `docs/product_roadmap.md`.
- Validation: `python -m pytest tests/ -q`: 533 passed, three optional PostgreSQL
  skips and existing dependency deprecation warnings. `python -m compileall -q .`,
  JavaScript syntax and diff checks passed. The existing integration browser test
  was updated for seven connectable cards; no new bank-consent browser test was
  added. Validation ran on installed Python 3.14; Python 3.12 is unavailable.

## 2026-10-11: KMD reverse-charge and ICS coverage (PR5)

- Audited seeded EE kinds and verified the EMTA KMD form. Qualified case (a):
  EEICS evidences supply; generic EERC cannot select detailed acquisition or
  special-arrangement fields. The proposed meanings for lines 7/8/9/11 differ
  from the official form, so those remain absent with classification warnings.
- Included posted intra-Community sales in line 3 and added the line 3.1 subset
  only when evidence exists, retaining credit signs and Decimal cash weighting.
- Added warnings for ambiguous reverse charge, supply-kind purchases and missing
  goods/service separation, with translations in all four locales.
- Added synthetic regression coverage for amounts, credits, cash weighting,
  draft/period/tenant exclusion, warning deduplication, UK isolation and CSV
  export. Documented existing field limitations and follow-ups in `docs/kmd.md`;
  roadmap scope is synchronised. No migration, tax-code or filing change.
- Validation: `python -m pytest tests/ -q`: 542 passed, three optional PostgreSQL
  skips and five existing dependency deprecation warnings. Targeted tax/locale
  checks, compilation and diff checks passed. Tests used synthetic data and no
  live providers. Python 3.14.6 was used because Python 3.12 is unavailable.

## 2026-10-12: Purchase periodisation

- Added P1 item 8 purchase schedules and per-period rows with migration
  `0021_periodisation`, composite tenant foreign keys, CHECK constraints and
  idempotent additive chart roles. Existing custom codes, roles, bills and posted
  ledger data are preserved. CI and all explicit migration assertions include
  the new migration.
- Draft bill approval books the full net cost to Periodised expenses in transit.
  Already posted bills gain a balanced reclassification on their original bill
  date, without changing the original bill or ledger lines. Equal monthly
  portions then debit real expense and credit deferred cost in one immutable
  balanced batch each. Assign the cent remainder to the first or last portion.
- Keep full input VAT deduction on the original bill. Portions contain zero VAT
  and leave AP and payment allocation unchanged. Validate the schedule against
  the whole real bill's net amount; support base-currency expense bills with
  fully recoverable VAT or no VAT.
- Added Draft activation, single-period and catch-up posting, progress, audit
  entries, locked-period guards, atomic journal links, concurrent retry safety
  and a daily automation-worker check with failure isolation. Cancellation only
  stops future Pending portions after due portions are posted. Posted journals
  remain intact; any funded deferred residual requires accountant review and an
  explicit adjustment.
- Added viewer-readable and write-role/CSRF-protected API routes with decimal
  strings, plus the Documents Periodised view, creation and detail dialogs,
  progress and posting/cancellation confirmations. New translation blocks are
  appended at the end of English, Estonian, Lithuanian and Latvian files without
  altering existing keys or copy. The design note explains ledger and VAT timing.
- Validation: Python 3.12.14, `python -m pytest -q`:
  `881 passed, 4 skipped in 652.14s (0:10:52)`. All 49 new feature checks passed,
  including offline browser flows in all four locales. The four skips are
  existing opt-in PostgreSQL checks. No live provider calls were made. JavaScript
  syntax, focused Python compilation, locale preservation and diff checks passed.
- Production accountant UAT, partial VAT recovery, foreign currency, irregular
  periods, monetary schedule editing and coordinated reversals or cancellation
  settlement remain deferred. Roadmap status and scope are synchronised.

## 2026-10-12: Payment link configuration

- Added the offline configuration slice of P1 item 9: organisation payment methods
  for EveryPay, LinkPay and custom URLs, plus persistent invoice/method links with
  stable unpredictable tokens. Migration `0022_payment_links` is additive and
  rerunnable, with composite tenant foreign keys and concurrent generation guards.
  Updated the inline CI migration list and all explicit migration expectations.
- Added validated HTTPS templates with Decimal-formatted total and due amounts,
  URL-encoded values, currency matching and optional currencyless methods. Hide
  disabled methods and ineligible invoices without deleting stored links. Refresh
  resolved URLs on later reads while preserving their tokens and creation times.
- Added viewer-readable configuration and invoice-link endpoints, invoice detail
  payloads, owner/administrator configuration writes and CSRF protection. Payment
  links do not initiate provider calls, post ledger entries or mark invoices paid.
- Added a small Settings Payment methods view and create/edit dialog, plus payment
  buttons, read-only URLs and copy controls in the authenticated invoice dialog.
  Appended all four locale sections and generalised the explicit catalogue merge.
  Existing translations and invoice PDF/XML routes are preserved.
- A public invoice page, provider HTTP integration, callbacks, payment verification,
  automatic reconciliation, provider-side revocation and production UAT remain
  deferred. Already shared URLs require merchant-side balance and expiry controls.
  The design note documents these limits; roadmap scope is synchronised.
- Validation: Python 3.12.14, `python -m pytest -q`:
  `916 passed, 4 skipped in 674.84s (0:11:14)`. All 35 new service, API,
  migration, locale and four-locale browser checks passed. The skips are existing
  opt-in PostgreSQL checks. Tests used synthetic data and no live provider calls.
  JavaScript syntax, focused Python compilation, existing locale preservation,
  diff and staged secret-pattern checks passed.

## 2026-10-12: Analytical objects

- Added the missing analytical object catalogue and tenant-scoped service/API,
  with four semantic types, audited admin CRUD and deactivation of used objects.
  No project/dimension primitive existed on the payment-links base branch.
- Added optional invoice, bill and journal line dimensions, persisted alongside
  their immutable parent lines through additive migration 0023. Composite foreign
  keys enforce tenant, parent and type. Posted tags cannot be inserted, edited
  or deleted; reversals preserve historical tags, including inactive objects.
- Kept tagged revenue groups separate and carried expense/non-recoverable tax
  tags into postings. Purchase deferrals and rounded portions retain exact
  dimension totals; recurring invoices inherit their source invoice's tags.
- Added object filters to general ledger, trial balance and P&L with matching
  comparison filters. Added Settings object management, invoice/bill selectors,
  report controls and appended English, Estonian, Lithuanian and Latvian copy.
  Updated CI and every migration count/list assertion.
- Documented deferred merging, multiple/combined dimensions, journal SPA editing,
  quote/schedule dimension authoring, dimension exports and production UAT.
  Existing historical rows are preserved and PostgreSQL checks remain opt-in.
- Validation: Python 3.12.14, `python -m pytest -q`:
  `936 passed, 4 skipped in 741.21s (0:12:21)`. All 20 new analytical object
  checks passed, including browser flows in all four locales. The skips are the
  existing PostgreSQL opt-in checks. JavaScript syntax, Python compilation,
  existing locale preservation, desktop/mobile visual review, diff and staged
  secret-pattern checks passed. All data used by the new tests is synthetic.

## 2026-10-12: Invoice list exports and filters

- Added shared read-only list selection in a tenant-scoped repository and
  service. Existing invoice and bill GET endpoints accept all six filters,
  with inclusive dates, literal search wildcards and clean unknown-value
  results. Malformed dates and reversed ranges return 400 on these routes.
- Added CSV and XLSX downloads for filtered sales invoices and purchase bills,
  available to viewers and other book members. Downloads preserve two-place
  money, row currencies and safe spreadsheet text. Existing invoice report
  XLSX downloads now honour the same filters and preserve their layout.
- Added labelled status, customer/supplier, date range, search and currency
  controls above both SPA lists, plus downloads carrying the current query.
  Retained the Overdue shortcut and appended new copy in all four locales.
- Added synthetic tests for both countries and kinds, every filter and combined
  selection, tenant isolation, CSV/Excel content, formula safety, date errors,
  viewer/non-member gates and offline desktop/mobile browser controls in four
  locales. Updated two existing locale-tail assertions for the required appended
  section and scoped the existing prepayment status assertion to table rows,
  avoiding the new filter option. No migration, dependency or live network calls
  were introduced.
- Deferred persisted preferences, large-list pagination/streaming and production
  accountant UAT. Scope is synchronised with the roadmap and design note.
- Validation: Python 3.12.14, `python -m pytest -q`:
  `960 passed, 4 skipped in 858.84s (0:14:18)`. All 24 new checks passed,
  including four-locale browser controls and both country/kind combinations.
  The skips are the existing opt-in PostgreSQL checks. JavaScript syntax,
  Python compilation, existing locale preservation and staged diff/copy/secret
  checks passed. Tests used synthetic data and no live network calls.

## 2026-10-12: Bulk invoice PDF sending

- Added P1 item 12 using the existing document sender and reminders' Postmark
  client boundary. The single-send subject, body, PDF and filename are reused.
- Added a strict write-role/CSRF-protected bulk API with a 50-entry cap,
  independent outcomes, tenant/contact scoping and eligibility gates. Duplicate
  IDs are reported without repeat sending; optional retry keys reuse audited
  outcomes, including explicit review instructions for interrupted sends.
- Retained exact emailed PDFs in the existing attachments store and linked them
  in invoice.delivery audit details. Existing delivery records reserve Prepared
  before HTTP and record Sent/Failed afterwards in separate transactions per
  invoice. Provider errors retain evidence and do not undo earlier successes.
- Added list selection, email confirmation/results and invoice-detail delivery
  history/PDF links. Appended English, Estonian, Lithuanian and Latvian strings
  and extended the two existing locale-tail checks. No ledger changes, migration,
  new dependency or live provider calls are introduced.
- Added synthetic tests for both countries, body/PDF consistency, audit readback,
  independent failures, roles/CSRF, tenant isolation, duplicates/cap, strict
  payloads, retry keys and interrupted persistence, plus four-locale offline
  browser confirmation, results and delivery history.
- Deferred queues, automatic retries, provider callbacks, template/subject editing,
  saved selection, columns, larger batches and production UAT. Roadmap scope and
  `docs/specs/bulk-sending.md` are synchronised.
- Validation: Python 3.12.14, `python -m pytest -q`:
  `987 passed, 4 skipped in 863.98s (0:14:23)`. All 27 new checks passed,
  including offline browser flows in all four locales. The four skips are the
  existing opt-in PostgreSQL checks. `node --check static/app.js`, catalogue
  preservation, staged diff/copy and credential-pattern checks passed. All new
  data is synthetic and no live provider calls were made.

## 2026-10-12: Organisation reminder rules

- Added the final P1 parity item 13: organisation-owned enabled flag, increasing
  overdue stage offsets within 1 to 14 days, and inclusive stop-after semantics.
  Stage 0 stays three days before due; absent rows retain the exact -3/+7/+14
  behaviour. Migration `0024_reminder_rules` seeds no rows and is rerunnable
  without PostgreSQL-specific substitution. CI and upgrade lists include it.
- Added viewer-readable GET and owner/administrator plus CSRF-protected PUT,
  strict boolean/integer/stage/payload validation, scoped persistence and an
  atomic `reminder_rules.updated` audit event. Worker selection honours enabled,
  offsets and stop while retaining invoice opt-outs and all existing gates.
  Event history and ledger data remain intact; email wording stays hard-coded.
- Added a Settings Reminders card with labelled controls and effective preview,
  disabled viewer controls and correct configured offsets in the recurring list.
  Appended and merged English, Estonian, Lithuanian and Latvian catalogue copy.
- Deferred configurable pre-due timing, longer horizons, extra stages, template
  editing, retry changes and production accountant UAT. PostgreSQL execution
  remains opt-in. Roadmap and `docs/specs/reminder-rules.md` share this scope.
- Validation: Python 3.14.6, `python -m pytest -q`: `1042 passed, 4 skipped
  in 904.55s (0:15:04)`. All 55 new offline checks passed, including owner/viewer
  browser flows in all four locales. The skips are the existing PostgreSQL opt-in
  checks. `node --check static/app.js`, Python compilation, catalogue preservation,
  CI migration-list matching and staged diff/copy checks passed. New data is
  synthetic and sends used MockTransport with no live provider calls.
