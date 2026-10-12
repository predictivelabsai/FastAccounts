# FastAccounts Product Roadmap

**Research baseline:** 2026-08-10  
**Status:** engineering pilot implemented; independent UK/EE accountant UAT and provider approvals pending

## 1. Product thesis

FastAccounts should be a trustworthy, understandable bookkeeping system for a
UK limited company or sole trader and an Estonian OÜ or FIE, with a clean
workspace for an external accountant. It is a standalone system of record, not
a thin screen over QuickBooks, Xero, or Merit, and not a general ERP.

The daily loop is intentionally small:

1. create and send a compliant sales invoice;
2. capture and approve a supplier bill or receipt;
3. import bank transactions and reconcile them;
4. post each approved event to an immutable double-entry ledger;
5. review receivables, payables, cash, VAT, profit and loss, balance sheet, and
   trial balance;
6. hand clean books and evidence to an accountant or submit through a supported
   tax integration.

### Explicit non-goals

- inventory, warehouses, purchase orders, sales orders, manufacturing, or
  logistics;
- general HR/payroll operations beyond Estonian accounting-bureau client books,
  CRM, project management, or a generic workflow platform;
- tax or legal advice, automated audit opinions, or unreviewed AI postings;
- full UK Corporation Tax/Companies House filing in the first release;
- direct Estonian annual-report submission in the first release.

## 2. Lessons reused from sister repositories

### Reuse from FastHRM

- Python 3.12 FastHTML/HTMX shell, shared Google/local account experience,
  health/build identity, FastAPI mount, Docker/Coolify shape, and synthetic demo;
- numbered migrations with a migration ledger;
- `.env.sample`, ignored `.env`, key-optional services, masked credentials,
  integration audit events, and null/fake connector implementations;
- pytest fixtures with isolated databases, browser verification, generated
  OpenAPI, and synchronized roadmap/change-log discipline.

The FastHRM credential helper is a useful pattern but must be strengthened here:
accounting OAuth refresh tokens need key versioning and a documented rotation
path rather than one key derived permanently from the session secret.

### Reuse from FastERP

- `Decimal`/`NUMERIC` monetary arithmetic;
- PostgreSQL connection pools and explicit transaction boundaries;
- immutable balanced posting batches, reversals linked to originals, period
  locks, voucher/source links, multicurrency amount columns, and idempotent
  posting;
- accounts, fiscal periods, invoices, bills, payments, allocations, journals,
  trial balance, P&L, and balance-sheet concepts.

Do not copy FastERP's stock/order model or its generic table-backed write API.
FastAccounts mutations must go through typed workflow services so validation,
authorization, tax, ledger posting, and audit records cannot be bypassed.

## 3. Competitive/API findings

### QuickBooks Online

QuickBooks' useful product pattern is a single workflow joining bank feeds,
rules/categorisation, receipts, invoices, bills, VAT/MTD, accountant access, and
reports. Its Accounting API uses OAuth 2.0 and a company `realmId`; webhooks and
30-day Change Data Capture support incremental sync. Relevant entities include
Account, Customer, Vendor, Item, TaxCode/TaxRate, Invoice, Bill, Payment,
BillPayment, Purchase, CreditMemo/VendorCredit, JournalEntry, and Attachments.

Adapter requirements: OAuth token rotation, realm-scoped external IDs, sparse
updates, pagination, webhook signature validation, CDC checkpoints, 429 retry,
idempotent replay, and conflict reporting. Current REST limits include 500
requests/minute per realm and 10 requests/second per realm/app.

Sources: [API overview](https://developer.intuit.com/app/developer/qbo/docs/learn/explore-the-quickbooks-online-api),
[OAuth](https://developer.intuit.com/app/developer/qbo/docs/develop/authentication-and-authorization/openid-connect),
[webhooks](https://developer.intuit.com/app/developer/qbo/docs/develop/webhooks/configure-webhooks),
[CDC](https://developer.intuit.com/app/developer/qbo/docs/learn/explore-the-quickbooks-online-api/change-data-capture),
[limits](https://developer.intuit.com/app/developer/qbo/docs/learn/limits-and-throttles).

### Xero

Xero's strongest patterns are an approachable invoice/bill lifecycle, bank
reconciliation, accountant collaboration, document capture, and explicit tax
and tracking fields. The Accounting API covers contacts, accounts, tax rates,
invoices (AR and AP), credit notes, payments, bank transactions/transfers,
manual journals, attachments, and reports.

Adapter requirements: OAuth 2.0 tenant selection, `offline_access`, granular
least-privilege scopes, tenant-scoped external IDs, Xero's line-level rounding,
incremental pulls, 429 `Retry-After`, and visible conflicts. As of the research
date, the limit is five concurrent calls, 60 calls/minute per tenant, and 1,000
daily calls on Starter or 5,000 on higher app tiers. Broad accounting scopes are
being replaced by granular scopes and are scheduled to remain only until
September 2027.

Sources: [Accounting API](https://developer.xero.com/documentation/api/accounting/overview),
[OAuth](https://developer.xero.com/documentation/guides/oauth2/overview),
[scopes](https://developer.xero.com/documentation/guides/oauth2/scopes),
[limits](https://developer.xero.com/documentation/guides/oauth2/limits/),
[tax behavior](https://developer.xero.com/documentation/guides/how-to-guides/tax-in-xero).

### Merit Aktiva

Implemented on 2026-10-11: the reviewed accounting adapter pulls accounts,
customers/vendors, sales and purchase invoice headers, payments and external
GL snapshots in bounded windows, and pushes GL batches plus sales invoices.
Synthetic fixture verification covers signing, Decimal normalisation, cursors,
contact fallback and the 500-row GL limit. GL and accounting pulls remain
**Documented contract · not live-verified**; the existing invoice/payment/check
APIs are in production use. Live test-company verification remains pending.
Invoice headers need reviewed line/account enrichment before draft application;
external GL snapshots never post to the local ledger. Other-direction payments
need manual review, and ChangedDate fallback lists cover only the recent year.
GL corrections use reversal journals. See [accounting-sync contracts](accounting-sync.md)
for endpoints, limits, cursor semantics and partial-push retry boundaries.

Merit is the most useful localization reference for Estonia. Its REST/JSON API
covers sales and purchase invoices, credit invoices, payments, bank statement
imports, GL transactions, taxes, accounts, customers/vendors, projects, cost
centres/dimensions, fixed assets, reports, PDF invoices, and Estonian e-invoice
flows. V2 is needed for dimensions.

Authentication uses company API ID/key credentials and a per-request UTC
timestamp plus Base64 HMAC-SHA256 over API ID, timestamp, and exact request
body. The API permits 100 requests/minute, returns 429 with rate headers, and
caps entered documents at 500 rows. It has no dedicated sandbox: Merit directs
developers to a free test company. API use requires Pro or Premium for live
companies.

Sources: [overview](https://api.merit.ee/merit-aktiva-api/),
[reference](https://api.merit.ee/connecting-robots/reference-manual/),
[authentication](https://api.merit.ee/connecting-robots/reference-manual/authentication/),
[rate limits](https://api.merit.ee/connecting-robots/reference-manual/rate-limiter/),
[sales invoice](https://api.merit.ee/connecting-robots/reference-manual/sales-invoices/create-sales-invoice/).

## 4. Country packs

Country behavior belongs behind a stable core contract. Tax codes are
effective-dated semantic records, not hard-coded percentages. A transaction
stores the applied tax-code version so a future rate change never rewrites
history.

### United Kingdom pack

Initial scope:

- GBP functional currency with optional foreign-currency documents;
- standard (20%), reduced (5%), zero, exempt, and out-of-scope VAT semantics;
- tax point, net/tax/gross line values, sequential invoice numbers, credit
  notes, reverse-charge labels/flags, and amounts needed for the nine-box VAT
  return;
- accrual accounting first; cash-accounting support as a separate, tested
  policy;
- digital VAT account, VAT return workpaper, evidence links, review/finalise
  declaration, submission receipt, and locked filed period;
- HMRC MTD VAT sandbox adapter, then production approval including mandatory
  fraud-prevention headers;
- six-year default VAT record retention (ten years for OSS records).

Later: MTD for Income Tax for sole traders/landlords, CIS, partial exemption,
margin schemes, EC/Northern Ireland edge cases, Corporation Tax, and Companies
House accounts. These should not silently appear as “supported” before their
fixtures and professional review are complete.

Sources: [HMRC VAT record keeping](https://www.gov.uk/guidance/record-keeping-for-vat-notice-70021),
[VAT MTD API](https://developer.service.hmrc.gov.uk/api-documentation/docs/api/service/vat-api/1.0),
[MTD end-to-end guide](https://developer.service.hmrc.gov.uk/guides/vat-mtd-end-to-end-service-guide/).

### Estonia pack

Initial scope:

- EUR functional currency with optional foreign-currency documents;
- effective-dated 24%, 13%, 9%, 0%, exempt, and reverse-charge/intra-EU tax
  semantics, with a mapping from transaction facts to KMD fields;
- Estonian invoice/reference-number fields, structured source documents,
  adjusting documents, and links from corrections to originals;
- KMD workpaper/export and VD data preparation where applicable;
- seven-year retention from the end of the relevant financial year, with
  electronic journal/ledger legibility and reconstruction of the audit trail;
- Estonian e-invoice import/export as a separate adapter; Merit V2 export/import
  with external-ID mapping and reconciliation.

Later: direct e-MTA submission if a supported, contractually accessible channel
is confirmed; annual-report taxonomy mapping/export; direct registry filing;
fixed assets and broader HR/payroll handoff to Merit Palk/FastHRM.

Sources: [Estonian VAT rates](https://www.emta.ee/en/business-client/taxes-and-payment/value-added-tax/vat-rates-and-supply-exempt-tax/supply-taxable-0-vat-rate-goods),
[KMD instructions](https://www.emta.ee/sites/default/files/documents/2025-02/vorm_kmd_2025_eng.pdf),
[Accounting Act](https://www.riigiteataja.ee/en/tolge/pdf/510032016003).

## 5. Target architecture

```text
FastHTML pages / FastAPI v1
             |
     typed workflow services
             |
  +----------+-----------+-------------+
  | documents | ledger/tax | banking   |
  | evidence  | reporting  | sync/jobs |
  +----------+-----------+-------------+
             |
 PostgreSQL + object/file storage
             |
  outbox workers / provider adapters
  (HMRC, Merit, QBO, Xero, open banking)
```

Use a modular monolith. It keeps invoice approval and ledger posting in one
ACID transaction while preserving clean module boundaries. Provider calls run
after commit through a durable outbox, never inside the accounting transaction.

### Core records

- identity: `organisations`, `users`, `memberships`, `roles`, invitations;
- setup: currencies/rates, fiscal years/periods, accounts, tax-code versions,
  payment terms, document sequences, organization/country settings;
- parties: contacts and their addresses, tax registrations, bank details;
- documents: invoices/lines, bills/lines, credit notes, statuses, delivery
  events, evidence/files and immutable hashes;
- accounting: posting batches, ledger lines, journal drafts, reversals,
  allocations, period locks, opening balances;
- banking: bank connections, bank accounts, imported transactions, match
  candidates, reconciliations and statement checkpoints;
- compliance: VAT returns/boxes/workpapers, declarations, submission attempts,
  receipts and locks;
- integration: encrypted connections, external object mappings, sync runs,
  cursors, conflicts, inbox/outbox messages and webhook receipts;
- governance: audit events, approvals, exports and retention holds.

Every table carrying business data has `organisation_id`. Authorization and
repository tests must prove cross-organization reads and writes fail. PostgreSQL
row-level security can be defense in depth, but does not replace service checks.

## 6. Workflow rules

### Sales invoices

`Draft -> Approved/Issued -> Part-paid -> Paid`, with `Void` and credit-note
paths. Approval assigns a gap-aware sequential number and posts receivable,
revenue, and VAT in one transaction. Issued documents are never deleted or
silently edited. PDF/email/e-invoice delivery occurs after commit and records
attempts, recipients, and provider IDs.

### Purchase bills and evidence

`Draft -> In review -> Approved -> Part-paid/Paid`, with rejection and reversal.
The first version supports upload plus manual entry; extraction can propose
fields later but a user approves every posting. Store the original file,
content hash, MIME/type checks, and links to the bill and ledger source.

### Bank reconciliation

CSV and CAMT.053 statement import comes before live open banking. Imported bank
transactions are idempotent and never become ledger entries merely because they
were downloaded. Matching ranks exact reference/amount, invoice number,
counterparty, date, and prior rule; the user confirms ambiguous matches.

### Corrections and close

Posted lines are immutable. A correction creates a linked reversal/adjustment.
Filed VAT periods and closed accounting periods reject normal posting; reopening
requires an authorized, reasoned, audited action.

## 7. Integration direction

Build one connector contract with capabilities, cursors, mappings, retry rules,
and conflict records. Start with one-way imports into an empty organization and
explicit exports from FastAccounts. Do not offer continuous bidirectional sync
until ownership rules are chosen per object; otherwise two accounting systems
can both post or renumber the same transaction.

### Data and boundaries

The reviewed import model is implemented through migrations
`0010_account_mappings`, `0011_external_gl`, and `0012_sync_review`. Pulled GL
is stored read-only in `external_gl_entries` and is NEVER posted to the local
ledger; it exists for reconciliation only. Pulled payments require a mapped
local document, imported invoices apply as drafts, and nothing is auto-posted
without accountant review.

Recommended order:

1. CSV import/export and opening-balance migration templates;
2. Merit V2 export/import for Estonian pilot customers;
3. Xero read/import, then opt-in invoice/contact export;
4. QuickBooks read/import, then opt-in invoice/customer export;
5. ongoing incremental sync only after replay/conflict tests pass.

## 8. Open-banking roadmap

Abstract bank data behind `BankDataProvider` and retain normalized raw payloads
for replay. The provider must cover business accounts in both GB and EE, expose
booked/pending transactions and stable IDs, support consent expiry/reconnect,
offer a sandbox, and clearly allocate AISP/regulatory responsibilities.

GoCardless Bank Account Data is the first candidate because its API exposes
country-filtered institutions, consent/requisition flows, accounts, balances,
and normalized transactions. TrueLayer is a strong UK alternative, but its new
Data API v3 is currently UK-only. Provider coverage and commercial terms must be
verified in live developer consoles before selection.

Open banking is read-only in the first roadmap slice. Payment initiation and
invoice “pay now” are separate regulated/product decisions.

Sources: [GoCardless bank selection](https://developer.gocardless.com/bank-account-data/bank-selection-ui/),
[transaction fields](https://developer.gocardless.com/bank-account-data/transactions),
[TrueLayer Data v3](https://docs.truelayer.com/docs/enable-your-users-to-connect-their-bank-account),
[UK Open Banking standard](https://standards.openbanking.org.uk/api-specifications/latest/).

## 9. Security and operability gates

- invite-only organization access; owner, administrator, accountant, approver,
  and read-only roles enforced on every page/API/export;
- secure cookies, CSRF protection, MFA-ready authentication, login throttling,
  signed webhooks, replay protection, and least-privilege OAuth scopes;
- key-versioned encryption for API keys and refresh tokens, secret masking,
  rotation/re-authentication, and no tokens in logs;
- MIME/signature/size validation and malware-scanning hook for evidence;
- tamper-evident audit trail and evidence hashes, encrypted backups, restore
  drills, health/build/schema identity, metrics, and alertable sync failures;
- GDPR export/deletion controls that preserve records under a statutory
  retention or legal hold rather than deleting required accounting evidence;
- no live provider calls in the normal test suite and no seeded real data.

## 10. Delivery phases and exit criteria

Durations are engineering estimates after the open decisions below are made.

### Phase 0 — foundation (2 weeks)

- [x] Public FastSME-style landing, responsive Integrations catalogue, build
  identity/health endpoint, exact Google OAuth entry/callback routes, local
  brand assets, and explicit no-network provider contracts (2026-08-10).
- [x] FastHTML/FastAPI app, PostgreSQL migrations, SQLite demo, Docker, health
  identity, `.env`, synthetic seed, auth, organization membership, RBAC, CSRF;
- [x] CI for compile, pytest, migration-from-empty, migration-upgrade, and secret
  scanning;
- [x] Threat model and accounting invariants documented as executable tests.

**Exit:** two organizations cannot see or mutate each other's data; empty and
upgrade migrations pass; no credential enters source or logs.

### Phase 1 — accounting kernel and invoicing MVP (4 weeks)

- [x] Country-aware organization setup and starter charts of accounts;
- [x] Customers, products/services, effective tax codes, sequences;
- [x] Create/preview/issue/email PDF sales invoice and issue credit note;
- [x] Immutable balanced ledger, journals, reversals, locks, audit log;
- [x] Trial balance, general ledger, P&L, balance sheet, AR aging.
- [x] Native Excel workbook exports for payroll pay runs, the general ledger,
  invoices, employees and VAT returns (2026-10-11; see section 28).

**Exit:** property/fixture tests prove every workflow stays balanced, duplicate
requests are idempotent, issued invoices cannot be rewritten, and UK/EE sample
invoices render required fields.

### Phase 2 — bills, evidence, cash and reconciliation (4 weeks)

- [x] Purchase bills/credits, approvals, attachments and AP aging;
- [x] Bank accounts, payments, allocations and over/underpayments;
- [x] CSV/CAMT.053 import, explainable suggestions, split matches and reconciliation;
- [x] Cash summary/bank reports and month-end checklist.

**Exit:** statement re-import creates no duplicates; every matched payment is
traceable from statement to document to ledger; ambiguous matches need review.

### Phase 3 — Estonia compliance pilot (3–5 weeks)

- [x] Estonian tax-code semantics and synthetic KMD/VD workpapers;
- [x] Estonian source/correction documents and retention-policy records;
- [x] Estonian-style e-invoice review export and import boundary;
- [x] Merit V2 connector, HMAC signing, mappings, dry-run contracts and
  reconciliation report.

**Exit:** an Estonian accountant signs off golden fixtures; Merit replay and 429
tests pass; totals reconcile to the local ledger.

### Phase 4 — UK compliance pilot (4–6 weeks)

- [x] UK VAT semantics, nine-box workpaper, accrual/cash policy fixtures;
- [x] HMRC OAuth plan, obligations, guarded sandbox submission, declaration,
  fraud-prevention headers and submission receipts;
- [x] Digital-record and digital-link audit export.

**Exit:** a UK accountant signs off golden fixtures; HMRC sandbox journey and
mandatory headers pass; production is still labelled unavailable until HMRC
approval is obtained.

### Phase 5 — migration and accounting-platform connectors (4–6 weeks)

- [x] Xero and QuickBooks OAuth/request adapters, read-only import/dry-run contracts,
  attachments, mappings, cursors, rate-limit queues and conflict UI;
- [x] Explicit contact/invoice export primitives after import reconciliation;
- [x] Provider contract tests, webhook/incremental sync records, deletion/void mapping plan,
  token rotation and reauthorization.

**Exit:** repeated imports are idempotent; source vs imported trial balances and
open AR/AP reconcile; no silent overwrite or duplicate posting is possible.

### Phase 6 — open banking and automation (3–5 weeks)

- [x] Select GoCardless Bank Account Data as the first technical candidate,
  subject to GB/EE coverage, commercial, and legal review;
- [x] Sandbox-capable consent/requisition and read-only normalized transaction adapter;
- [x] Daily scheduled GoCardless pulls with tenant-scoped status and consent warnings;
- [ ] Production reconnect UAT and operational monitoring after legal review;
- [x] Deterministic import fingerprinting and explainable match confidence;
- [ ] Optional AI field/match suggestions remain a post-UAT roadmap item behind human approval;
- [x] Demo-scope recurring invoices and the payment-reminder ladder (see section 15).

**Exit:** consent expiry and bank/provider outages are recoverable; transaction
replay is idempotent; no suggestion auto-posts without an explicit policy.

## 11. Confirmed product decisions

Confirmed by the product owner on 2026-08-10:

1. UK and Estonian pilots and country packs will be developed concurrently.
2. The initial data model and workflows must cover both incorporated entities
   (UK companies and Estonian OÜs) and sole traders (including Estonian FIEs).
3. FastAccounts must coexist with QuickBooks Online, Xero, and Merit Aktiva.
   Each connection will expose explicit object ownership and sync direction;
   continuous two-way posting stays disabled until those rules are configured
   and reconciliation tests pass.
4. Initial tax compliance means accountant-reviewed workpapers and exports.
   Direct HMRC, e-MTA, and registry filing remains an agent/connector stub with
   a published implementation and approval plan; no stub is presented as live.
5. UK and Estonian accountants will perform later UAT and provide feedback.
   Country packs cannot be labelled professionally validated before that UAT is
   recorded and all resulting blocking issues are resolved.

Still to be decided before production rollout: the authoritative system per
connected object, managed-hosting scope, open-banking provider, and whether
payment initiation belongs after the read-only banking phase.

## 12. Pilot completion record (2026-08-10)

The implementation now includes four portable migrations, a FastHTML workspace,
typed OpenAPI routes, encrypted coexistence records, provider adapters, CI/Docker,
synthetic UK/EE books, Coolify/FastDevOps registration, and an accountant UAT pack.
Automated tests and browser checks use synthetic data only.

The following are intentionally external release gates rather than unfinished
code: qualified accountant sign-off for both country packs, HMRC production
approval/fraud-header validation, an e-MTA X-Road agreement, Merit/Xero/Intuit
test-company credentials, and open-banking regulatory/commercial approval. The
UI and documentation must continue to label those capabilities unavailable until
their evidence is recorded.

## 13. Accounting-bureau payroll demo (2026-10-08)

Estonian client-book payroll is now demo scope: employee records, frozen monthly
payslips, draft/approve/delete workflows, atomic balanced payroll posting, and
localized Unicode multi-page PDF export with employer details and TSD review/UAT
wording. Payroll requests and navigation are gated to EE/EUR books; other books
show a neutral KPI and a localized scope notice. Six named synthetic employees,
July–September 2026 approved runs and an October draft extend the EE demo only.
Both fresh demo books contain five customers, five suppliers, 18 sales invoices,
eight supplier bills and 28 bank transactions, with reconciled payments and
pending document-number matches. Repeated seeding preserves posted records.
The final demo locale pass is verified: country-specific contact/bank names and
references, Demo Kasutaja test-login identity, Estonian payroll account names,
Estonian tax descriptions rendered from the API, and Baltic unmatched-status
translations. Seed amounts, dates, balances and tax mappings are unchanged.
The full suite passed (78 passed, one optional PostgreSQL test skipped), including
browser regressions, on local Python 3.14; Python 3.12 was not installed for
target-runtime verification. Existing-database account names are not migrated; fresh
books use the seed constants. Backend validation errors and stored payroll memos
can still be English.
Rules and corrected arithmetic fixtures are in
[payroll rules](payroll_rules.md). Production accountant UAT remains pending;
Direct TSD filing, payment execution, leave, benefits, and general HR are not
included. Reviewed TSD manual-upload files are delivered in section 32.

## 14. Payroll part-time, hourly pay and social tax minimum (2026-10-08, v0.2.1)

Delivered for the bureau prospect demo: part-time work-time fraction with a
pro-rated minimum wage, hourly pay from hours entered on the run (minimum
EUR 5.67/h from April 2026), monthly/hourly/board-fee pay basis, II pillar 0%
for anyone outside the scheme, and the 2026 social tax minimum obligation
(EUR 886 base, top-up posted as an employer cost) with per-employee EMTA
exemption reasons and calendar-day pro-rating for partial months. A clearly
labelled "Demo OÜ (sample payroll)" seed organisation carries seven synthetic
employees. Still open: the reduced minimum for the employer applying the basic
exemption when there are several employers, Töötukassa social tax relief for
reduced-work-ability staff, automatic pro-rating of monthly pay for partial
months, pension-age unemployment insurance, leave and sickness pay. Reviewed
TSD manual-upload export is delivered in section 32; direct filing remains out
of scope.
See [payroll rules](payroll_rules.md).

## 15. Automation demo: recurring invoices and payment reminders (2026-10-08)

UK books can now turn any issued or draft invoice into a recurring schedule
(weekly, monthly, quarterly or a custom day interval, optional end date, optional
auto-email). When a schedule comes due — including catch-up for up to 24 missed
periods — the service claims it with a compare-and-set date update and deduplicates
with a unique (schedule, period) constraint, then issues an ordinary invoice through
the standard sequential numbering and immutable balanced ledger batch path. Missed
or partial worker gaps never double-issue: a crash before commit retries the period,
and a second pass over an already-run period issues nothing.

Payment reminders follow a three-stage ladder (3 days before due, then 7 and 14
days overdue), computed from each invoice's due date. Every attempt is recorded as
a per-stage event, so a stage is never sent twice, including on failure; individual
invoices can opt out. Sends go through the existing Postmark delivery path: when
`POSTMARK_API_TOKEN`/`FROM_EMAIL` are unset, nothing is sent and no success is
faked — the UI shows an "email not connected" notice, the integrations page shows
the connection status, and manual sends fail with an explanatory message instead of
a fabricated success. A background worker is available for deployed instances via
`FASTACCOUNTS_AUTOMATION_WORKER=true` (off by default; poll interval
`FASTACCOUNTS_AUTOMATION_POLL_SECONDS`, default 60 s) and is env-gated off in tests.

The demo UK book ships an idempotent "Retainer – Willow Design" monthly schedule
whose next run is 7 days out; reminder stages are exercised by the existing overdue
demonstration invoices. The workspace gains a localized "Recurring & reminders"
view (schedules, run history, reminders due) and localized UI in English, Estonian,
Latvian and Lithuanian. The full suite passed (147 passed, one optional PostgreSQL
test skipped) on local Python 3.14.6; accountant UAT for real-world reminder copy
and delivery remains pending.
## 16. HR and payroll software catalogue (2026-10-09)

The public integration catalogue now records 20 HR and payroll systems as
possible data sources for accounting-bureau payroll. The intended workflow is
for employee master data, working time, absences and other payroll inputs to
flow from a client's chosen HR system into FastAccounts as reviewed imports;
these products are integrations, not competing FastAccounts modules.

No HR adapter has been built. Every entry is explicitly labelled as roadmap
work, with import-first direction and per-object ownership. Adapter delivery
will require provider access, tenant-scoped credential design, field mapping,
idempotency and reconciliation tests, and accountant UAT before any readiness
claim or unattended data flow is enabled.

## 17. Integration connection lifecycle (2026-10-09)

The connector registry now covers every public catalogue key and is the single
source for adapter readiness and ordered credential-field metadata. QuickBooks,
Xero and Merit retain their adapter-ready classification; HMRC, e-MTA and open
banking remain explicit planning stubs; all 20 HR/payroll providers resolve to
no-network roadmap stubs until reviewed adapters are delivered.

Owner and administrator APIs can configure, list, test and disconnect a
tenant-scoped provider connection. Tests use credentials supplied in the test
request without storing those test values. A configured connection records the
result as `Connected` only when a connector reports both `ok=True` and
`live=True`; every other result records `Error`, including roadmap stubs. An
unconfigured provider can be checked without creating a connection row. API
responses expose only connection identity, status, external tenant, non-secret
configuration, update time and registry status; credentials and encrypted
material remain internal to the credential vault.

## 18. Reviewed employee-import pipeline (2026-10-09)

Configured connectors can now pull employee master data into a tenant-scoped
staging area without changing payroll records. The review queue preserves sync
cursors, deduplicates repeated provider IDs within each run, and suggests a local
employee only when email or personal ID identifies exactly one record; ambiguous
matches remain explicit review items.

Owners and administrators decide which staged rows to apply or reject. Applied
rows reuse the payroll service's validation and Decimal rules, create or update
employees through idempotent external mappings, and record per-row outcomes.
Invalid records fail independently with a sync conflict, so one bad salary, name,
or pension field cannot partially apply that row or stop the rest of the batch.
No roadmap connector becomes live through this work: unbuilt adapters still fail
clearly and stage no records, and automated tests make no provider network calls.

## 19. FastHR employee connector (2026-10-09)

FastHR is the first live HR source adapter for the reviewed bureau-payroll import
pipeline. It is pull-only: tenant-scoped bearer credentials read all employee
pages, stage canonical name, email, active status and exact base salary values,
and preserve selected FastHR-only fields for review before payroll records change.

The source API does not provide isikukood, funded-pension settings or a
board-member flag, and the adapter does not infer them. Offset pagination,
authentication and connection failures, empty results, external mappings and a
repeat sync/apply cycle are covered with mocked HTTP transport; automated tests
make no live FastHR requests. Production bureau use still requires customer
configuration and accountant UAT.

## 20. Integration workspace (2026-10-09)

The signed-in workspace now makes the connector lifecycle usable without curl.
Adapter-ready providers are shown first with tenant-scoped connection status and
registry-driven configure, test and disconnect controls; secret values are never
returned or prefilled. Planning stubs and roadmap entries stay collapsed and do
not compete with usable adapters.

FastHR adds an employee-import action and a reviewed staging workspace. Owners
and administrators can inspect source payloads, suggested local matches and
review notes; approve, reject or retry failed rows; apply selected decisions; and
review outcome counts, failure reasons and recent runs. Empty pulls, unknown
links and completed queues have explicit non-destructive states. The interface is
localized in English, Estonian, Latvian and Lithuanian. This adds no migration,
does not enable unattended imports, and does not change the pending production
accountant UAT gate.

## 21. Finance connector health checks (2026-10-09)

QuickBooks, Xero and Merit connection tests now construct the existing real
provider adapters from tenant-supplied credentials and perform a lightweight,
company-scoped health request. Results distinguish a reachable provider that
rejects credentials from a connection failure or timeout, while response and
audit messages never include credential values. QuickBooks checks respect the
sandbox setting; Xero validates the selected tenant; Merit signs the probe with
the existing HMAC convention.

This work changes connection health checks only. It does not add finance-provider
pulls to the reviewed import pipeline or change invoice/query submission behavior.
HMRC, e-MTA and open banking remain explicit planning stubs. Mocked HTTP coverage
verifies successful, unauthorized and unavailable providers without live network
calls. Section 20 covers the integration workspace, which merged before this
change.

## 22. Universal file import (2026-10-09)

The connection-free `file_import` adapter accepts employee CSV and TSV exports
from any payroll or HR system and feeds them into the same tenant-scoped review
and apply workflow as provider adapters. It detects comma, semicolon and tab
delimiters; supports UTF-8 with or without a BOM, quoted fields and CRLF or LF;
uses exact Decimal salary parsing; and assigns a stable short hash when no source
employee ID exists. Empty rows are ignored and duplicate employee IDs within one
run resolve to one staged record.

The supported header aliases are explicit:

| Canonical field | Accepted source headers |
| --- | --- |
| `external_id` | `ID`, `Employee ID`, `Töötaja ID` |
| `name` | `Name`, `Nimi`, `Full name` |
| `email` | `Email`, `E-post`, `e-mail` |
| `gross_salary` | `Salary`, `Base salary`, `Palk`, `Baaspalk`, `Gross salary` |
| `personal_id` | `Personal ID`, `Isikukood`, `Personal code`, `ID code` |
| `status` | `Status`, `Staatus` |

Blank, `active`, `aktiivne` and `tööl` status values are active; other values are
inactive. Unmapped columns remain visible in review with a `file_` prefix. The
browser can read a selected file or accept pasted content, but the raw CSV/TSV is
never retained: only parsed staged records are stored. Native Excel workbooks are
out of scope and must first be exported as CSV. No provider API key, migration or
live network test is required. Section 21 covers the finance-connector health
checks, which merged before this change.

## 23. Personio and BambooHR documented-contract adapters (2026-10-09)

Personio and BambooHR now have pull-only employee adapters implemented against
their published contracts. Personio exchanges client credentials in a JSON POST
body, uses the resulting bearer token, reads every employee page and maps only an
exact `active` status to active employment, with past or current termination dates
forcing inactivity. BambooHR uses API-key Basic authentication and reads the
unpaginated company directory, preserving exposed custom fields for review.

Neither adapter has been exercised with vendor credentials. They are labelled
`Documented contract · not live-verified`: fixture-tested adapters shipped without
vendor access use this status, and the first change that verifies one against a
real permitted tenant may promote it to `Adapter ready`. FastHR keeps its existing
label in this change to avoid unrelated status churn. Production use remains
gated on customer credential verification, tenant configuration and accountant
review; automated tests make no live network calls.

Neither source is treated as authoritative for a FastAccounts gross salary.
Records omit `gross_salary` unless a tenant explicitly configures a reviewed
Personio `salary_attribute` or BambooHR `salary_field_id`. Without that mapping,
staging succeeds but applying the row fails independently with `Gross salary is
required`, leaving the rest of the batch available for review. Section 22 covers
the universal file import, which merged before this change.

## 24. Bilingual user guide and regression walk-through (2026-10-09)

FastAccounts now has matching English and Estonian user guides covering every
workspace area, with accounting-bureau payroll documented in depth. Each edition
has 40 pages with explanatory text and corresponding screenshots, and is provided
as PDF, HTML and PowerPoint alongside its Markdown source. Rebuild instructions
and shared guide styling are kept with the documentation.

The reproducible capture script creates an isolated seeded instance, mocks the
FastHR API and records 28 screenshots per language while exercising the complete
workspace with Playwright. The guide commit also passed the full Python 3.12 and
3.13 test suites, the English and Estonian browser walk-throughs and a read-only
public-page smoke test. It changes no application behavior or migration and keeps
the application version at 0.3.0. Section 23 covers the Personio and BambooHR
documented-contract adapters, which merged before this change.

## 25. Website trust pages and roadmap (2026-10-09)

The public site now has first-party Security, Privacy, Company, Contact and
draft Terms pages, plus buyer-readable Roadmap and Changelog pages. The trust
copy distinguishes controls present in the repository from production gates:
integration credentials use key-versioned Fernet encryption at rest, while
managed backup/restore drills, incident operations, the hosting-subprocessor
schedule and independent country-accountant UAT remain explicitly unfinished.
The privacy page records optional Google sign-in and Postmark account, invoice
and reminder email as the current code-evidenced subprocessors and does not
claim an analytics service or an undocumented hosting location.

The public navigation now leads to Product, For bureaus, Integrations, Pricing,
Security and Changelog before the language control and sign-in action. The
footer exposes Security, Privacy, Terms, Company, Contact, Roadmap, Changelog,
Status, Documentation and Source, identifies Predictive Labs Ltd and publishes
the working `info@predictivelabs.ai` sales/support path. GitHub remains a
secondary source destination rather than the Roadmap destination.

The public roadmap uses Now / Next / Later / Shipped sections and market tags.
Shipped dates come from the checked-in change log: the public foundation and
engineering pilot 0.2.0 on 2026-08-10, payroll 0.2.1 on 2026-10-08 and release
0.3.0 plus email/password release 0.4.0 on 2026-10-09. The change log does not
record a 0.1.x application release, so the page labels the earlier foundation as
pre-versioned rather than inventing a release number. Bureau tax copy now names
Estonian VAT (KMD) and UK VAT separately and states that export is available
while direct filing is not.

All new and changed public copy is maintained in English, Estonian, Latvian and
Lithuanian. Route coverage verifies every new page, substantive page markers,
the required navigation/footer destinations, locale rendering and the clarified
KMD filing boundary. No accounting workflow, migration, credential or production
data changes in this section.
## 26. Email and password accounts beside Google SSO (2026-10-09, v0.4.0)

People can now create an account with their email address and a password, sign
in with it, and reset a forgotten password, next to the existing Google button.
Both methods lead to the same account for the same verified address, so a
Google user can add a password through the reset flow and an email user can
later continue with Google. Access rules are unchanged: an address still needs
an organisation membership, a pending invitation or an approved domain or
address, and invitations are accepted by the signed-in address as before.

Accounts follow the shared FastSME local-account pattern from the sister
products and are stored in the main database (migration
`0009_local_accounts`). Sign-up is confirmed by email; the confirmation link also
asks for the chosen password so nobody can pre-register someone else's address.
Reset links are single-use, stored only as hashes and valid for one hour. Sign-in
and reset are throttled, responses never reveal whether an address has an
account, every sign-in starts a fresh session, and a reset signs the account out
everywhere else. Email is sent through Postmark with `POSTMARK_API_TOKEN` and
`FROM_EMAIL`; without them, requests log a warning and show the same message.

## 27. Public-site audience and availability polish (2026-10-09)

The landing now separates accounting bureaus from small businesses before the
feature detail. Bureau copy focuses on payroll, payables and separate client
books; small-business copy focuses on invoices, bills, bank reconciliation and
VAT workpapers for one organisation. The sibling-product strip now gives each
FastSME product a distinct purpose and one catalogue link.

All public pages use four availability labels: **Available**, **Review
required**, **Pilot** and **Planned**, with localized equivalents in Estonian,
Latvian and Lithuanian. Integration cards and the public roadmap use the same
labels. UK VAT and Estonian KMD capability remains workpapers plus export;
direct filing is Planned. Estonian accounting-bureau payroll remains Review
required until production UAT is complete. Trust pages expose no more than one
primary and one secondary button, with additional contact routes kept as text
links. This section changes public presentation only; no accounting workflow,
migration or provider connection changed.

## 28. Excel workbook export pack (2026-10-11)

Shipped native Excel workbooks for payroll pay runs, the general ledger,
invoices, employees and VAT returns. Payroll exports reconcile stored run totals
against frozen employee items and add the posted accounting lines when present.
General-ledger exports support optional validated date bounds; all workbook
routes are organisation-scoped and use the existing read-role guards.

The exports are pure rendered reports: they make no database changes and require
no migration. Monetary calculations stay Decimal-based, while final two-decimal
values are written as numeric Excel cells for spreadsheet calculations.

## 29. SmartAccounts reviewed accounting adapter (2026-10-11)

- [x] Implement the documented company-key signature contract, Tallinn timestamps,
  accounts/clients/invoices/payments/manual-ledger pulls and paginated dated cursors.
- [x] Add validated balanced EUR GL batch pushes, registry/catalogue metadata,
  text service logo and synthetic encrypted demo connection, with offline pytest
  coverage and [accounting-sync documentation](accounting-sync.md#smartaccounts).
- [ ] Verify with a SmartAccounts test company before production acceptance.

Status: **Documented contract · not live-verified**. Reviewed invoice lines need
local account/tax mappings and payments need local bank-account review. External
GL is reconciliation data; provider delete/edit is unused and corrections are
new reversal entries. No row cap or idempotency token is documented, so each
batch is sent once per request and uncertain outcomes require reconciliation.

## 30. Reviewed push pipeline (2026-10-11)

- [x] Prepare, review and explicitly execute approved payroll and local ledger
  journals to Merit Aktiva and SmartAccounts with confirmed account mappings.
- [x] Add Decimal-safe frozen payloads, migration `0014_sync_push`, tenant and
  EE/EUR gates, duplicate refusal, export attribution and manual failure retry.
- [x] Expose payroll/provider push history, mapping editing, offline suggestions
  and GL reconciliation with translated workspace controls and synthetic seed.
- [x] Cover reviewed export success/failure, source changes, roles, tenancy,
  Decimal round trips and reversal corrections with offline tests.
- [ ] Complete provider test-company acceptance and production UAT.

Status: **Documented contract · not live-verified**. These are new exports of
FastAccounts-approved ledger journals. Provider records are never edited or
deleted; corrections use reversal entries. Uncertain outcomes require provider
reconciliation before explicit retry. The seed retains the real payroll batch's
seven lines so its stored payload can pass source-based review.

## 31. Open sign-up switch (2026-10-11)

Anyone may now create a FastAccounts account while the product is early-stage.
A single shared switch, `FASTACCOUNTS_OPEN_SIGNUP`, is honoured by the sign-in
policy that both mail sign-up and Google SSO already check; when it is not set
or false, access rules fall back to the exact v0.4.0 behaviour (organisation
membership, pending invitation, approved domain or address, first-owner
bootstrap).

- [x] Implement the shared switch in the sign-in policy and document it.
- [x] Cover open sign-up mail-verify-and-sign-in, Google-identity acceptance and
  default-off strict behaviour in the auth suite.
- [ ] Confirm a live public sign-up end to end on production after deployment.

Existing defences are unchanged and stay in force with sign-up open: per-IP and
per-address registration and sign-in throttles, email confirmation before any
session, single-use hashed tokens, fresh sessions on every sign-in and identical
public outcomes for unknown addresses.

## 32. Accountant-reviewed Estonian TSD file export (2026-10-09)

Approved Estonian EUR payroll runs can now be prepared as one frozen payment
record per employee for the data-based TSD Annex 1–2 direction. An accountant
review gate precedes downloadable XBRL GL XML and the transitional CSV variant,
which is limited to payment dates through the end of 2027. Both formats use
Decimal-derived values and must reconcile gross, net and employer-cost totals to
the approved pay run.

The implementation snapshots the employee personal ID on the pay-run item,
records the preparation as a tenant-scoped e-MTA export in `sync_runs`, and keeps
the not-live-verified UAT status visible in the workspace and XML. Current
payroll calculations remain resident-only, so generated payments map to Annex 1;
Annex 2 is reserved without inferring non-resident status. The assumed payment
date, semantic classification labels and every field mapping are documented in
[`tsd-export.md`](tsd-export.md).

This is file export only. There is no X-tee, SOAP, upload, submission,
confirmation or network client, and the TSD provider boundary rejects direct
submission. Production accountant UAT and e-MTA upload verification remain
pending.

## 33. Payment orders and document evidence (PR1, 2026-10-11)

- [x] Add migration `0015_payment_orders`, full bank and supplier IBAN fields,
  and frozen payment-order headers and lines. Retain the existing masked bank
  IBAN field. Account mappings and external GL tables from migrations 0011–0014
  contain no payment details and are not used as bank accounts.
- [x] Preview approved and part-paid bills, outstanding balances, currency
  totals and exclusion reasons, with an optional inclusive due-date cutoff.
- [x] Create tenant-scoped, audited payment instructions for one paying bank
  account. Explicit bill selections must all match its currency. Creation and
  download never change bill status, paid totals, payments or ledger entries.
- [x] Download pain.001.001.03 XML from frozen amounts, payer and payee details,
  and references, with fixed two-decimal amounts and currency payment groups.
  XML payment identifiers use UUIDs without hyphens to fit the 35-character
  limit. Stored bill IDs remain unchanged and the mapping is reversible.
- [x] Add payment-order creation and history within the bills view, and
  attachment upload, listing and download within invoice and bill dialogs.
- [x] Route the evidence service for invoices, bills and manual journal batches,
  enforcing tenant ownership, size limits, duplicate hashes per owner and
  download integrity. Browser responses do not expose stored file paths.
- [ ] Add contact and bank-account update flows. IBANs can currently be entered
  only when creating a contact or bank account; existing masked values cannot
  recover the full IBAN.
- [ ] Verify exports with the intended banks before production use, including
  their bank-specific requirements and payment identifier limits. This feature
  only creates downloadable instructions and does not submit or settle payments.

## 34. Opening balances (PR2, 2026-10-11)

- [x] Add a Decimal-only opening-balance service, tenant-scoped snapshot and
  role/CSRF-protected posting routes, without new migrations. Create only the
  requested missing monthly fiscal period; never modify or reopen existing
  periods. Locked periods reject new opening postings.
- [x] Restrict opening inputs to active Asset, Liability and Equity accounts.
  Post any signed remainder to RETAINED_EARNINGS in the same immutable,
  balanced ledger transaction. Reject invalid amounts and debit/credit lines.
- [x] Compare account debit/credit totals and posting dates before returning an
  existing opening batch. Reordered or split equivalent inputs and empty no-op
  retries return the original; changed inputs or reversed batches require a
  correcting journal. Input and generated-offset lines are identified separately.
- [x] Preview CSV customer/supplier open items with row-numbered errors and
  per-side totals. Post contact-linked AR debits and AP credits, due dates and
  original references, with separate retained-earnings offsets. Reuse contacts
  within the organisation and promote their type to both where needed. Create
  no invoice or bill documents and no prior-period income or expenses.
- [x] Use the first 16 hex characters of SHA-256 of the exact UTF-8 CSV text for
  raw-file retries. Different file content creates a separate batch. Parsed-row
  API submissions use canonical JSON of validated rows as their separate input
  identity; use raw CSV consistently when retrying file uploads. A changed
  posting date or reversed file batch is rejected rather than silently reused.
- [x] Add both dialogs to Accounting, using existing dialog and form controls,
  exact integer-cent running totals, read-only snapshots, import previews and
  English, Estonian, Lithuanian and Latvian copy. GET and POST preview routes
  return decimal strings; the browser uses POST for file-sized content.
- [x] Cover periods, offsets, invalid inputs, retry comparisons, transaction
  rollback, contact balances, tenant isolation, route status/access/CSRF and
  desktop/mobile browser flows with synthetic tests and intercepted requests.
- [ ] Accountant UAT and Estonian copy proofreading remain pending. Importing
  open items adds to AR/AP; exclude those same amounts from the main opening
  journal to avoid double counting. Existing document-based ageing and payment
  workflows do not treat these ledger-only entries as invoice/bill documents;
  their settlement and ageing support remain follow-up work.

## 35. Estonian e-invoice export and purchase inbox (PR3, 2026-10-11)

- [x] Write e-arve 1.2 sales XML with seller/buyer details, Decimal item amounts,
  grouped VAT totals and optional bank payment information. Export only Issued,
  Part Paid and Paid invoices; retain generic UK XML. No migration is required.
- [x] Parse purchase e-arve XML independently of namespaces and validate item
  arithmetic and declared net/VAT/gross totals at two-decimal precision.
  Use synthetic fixtures and writer/parser round trips for intake consistency.
- [x] Add a write-role, CSRF-protected upload route and Bills import dialog.
  Resolve suppliers by tenant-scoped registry number, map tax codes by rate,
  create a Draft bill and retain source XML evidence. Duplicate supplier invoice
  numbers return a conflict. Translate the dialog in all four workspace locales.
- [x] Register an explicit Planning stub for e-invoice operator delivery;
  submission remains disabled pending Finbite/Omniva operator contracts.
- [ ] Complete accountant UAT, independent schema/XSD validation and external
  system acceptance checks. The writer is spec-faithful and review-gated, not
  XSD-live-verified. Review supplier registry collisions and zero-rate or
  reverse-charge tax-code choices before approval. See
  [`e-invoices.md`](e-invoices.md) for schema details and intake boundaries.

## PR4: GoCardless Bank Account Data bank feed (2026-10-11)

- Implemented a read-only bank feed with encrypted user secrets, a bank consent
  link, consent completion and tenant-scoped mapping to existing bank accounts.
- Manual pulls import the last 90 days of booked transactions through the existing
  source-hash and row-fingerprint deduplication path. Pending transactions are
  excluded. Amounts retain their signs, and reconciliation remains review-first.
- The integration card supports bank selection, consent completion, account
  balances, local account mapping and per-account pulls in all four locales.
- The initial slice had no schema migration or background worker. Daily pulls
  are now implemented in the worker entry below.
- Consent may last around 180 days depending on the bank and agreement; re-link
  to renew it. GoCardless's documented default agreement currently gives 90 days
  of account access. API access tokens expire separately, typically after one day,
  and the adapter fetches them lazily and retries once after HTTP 401.
- Acceptance: fake-provider and MockTransport tests cover consent state, encrypted
  credentials, request contracts, imports, duplicates, routes and tenant isolation.
  Live bank consent UAT remains pending.
- Validation: `python -m pytest tests/ -q` passed with 533 tests and three optional
  PostgreSQL skips. `python -m compileall -q .`, JavaScript syntax and diff checks
  passed. The existing integration browser regression includes the seventh
  connectable card; no new bank-consent browser test was added. Commands ran on
  installed Python 3.14 because Python 3.12 is unavailable on this machine.

## PR5: KMD reverse-charge and ICS coverage (2026-10-11)

- [x] Audit the existing EE tax kinds against the EMTA KMD form. Include posted
  intra-Community supply in line 3 and derive its line 3.1 subset only when present,
  with existing credit signs, Decimal rounding and cash weighting.
- [x] Warn on generic reverse-charge activity and purchase-side use of the supply
  kind. No ambiguous acquisition, import or reverse-charge field is inferred.
  Add the line label and warnings in English, Estonian, Lithuanian and Latvian.
- [x] Document verified numbering, formulas and retained limitations in
  [`kmd.md`](kmd.md). No migration, new tax code or filing change.
- [ ] More specific acquisition/import evidence, goods/service separation,
  existing line 2/12 form alignment and accountant UAT remain follow-ups.
- Validation: `python -m pytest tests/ -q` passed with 542 tests and three optional
  PostgreSQL skips. Targeted tax/locale checks, compilation and diff checks passed.
  Tests used synthetic data and no live providers. Python 3.14.6 was used because
  Python 3.12 is unavailable on this machine.

## PR6: Customer and supplier statements of account (2026-10-12)

- [x] Add tenant-scoped contact statements from posted and reversed AR/AP ledger
  entries. Opening balances include earlier contact-tagged open items; the
  selected range includes both endpoints. Keep customer and supplier sides
  separate, with positive debts/liabilities and signed movements.
- [x] Return Decimal base amounts and separate running balances for each
  transaction currency. Include EUR presentation amounts without changing
  posted entries. EUR organisations use rate 1; other base currencies require
  an explicit positive EUR-per-base-unit presentation rate, shown in the PDF.
  The repository has no historical EUR rate store; this is a presentation
  conversion of recorded ledger amounts, not foreign-exchange revaluation.
- [x] Add authorised JSON and PDF contact routes, available through the web
  application's existing /api mount. Add a Contacts download dialog with range,
  customer/supplier selection and a EUR rate required for non-EUR organisations,
  translated in all four locales. PDFs use Estonian saldoteatis labels for EE and English elsewhere,
  Unicode fonts, wrapped descriptions and repeated table headers. No migration.
- [x] Verify arithmetic, date boundaries, opening imports, payments, reversals,
  currency separation, tenant/contact isolation, invalid input and PDF bytes.
  Browser regressions cover English/GBP and Estonian/EUR downloads, validation
  errors and mobile dialog layout with intercepted requests.
- [ ] Accountant UAT and historical exchange-rate sourcing remain follow-ups.
  Statements reproduce existing postings; they do not repair upstream currency
  conversion or change document ageing and opening-item allocation workflows.
- Validation: seven relevant pytest files passed with 106 tests and one existing
  dependency warning on Python 3.14.6. Compilation, JavaScript syntax and diff
  checks passed; a synthetic nine-page PDF was rendered and visually reviewed.

## Daily GoCardless bank feed worker (2026-10-12)

- [x] Add additive migration `0016_bank_feed_schedules` and the matching CI
  migration-list entry. Keep one daily schedule per organisation and mapped
  GoCardless account, with last attempt, result, safe error and timestamps.
  Preserve inactive schedules; explicit account linking enables them again.
- [x] Discover existing valid mappings and schedule newly linked accounts for
  today. The existing automation worker claims each due account before network
  access and calls the idempotent pull with actor `system`. The cadence follows
  the server's calendar date; timestamps are UTC. Enable the existing
  `FASTACCOUNTS_AUTOMATION_WORKER=true` switch on one deployment instance;
  polling defaults to 60 seconds and remains disabled by default.
- [x] Catch up an overdue schedule with one overlapping 90-day import, then
  advance to tomorrow. Failures also advance to tomorrow to avoid repeated
  requests each polling tick. Transient Error connections recheck consent before
  the next daily pull. Reauth Required connections make no bank requests until
  consent is renewed and accounts are mapped again. Interrupted Running attempts
  are retried on the next day; no ledger reconciliation is automated.
- [x] Show local last scheduled pull, result and renewal warnings on the existing
  integration card through an authorised, tenant-scoped status GET route. Status
  remains available when account/balance requests fail. Add English, Estonian,
  Lithuanian and Latvian copy without changing existing translations; Estonian
  uses pangafeed and "Impordi kohe" for "Pull now".
- [x] Cover daily and overdue cadence, same-day deduplication, concurrent claims,
  account and organisation failure isolation, transient recovery, consent expiry,
  tenant ownership, safe status routes and data-preserving migration upgrades.
  Browser checks intercept every request and cover all four locales, mobile
  layout, manual pull refresh and consent expiry while loading accounts.
- [ ] Live GoCardless consent UAT, GB/EE bank coverage and regulatory/commercial
  acceptance remain pending. PostgreSQL integration checks require an explicit
  test database; Python 3.12 is unavailable locally, so validation uses 3.14.6.
- Validation: `python -m pytest tests/ -q` passed with 582 tests, three optional
  PostgreSQL skips and one existing dependency warning. The final focused run
  passed 101 tests, including all 12 browser cases. The fresh migration list
  matches CI exactly and reruns are idempotent.
  Python compilation, JavaScript syntax and diff checks passed. No live bank
  requests or real accounting data were used.

## Customer and supplier prepayments (2026-10-12)

- [x] Add additive migration `0017_prepayments`, CI migration-list parity,
  prepayments, allocation/refund events and tenant-scoped contact indexes.
  Seed asset `SUPPLIER_PREPAYMENTS` and liability `CUSTOMER_PREPAYMENTS` roles
  in both charts and add missing roles to existing organisations, preserving
  custom accounts, occupied codes, existing roles and posted books.
- [x] Post customer advances as debit bank / credit customer prepayments, and
  supplier advances as debit supplier prepayments / credit bank. Keep each
  creation, allocation and refund balanced, immutable and atomic with its event
  record. Require stable idempotency keys and serialise concurrent retries.
- [x] Allocate customer advances to issued invoices as debit customer prepayments
  / credit contact AR; allocate supplier advances to approved bills as debit
  contact AP / credit supplier prepayments. Update paid totals and Part Paid/Paid
  status without another bank leg. Reject closed/draft/credit documents, wrong
  contacts or tenants, over-allocation, invalid dates and locked periods.
- [x] Refund only remaining unallocated funds through the original bank account,
  linking compensating entries and their batch to the original prepayment. Keep
  allocation history intact and track the remaining balance per contact.
- [x] Provide authorised list/create/get/allocate/refund API routes and a contact
  outstanding route through the existing web API mount. Add sales/purchases
  tables and dialogs and a contact outstanding view, with append-only copy in
  all four locales. Encode exact amounts as decimal strings in API responses.
- [x] Verify both sides/country charts, event balances, retries/concurrent writes,
  status transitions, rollback after posting, tenant isolation, refunds and
  data-preserving upgrades. Verify contact-statement movements and current ageing
  after allocation. Intercept browser traffic and verify all four languages,
  error correction, stable retry keys, refreshed balances and mobile dialogs.
- [ ] Accountant UAT, allocation reversal, foreign-currency advances/FX differences,
  bank-feed matching and VAT-on-advance/cash-VAT treatment remain follow-ups.
  The first implementation uses the organisation base currency. Existing
  historical document-ageing behaviour is unchanged; statements remain dated
  ledger views. PostgreSQL integration checks require `TEST_POSTGRES_URL`;
  Python 3.12 is unavailable locally, so validation uses Python 3.14.6.
- Validation: `python -m pytest tests/ -q --tb=short` passed with 627 tests,
  four optional PostgreSQL skips and five dependency deprecation warnings.
  The focused run passed 77 tests; the final eight browser cases passed, including
  the contact outstanding view. Fresh `db.migrate()` matches CI's 17 migrations
  exactly and reruns apply nothing. Compilation, JavaScript syntax, diff checks
  and append-only locale verification passed. Tests used synthetic data and
  intercepted browser requests on Python 3.14.6.


## Fixed assets and automatic depreciation (2026-10-12)

- [x] Add additive migration `0018_fixed_assets`, CI migration-list parity and
  tenant-scoped asset groups, acquired assets, depreciation runs and per-asset
  run details. Add fixed asset, accumulated depreciation and depreciation expense
  roles in both seeded charts and existing organisations, preserving custom
  accounts, occupied codes, existing roles and posted books. Default groups are
  created at first use by the service: equipment 20%, computers 25%, other 10%,
  with locale-appropriate names and monthly depreciation.
- [x] Post paid acquisitions as debit fixed assets / credit bank. Snapshot each
  asset's percentage, frequency and accounting accounts at acquisition so later
  group configuration cannot rewrite its policy or posted history. Use Decimal
  money and stable acquisition vouchers in an atomic event transaction.
- [x] Depreciate at calendar month, quarter or year end, including a full first
  acquisition period. Each charge is the rounded cumulative straight-line target
  less earlier charges, capped at acquisition cost. This avoids repeated rounding
  drift and makes the final period top up exactly to cost. Keep reproducible
  zero-cent instalments without an empty ledger batch. One organisation/period/
  frequency run posts one balanced immutable batch for all eligible assets, with
  asset-tagged expense and accumulated depreciation lines. Reruns return the
  recorded result; completed runs cannot absorb later acquisitions.
- [x] Dispose through one balanced event batch, catching up unpaid scheduled
  charges through the disposal calendar period. Full periods apply without daily
  prorating. Debit accumulated depreciation and bank proceeds, credit original
  cost, and post any explicit gain to sales or loss to operating expenses.
  Preserve acquisition and run history; disposed assets receive no later charges.
- [x] Add authorised tenant-scoped asset group, acquisition, disposal, run,
  register and schedule API routes through the existing web API mount. Add the
  fixed assets page, register totals per asset/group, runs and schedule lists,
  and acquisition, group, disposal and manual-run dialogs. Append natural
  English, Estonian, Lithuanian and Latvian copy; Estonian uses põhivarad,
  põhivara grupp and kulumi arvutus.
- [x] Extend the existing default-off automation worker with due depreciation,
  retaining `FASTACCOUNTS_AUTOMATION_WORKER`. Each organisation failure is isolated
  and exposes a safe scheduling error, without stopping other worker operations.
- [ ] Accountant UAT, acquisition reversal, tax-specific depreciation, residual
  values, revaluation, impairment, asset transfers and VAT/foreign-currency
  acquisition treatment remain follow-ups. Initial acquisitions use the
  organisation base currency and a bank payment. Disposal gain/loss uses existing
  sales and operating-expense roles; dedicated disposal roles remain a follow-up.
- Validation: full pytest suite on Python 3.12.14 passed: 677 passed and four
  opt-in PostgreSQL tests skipped because `TEST_POSTGRES_URL` was not set.
  Critical acquisition, group, depreciation and disposal browser flows passed
  in all four locales. All 18 migrations match CI exactly and an immediate
  rerun is empty. Compilation, JavaScript syntax, append-only locale and
  staged diff/secret-pattern checks passed.

### Cash-flow statement and comparative reports (2026-10-12)

- [x] Add a read-only direct-method cash-flow statement in base currency, using
  tenant-scoped BANK-role accounts and Posted/Reversed journal batches. Opening
  balances exclude the start date; movements include both endpoints. Show trade
  receipts, supplier payments, payroll, VAT, revenue, expenses, financing and
  Other, with memos and contact ids in liquid-account detail.
- [x] Net opposing liquid lines as internal transfers and exclude their gross
  amounts from headline inflows/outflows. Where journals have no explicit contra
  pairing, match liquid sides first and allocate external amounts proportionally
  over opposite contra lines, preserving every cent and the balance identity.
- [x] Add optional previous-period, prior-year and YTD comparisons to P&L and
  balance-sheet services and API routes. Whole calendar months, quarters and
  years compare to preceding calendar periods; custom ranges use equal day
  counts. Prior-year whole periods include the corresponding month end, including
  leap days. YTD runs from 1 January through the selected end month and compares
  with the same months of the prior calendar year. Balance sheets remain
  cumulative snapshots at each period end; omitted comparison parameters retain
  the existing single-period response.
- [x] Add accounting date-range and period controls, comparison columns, and a
  cash-flow navigation entry, statement and account detail. Append copy to all
  four locales without changing existing terminology or values.
- [ ] Follow-up: today's unique organisation/system_role constraint permits only
  one BANK-role account. Bank accounts created by the payment service have no
  BANK role and are excluded under this report's explicit role-based scope.
  Supporting those accounts and assigning multiple distinct BANK roles requires
  a separately agreed account-role/schema change. No migration is added here.
- Validation: Python 3.12.14, `python -m pytest -q`: `724 passed, 4 skipped in 482.16s (0:08:02)`. The four skipped tests
  are opt-in PostgreSQL checks. Synthetic service, API and all-four-locale
  browser checks passed, including boundaries, status filtering, tenant
  isolation, split allocation, internal transfer netting, calendar and
  leap-year comparisons, and preservation of BANK roles through upgrades.
  Existing locale keys and values remain unchanged; JavaScript syntax and
  diff checks passed. No live provider calls were made.

### Staged contact and item CSV import (2026-10-12)

- [x] Add a reusable master-data pipeline with per-kind column sets and validators,
  row-level issues, tenant-scoped staging, created entity ids and audit events.
  CSV parsing uses the Python standard library. Discard retains rows for audit.
- [x] Commit valid rows atomically, reject repeated commits and serialise imports
  per organisation. Skip existing contacts by name or registry/personal code and
  items by code, preserving existing data and reporting warnings.
- [x] Add migration `0019_master_data_import` with constrained batches, tenant
  foreign keys, staging rows, item unit and purchase price fields. Sale prices
  use the existing unit price field. Prices remain in base currency, with exact
  decimal validation and standard sales/cost-of-sales account defaults.
- [x] Add viewer-readable status and write-role, CSRF-protected stage, commit and
  discard API routes. Provide settings and contacts import actions, file upload
  or pasted CSV, review with row errors/warnings, commit and discard controls in
  English, Estonian, Lithuanian and Latvian.
- Validation: offline pytest service, API, migration and browser checks cover
  idempotency, isolated errors, malformed CSV, rollback, concurrent batches,
  account changes, tenant isolation and all four locales. Python 3.12.14,
  `python -m pytest -q`: `764 passed, 4 skipped in 528.45s (0:08:48)`.
  The four skipped tests are opt-in PostgreSQL checks.
- [ ] Production UAT remains pending. Spreadsheet workbook parsing and updates
  to existing master data are outside this CSV import scope.

### Sales quotes (2026-10-12)

- [x] Add tenant-scoped quotes and quote lines with migration `0020_quotes`, exact
  decimal amounts, base-currency validation and a separate `QUO-` series in the
  existing document sequences. Update the CI migration list and upgrade checks.
- [x] Quotes remain outside the ledger through Draft, Sent, Accepted, Declined and
  Expired. Only Draft is editable; only Sent can be accepted or declined.
  Validity includes the last valid day. Stale offers cannot be sent or accepted;
  the daily-worker helper expires only overdue Draft and Sent offers.
- [x] Convert an Accepted quote into a created and issued sales invoice through the
  existing invoice service, preserving lines, taxes, amount type and notes.
  The invoice uses the quote date, contact payment terms and invoice numbering.
  Invoice posting and the quote link commit atomically, including locked-period
  rejection. Repeated or concurrent conversion returns the same invoice.
- [x] Provide viewer-readable and write-role, CSRF-protected API routes and a Quotes
  view in Documents, with multiple editable lines, status actions and a posting
  confirmation on conversion. Append translations in all four locales.
- Validation: offline pytest workflow, API, migration and all-four-locale browser
  regressions passed. Python 3.12.14, `python -m pytest -q`:
  `832 passed, 4 skipped in 595.30s (0:09:55)`. The four skips are existing
  opt-in PostgreSQL checks. No live provider calls were made.
- [ ] Deferred: quote email delivery, scheduling the daily expiry helper and
  production UAT. Mark sent records status only and says so in the interface.

### Purchase periodisation (2026-10-12)

- [x] Deliver P1 item 8 with additive, rerunnable migration `0021_periodisation`,
  tenant-scoped purchase schedules and periods, composite foreign keys, CHECK
  constraints and a deferred-cost role in both UK and Estonian charts. Preserve
  existing chart codes and roles, and update the inline CI migration list and
  all explicit migration expectations.
- [x] Schedule a whole purchase bill's net cost in 1 to 120 monthly portions,
  with exact Decimal amounts and deterministic first/last cent remainder.
  Defer net cost at draft-bill approval, or add a balanced reclassification for
  an already posted bill without editing the original bill or journal lines.
  Each portion posts one immutable balanced expense-to-deferred-cost batch.
- [x] Keep full input VAT deduction on the original bill. Period portions carry
  no VAT and do not change AP or payment allocation. Support base-currency
  expense bills with fully recoverable VAT or no VAT.
- [x] Add Draft activation, due-period or catch-up posting, progress, retries,
  organisation row locking, locked-period rejection, audit events and daily
  automation-worker failure isolation. Cancel only future Pending portions after
  due portions are posted; retain posted journals and any remaining funded
  deferred balance for an explicit accountant-reviewed adjustment.
- [x] Add viewer-readable GET and write-role/CSRF-protected API routes with exact
  decimal-string responses. Add Periodised under Documents with creation,
  period details, progress and posting/cancellation confirmations. Append a
  feature translation block at the end of all four locale files, preserving
  every existing key and translation.
- Validation: Python 3.12.14, `python -m pytest -q`:
  `881 passed, 4 skipped in 652.14s (0:10:52)`. All 49 new service, API, migration
  and four-locale browser checks passed. The skips are existing opt-in PostgreSQL
  checks. Tests used synthetic data and no live provider calls. JavaScript
  syntax, focused Python compilation, locale preservation and diff checks passed.
- [ ] Deferred: production accountant UAT, partial VAT recovery, foreign currency,
  explicit irregular period lists, monetary schedule editing and coordinated
  bill/deferral/portion reversals or cancellation settlement. See
  `docs/specs/purchase-periodisation.md` for the ledger and VAT decisions.

### Payment links (2026-10-12)

- [x] Deliver the offline configuration slice of P1 item 9 with additive, rerunnable
  migration `0022_payment_links`, organisation-owned URL templates and stable
  random per-invoice/per-method tokens. Composite tenant foreign keys and an
  organisation lock preserve isolation and concurrent generation idempotency.
- Support EveryPay, LinkPay and custom provider labels without HTTP adapters or
  live provider calls. Format totals and remaining balances with Decimal to two
  places and URL-encode placeholder values. Refuse disabled methods, drafts,
  paid invoices, credit notes and explicit currency mismatches; an empty method
  currency allows any invoice currency without conversion.
- Add owner/administrator configuration writes with WRITE_ROLES restriction and
  CSRF protection, plus viewer-readable method and invoice-link GET endpoints.
  Invoice detail includes generated links. Reads materialise local URLs only,
  with no payment initiation, ledger posting or payment-status change.
- Add Payment methods under Settings and a tiny create/edit dialog. The existing
  authenticated invoice dialog shows clickable payment links, read-only URL
  fields and copy controls. Append translations in all four locales and merge
  both periodisation and payment-link additions into their explicit root sections.
- No public invoice view exists. A new unauthenticated share page, actual
  EveryPay/LinkPay sessions and callbacks, verification, automatic reconciliation,
  provider-side revocation and production UAT remain deferred. Already shared
  external URLs depend on the merchant service for current balance and expiry.
  See `docs/specs/payment-links.md` for the template and token contract.
- Validation: Python 3.12.14, `python -m pytest -q`:
  `916 passed, 4 skipped in 674.84s (0:11:14)`. All 35 new service, API,
  migration, locale and four-locale browser checks passed. The skips are existing
  opt-in PostgreSQL checks. Tests used synthetic data and no live provider calls.
  JavaScript syntax, focused Python compilation, existing locale preservation,
  diff and staged secret-pattern checks passed.

### Analytical objects (2026-10-12)

- [x] Deliver P1 item 10 with additive, rerunnable migration
  `0023_analytical_objects.sql`. The base had no project catalogue or dimension
  fields; the similarly named sibling-server tool was not present here.
- Add project, location, person and generic object records with code, name,
  notes, active status, tenant/type composite foreign keys, parent unique indexes,
  owner/administrator CRUD, CSRF protection and audit events. Referenced objects
  must be deactivated rather than deleted or retyped.
- Carry optional `projects_*` IDs through invoice, bill and journal lines into
  immutable ledger dimension companion rows in the same posting transaction.
  Preserve tags on reversals, credit documents, purchase periodisation and
  recurring invoices inherited from their source invoice. Distinct tags prevent
  invoice revenue aggregation from losing line attribution.
- Add `object_id` filters to trial balance, general ledger and P&L, including
  every P&L comparison period. Add a Settings Objects list/dialog, optional
  invoice/bill selectors and a report filter including inactive historical objects.
  Append all four locales through the `analytical_objects` merge section;
  Estonian navigation and title are `Objektid`.
- Leave existing untagged postings unchanged. Object merging, multiple objects
  per dimension, combined filters, manual journal SPA editing, quote/schedule
  dimension authoring, dimension exports and production UAT remain deferred.
  See `docs/specs/analytical-objects.md` for storage and attribution details.
- Validation: Python 3.12.14, `python -m pytest -q`:
  `936 passed, 4 skipped in 741.21s (0:12:21)`. All 20 new analytical object
  checks passed, including browser flows in all four locales. The skips are the
  existing PostgreSQL opt-in checks. JavaScript syntax, Python compilation,
  existing locale preservation, desktop/mobile visual review, diff and staged
  secret-pattern checks passed. All data used by the new tests is synthetic.

### Invoice list exports and filters (2026-10-12)

- [x] Deliver P1 item 11 for UK and Estonian books: existing sales invoice and
  purchase bill lists accept status, contact, inclusive document-date range,
  currency and number/reference/contact search filters. Preserve the sales
  Overdue shortcut and scope every contact join to the organisation.
- Add viewer-readable CSV and Excel downloads for both document kinds using
  the same selection service and existing workbook style. Preserve Decimal
  money, quote CSV text, prevent spreadsheet formulas and retain per-row
  currencies without mixed-currency totals. Existing invoice report downloads
  also honour these filters while retaining their established layout.
- Add compact labelled controls and matching download links to both existing
  SPA lists. Keep session filters separate per book and kind, support narrow
  screens and append new English, Estonian, Lithuanian and Latvian copy.
- No migration, new dependency, saved filters or per-user columns. Persisted
  preferences, large-list pagination/streaming and production accountant UAT
  remain follow-ups. See `docs/specs/invoice-list-exports.md`.
- Validation: Python 3.12.14, `python -m pytest -q`:
  `960 passed, 4 skipped in 858.84s (0:14:18)`. All 24 new checks passed,
  including four-locale browser controls and both country/kind combinations.
  The skips are the existing opt-in PostgreSQL checks. JavaScript syntax,
  Python compilation, existing locale preservation and staged diff/copy/secret
  checks passed. Tests used synthetic data and no live network calls.

### Bulk invoice PDF sending (2026-10-12)

- [x] Deliver P1 item 12 through the existing `DocumentService.send_invoice_email`
  Postmark path, shared with reminders. Retain the single-send PDF renderer,
  subject, body, filename and stream. No migration or parallel mailer.
- Add the write-role/CSRF-protected `invoices/send-bulk` API with strict input,
  a 50-entry cap and independent ordered sent/failed results. Refuse foreign or
  missing IDs, credit notes, ineligible status and missing contact email.
  Duplicate IDs never trigger a second email within a request.
- Store the exact sent PDF in existing attachments and link its ID in the
  existing delivery audit trail. Reserve Prepared before HTTP and persist each
  final outcome separately, preserving earlier successes and all ledger rows.
  Optional retry keys reuse outcomes and require review of uncertain Prepared
  records before an intentional resend with a new key.
- Add invoice-list checkboxes, confirmation and results, plus invoice-detail
  email history and retained PDF links. Append all four locale catalogues.
- Defer queues, automatic retries, provider callbacks, template/subject editing,
  saved selection, column configuration, larger batches and production UAT.
  See `docs/specs/bulk-sending.md` for eligibility and retry semantics.
- Validation: Python 3.12.14, `python -m pytest -q`:
  `987 passed, 4 skipped in 863.98s (0:14:23)`. All 27 new checks passed,
  including offline browser flows in all four locales. The four skips are the
  existing opt-in PostgreSQL checks. `node --check static/app.js`, catalogue
  preservation, staged diff/copy and credential-pattern checks passed. All new
  data is synthetic and no live provider calls were made.

### Organisation reminder rules (2026-10-12)

- [x] Deliver P1 item 13, the final P1 parity item: one organisation-owned rule
  row with an enabled flag, increasing stage 1/2 offsets within 1 to 14 days
  overdue, and an inclusive optional stop at stage 0, 1 or 2. Keep stage 0 at
  three days before due. No row retains the exact existing -3/+7/+14 ladder.
- Add portable, rerunnable migration `0024_reminder_rules` without seeded rows;
  append it to CI's inline migration list and all explicit upgrade expectations.
  Persist and audit saves atomically with parameterised tenant-scoped queries.
- Add viewer-readable GET and owner/administrator plus CSRF-protected PUT at
  `reminder-rules`. Preserve worker eligibility, per-invoice opt-outs, event
  deduplication, catch-up, hard-coded email content and ledger data.
- Add a compact Settings Reminders card with enable/day/stop controls, save and
  current effective preview. Viewers have read-only controls. Show actual offsets
  in the recurring reminder list. Append all four locales in `reminder_rules`.
- Defer configurable pre-due timing, longer horizons, additional stages,
  template editing, retry changes and production accountant UAT. PostgreSQL
  execution remains opt-in. See `docs/specs/reminder-rules.md`.
- Validation: Python 3.12.14, `python -m pytest -q`: `1042 passed, 4 skipped
  in 904.55s (0:15:04)`. All 55 new offline checks passed, including owner/viewer
  browser flows in all four locales. The skips are the existing PostgreSQL opt-in
  checks. `node --check static/app.js`, Python compilation, catalogue preservation,
  CI migration-list matching and staged diff/copy checks passed. New data is
  synthetic and sends used MockTransport with no live provider calls.
