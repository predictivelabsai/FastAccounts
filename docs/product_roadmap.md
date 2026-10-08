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
- [ ] Production reconnect, scheduled pull and operational monitoring after legal review;
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
TSD filing, payment execution, leave, benefits, and general HR are not included.

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
months, pension-age unemployment insurance, leave and sickness pay, TSD export.
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
