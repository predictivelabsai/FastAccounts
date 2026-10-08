# FastAccounts Change Log

Keep this file synchronized with `docs/product_roadmap.md`. Entries describe
implemented and verified product changes; planning status alone is not marked as
delivered.

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
