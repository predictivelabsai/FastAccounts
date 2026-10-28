# FastAccounts Product Roadmap

**Research baseline:** 2026-08-10  
**Status:** engineering pilot implemented; independent UK/EE accountant UAT and provider approvals pending

## Payroll absences series (in progress)

- Implemented migration 0042 for wage-eligibility and active payment-type
  metadata, including a frozen wage flag on component history. Preset defaults
  are documented in `payroll_rules.md`.
- Implemented migration 0043 and the tenant-scoped absence register, calendar-day
  and working-day counts, annual-leave holiday exclusions, overlap refusal,
  collective leave, audit events, role/CSRF protected APIs and the translated
  payroll workspace dialog. Unit tests and four-language browser flow pass.
  Unit 3 adds frozen worked/norm day counts, monthly salary and minimum-wage
  proration by interrupted working days, with hourly payroll unchanged and the
  ratio shown on the run and payslip. Unit 4 adds the pure, Decimal average-pay
  engine with approved wages, historical earnings, explicit absence exclusions,
  three averages and a documented fallback breakdown. Absence pay, historical
  import and liability work remains in progress. Unit 5 adds tested pure
  vacation and sickness payment calculations, but pending-pay persistence,
  payout linkage and payroll-run integration are outstanding. Migration 0045
  adds effective-dated entitlement, reviewed opening-balance and reviewed
  historical-earning tables. Import routes, UI and application logic remain
  outstanding. Unit 7 now has pure calendar-day accrual, FIFO/expiry and
  employer-cost valuation functions with focused tests. Leave-lot persistence,
  organisation expiry settings, reports and reserve posting remain outstanding.
  Unit 8 adds run-snapshot absences to payslips and dashboard counts for annual
  leave and sick leave today, with labels in all four locales. Remaining leave
  balances and optional payslip balances remain outstanding.

## 2026-10-28: Payroll calendar and payouts

- Added the Estonian working calendar with Riigipühad, Gregorian Easter
  calculations and TLS § 53 shortened pre-holiday norms. 2026 February, June,
  October and December day/hour totals are documented and tested.
- Added migration 0038 for payroll start date and dated payday rules. Day rules
  clamp to month end and weekend/public-holiday dates move backwards; first
  working day of next month moves forward. Payroll settings support English,
  Estonian, Latvian and Lithuanian, with owner/administrator writes and viewer
  reads.
- Added migration 0039 for run-linked employee payout batches, frozen IBAN and
  account-owner details, partial net payments, paid ledger posting, cancellation
  reversals and state audits. Run and organisation views show paid, pending and
  unpaid amounts. Approved runs reject a salary payout moved to a different
  payment month.
- Added migration 0040 for a frozen payroll settlement date. Later approved
  pay-run items share the remaining tax-free exemption within the same employee
  payment month. TSD payment dates now use the salary payout, frozen payday date
  or legacy period end, in that order. Filing due dates move forward from the
  10th when it falls on a non-working day.
- Added migration 0041 for optional bank BIC and organisation language. Payroll
  payouts can download structured pain.001.001.03 XML with stable transaction
  IDs, remittance text, totals and explicit employee IBAN validation. No
  pain.001 XSD is vendored; validation is structural. Live bank acceptance and
  accountant UAT remain pending.
- Targeted tests cover calendar norms, payday histories, payout partials and
  reversals, tenant/role/CSRF checks, payment-month exemption sharing, TSD dates,
  migration preservation and pain.001 content. See
  `payroll_payouts_validation.md` for exact commands and limits.

## 2026-10-28: Payroll tax settings and employee details

- Implemented date-selected, immutable payroll rules with every verified 2026
  value unchanged, including the April minimum-wage switch. Unsupported years
  fail translated validation; no rates for other years are supplied.
- Added migration 0037 for effective-dated tax-free income applications (maximum,
  limited or none), II pillar pension rates (0/2/4/6%) and employee unemployment
  insurance elections. Existing settings are backfilled at employment start or
  2026-01-01. Month-end resolution and pay-item snapshots preserve approved pay;
  actual payout-date selection remains a later item.
- Added tenant-scoped, audited history editing with payroll role and CSRF checks,
  viewer read-only access and translated frozen-row conflicts. Employee dialogs
  show all three histories in English, Estonian, Latvian and Lithuanian.
- Added phone, checksum-validated IBAN, account owner, address and derived or
  manual birth date to employee writes, dialogs and XLSX exports.
- Fixed services-contract TSD preparation/export using an internal contractor-fee
  classification. Official e-MTA code mapping and accountant production UAT remain
  pending. No direct filing, payment execution or broader HR scope is added.
- Regression coverage includes the EUR 2,000 Merit vector (net EUR 1,657.84),
  dated elections, frozen rows, upgrades, tenant isolation, CSRF and offline
  mobile/desktop browser flows. See `payroll_rules.md` for API compatibility and
  `payroll_tax_settings_validation.md` for commands and verification limits.

## 2026-10-24: On-demand Merit Palk imports

- Implemented the documented Estonian Merit Palk API as a separate pull-only
  connector with encrypted credentials, connection testing and owner/administrator
  on-demand controls in the existing integration workspace. All five endpoint
  pages under the [reference manual](https://api.merit.ee/merit-palk-api/palk-reference-manual/)
  were reachable; no endpoint names were guessed.
- Employee and salary-agreement pulls use reviewed employee upserts, ImportCode
  or PersonalCode identity and tenant-scoped matching. Board contracts map to
  board fees. Monthly salary amounts require per-import confirmation because
  the documented tariff has no explicit unit. Ambiguous agreements/contracts
  are blocked. Services contracts (TypeId 5) now apply with the `income_line`
  basis, zero base pay and reviewed income components, without an automatic
  employment-contract social tax minimum.
- GL imports reuse journal balance/account/date review and immutable atomic
  posting, with provider-specific mappings, repeat-import idempotency and a
  correction guard for changed posted batches. Original dimensions remain in
  the staged source payload.
- Vacation balances are display-only snapshots with no payroll or ledger writes.
  Salary/hours imports now stage each employee and month for the existing draft
  pay-run editor, applying mapped base pay, hourly hours and existing component
  types. Unknown types and missing or ambiguous organisation-scoped name matches
  stay in review. Apply creates or updates only a draft, preserves approval and
  the one-run-per-period constraint, and remains idempotent. TSD submission,
  export and new HR scope are excluded.
- All four locales cover the flow. A result at the 100-employee ceiling requires
  exact PersonalCode filtering rather than silently importing a truncated list.
  There is no documented offset, cursor or personal-code range support; the UI
  explains the requirement for companies with more than 100 employees.
  Synthetic contract and browser validation is implemented. Live Merit Palk PRO
  verification, salary units, unpaid-salary report reconciliation and production
  accountant UAT remain pending.
- Validation: **183 focused tests passed**, each file run separately under five
  minutes: Merit Palk 49, payroll 16, part-time/hourly payroll 30, workspace
  payroll 9, workspace integrations 6, copilot 60 and i18n 13. Includes offline
  Playwright review-to-payroll flow, draft correction, concurrent apply, approval
  protection, component collision, tenant isolation and migration preservation.
- Ran the full suite once with `.venv\Scripts\python.exe -m pytest -q`, capped
  at 45 minutes. It reached 100% in approximately 28 minutes: **1,630 passed,
  2 failed, 4 skipped**. Both failures were stale catalogue expectations already
  present before this completion change: file-import capabilities and Merit
  Palk's documented-adapter status. Corrected those assertions, then reran only
  the affected files: **29 API tests and 60 public-page tests passed**. No full
  suite rerun was performed. The Windows log-streaming wrapper hit an encoding
  error while printing failure details after 100%; the complete progress log
  supplies the full-run outcome counts, and targeted reruns captured the details.
- JavaScript syntax, Python 3.12 grammar and diff whitespace checks passed.
  Tests used the existing project venv, Python 3.14.6, without modifying it.
  The four skips are opt-in PostgreSQL checks. Live Merit Palk PRO response
  reconciliation, salary units and accountant UAT remain pending.

## 2026-10-23: Streamed copilot chat

- Chat replies now stream progressively using SSE, with the existing JSON send
  path retained for older browsers and rejected streaming negotiations. The
  composer stays disabled in flight. Access and quotas are checked before
  provider calls; quota capacity is reserved under the organisation lock.
- Assistant replies and usage totals persist together before the final event.
  Interrupted text is retained with a translated note and explicit Retry;
  incomplete replies cannot produce stage proposals. Pre-text failures retain
  the zero-token failure behaviour. Completion audits include model and usage.
- Added escaped lightweight Markdown, safe external links and labelled copy
  buttons to assistant replies in all four languages. User accent bubbles,
  staging controls, keyboard behaviour and drawer administration remain.
- All copilot settings writes now use CSRF-protected POST; PUT returns 405.
- Validation: project-venv `pytest tests/test_copilot.py -q` passed all 60 tests,
  including offline Playwright checks. `node --check static/app.js`, Python 3.12
  syntax checks and `git diff --check` passed. The supplied venv runs Python
  3.14.6; runtime validation on Python 3.12 remains a deployment check. The final
  full `pytest -q` run was stopped at the 30-minute limit after reaching 97%,
  with no failures reported and four skips. It did not complete; the focused
  suite is the completed regression result.

## 2026-10-23: Organisation copilot credentials

- Owners and administrators can save or clear an encrypted organisation xAI key
  and optional model in the drawer. POST writes require CSRF; reads expose only
  configuration status and the model. Settings audits never contain credentials.
- Migration 0033 reuses the integration CredentialVault and records its key
  version. Organisation credentials take precedence over the environment key
  for chat and scans. Global and organisation switches and access grants remain.
- Validation: offline settings tests passed; JavaScript syntax checked.

## 2026-10-21: Copilot chat and provider fixes

- Redesigned the workspace drawer as a scrolling chat with a pinned composer,
  suggestion chips, document attachment chips, optimistic messages, typing dots
  and inline errors with retry. Enter sends; Shift+Enter adds a newline. A header
  settings button reveals administration outside the message flow. Existing
  shortcut hints, staged imports and mobile/reduced-motion support are retained.
- Corrected the default provider model to `grok-4-1-fast-reasoning`, preserving
  the environment override. Provider failures return HTTP 502 with a useful
  detail and persist an assistant error reply without tokens or stage proposals;
  quota accounting is unchanged. API-key rejection covers both 401 and 403.
- Added offline provider and browser regressions and translated chat controls
  into English, Estonian, Lithuanian and Latvian.
- Validation: `python -m pytest tests/test_copilot.py -q` (43 passed),
  `node --check static/app.js` and `git diff --check` passed. The full
  `python -m pytest -q` run recorded 1,522 passed, 4 skipped and one stale
  static-asset hash failure after CSS changed during that process. A fresh
  `python -m pytest tests/test_public.py -q` run passed all 60 public/static
  tests. Runtime tests used the machine's default Python 3.14; Python 3.12
  syntax checks passed, but its test dependencies are not installed.

## 2026-10-15: Copilot workspace drawer

- Replaced the standalone Assistant > AI copilot page with a retractable right-side
  drawer on every authenticated workspace feature page. The floating button,
  close button and Escape support keyboard use and focus restoration; narrow
  screens use full width and reduced-motion preferences are respected.
- Added Ctrl+/ (Windows/Linux) and ⌘/ (macOS) to toggle the drawer, including
  from the composer. The shortcut pauses for open modals or no selected
  organisation. Localised tooltips, shortcut metadata and a muted, dismissible
  first-open hint make it discoverable; the hint is marked seen immediately in
  localStorage, with a once-per-page fallback when storage is unavailable.
- The shortcut also works on keyboard layouts where '/' requires Shift.
- Preserved the transcript, single attachment picker, staged-import proposals,
  quota notices and owner/administrator controls for organisation settings,
  access grants/revocations and usage in a collapsible administration section.
- Added optional validated page context to messages within the existing text
  cap. No autonomous accounting actions or quota changes were introduced.
- Updated English, Estonian, Latvian and Lithuanian drawer copy and removed
  the obsolete copilot navigation strings.
- Shortcut/hint validation: `python -m pytest tests/test_copilot.py -q`
  (37 passed, one dependency deprecation warning). Offline browser coverage
  includes both platform shortcuts, composer/input focus, modal and organisation
  guards, translated hints in all four languages, dismissal, reload persistence
  and blocked hint storage. JavaScript syntax and whitespace checks passed;
  the full suite was not rerun for this addition.
- Validation: `python -m pytest tests/test_copilot.py -q` (37 passed),
  `python -m pytest -q` (1,517 passed, 4 skipped),
  `node --check static/app.js` and `git diff --check` passed. Offline Chromium
  checks cover all four languages, owner/administrator/viewer roles, focus,
  mobile width, draft preservation and current-page message context; the
  375px drawer was also visually checked.

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

Self-service demo company (2026-10-14): any signed-in account can load one
clearly labelled "Demo OÜ (sample data)" organisation from the organisation menu
or first-run screen. It reuses the EE seed books (contacts, 18 sales invoices,
eight bills, bank lines) and the seven sample-payroll employees with an approved
September and a draft October run, attributed to the requesting account. Repeat
requests reuse that account's company and never touch other organisations.

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
never retained: only parsed staged records are stored. Employee Excel workbooks
must first be exported as CSV; titled bookkeeping journal XLSX files are supported
by the reviewed journal workflow described below. No provider API key, migration or
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
- [x] Expose supported pulls in the workspace for connected Merit and SmartAccounts
  providers, including SmartAccounts workers, with reviewed staging, generic
  accounting-record summaries, recent runs and offline browser coverage (2026-10-14).
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
- [ ] Accountant UAT and allocation reversal,
  bank-feed matching and VAT-on-advance/cash-VAT treatment remain follow-ups.
  Foreign-currency advances and FX differences are delivered in P2 item 2 below.
  Existing
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
- [ ] Deferred: production accountant UAT, partial VAT recovery,
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
- Validation: Python 3.14.6, `python -m pytest -q`: `1042 passed, 4 skipped
  in 904.55s (0:15:04)`. All 55 new offline checks passed, including owner/viewer
  browser flows in all four locales. The skips are the existing PostgreSQL opt-in
  checks. `node --check static/app.js`, Python compilation, catalogue preservation,
  CI migration-list matching and staged diff/copy checks passed. New data is
  synthetic and sends used MockTransport with no live provider calls.

### FX foundation: P2 item 1 (2026-10-12)

- [x] Add manual rate maintenance and document/payment booking conversion.
  Reuse the existing exchange_rates table, positive-rate check and uniqueness
  constraint. No migration is needed; the migration count remains 24.
- Rates mean to-currency units per one from-currency unit. Resolve explicit rate,
  then latest exact-direction row on/before the document/payment date, then 1.
  No inverse lookup or network feeds. Invoice/bill and credit paths retain the
  applied rate; payments retain it in their immutable ledger entries.
- Convert debit/credit in ledger.post into base currency using Decimal money()
  with ROUND_HALF_UP to 0.01. Preserve original transaction amounts and currency.
  Reject rounding imbalance atomically. Same-currency rate-1 storage remains
  bit-identical. No gain/loss account is added.
- Add viewer-readable GET, owner/administrator plus CSRF POST/DELETE, duplicate
  refusal and create/delete audits, with organisation-scoped queries. Settings
  provides a compact rate table/form and disabled non-administrator controls.
  Append fx_rates in all four locale catalogues.
- [x] Realised FX, dedicated gain/loss account, prepayment and periodisation FX
  integration are implemented in P2 item 2 below. Periodic revaluation of open
  balances is covered in P2 item 3 below. Automated feeds and accountant UAT remain open.
  See docs/specs/fx-rates.md.
- Validation: Python 3.14.6, full `python -m pytest -q`: `1099 passed,
  4 skipped, 5 warnings in 824.88s (0:13:44)`. All 57 new FX checks passed,
  including offline owner/viewer browser flows in all four locales. The skips
  remain the existing PostgreSQL opt-in checks. `node --check static/app.js`,
  diff checks and preservation of existing locale sections passed. EstNLTK is
  unavailable locally; Estonian copy follows the existing valuuta terminology.


### Realised FX and settlement integration: P2 item 2 (2026-10-12)

- [x] Add migration `0025_fx_realised`, the combined `FX_GAIN_LOSS` chart role
  with recursive next-free-code seeding, default UK/EE chart entries, stored
  prepayment booking rates and exact payment-allocation booked-base portions.
  CI and upgrade checks now include 25 migrations.
- [x] Settle receipts and supplier payments with the actual original booked
  AR/AP base portions, two aggregate legs and one net FX line. Higher-rate
  receipts recognise gains; higher-rate supplier payments recognise losses.
  Ordinary equal effective rates preserve previous aggregate batches without FX;
  final-cent rounding exceptions prioritise exact clearing.
  Base-currency documents use effective rate 1 regardless of stored explicit rate.
- [x] Enable foreign-currency prepayment creation, foreign/base allocation in
  both directions and refund FX with original reversal links, atomic writes and
  document-currency balances. Enable periodisation at the document's effective
  rate; cumulative funded-base cents clear transit exactly across the schedule.
  Existing VAT, equal-first/equal-last, cancellation and tenancy rules remain.
- No new screens, routes or locale changes. See `docs/specs/fx-rates.md` for
  booked-base determination, allocation amount semantics and refund behaviour.
- Validation: Windows, Python 3.14.6, full `python -m pytest -q`:
  `1168 passed, 4 skipped, 5 warnings in 893.41s (0:14:53)`. All 69 new
  realised-FX checks passed. The skips are existing PostgreSQL opt-ins; warnings
  are existing dependency deprecations. Tests used synthetic data and no live
  providers. Diff checks passed.
- Periodic revaluation of open balances is covered in P2 item 3 below. Automated
  feeds, production accountant UAT and live PostgreSQL validation remain deferred.

### Open-balance FX revaluation: P2 item 3 (2026-10-12)

- [x] Add rerun-safe migration `0026_fx_revaluations` with tenant-scoped run identity,
  one run per organisation/date and an optional immutable posting batch. CI and
  upgrade expectations include 26 migrations. Per-document results are retained
  in the `fx_revaluation.posted` audit rather than a companion table.
- Include open foreign AR/AP documents and both customer/supplier prepayments.
  Compute current original plus attributable revaluation base less tracked
  relief; target remaining currency units at the selected date's exact-direction
  rate, with fallback 1. Post deltas in one balanced base-currency batch with one
  aggregate FX line when its net amount is non-zero. Zero deltas post no rows.
- Later-date runs converge from current state; same-date repeats are refused,
  including Empty runs. Subsequent payments, prepayment offsets and refunds use
  the remaining revalued baseline and clear final cents exactly. Source links,
  original postings, transaction-currency totals and tenant boundaries are retained.
- Add viewer-readable history, owner/administrator plus CSRF POST and strict date
  input. Exchange rates settings adds a compact run form, result table and history,
  with disabled viewer controls. Copy is added within the existing fx_rates tails
  in all four locales. See `docs/specs/fx-rates.md` for scope and accounting rules.
- Validation: Windows, Python 3.14.6, full `python -m pytest -q`:
  `1219 passed, 4 skipped, 5 warnings in 1233.70s (0:20:33)`. All 51 new
  revaluation checks passed, including offline owner/viewer browser flows in all
  four locales. The skips are existing PostgreSQL opt-ins; warnings are existing
  dependency deprecations. Synthetic data only, no live provider calls. Diff and
  locale preservation checks passed; Estonian additions are listed for copy QA
  in `docs/specs/fx-rates.md`.
- Automated rate feeds/schedules, bank cash revaluation, historical as-of
  reconstruction, accountant UAT and live PostgreSQL validation remain outside
  this delivery. No prepayment scope deferral.


### TOTP two-factor authentication: authentication slate P2 item 3 (2026-10-12)

- Implemented optional personal MFA with RFC 6238 SHA1 TOTP and 10 single-use
  recovery codes. Password and Google sign-ins use a CSRF-protected second step,
  account/IP throttles, expiry and replay defence. Existing sessions remain valid.
- Added `/mfa` for password-proved enrolment, activation, disable and code
  regeneration, with a minimal workspace link and matching en/et/lt/lv copy.
- Migration `0027_mfa` is additive with SQLite column guards for interrupted
  upgrades; CI and upgrade expectations include 27 migrations.
- Validation: focused MFA checks: 52 passed, 1 existing dependency warning.
  Full `python -m pytest -q` on Windows/Python 3.14.6: 1271 passed,
  4 skipped, 5 warnings in 1296.31s (0:21:36). The skips are existing
  PostgreSQL opt-ins and the warnings are existing dependency deprecations.
  FX migration regression checks: 126 passed, 1 existing dependency warning.
  Acceptance includes offline browser flows and concurrency/replay checks.
- The paired change log lists every new locale key with Estonian, Lithuanian
  and Latvian strings for copy QA. Model and scope: `docs/specs/mfa.md`.
- Deferred: email/OTP push, hardware keys, organisation-wide enforcement,
  QR rendering, additional secret encryption and support recovery workflows.

## 2026-10-12: Document appearance settings (parity slate P2 item 4)

- Added rerun-safe migration `0028_document_settings`, one optional row per
  organisation, database colour/footer constraints and the PostgreSQL adapter.
  CI and exact upgrade expectations now include 28 migrations.
- Added audited organisation-locked settings writes, owner/administrator and
  CSRF routes, member-readable settings/logo access and bounded PNG/JPEG uploads.
  Evidence checks MIME type, extension, magic bytes, SHA-256 and size. Removal
  and replacement clean up the attachment row and stored file.
- Applied accent colour to sales invoice/credit note titles, a proportionate
  top-right logo and a grey footer on every PDF page. Missing or broken logos
  are skipped silently. Appearance reads reuse the caller's transaction and
  unchanged input produces deterministic PDF bytes.
- Added Settings > Document appearance, nullable accent/footer controls, logo
  preview/upload/removal, viewer gating and matching English, Estonian,
  Lithuanian and Latvian copy. Existing catalogue values are preserved.
- Validation: focused document-settings checks: 42 passed, 1 existing dependency
  warning in 38.75s; both strengthened accent/footer checks also passed.
  Existing document/bulk-email regressions: 33 passed, 1 warning in 39.48s.
  Full `python -m pytest -q` on Windows/Python 3.14.6: 1313 passed,
  4 skipped, 5 existing dependency warnings in 1131.25s (0:18:51).
  All eight offline four-language owner/viewer browser flows passed.
  JavaScript syntax, diff, locale preservation and new-copy checks passed. Synthetic data only; network calls are blocked
  and browser requests are fulfilled locally. See `docs/specs/document-settings.md`.
- Open follow-ups: independent native-language copy QA and live PostgreSQL
  validation. Payroll/statement branding and editable templates remain outside scope.

### Four-language copy QA

All new strings are recorded verbatim below. Matching keys, section order,
catalogue merges and punctuation are checked automatically. Independent
native-language review, including Estonian estnltk QA, remains pending.

| Key | English | Estonian | Lithuanian | Latvian |
| --- | --- | --- | --- | --- |
| `document_settings.nav.document_settings` | Document appearance | Dokumentide kujundus | Dokumentų išvaizda | Dokumentu izskats |
| `document_settings.workspace.Document appearance` | Document appearance | Dokumentide kujundus | Dokumentų išvaizda | Dokumentu izskats |
| `document_settings.workspace.Customise sales invoice and credit note PDFs for this organisation.` | Customise sales invoice and credit note PDFs for this organisation. | Kohanda selle organisatsiooni müügiarvete ja kreeditarvete PDF-failide kujundust. | Pritaikykite šios organizacijos pardavimo sąskaitų ir kreditinių sąskaitų PDF failų išvaizdą. | Pielāgojiet šīs organizācijas pārdošanas rēķinu un kredītrēķinu PDF failu izskatu. |
| `document_settings.workspace.Appearance settings` | Appearance settings | Kujundusseaded | Išvaizdos nustatymai | Izskata iestatījumi |
| `document_settings.workspace.Use an accent colour` | Use an accent colour | Kasuta aktsentvärvi | Naudoti akcento spalvą | Izmantot akcenta krāsu |
| `document_settings.workspace.Accent colour` | Accent colour | Aktsentvärv | Akcento spalva | Akcenta krāsa |
| `document_settings.workspace.Invoice footer` | Invoice footer | Arve jalus | Sąskaitos poraštė | Rēķina kājene |
| `document_settings.workspace.Organisation logo` | Organisation logo | Organisatsiooni logo | Organizacijos logotipas | Organizācijas logotips |
| `document_settings.workspace.No logo uploaded.` | No logo uploaded. | Logo pole üles laaditud. | Logotipas neįkeltas. | Logotips nav augšupielādēts. |
| `document_settings.workspace.Upload a PNG or JPEG image, up to 512 KB.` | Upload a PNG or JPEG image, up to 512 KB. | Laadi üles PNG- või JPEG-pilt suurusega kuni 512 KB. | Įkelkite PNG arba JPEG paveikslėlį, ne didesnį nei 512 KB. | Augšupielādējiet PNG vai JPEG attēlu, kura izmērs nepārsniedz 512 KB. |
| `document_settings.workspace.Logo file` | Logo file | Logofail | Logotipo failas | Logotipa fails |
| `document_settings.workspace.Upload logo` | Upload logo | Laadi logo üles | Įkelti logotipą | Augšupielādēt logotipu |
| `document_settings.workspace.Remove logo` | Remove logo | Eemalda logo | Pašalinti logotipą | Noņemt logotipu |
| `document_settings.workspace.Remove the logo from sales invoice and credit note PDFs?` | Remove the logo from sales invoice and credit note PDFs? | Kas eemaldada logo müügiarvete ja kreeditarvete PDF-failidest? | Pašalinti logotipą iš pardavimo sąskaitų ir kreditinių sąskaitų PDF failų? | Vai noņemt logotipu no pārdošanas rēķinu un kredītrēķinu PDF failiem? |
| `document_settings.workspace.Logo must be no larger than 512 KB.` | Logo must be no larger than 512 KB. | Logo suurus ei tohi ületada 512 KB. | Logotipas negali būti didesnis nei 512 KB. | Logotipa izmērs nedrīkst pārsniegt 512 KB. |
| `document_settings.workspace.Accent colour must contain six hexadecimal digits after #` | Accent colour must contain six hexadecimal digits after # | Aktsentvärv peab olema kujul #RRGGBB | Akcento spalvą turi sudaryti ženklas # ir šeši šešioliktainiai skaitmenys | Akcenta krāsai jāsastāv no zīmes # un sešiem heksadecimāliem cipariem |
| `document_settings.workspace.Invoice footer must contain at most 500 characters` | Invoice footer must contain at most 500 characters | Arve jalus võib sisaldada kuni 500 märki | Sąskaitos poraštėje gali būti ne daugiau kaip 500 simbolių | Rēķina kājenē drīkst būt ne vairāk kā 500 rakstzīmes |
| `document_settings.workspace.Logo must be a PNG or JPEG image` | Logo must be a PNG or JPEG image | Logo peab olema PNG- või JPEG-pilt | Logotipas turi būti PNG arba JPEG paveikslėlis | Logotipam jābūt PNG vai JPEG attēlam |
| `document_settings.workspace.Logo must contain at most 512 KB` | Logo must contain at most 512 KB | Logo suurus võib olla kuni 512 KB | Logotipo dydis negali viršyti 512 KB | Logotipa izmērs nedrīkst pārsniegt 512 KB |
| `document_settings.workspace.Logo content and filename must match its image type` | Logo content and filename must match its image type | Logo sisu ja failinimi peavad vastama pildi tüübile | Logotipo turinys ir failo pavadinimas turi atitikti paveikslėlio tipą | Logotipa saturam un faila nosaukumam jāatbilst attēla tipam |
| `document_settings.workspace.Logo not found` | Logo not found | Logo ei leitud | Logotipas nerastas | Logotips nav atrasts |
| `document_settings.workspace.Logo file not found` | Logo file not found | Logofaili ei leitud | Logotipo failas nerastas | Logotipa fails nav atrasts |

## 2026-10-12: CSV exports across lists and reports (parity slate P2 item 5)

- Added read-only CSV attachments at
  `/organisations/{organisation_id}/contacts/export.csv`, `quotes/export.csv`,
  `bank-transactions/export.csv` and `objects/export.csv` with member-readable
  roles, matching the invoice/bill list exports: UTF-8 BOM, explicit header row
  that stays useful on empty lists, spreadsheet formula-injection guard for
  user text and money rendered as plain two-decimal strings.
- Added `/organisations/{organisation_id}/reports/{tab}.csv` for trial balance,
  profit and loss, balance sheet, general ledger, cash-flow statement and the
  receivables/payables aging. Exports reuse exactly the JSON routes' services
  and query parameters, ignore the comparison option and mirror each JSON
  route's role matrix (general-ledger and aging read-only roles stay aligned).
  Missing or malformed dates and unknown tabs fail exactly like the JSON API.
- Linked exports in the workspace: buttons in Contacts, Quotes, Banking,
  Objects and Quotes lists; an accounting export control that follows the
  active tab and currently applied date/object filters; the existing
  general-ledger Excel workbook book route surfaced on its tab; and the
  employees Excel workbook linked from the payroll view. The cash summary tab
  keeps only its own summary view. No new catalogue keys were introduced:
  existing keys are reused in all four languages.
- Validation: focused exports checks: 44 passed, 1 existing dependency warning
  in 79.42s, covering CSV contracts and content per list and report tab, JSON
  parity for every report, date filters, read-only behaviour verified against a
  whole-database snapshot, tenant isolation, viewer/outsider roles and a
  four-language offline browser pass over every new link. Full
  `python -m pytest -q` on Windows/Python 3.14.6: 1357 passed, 4 skipped.
  JavaScript syntax, whitespace, em-dash and attribution checks passed. No
  migration accompanied this change, so CI stays at 28 migrations.
- Open follow-ups: independent native-language copy review, live PostgreSQL
  validation and XLSX renderers for the remaining lists remain out of scope;
  objects/bank CSV column sets are intentionally minimal.

## 2026-10-14: Copilot access grants (extension of copilot)

- Added rerun-safe migration `0032_copilot_access` (count 32, CI list
  updated): `copilot_access_grants` with one row per granted account per
  organisation. The provider key itself is never stored, logged or exposed.
- Changed the copilot access model: owners and administrators of an enabled
  organisation always have access; every other member is refused with 403
  until an administrator grants access to their account, and revoking is
  immediate. Grant and revocation write audited `copilot.access_granted` /
  `copilot.access_revoked` events under an organisation lock, validate that
  the granted address belongs to a member, deduplicate (case-insensitively)
  and surface to administrators in the status payload.
- Added owner/administrator CSRF-guarded grant and revoke routes and a
  Copilot access panel in the workspace view with granted accounts, granted
  by, revoke confirmations and an email grant form; viewer gating follows
  the enable toggle. English, Estonian, Lithuanian and Latvian keys appended
  in place; Estonian passed estnltk checks on this machine.
- Validation: focused copilot suite: 17 passed, 1 existing dependency
  warning in 18.99s, adding the admin-always/member-grant matrix, granted
  status views per role, duplicate/unknown/invalid grants, immediate
  revocation, audit order and role checks on the new routes; a disabled
  organisation still blocks administrators with 409 before any provider
  call. Full `python -m pytest -q` counts land with this PR's suite
  run: 1441 passed, 4 skipped, 5 existing dependency warnings in 1433.67s.
- Deployment note: the dedicated key goes ONLY into the server environment
  (`FASTACCOUNTS_GROK_API_KEY` plus `FASTACCOUNTS_COPILOT_ENABLED=true` in
  the FastDevOps/Coolify service environment, then redeploy); it never
  enters the repository or any user's hands. Administrators manage access
  to the copilot, not to the key.

## 2026-10-13: Contact and user groups (parity slate P2 item 9)

- Added rerun-safe migration `0031_master_data_groups` (count 31, CI list
  updated): `contact_groups`/`contact_group_members` and
  `user_groups`/`user_group_members` with organisation-scoped unique names,
  cascade-deleted memberships and a tenant index on contact membership.
- Added `contact_groups.py`: audited, organisation-locked CRUD for both
  kinds, membership add/remove (contacts validated to exist in the org;
  user groups may stage addresses that have not joined yet), member counts
  and filtering. Groups are labels: they do not gate access in any way.
- Added routes under `/organisations/{oid}/{kind}-groups` (owner/administrator
  writes with CSRF, member reads for all roles), a `group_id` filter on the
  contacts list, and the Settings > Groups workspace view with two sections,
  member dialogs, confirmations and viewer gating; English, Estonian,
  Lithuanian and Latvian keys appended in place; Estonian passed estnltk
  spelling checks. Also registered the new views (and the earlier `periods`
  view that the merged brand-icons pass missed) in the workspace icon map
  with distinct calendar, wrench and team drawings, keeping the icon-set
  contract green.
- Validation: focused group checks: 14 passed, 1 existing dependency
  warning in 20.15s, covering CRUD, duplicate refusal, membership add and
  remove with the idempotency error, contact-group filtering of the
  contacts list, user-group staging semantics, audit actions in order,
  role matrix, tenant isolation, migration rerun and CI count, four-language
  key parity and an offline browser member-dialog flow. Full
  `python -m pytest -q` on Windows/Python 3.14.6: 1438 passed,
  4 skipped, 5 existing dependency warnings in 1817.13s. Neighbour suites (brand, icons, public, maintenance,
  copilot, period close, VAT replacement, prepayments, periodisation)
  verified green alongside.
- Open follow-ups: group filters on report surfaces and invoice exports,
  bulk membership import, live PostgreSQL validation.

## 2026-10-13: Master-data maintenance (parity slate P2 item 8)

- Added rerun-safe migration `0030_master_data_maintenance` (count 30, CI
  list updated): contacts gain an `active` flag defaulting to on; items had
  one since `0003_operations`. Partial upgrades guard the ALTER the same way
  migrations 0027 and 0029 do.
- Added `master_data_maintenance.py` with a read-only analysis and audited
  lifecycle actions. The analysis finds contacts without any invoice, bill,
  quote, prepayment or journal reference; duplicate contacts that share a
  normalised name, VAT number or registration number; in-use contacts
  missing both a VAT number and a registration number; and supplier numbers
  reused across different suppliers (the database only forbids duplicates
  within one supplier).
- Actions under owner/administrator plus CSRF: deactivate and reactivate a
  contact (organisation-locked, audited `contact.deactivated` /
  `contact.reactivated`), delete a contact only when it carries no
  documents or payments at all (`contact.deleted`), and deactivate or
  delete catalogue items. The contacts list hides deactivated contacts by
  default and accepts `include_inactive=true`; exports keep the full list.
- Added Settings > Data maintenance in the workspace with the four findings
  tables and per-contact actions behind confirmation dialogs; English,
  Estonian, Lithuanian and Latvian keys appended in place (brand-system
  convention); Estonian passed estnltk spelling checks.
- Validation: focused maintenance checks: 9 passed, 1 existing dependency
  warning in 7.18s, covering the four findings on crafted data, the
  contact lifecycle with the list filter and audit trail, item actions,
  the role matrix, tenant scoping, migration rerun and CI count and a
  four-language offline browser flow. Full `python -m pytest -q` on
  Windows/Python 3.14.6 counts land with this PR's suite
  run: 1420 passed, 4 skipped, 5 existing dependency warnings in 1591.59s.
- Open follow-ups: merge-into-existing-contact tooling for duplicates,
  identifier backfill suggestions, live PostgreSQL validation.

## 2026-10-13: Bulk VAT replacement for drafts (parity slate P2 item 7)

- Added `tax_replacement.py`: a preview and an audited apply that replace one
  tax code with another across every DRAFT invoice and bill of an
  organisation. Recomputation keeps each document's amount basis (exclusive
  lines keep net and recompute tax/gross; inclusive sales lines keep gross
  and recompute the net/tax split), replaced bill lines take the target
  code's recoverable percentage, and header subtotals, VAT totals and totals
  are rewritten atomically under an organisation lock.
- Posted documents are never touched: previews report how many issued
  invoices and approved bills still use the source code so accountants can
  reverse and rebook them deliberately. Voided documents are excluded from
  the skipped counts.
- Added owner/administrator apply and approve-plus-accountant preview routes
  (both CSRF-guarded), and the Tax workspace view gained a VAT replacement
  panel: from/to tax code selectors, a preview table with per-document old
  and new VAT, the skipped-posted note, an apply button for owners and
  administrators and result copy. English, Estonian, Lithuanian and Latvian
  workspace keys were appended in place (the merged brand-system convention).
- Validation: focused VAT-replacement checks: 11 passed, 1 existing
  dependency warning in 9.54s, covering draft-only replacement for invoices
  and bills with recoverable tax, inclusive split recalculation, preview
  dry runs changing nothing, the role matrix, validation errors (same code,
  missing source, inactive target, no candidates), tenant isolation, audit
  events, four-language key parity and an offline tax-view browser flow
  with the preview applied.
Full `python -m pytest -q` on Windows/Python 3.14.6: 1411 passed,
  4 skipped, 5 existing dependency warnings in 1374.65s. `node --check static/app.js`, whitespace,
  em-dash and attribution checks passed; Estonian copy passed estnltk
  spelling checks (`auditilogisse` follows existing usage).
- Open follow-ups: replacing codes on in-review bills, replacing the tax
  code on quotes before conversion and live PostgreSQL validation.

### Four-language copy QA (VAT replacement)

| Key | English | Estonian | Lithuanian | Latvian |
| --- | --- | --- | --- | --- |
| `workspace.VAT replacement` | VAT replacement | Käibemaksu asendus | PVM keitimas | PVN aizstāšana |
| `workspace.Replace a tax code across this organisation's draft invoices and bills. Posted documents are never changed.` | Replace a tax code across this organisation's draft invoices and bills. Posted documents are never changed. | Asenda üks käibemaksukood selles organisatsioonis kavanddokumentides: müügiarvetes ja arvetes. Kinnitatud dokumente ei muudeta kunagi. | Pakeiskite PVM kodą šios organizacijos juodraštiniuose pardavimo sąskaitose ir sąskaitose faktūrose. Užregistruoti dokumentai niekada nekeičiami. | Nomainiet PVN kodu šīs organizācijas melnrakstu pārdošanas rēķinos un rēķinos. Reģistrētie dokumenti nekad netiek mainīti. |
| `workspace.Choose two different tax codes.` | Choose two different tax codes. | Vali kaks erinevat käibemaksukoodi. | Pasirinkite du skirtingus PVM kodus. | Izvēlieties divus dažādus PVN kodus. |
| `workspace.{documents} draft documents would change; {lines} lines would be recalculated.` | {documents} draft documents would change; {lines} lines would be recalculated. | {documents} kavandit muutuks; {lines} rida arvutataks ümber. | Pasikeistų {documents} juodraštinių dokumentų; perskaičiuotų {lines} eilučių. | Mainītos {documents} melnraksta dokumentus; pārrēķinātu {lines} rindu. |
| `workspace.Nothing to replace: no draft documents use the source tax code.` | Nothing to replace: no draft documents use the source tax code. | Asendada ei ole midagi: ükski kavand ei kasuta lähtekäibemaksukoodi. | Nėra ko keisti: nė vienas juodraštinis dokumentas nenaudoja šaltinio PVM kodo. | Nav ko aizstāt: neviens melnraksta dokuments neizmanto avota PVN kodu. |
| `workspace.Posted documents are skipped: {invoices} invoices and {bills} bills use the source code and must be reversed deliberately.` | Posted documents are skipped: {invoices} invoices and {bills} bills use the source code and must be reversed deliberately. | Kinnitatud dokumente jäetakse vahele: lähtekoodi kasutavad {invoices} müügiarvet ja {bills} arvet; need tuleb tahtlikult tagasi võtta ja uuesti esitada. | Užregistruoti dokumentai praleidžiami: šaltinio kodą naudoja {invoices} pardavimo sąskaitų ir {bills} sąskaitų faktūrų; jas reikėtų sąmoningai anuliuoti ir įrašyti iš naujo. | Reģistrētos dokumentus izlaižam: avota kodu izmanto {invoices} pārdošanas rēķini un {bills} rēķini; tos apzināti jāatceļ un jāreģistrē no jauna. |
| `workspace.From tax code` | From tax code | Lähtekäibemaksukood | Šaltinio PVM kodas | Avota PVN kods |
| `workspace.To tax code` | To tax code | Sihtkäibemaksukood | Paskirties PVM kodas | Pārdomātais PVN kods |
| `workspace.Choose a tax code` | Choose a tax code | Vali käibemaksukood | Pasirinkite PVM kodą | Izvēlieties PVN kodu |
| `workspace.Preview` | Preview | Eelvaade | Peržiūra | Priekšskatījums |
| `workspace.Apply replacement` | Apply replacement | Rakenda asendus | Taikyti keitimą | Piemērot aizstāšanu |
| `workspace.Apply VAT replacement` | Apply VAT replacement | Käibemaksu asenduse kinnitamine | Taikyti PVM keitimą | Piemērot PVN aizstāšanu |
| `workspace.Draft lines with the source code switch to the target code and totals recalculate. Applied documents are audited. Continue?` | Draft lines with the source code switch to the target code and totals recalculate. Applied documents are audited. Continue? | Lähtekoodi read vahetuvad sihtkoodi vastu ja summad arvutatakse ümber. Rakendatud dokumendid kantakse auditilogisse. Jätka? | Šaltinio kodo juodraščio eilutės perkeliamos į paskirties kodą, o sumos perskaičiuojamos. Taikyti dokumentai užfiksuojami audite. Tęsti? | Melnraksta rindas ar avota kodu pāriet uz mērķa kodu, un summas tiek pārrēķinātas. Piemērotie dokumenti tiek fiksēti auditā. Turpināt? |
| `workspace.Replacement applied: {documents} documents, {lines} lines.` | Replacement applied: {documents} documents, {lines} lines. | Asendus rakendatud: {documents} dokumenti, {lines} rida. | Keitimas taikytas: {documents} dokumentų, {lines} eilučių. | Aizstāšana piemērota: {documents} dokumenti, {lines} rindas. |
| `workspace.Kind` | Kind | Liik | Rūšis | Veids |
| `workspace.Document` | Document | Dokument | Dokumentas | Dokuments |
| `workspace.Old VAT` | Old VAT | Vana käibemaks | Ankstesnis PVM | Iepriekšējais PVN |
| `workspace.New VAT` | New VAT | Uus käibemaks | Naujas PVM | Jaunais PVN |

## 2026-10-13: Fiscal period close and reopen (parity slate P2 item 6)

- Extended the ledger service: `list_periods` returns the organisation's
  fiscal periods ordered by start, `lock_period` now refuses an already
  locked period with a dedicated message, and a new `unlock_period` reopens
  a locked period with a mandatory note, clearing the lock fields and
  recording the previous lock in the `period.reopened` audit event. No
  migration: the schema already carried status, lock fields and a
  two-value check from `0001_accounting_core`, and postings into locked
  periods were already refused.
- Added member-readable `GET /periods` and owner/administrator CSRF-guarded
  `PUT /periods/{id}/close` and `PUT /periods/{id}/reopen` routes with
  required reasons (at most 500 characters), organisation-scoped period
  checks and `period.locked` / `period.reopened` audit events.
- Added the Accounting > Fiscal periods workspace view: a period table with
  status, lock note and owner/administrator close and reopen actions that
  collect a reason in a dialog; English, Estonian, Lithuanian and Latvian
  copy appended in a trailing `periods` section.
- Validation: focused period-close checks: 15 passed, 1 existing dependency
  warning in 17.65s, covering the close/reopen cycle with posting freeze
  and resumption, duplicate-lock and wrong-state refusals, the
  close/reopen role matrix, read roles, reason validation, tenant
  isolation, audit events, four-language key parity and an offline browser
  flow. Full `python -m pytest -q` (Windows, Python 3.14.6): 1400 passed,
  4 skipped, 5 existing dependency warnings in 2292.00s.
  JavaScript syntax, whitespace, em-dash and attribution checks passed; the
  Estonian copy passed estnltk spelling and compound checks (`auditilogisse`
  follows the existing et.json usage).
- Open follow-ups: month-end checklist visibility in the periods view
  (the existing governance checklist stays API-only), retention holds in
  the same view and live PostgreSQL validation.

### Four-language copy QA (fiscal periods)

All new strings are recorded verbatim below. Matching keys, section order,
catalogue merges and punctuation are checked automatically. Estonian was
checked with estnltk spelling and compound checks on this machine.

| Key | English | Estonian | Lithuanian | Latvian |
| --- | --- | --- | --- | --- |
| `periods.nav.periods` | Fiscal periods | Finantsperioodid | Finansiniai laikotarpiai | Fiskālie periodi |
| `periods.workspace.Fiscal periods` | Fiscal periods | Finantsperioodid | Finansiniai laikotarpiai | Fiskālie periodi |
| `periods.workspace.Lock a period to stop changes to its postings. Reopening needs a note and is audited.` | Lock a period to stop changes to its postings. Reopening needs a note and is audited. | Lukusta periood, et peatada selle kannete muutmine. Taasavamine vajab märkust ja kantakse auditilogisse. | Užrakinkite laikotarpį, kad sustabdytumėte jo įrašų keitimą. Pakartotinai atverti reikia pastabos, o veiksmas užfiksuojamas audite. | Noslēdziet periodu, lai apturētu tā grāmatojumu izmaiņas. Atkārtotai atvēršanai vajadzīgs piezīmes ieraksts, un tas tiek fiksēts auditā. |
| `periods.workspace.Periods` | Periods | Perioodid | Laikotarpiai | Periodi |
| `periods.workspace.Period` | Period | Periood | Laikotarpis | Periods |
| `periods.workspace.From` | From | Alates | Nuo | No |
| `periods.workspace.To` | To | Kuni | Iki | Līdz |
| `periods.workspace.Locked at` | Locked at | Lukustatud | Užrakinta | Noslēgts |
| `periods.workspace.Open` | Open | Avatud | Atidaryta | Atvērts |
| `periods.workspace.Locked` | Locked | Lukus | Užrakinta | Noslēgts |
| `periods.workspace.Close period` | Close period | Lukusta periood | Užrakinti laikotarpį | Noslēgt periodu |
| `periods.workspace.Reopen period` | Reopen period | Ava periood uuesti | Atverti laikotarpį | Atkārtoti atvērt periodu |
| `periods.workspace.Reason` | Reason | Põhjus | Priežastis | Iemesls |
| `periods.workspace.Locked period` | Locked period | Periood lukustatud | Laikotarpis užrakintas | Periods noslēgts |
| `periods.workspace.Period reopened` | Period reopened | Periood taasavatud | Laikotarpis atvertas | Periods atkārtoti atvērts |

## 2026-10-13: AI copilot with Grok (parity slate extension)

- Added rerun-safe migration `0029_copilot` (count 29, CI list updated): the
  `organisations.copilot_enabled` opt-in flag defaulting to off, per-user
  copilot message transcripts and per-day usage counters. Partial upgrades
  guard the ALTER the same way migration 0027 does.
- Added a Grok-powered assistant with defence in depth against provider spend
  abuse: a global environment kill switch (`FASTACCOUNTS_COPILOT_ENABLED` and
  `FASTACCOUNTS_GROK_API_KEY`, both required), a per-organisation opt-in that
  only owner/administrator can change, member-readable routes, hard daily
  quotas (30 messages per user, 200 per organisation, 120k prompt characters
  per user, 20 document scans, 2,048-token reply cap, ten messages per user
  per minute) all checked in one transaction before any provider call, and
  audited `copilot.*` events with token counts. The API key exists only in
  the environment and never enters prompts, logs, audits or responses.
- The assistant answers from server-computed context (organisation facts,
  receivables and payables aging, unreviewed bank rows, awaiting quotes) and
  never changes records: document evidence (PDFs via pypdf text extraction,
  images as base64 vision parts) is delimited as untrusted data, and any
  contacts/items import the model proposes stays a staged draft that a human
  reviews and commits through the existing Data import pipeline.
- Added the original workspace Assistant > AI copilot view (replaced by the
  global drawer on 2026-10-15): transcript with token
  counts, composer with an attachment picker, owner/administrator enable
  toggle, per-user usage panel and staged-import buttons; English, Estonian,
  Lithuanian and Latvian copy appended in a trailing `copilot` section.
- Validation: focused copilot checks: 14 passed, 1 existing dependency warning
  in 14.11s, covering kill-switch paths before any provider call, org opt-in
  and role matrix, transcript/usage/audit persistence, PDF and image evidence
  with injection delimiters, the key staying out of wire payloads and audit
  rows, unsupported documents, cross-org scanning, quota/burst/size limits,
  retryable provider errors, fence parsing, migration reruns, four-language
  key parity and offline browser flows. Full `python -m pytest -q` on
  Windows/Python 3.14.6: 1371 passed, 4 skipped, 5 existing dependency
  warnings in 1288.55s.
  JavaScript syntax, whitespace, em-dash and attribution checks passed.
- Open follow-ups: deployment wiring for the dedicated FastAccounts Grok key
  (FastDevOps environment only), accountant UAT, streaming responses,
  employee-document staging via the integration pipeline and live PostgreSQL
  validation.

### Four-language copy QA

All new strings are recorded verbatim below. Matching keys, section order,
catalogue merges and punctuation are checked automatically. Independent
native-language review, including Estonian estnltk QA, has been run once
(spelling, abbreviation hyphenation and compound checks; the tokenid loanword
follows the existing et.json precedent at line 1577).

| Key | English | Estonian | Lithuanian | Latvian |
| --- | --- | --- | --- | --- |
| `copilot.workspace.Open AI copilot ({shortcut})` | Open AI copilot ({shortcut}) | Ava AI-kaaslane ({shortcut}) | Atverti AI asistentą ({shortcut}) | Atvērt AI asistentu ({shortcut}) |
| `copilot.workspace.Close AI copilot ({shortcut})` | Close AI copilot ({shortcut}) | Sulge AI-kaaslane ({shortcut}) | Užverti AI asistentą ({shortcut}) | Aizvērt AI asistentu ({shortcut}) |
| `copilot.workspace.Tip: press {shortcut} to open or close the copilot from any page.` | Tip: press {shortcut} to open or close the copilot from any page. | Vihje: vajuta {shortcut}, et avada või sulgeda kaaslane mis tahes lehel. | Patarimas: paspauskite {shortcut}, kad atvertumėte arba užvertumėte asistentą bet kuriame puslapyje. | Padoms: nospiediet {shortcut}, lai atvērtu vai aizvērtu asistentu jebkurā lapā. |
| `copilot.workspace.Got it` | Got it | Selge | Supratau | Sapratu |
| `copilot.workspace.AI copilot` | AI copilot | AI-kaaslane | AI asistentas | AI asistents |
| `copilot.workspace.Ask about your books, scan documents and draft staged imports. The copilot never changes records on its own.` | Ask about your books, scan documents and draft staged imports. The copilot never changes records on its own. | Küsi oma raamatupidamise kohta, skaneeri dokumente ja koosta importimise ridade eelvaateid. Kaaslane ei muuda kunagi kirjeid iseseisvalt. | Klauskite apie savo apskaitą, skenuokite dokumentus ir rengkite importo eilučių peržiūrą. Asistentas pats niekada nekeičia įrašų. | Jautiet par savām uzskaitēm, skenējiet dokumentus un sagatavojiet importēšanas rindu priekšskatījumu. Asistents pats nekad nemaina ierakstus. |
| `copilot.workspace.AI copilot is not configured on this service.` | AI copilot is not configured on this service. | AI-kaaslane pole selles teenuses seadistatud. | AI asistentas šioje paslaugoje nesukonfigūruotas. | AI asistents šajā servisā nav konfigurēts. |
| `copilot.workspace.AI copilot is off for this organisation. An owner or administrator can enable it here.` | AI copilot is off for this organisation. An owner or administrator can enable it here. | AI-kaaslane on selles organisatsioonis välja lülitatud. Omanik või administraator saab selle siin lubada. | AI asistentas šioje organizacijoje išjungtas. Savininkas arba administratorius gali jį čia įjungti. | AI asistents šajā organizācijā ir izslēgts. Īpašnieks vai administrators to var ieslēgt šeit. |
| `copilot.workspace.Used today` | Used today | Täna kasutatud | Šiandien panaudota | Šodien izmantots |
| `copilot.workspace.Enable AI copilot for this organisation` | Enable AI copilot for this organisation | Luba selles organisatsioonis AI-kaaslane | Leisti AI asistentą šioje organizacijoje | Atļaut AI asistentu šajā organizācijā |
| `copilot.workspace.Conversation` | Conversation | Vestlus | Pokalbis | Saruna |
| `copilot.workspace.Message` | Message | Sõnum | Pranešimas | Ziņojums |
| `copilot.workspace.Attach document` | Attach document | Manusta dokument | Pridėti dokumentą | Pievienot dokumentu |
| `copilot.workspace.No attachment` | No attachment | Ilma manuseta | Be priedo | Bez pielikuma |
| `copilot.workspace.Send message` | Send message | Saada sõnum | Siųsti pranešimą | Sūtīt ziņojumu |
| `copilot.workspace.Copilot replied` | Copilot replied | Kaaslane vastas | Asistentas atsakė | Asistents atbildēja |
| `copilot.workspace.No copilot messages yet.` | No copilot messages yet. | Kaaslase sõnumeid veel ei ole. | Asistento pranešimų dar nėra. | Asistenta ziņojumu vēl nav. |
| `copilot.workspace.Input tokens` | Input tokens | Päringu tokenid | Užklausos tokenai | Pieprasījuma tokeni |
| `copilot.workspace.Output tokens` | Output tokens | Vastuse tokenid | Atsako tokenai | Atbildes tokeni |
| `copilot.workspace.Copilot usage` | Copilot usage | Kaaslase kasutus | Asistento naudojimas | Asistenta lietošana |
| `copilot.workspace.Per-user daily usage counts every message, scan and token billed to this organisation.` | Per-user daily usage counts every message, scan and token billed to this organisation. | Päevane kasutus kasutaja kaupa hõlmab kõik selle organisatsiooni eest arvatud sõnumid, skaneerimised ja tokenid. | Kasdienis naudojimas naudotojui parodo visus pranešimus, skenavimus ir tokenus, kuriems ši organizacija moka. | Ikdienas lietošana uz lietotāju rāda visus ziņojumus, skenējumus un tokenus, ko izrakstām šai organizācijai. |
| `copilot.workspace.Stage {rows} rows for import` | Stage {rows} rows for import | Lisa {rows} rida eelvaate importi | Įtraukti {rows} eilutes į importo peržiūrą | Iekļaut {rows} rindas importēšanas priekšskatījumā |
| `copilot.workspace.Stage import rows` | Stage import rows | Impordi ridade eelvaade | Importo eilučių peržiūra | Importēšanas rindu priekšskatījums |
| `copilot.workspace.Review these rows in Data import before they touch your books. Stage them now?` | Review these rows in Data import before they touch your books. Stage them now? | Vaata read andmeimpordis üle enne, kui need raamatupidamisesse jõuavad. Lisa kohe eelvaatesse? | Peržiūrėkite šias eilutes duomenų importe, kol jos nepateko į apskaitą. Įtraukti į peržiūrą dabar? | Pārskatiet šīs rindas datu importēšanā, pirms tās nonāk uzskaitē. Iekļaut priekšskatījumā tagad? |
| `copilot.workspace.Import batch staged. Review it under Data import.` | Import batch staged. Review it under Data import. | Impordipartii lisati eelvaatesse. Vaata seda andmeimpordi all üle. | Importo paketas įtrauktas į peržiūrą. Peržiūrėkite jį duomenų importe. | Importēšanas pakete iekļauta priekšskatījumā. Pārskatiet to datu importēšanā. |

## Payroll bureau demo fixes (2026-10-23)

Employee archive/unarchive and audited deletion of unused employees, organisation
payment types with editable levy defaults, frozen run components, hourly draft
editing, component exports and configurable month-end accrual postings are in
bureau demo scope. Explicit TSD reclassification uses the following-month 10th,
with preparation/settlement tracking, overdue periods and dashboard counts.
Migration 0034 preserves historical posted batches and provider chart mappings.
The SPA exposes per-line levy flags and deduction accounts, preserves saved
settings when type defaults change, and saves only changed posting mappings.
Draft adjustments retain the monthly minimum and the hourly minimum for entered hours.
All new workspace labels are available in EN, ET, LV and LT. Monthly and hourly
browser flows cover multiple components at a mobile viewport.
Historical payroll migration tests now use a catalogue scoped to one migration
call, with a concurrent legacy/current database isolation regression.

Acceptance checks cover tenant isolation, snapshots, mixed levy bases, social
minimum top-ups, balanced postings, account remapping, locks, repeated actions,
migration reruns and browser interactions. Validation results are recorded in the
paired change log. Production accountant UAT remains pending, especially author
remuneration, parental-leave defaults and mixed-component tax treatment. See
[payroll rules](payroll_rules.md). Direct filing, payment execution, automatic
leave calculations and general HR remain outside this change.

Validation on 2026-10-24: the five required files passed 129 tests individually;
payroll demo checks passed 17, i18n 13 and seed integration 1. JavaScript syntax
and Python 3.12 grammar checks for all 157 tracked Python files passed on the
supplied Python 3.14.6 venv. The final marked full run on commit `225c203` completed
in 25m 18s with **1,560 passed, four skipped, two warnings and no failures**.
The payroll upgrade and source-journal export regressions passed in full-suite
ordering. Python 3.12 runtime verification and the four live PostgreSQL opt-in
checks remain follow-ups. The paired change log records details.


## Reviewed Excel bookkeeping journal import (2026-10-24)

- The Data import workspace accepts a synthetic-template-compatible `.xlsx`
  bookkeeping journal (Estonian label: raamatupidamiskanded). Every titled block
  on every sheet becomes one `file_import` / `journal` proposal in the existing
  staged review and apply lifecycle. Titles are generic, including digits; no
  payroll title has special meaning. Loose Estonian/English headers, blank title
  cells, optional dates and unknown columns are supported.
- Review shows Decimal debit/credit totals, balance, source lines and account
  mapping warnings. Unbalanced, malformed, zero-only or mixed-date blocks cannot
  be posted. Formula cells require values instead. Zero-value source lines remain
  in review and are omitted from ledger posting.
- Active organisation chart codes and confirmed migration-0011 file-import
  mappings resolve accounts. Owners and administrators can confirm an unmapped
  code in review. Apply revalidates every mapping and amount. Undated blocks use
  the reviewer's chosen apply date; dated blocks retain their source date.
- Apply creates one immutable balanced ledger batch per block, together with its
  external mapping, staged status and audit in one transaction. Fiscal locks and
  tenant scope apply. Concurrent identical reimports post once. Rejected proposals
  cannot be applied; posting corrections use the existing reversal workflow.
- Reuses existing staging, mapping and posting tables. No migration, stored
  connection, uploaded workbook retention or live network dependency is added.
  Uploads are limited to 2 MB compressed, 20 MB expanded, 10,000 rows and 200
  columns per sheet. Identity includes sheet, source row and parsed block content;
  rearranged or edited files need duplicate review, since they have new identities.
- Production accountant UAT is pending. This imports bookkeeping entries only;
  it does not calculate payroll or submit TSD.
- Verified offline in nine individually run files: file import 12, journal
  import 23, reviewed import pipeline 10, master-data import 32, import objects
  4, workspace payroll 9, copilot 60, workspace integrations 6 and i18n 13
  (**169 passed**). Node syntax, diff whitespace and Python 3.12 grammar checks
  passed. Runtime tests used Python 3.14.6 and SQLite; Python 3.12 runtime and
  PostgreSQL checks remain unrun. No unattended full-suite run was performed.


## Estonian payroll payment catalogue and settings (2026-10-25)

- Expanded the Estonian payroll catalogue from five to 27 stable presets, with
  names and treatment descriptions in English, Estonian, Latvian and Lithuanian.
  Includes leave pay, unused leave compensation, qualifying employer sick pay,
  ordinary pay supplements, termination compensation, documented cost
  reimbursement, salary advances, alimony, union fees and other net deductions.
- Added additive migration 0036 using 0034's organisation/preset uniqueness and
  `ON CONFLICT DO NOTHING`. Existing bureau edits, custom categories, saved
  components and posted ledger data are preserved. New EE organisations receive
  the same catalogue through the existing organisation seeding function. UK
  organisations receive no presets.
- Added Payment types / Makseliigid under Settings, reusing the payroll editor's
  management components and existing organisation-scoped routes. Users can add
  and edit custom categories and reach payroll account mappings. New custom
  income types start fully taxable. All four locales have mobile browser coverage.
- Uncertain new defaults, including author and employer parental-leave payments,
  are fully taxable. Qualifying employer sick pay is income-tax-only within
  statutory limits; reimbursement is restricted to documented employer costs.
  Net deductions use PAYROLL_DEDUCTION except bailiff garnishments. Accountant
  UAT remains pending for author/parental payment basis, contract recipients,
  severance exceptions, standby/study/average pay and social-minimum treatment.
  Sick-pay limits and reimbursement evidence require bureau confirmation. See
  [payroll rules](payroll_rules.md) for the full catalogue and EMTA references.
- Validation: **221 focused tests passed**, each file run separately: payroll
  16, part-time/hourly payroll 30, workspace payroll 13, migrations/tenancy 15,
  Merit Palk 49, copilot 60, i18n 14 and payroll component regressions 24. Four
  icon tests also passed. Node syntax, diff whitespace, the CI credential-pattern
  guard and Python 3.12 grammar checks for all 160 tracked Python files passed.
- The final full suite ran once with `.venv\Scripts\python.exe -m pytest -q`:
  **1,645 passed, four skipped, two warnings and zero failures** in **53m 25s**
  (3,205.21 seconds). The skips are the four PostgreSQL opt-in tests. Warnings
  concern fastcore's deprecated coroutine detection and an existing pytest
  parametrisation iterator in the MFA tests. No live provider calls or production
  accounting data are used. Python 3.12 runtime and live PostgreSQL checks remain
  unrun; the available Windows venv uses Python 3.14.6 and SQLite.
