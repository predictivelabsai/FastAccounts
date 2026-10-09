# FastAccounts Change Log

Keep this file synchronized with `docs/product_roadmap.md`. Entries describe
implemented and verified product changes; planning status alone is not marked as
delivered.

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
