# Estonian multi-client payroll: Phase 1 discovery and plan

Status: PHASE 1 (discovery + plan), written 2026-10-08 (Europe/Tallinn). Update 2026-10-08: part-time (FTE), hourly pay, II pillar 0% for anyone and the social tax minimum were implemented in FastAccounts v0.2.1 (see `docs/change_log.md` and `docs/payroll_rules.md`). FastHRM work is not approved yet. Security-sensitive FastHRM details are redacted in this public copy.

## 0. TL;DR

* **Payroll already exists in two places, built separately.**
  * **FastAccounts** `main` got PR #2 "Estonian payroll for accounting-bureau client books" from Joosep Laats, merged 2026-10-08 11:35 EEST, and it is **already live** on fastaccounts.org. The live `static/app.js` has the payroll wizard and Postgres reports `migrations: 5`, which includes `0005_payroll`. So the statement "#payroll has no functionality" was out of date as of this morning. The module is a tenant-scoped demo: employees, monthly runs, Decimal maths, posting to the ledger and payslip PDFs. It covers EE/EUR books and 2026 periods only.
  * **FastHRM** `main` (live on fasthr.eu, commit bbaddae, migrations 15) has its own payroll: pay runs, payslip lines, holiday pay, sick pay for days 4 to 8, and TÖR/TSD CSV exports. It is **single-tenant** (one employer per deployment), uses float maths, and **calculates income tax wrongly**: 22% of gross with no basic exemption and no deduction of pension or unemployment insurance (UI) contributions.
* **Recommendation:** one shared, pure-Python **`fastsme-payroll-ee` rules package**, seeded from FastAccounts `payroll.py`. FastHRM is the system of record for employers, employees, contracts, absences, pay runs and statutory files. FastAccounts is the ledger and the bureau's single login, and receives approved pay runs through an idempotent journal-import API. Details in §4.
* **Sample employees on fasthr.eu: BLOCKED.**
  * There is no employee-create API. `/api/v1/employees` is read-only.
  * Production writes are disabled (`/api/v1/health` returns `writes_enabled:false` because `FASTSME_API_TOKEN` is unset).
  * There is no employer/company entity to attach employees to.
  * **Security issue:** a FastHRM API access-control issue (details withheld from this public repository; reported to Julian privately). Resolve it before any real isikukood is stored.
  * The seed script and fixture were written locally instead (§7).

## 1. Repo findings

### Where the code lives
| | FastAccounts | FastHRM |
|---|---|---|
| Remote | github.com/predictivelabsai/FastAccounts | github.com/predictivelabsai/FastHRM |
| Default/deploy branch | `main` (Coolify push webhook) | `main` (Coolify push webhook; `scripts/coolify.py status`) |
| `main` HEAD | fb830f7 (2026-10-08, merge PR #2 payroll) | bbaddae (2026-09-16, merge PR #42) |
| Live | fastaccounts.org, v0.2.0, Postgres schema `fast_accounts`, migrations 5; payroll JS present | fasthr.eu, v0.4.0, commit bbaddae, `dirty:false`, migrations 15. Live matches `main` |
| Local copies | **Not** at `~/dev/plai/` on any machine. Found at `~/dev/fastsme/FastAccounts` and `~/dev/fastsme/FastHRM`. ThinkPad (2f2ce993, `kasutaja-ThinkPad-T15-Gen-1`; note this ID is the ThinkPad, not the Mac): FastAccounts at 49a894f, behind main, with **uncommitted Latvia work** including `migrations/*/0005_latvia_foundation.sql`. **That migration number collides with main's `0005_payroll.sql`.** HP (b7e1552e): FastAccounts at b4bfe86 (clean, old). FastHRM ThinkPad deff1fb with dirty `byok/`; HP fbe3991 with dirty connectors/docs. Mac (e4a207ef): no checkouts under `~/dev/fastsme` or `~/dev/plai`. | |
| FastDevOps | `config/services.yaml`: `fastaccounts` port 5012, domain fastaccounts.org, health check disabled. `FASTSME_API_TOKEN` is not in the required env. | `fasthrm` port 5010, domain listed as hrm.fastsme.com (live is fasthr.eu); SQLite at `/data/fasthr.sqlite` |

### Stack
* Both use Python 3.12, FastHTML/HTMX server-rendered pages, and FastAPI under `/api`.
* FastAccounts: PostgreSQL (psycopg pool) or SQLite, numbered SQL migrations, `Decimal`/NUMERIC money, and immutable double-entry `posting_batches`. The SPA-like workspace is in `static/app.js` (~62 KB), with reportlab PDFs and pytest.
* FastHRM: SQLite only (`db.py`), with REAL/float money and migrations 0001 to 0015. Payroll-related migrations: `0006_pay_runs`, `0010_tor_tsd_exports`, `0011_holiday_incapacity_pay`, `0012_granular_rbac`, `0013_benefits`. Uses pytest.

### Data model
**FastAccounts**
* `organisations` (country_code, base_currency).
* `memberships` (email, role: owner/administrator/accountant/approver/viewer). This is the multi-tenancy layer: one login can belong to many organisations, so a bureau can switch between client books. There is no explicit "bureau/office" entity.
* Also: `accounts` (with `system_role`), `posting_batches`/lines (immutable), contacts, invoices, bills, bank, tax codes, fiscal periods, audit.
* Payroll (0005): `employees` (organisation_id, name, email, personal_id, gross_salary, funded_pension_percent, apply_tax_free_minimum, board_member, active), `pay_runs` (Draft→Approved, posted_batch_id), `pay_run_items` (frozen calculation).
* Seeded EE accounts: 6110/6120/6130 expense and 2210/2220/2230/2240 liabilities.

**FastHRM**
* `employees` (code, names, email, dept_id, designation, manager_id, branch, status, date_of_joining, gender, **base_salary = annual**, employment_type, personal_code, working_time_ratio, latest_amendment_date, candidate_id…).
* Also: `departments`, `leave_requests`/`leave_balances`, `attendance`, `payslips` + `payslip_lines`, `pay_runs` (period UNIQUE), `statutory_exports` (TOR/TSD CSV), benefits, expenses/advances/travel, shifts.
* `organizations` exist only for the recruiting product. Employees are **not** scoped to any employer.

### Auth and API surface
* **FastAccounts API:**
  * Session cookie (Google SSO / local accounts) plus `X-CSRF-Token` on writes.
  * The `X-Test-User` header only works when `FASTACCOUNTS_ALLOW_TEST_AUTH=true`, which is false in production.
  * Payroll routes: `/api/organisations/{oid}/employees` (GET/POST/PATCH), `/pay-runs` (GET/POST), `/pay-runs/{id}/approve`, `DELETE /pay-runs/{id}`, `/pay-runs/{id}/payslips.pdf`.
  * There is **no service-to-service token**.
* **FastHRM API:**
  * `web/api_core.py` is a generic SQLite resource API; writes require a bearer token. Read access control: see the security note in §0 (redacted).
  * Write-enabled resources: leave, applications, organizations, brands, career-sites, organization-teams, job-distributions.
  * **No writes for employees or departments.**
  * UI routes cover `/employees`, `/payroll/runs*` and `/payroll/runs/{id}/export/{tor|tsd}`, using session auth and RBAC.
* **Integrations between Fast\* apps: none.** FastAccounts' integrations registry lists QuickBooks/Xero/Merit/HMRC/EMTA/Open banking as stubs (`live_integrations: 0`). FastHRM has none toward FastAccounts.

### i18n
* **FastAccounts:** `web/i18n.py` plus JSON catalogues `web/locales/{en,et,lv,lt}.json`. Default `en` (`FASTACCOUNTS_DEFAULT_LANG`), with `Accept-Language` detection and a session override. The public site and workspace strings go through `t()`/`tr()` in app.js. Known gaps (from the change log): backend validation errors and stored payroll memos can still be English. `tests/test_i18n.py` exists.
* **FastHRM:** `web/i18n.py`, a 133 KB Python dict (`COPY` for public pages, `APP_COPY` for the app). Languages `("et","en")`, **default `et`**, selected by `?lang=` then the session. The app shell was fully localised in PRs #39 to #41 (2026-09-15). Payslip line labels are hard-coded bilingual strings in `db.py`.

### Payroll wiring in FastAccounts (`#payroll`)
* `static/app.js` `views.payroll` loads `/employees` and `/pay-runs`.
* The nav item is disabled with a tooltip unless the organisation is EE + EUR.
* `payrollWizard` creates a draft, then Approve posts `PAY-YYYY-MM` at month-end, and payslips can be downloaded as PDF.
* Rules are in `docs/payroll_rules.md`.

### Tests and docs
* Both repos have pytest suites and keep `docs/change_log.md` and `docs/product_roadmap.md` in sync (rule in AGENTS.md).
* FastAccounts adds `tests/test_payroll.py` and `tests/test_workspace_payroll.py`.

### Defects to fix whatever architecture is chosen
1. **FastHRM income tax is wrong.** `create_pay_run` computes `0.22 × gross` with no basic exemption and no deduction of pension/UI. II pillar is hard-coded to 2%. The employer UI line is labelled "Deduction". Salary is stored annually and divided by 12. No social-tax line is stored; the TSD export assumes 33%.
2. **FastHRM API security.** A FastHRM API access-control issue (details withheld from this public repository; reported to Julian privately). Fix it **before** any isikukood is stored.
3. **FastHRM TSD/TÖR exports use made-up CSV headers.** Since 2026-10-01 the old TSD XML is invalid; see §3.
4. **FastAccounts gaps:**
   * II pillar 0% is allowed only for board members, but since 2021 anyone may not have joined or may have left II pillar.
   * No FTE: the minimum-wage check uses full-time €886/€946, so a 0.5 FTE employee is wrongly rejected.
   * No hourly pay.
   * Social-tax minimum base (€886) is not applied.
   * No 776 € pension-age exemption, and employee UI does not stop at pension age.
   * Only 2026 periods are accepted.
5. **Migration-number collision** (FastAccounts `0005_latvia_foundation` local vs `0005_payroll` on main). Renumber before the Latvia work is committed.

## 2. Competitors

| Product | Payroll scope | Bureau / multi-company | EMTA / TÖR | Price (excl. VAT) |
|---|---|---|---|---|
| **Merit Palk** (separate from Merit Aktiva) | <ul><li>Cloud payroll; tax rates update automatically</li><li>Imports employees and contracts from TÖR</li><li>Payslips by e-mail; bank payment orders</li><li>Holiday and sick pay on average earnings</li><li>Posts to any finance software</li></ul> | <ul><li>Unlimited companies</li><li>Package chosen by the largest company</li><li>1–2 companies included; each extra company €3.50/month (€5.50 from 1.12.2026)</li></ul> | <ul><li>Data-based TSD from 1.10.2026: sends per-payment transactions through the m2m interface (Swedbank AS runs the security server)</li><li>Final TSD confirmation is still done in e-MTA</li></ul> | <ul><li>Free for 1–2 employees</li><li>Standard €9–249/month, Pro €14–399/month by headcount</li></ul> |
| **Directo** (ERP) | Personnel and payroll module, TSD export/upload | Many companies (ERP) | <ul><li>TSD sent straight to e-MTA (annexes 4–6 too)</li><li>TÖR m2m (company grants rights to Directo, reg 10652749)</li><li>Tervisekassa sick-leave certificate interface</li><li>Data-based TSD 2026/27</li></ul> | Payroll and personnel €79/month up to 250 persons (from 1.9.2026) |
| **SmartAccounts** | <ul><li>Payslips and hourly pay</li><li>Holidays and absences</li><li>Pensionikeskus query, TÖR submission</li></ul> | "Büroo" package, discounted from 4 companies | TSD/KMD through the e-MTA interface (Pro) | Pro €27/month; Starter by entries, payroll for 1 employee only |
| **Standard Books** (Excellent) | Payroll module; imports employees from TÖR | Multi-company ERP | TSD straight to EMTA, annexes 4–6 | From €129/month |

Sources:
* Merit: https://www.merit.ee/merit-palk/palgaprogramm/ , https://www.merit.ee/merit-palk/hinnad/ , https://www.merit.ee/wp-content/uploads/2026/10/hinnakiri-2026.docx.pdf , https://support.merit.ee/et/articles/833392-andmepohine-tsd-merit-palk-programmis-alates-1-oktoobrist-2026
* Directo: https://wiki.directo.ee/et/tsd , https://wiki.directo.ee/et/per_tootreg , https://wiki.directo.ee/et/incapacity_for_work_report , https://directo.ee/uudised/andmepohine-aruandlus-2026-27 , https://directo.ee/uudised/directo-hinnakirja-uuendus-2026
* SmartAccounts: https://www.smartaccounts.eu/et/hind/ , https://www.smartaccounts.eu/et/raamatupidamisbyroo/
* Standard Books: https://www.excellent.ee/standard-booksi-palgamoodul/ , https://www.excellent.ee/hinnad/

**What this means for us:** the minimum a bureau expects is:
* multi-company payroll under one login;
* TÖR import and registration;
* data-based TSD over the m2m interface (since 1.10.2026);
* holiday and sick-pay averages;
* payslips by e-mail;
* a bank payment file;
* posting to the ledger.

Merit sets the price anchor (free for 1–2 employees, about €5.50 per extra company). Our angle is one app for bureau bookkeeping and payroll, with open source/BYOC and €1/month hosting.

## 3. Estonian government integrations

**TSD (EMTA)**
* Due by the 10th of the following month.
* **From 1.10.2026 TSD annexes 1–2 are "data-based" (andmepõhine).** Payroll software sends per-payment transactions in **XBRL GL XML**. **The old TSD XML format is no longer valid.**
* e-MTA accepts XBRL GL file upload. **CSV upload is a transitional option until the end of 2027.**
* X-tee v6 services: `uploadMime` (SOAP with gzip attachment), `confirmTsd`, `getTsdStatus`, `getTsdFeedback`.
* The client company grants the security-server operator either the e-MTA X-tee authorisation "Väljamakseandmete edastamine X-tee kaudu" or the "Masin-masin liidese volituste pakett (KMD, TÖR, TSD)".
* Test window: April to August 2026, environments ee-test/ee-dev requested via x-tee.ee.
* Annexes 3–8 stay as before.
* Sources: https://emta.ee/ariklient/maksud-ja-tasumine/tulumaks-ja-sotsiaalmaks/deklaratsiooni-tsd-esitamine/deklaratsiooni-tsd-esitamine-muutub-andmepohiseks , https://emta.ee/ariklient/e-teenused-koolitused/e-teenuste-kasutamine/teenuste-tehniline-info , https://www.emta.ee/ariklient/maksud-ja-tasumine/tulumaks-ja-sotsiaalmaks/deklaratsiooni-tsd-esitamine/x-tee-teenuste-kasutamiseks-vajalikud-paasuoigused , https://emta.ee/ariklient/amet-uudised-ja-kontakt/arendustegevus/andmepohine-aruandlus , https://www.emta.ee/uudised/andmepohise-aruandluse-uudiskiri-nr-2

**TÖR (employment register)**
* X-tee services `EE/GOV/70000349/tor/TOOTREG/v2` (register/change) and `TORRGNO/v2` (suspend). The WSDL also has TORSYNK, TORKODAK, TORIK, TORRKA.
* TOOTREG/TORRGNO **need no data-exchange agreement**, but EMTA must open them for the subsystem (request to andmed@emta.ee).
* The employer authorises the security-server owner; the person submitting needs the 240TÖR right.
* Data-based TÖR is planned from 1.1.2027 (Directo).
* Sources: https://emta.ee/ariklient/e-teenused-koolitused/e-teenuste-kasutamine/x-tee-teenused , https://koodivaramu.eesti.ee/tehik/t-ja-kesksete-teenuste-valdkond/t-inspektsioon/teis/xroad-gateway/-/blob/2.12.0/service/src/main/schemas/xjc/emtav6-tor.wsdl

**X-tee generally**
* We need either our own X-tee member and security server (Estonian legal entity, RIA membership, SK auth/sign certificates) **or** a security-server service provider. Merit uses Swedbank's.
* EMTA does not charge for X-tee queries.
* MVP needs none of this: manual file upload to e-MTA.

**Tervisekassa (sick-leave certificates, TVL)**
* Employer X-tee services ("Tööandja X-tee teenused"). The employer grants the vendor authority in eesti.ee.
* The employer must complete the TVL within 7 days of learning it was closed.
* Employer pays days 4–8 at 70% of average pay (no cap). Tervisekassa pays from day 9 at 70%, capped at €126.87/day in 2026. Days 1–3 are unpaid.
* Sources: https://tervisekassa.ee/inimesele/huvitised/haigushuvitis , https://tervisekassa.ee/tooandjale/ajutise-toovoimetuse-huvitis/toovoimetuslehe-andmete-edastamine , https://www.riigiteataja.ee/et/dyn/126022016007/id/110112015013

**Pensionikeskus (II pillar)**
* XML "automaatne liitumiskontroll" query by isikukood: joined or not, and the rate (2/4/6%).
* The obligation can change on 1 Jan, 1 May and 1 Sep. Re-check in December, April and August.
* Sources: https://www.pensionikeskus.ee/raamatupidajale/ii-sammas/automaatne-liitumiskontroll/ , https://www.pensionikeskus.ee/ii-sammas/sissemaksed/makse-maara-muutmine/

**Töötukassa**
* No separate employer filing: unemployment-insurance contributions are declared and paid through TSD.
* Employee UI withholding stops at pension age; the employer's 0.8% continues.

**Bank salary file**
* ISO 20022 **pain.001.001.09**. Estonian banks dropped the common Pangaliit standard in 2024.
* **SEB stops accepting pain.001.001.03 and M-type files on 15.11.2026**, and requires structured or hybrid addresses (TwnNm + Ctry).
* Batch booking: `BtchBookg=true` and/or `CtgyPurp=SALA`.
* Sources: https://www.seb.ee/iso-xml-muudatused , https://docs.lhv.com/home/connect/services/payments/pain.001.001.09-format , https://www.seb.ee/palga-maksmine-uhe-maksekorraldusega-koigile-tootajatele , https://pangaliit.ee/arveldused/xml-b2c-and-c2b-suhtlussonumid

## 3b. 2026 payroll rates (verified)
| Item | 2026 value | Source |
|---|---|---|
| Income tax | 22% | EMTA Maksumäärad (updated 26.03.2026) |
| Basic exemption (maksuvaba tulu) | <ul><li>Flat **€700/month** (€8,400/year); the old sliding reduction ("maksuküür") is abolished</li><li>€776/month at pension age</li><li>Applied only on the employee's written application, at one employer</li><li>Monthly; unused amount cannot be carried forward (settled in the annual return)</li></ul> | EMTA Maksumäärad; https://emta.ee/eraklient/maksud-ja-tasumine/maksusoodustused/maksuvaba-tulu-arvestamine ; https://emta.ee/uudised/maksumuudatused-2026 |
| Taxable base | gross − II pillar − employee UI − exemption | EMTA |
| Social tax | 33%; minimum monthly base **€886** (minimum €292.38) | EMTA Maksumäärad |
| Unemployment insurance | employee **1.6%**, employer **0.8%**; not for board-member fees | EMTA Maksumäärad |
| II pillar | **2% (default) / 4% / 6%**, or 0 if not joined/left; the state adds 4% from social tax | Pensionikeskus; EMTA |
| Minimum wage | **€886/month** (€5.31/h) until 31.03.2026 (rate from 1.1.2025); **€946/month, €5.67/h from 1.4.2026** (Government regulation no. 36 of 23.03.2026) | EMTA Maksumäärad "Töötasu alammäärad" |
| Holiday pay | Average calendar-day pay: last 6 months' earned pay ÷ calendar days, excluding public holidays and absence days. Pay is simply kept unchanged if the salary did not change in the 6 months | https://www.tooelu.ee/et/176/keskmise-tootasu-arvutamine (VV määrus nr 91) |
| Sick pay | Days 1–3 unpaid; days 4–8 employer pays 70% of average calendar-day pay; day 9+ Tervisekassa pays 70% (cap €126.87/day) | Tervisekassa; TTOS § 12² |

**Flagged as uncertain:**
1. "€1,886 minimum wage" in the brief is a typo. The minimum wage is €886 until March and €946 from April 2026.
2. The social-tax minimum base has exceptions not modelled: pensioners, disability, another employer already paying it, and others. Confirm with an accountant.
3. Whether the base is pro-rated for part-time staff: it is **not** pro-rated by FTE, but the exceptions in point 2 apply.
4. The XBRL GL TSD taxonomy details have not been read yet (the docs are on the EMTA andmepõhine aruandlus page).
5. The UI rates are reported as fixed through 2028 in FastAccounts' spec. This is not verified.

## 4. Recommended architecture

### Options considered
* **A. FastHRM as payroll service, FastAccounts as API client only.** Matches Julian's ownership intent. But FastHRM is single-tenant, uses SQLite and floats, and has wrong tax maths. A bureau would need a FastHRM tenancy refactor *before* any value is delivered.
* **B. Shared package only, each app keeps its own payroll tables.** Fast, but leaves two systems of record for employees.
* **C. Recommended hybrid: shared rules package + FastHRM system of record + FastAccounts ledger/bureau shell.**

### Recommended design (C)
1. **`fastsme-payroll-ee`** is a new repo, `predictivelabsai/fastsme-payroll`, pip-installable from a git tag.
   * Pure functions with no database: `calculate(employee_snapshot, period, inputs, rules)` returns lines and totals, using Decimal and ROUND_HALF_UP.
   * Year-versioned rule tables (2026, 2027…): rates, exemption, minimum wage by effective date, social-tax minimum base, sick-pay cap.
   * Average-pay calculator (holiday and sick pay).
   * Statutory builders: TSD XBRL GL (and the transitional CSV), TÖR payloads, pain.001.001.09, payslip PDF data model.
   * Golden test vectors (our fixture plus accountant-verified cases).
   * Seed it from FastAccounts `payroll.py`, which is the better implementation, and fix the gaps listed in §1.
2. **FastHRM owns the payroll domain:**
   * employers (client companies), employees, contracts (type, FTE, pay basis, salary history), tax settings (exemption application, II pillar rate plus Pensionikeskus check date), absences (holiday, sick, TVL);
   * pay runs, payslips, TÖR events, TSD submissions, bank files.
   * This requires **employer tenancy** in FastHRM: an `employer_id` on every HR/payroll table plus membership/roles. **Postgres is strongly recommended** for multi-client payroll.
3. **FastAccounts stays the ledger and the bureau's single login:**
   * It already supports one user across many organisations.
   * It links each FastAccounts organisation to a FastHRM employer.
   * It exposes an idempotent **journal-import API** that FastHRM calls on run approval and on payment.
   * Payroll screens in FastAccounts become an embedded/deep-linked FastHRM view plus posted-journal status.
   * The current FastAccounts payroll demo stays as a "lite" fallback until FastHRM reaches parity. Then it is retired: its migrations stay, the UI is switched off.
4. **Identity:** shared FastSME accounts (`FASTSME_AUTH_DB` already exists in FastHRM) or Google SSO, with the same email on both sides. Service-to-service calls use per-link OAuth2 client credentials or HMAC-signed bearer tokens stored encrypted (FastAccounts already has key-versioned encryption).

**Why this design:**
* The rules are reused in exactly one place: statutory logic changes yearly and must not drift between two repos.
* HR data stays in HR, and the ledger keeps its invariants (immutable balanced batches).
* Bureaus get one login.
* Each app can still be sold standalone.

### Data model (FastHRM, new or changed)
* `employers`: id, name, registry_code, vat_no, address, country=EE, currency=EUR, payday (day of month), default_bank_iban, emta_m2m_authorised (bool, date), fastaccounts_org_id, locale.
* `employer_members`: employer_id, account_email, role (bureau_admin / payroll_accountant / approver / employer_viewer / employee). A bureau is a set of members spanning many employers. An optional `bureaus` table holds branding/billing.
* `employees` (existing, plus): employer_id, personal_code (encrypted at rest, masked in UI and API), date_of_birth, citizenship, tax_residency, address (structured: street, city, postcode, country), iban, email, phone. Keep employee code and names.
* `contracts`: employee_id, contract_type (employment / board_member / service_contract (VÕS) / other), tor_work_type, position_title, tor_occupation_code (8-digit), department_id, start_date, end_date, fte (0–1), weekly_hours, pay_basis (monthly / hourly / fee), base_amount, currency, probation_end, tor_status, tor_registration_id, tor_submitted_at.
* `salary_changes`: contract_id, effective_date, base_amount (supports the indexation/average rules).
* `tax_settings`: employee_id, valid_from, apply_basic_exemption (bool, application_date), exemption_amount (default from rules), pension_rate (0/2/4/6), pension_checked_at (Pensionikeskus), pensioner_flag (stops employee UI, 776 exemption), social_tax_min_exempt_reason.
* `absences`: employee_id, type (annual / study / sick / care / maternity / unpaid…), from, to, tvl_number, tvl_status, employer_days, avg_daily_pay.
* `pay_items_catalog`: code, label_et, label_en, kind (earning / deduction / employer), tsd_payment_type (e.g. 10 Palgatulu…), taxable flags (IT/ST/UI/pension), gl_role.
* `pay_runs`: employer_id, period, payment_date, status (Draft → Calculated → Approved → Paid → Declared), rules_version, totals, approved_by/at, posted_journal_ref, bank_file_id, tsd_submission_id.
* `payslips` and `payslip_lines`: as today plus employer_id, item code, quantity/rate/base, tsd_payment_type, frozen employee snapshot.
* `statutory_submissions`: kind (TSD / TOR / TVL), employer_id, period, format (xbrl_gl / csv / xtee), payload, status, emta_ref, feedback.
* `bank_files`: pay_run_id, format (pain.001.001.09), msg_id, payload, checksum.
* All money uses NUMERIC/Decimal, and all rows carry employer_id.

### Data-model gaps in the current FastHRM API (the sample seed could not be stored)
* employer/company link (`employer_id`)
* contract_type and board-member flag
* pay_basis (monthly / hourly / fee); hourly_rate; monthly salary (today `base_salary` is annual)
* II pillar rate; basic-exemption application flag/date; pensioner flag
* IBAN; structured address; date_of_birth; tax residency; citizenship
* TÖR work type and occupation code; TÖR registration status
* department as a writable link (departments are read-only via the API)
* `personal_code` and `working_time_ratio` exist as columns but are not writable via the API

### FastHRM ↔ FastAccounts API contract (v1)
**Auth:** `Authorization: Bearer <link token>`, scoped to one (FastHRM employer ↔ FastAccounts organisation) pair, plus an `Idempotency-Key` header. All amounts are decimal strings and currency is EUR.

**FastAccounts endpoints (new)**
* `POST /api/integrations/fasthrm/links`: bureau user (session + CSRF) links organisation ↔ employer. Returns a one-time link secret.
* `GET /api/organisations/{oid}/chart/payroll-roles`: returns the account mapping (codes per `system_role`) so FastHRM can preview postings.
* `POST /api/organisations/{oid}/journal-imports` (service token):
  * Request body:
    ```json
    {"source":"fasthrm","source_id":"payrun:<employer>:<period>","voucher_code":"PAY-2026-10",
     "posting_date":"2026-10-31","memo":"Palk 10/2026",
     "lines":[{"role":"PAYROLL_SALARY","debit":"18254.00","dimensions":{"department":"Engineering"}}, ...],
     "attachments":[{"kind":"payroll_summary_pdf","url":"..."}]}
    ```
  * Returns `201 {"batch_id","status":"posted"}`. A retry with the same key and source_id returns `200` with the same batch.
  * Errors: `409` period locked or duplicate with different totals; `422` unbalanced or missing role.
* `POST /api/organisations/{oid}/journal-imports/{batch_id}/reverse`: reversal for a corrected run.
* `POST /api/organisations/{oid}/payment-imports`: on salary/tax payment, clears 2210 and 2220–2240 against the bank account (optional; bank reconciliation can match instead).

**FastHRM endpoints (new, token- or session-authenticated for reads and writes)**
* `GET/POST/PATCH /api/v1/employers/{eid}/employees`, `/contracts`, `/tax-settings`, `/absences`
* `POST /api/v1/employers/{eid}/pay-runs` with `{period, payment_date}`; then `/calculate`, `/approve` (triggers the journal import), `/payslips.pdf`, `/bank-file` (pain.001), `/tsd` (XBRL GL / CSV), `/tor-events`
* Webhooks to FastAccounts: `payrun.approved`, `payrun.paid`, `payrun.reversed`

**Journal mapping (Estonian chart; matches the existing FastAccounts EE roles)**
| Role | Account (default) | Dr/Cr |
|---|---|---|
| PAYROLL_SALARY | 6110 Palgakulu (split board fees to 6111 Juhatuse tasud and holiday pay to 6112 Puhkusetasud if desired) | Dr gross |
| PAYROLL_SOCIAL | 6120 Sotsiaalmaksukulu | Dr social tax |
| PAYROLL_UI | 6130 Tööandja töötuskindlustusmakse | Dr employer UI |
| PAYROLL_SICK (new) | 6140 Haigushüvitis (days 4–8) | Dr |
| PAYROLL_NET | 2210 Võlad töövõtjatele | Cr net |
| PAYROLL_INCOME_TAX | 2220 Kinnipeetud tulumaks | Cr |
| PAYROLL_WITHHOLDING | 2230 Kogumispension + töötaja töötuskindlustus | Cr |
| PAYROLL_EMPLOYER_TAX | 2240 Sotsiaalmaks + tööandja töötuskindlustus | Cr |
| HOLIDAY_ACCRUAL (phase 3) | 2250 Puhkusetasude kohustis / 6112 | accrual |

On payment day: Dr 2210 / Cr bank (net). On the 10th: Dr 2220/2230/2240 / Cr bank (EMTA prepayment account).

### Pay-run flow
1. Select employer and period.
2. Pull active contracts, tax settings, approved absences and hours.
3. Run the Pensionikeskus check (phase 2).
4. Calculate with the rules package and freeze snapshots.
5. Review screen with warnings: below minimum wage pro-rated by FTE, missing isikukood/IBAN, social-tax minimum top-up, exemption applied at more than one employer cannot be checked.
6. Approve: payslips are locked, then the journal import goes to FastAccounts.
7. Generate pain.001 and upload to the bank (phase 2: bank API).
8. Mark paid; send the payment import.
9. Generate TSD: MVP downloads an XBRL GL or CSV file for e-MTA upload; phase 3 sends over X-tee `uploadMime`, then `getTsdStatus`/`getTsdFeedback`, and the user confirms in e-MTA.
10. Email payslips (PDF, et/en).
11. TÖR: MVP gives a checklist/export plus a deep link to e-MTA; phase 3 uses X-tee TOOTREG on contract start, change and end.

### Bureau multi-client UX
* Bureau home: a grid of client employers showing next payday, run status, TSD due (10th), TÖR/TVL to-dos and warnings.
* Bulk actions: create runs for all clients for the period, then review one client at a time.
* Roles: bureau staff assigned per client; client approver; employee self-service for payslips (FastHRM portal already exists).
* One login across FastAccounts and FastHRM through shared FastSME accounts/SSO. A client switcher in both apps keeps the same client in context. The deep link from FastAccounts `#payroll` goes to FastHRM `/employers/{id}/payroll`.

### Full i18n plan (et + en, both apps, whole UI)
* **One approach for both apps:** gettext-style keyed catalogues in JSON (FastAccounts already does this) and a shared tiny helper in the shared package or a vendored `fastsme_i18n`.
* **FastHRM:** move the 133 KB Python dict to `locales/et.json` and `locales/en.json` with a migration script. Keep **et** as default for FastHRM and make FastAccounts' default configurable (et for the EE market).
* **Scope:** all UI strings, server validation errors (error codes mapped to translated messages), PDF payslips, emails, CSV/XBRL labels, enum labels (contract types, absence types, pay items with `label_et`/`label_en`), and number/date formatting (et: `1 234,56 €`, `31.10.2026`; Babel or a small formatter).
* **Stored data:** ledger memos store a key plus parameters, rendered at view time.
* **CI checks:** every key exists in both catalogues; no hard-coded user-visible strings in templates (lint); screenshot tests in both languages; Estonian copy reviewed by a native accountant (payroll terminology glossary in `docs/glossary_et.md`).
* **Effort:** about 3–5 days per app for the remaining FastAccounts backend/PDF strings and the FastHRM catalogue migration, plus about 2 days for the glossary/review.

## 5. Milestones (effort assumes 1 developer, AI-assisted)
| # | Milestone | Content | Effort |
|---|---|---|---|
| M0 | Safety and hygiene (now) | <ul><li>Fix the FastHRM API access-control issue (private note)</li><li>Fix the FastHRM income-tax formula or hide the FastHRM payroll</li><li>Renumber FastAccounts' local Latvia migration</li><li>Align with Joosep on ownership</li></ul> | 1–2 d |
| M1 | Prospect demo (already possible) | <ul><li>Use the live FastAccounts EE payroll demo (multi-organisation, payslip PDF, ledger posting)</li><li>Fix the quick gaps: 0% pension for anyone, FTE + pro-rated minimum wage, hourly, social-tax minimum base</li></ul> | 2–3 d |
| M2 | `fastsme-payroll-ee` package | Rules engine extracted from FastAccounts, year tables, average pay, golden vectors; FastAccounts switched to it | 4–6 d |
| M3 | FastHRM employer tenancy + Postgres | `employer_id` everywhere, members/roles, contracts/tax settings/absences model, authenticated employee CRUD API, seed (our fixture) | 8–12 d |
| M4 | FastHRM payroll on the package | Runs, holiday and sick pay, payslip PDFs et/en, e-mail, pain.001.001.09 export | 6–8 d |
| M5 | FastAccounts integration | Org↔employer link, service tokens, journal-imports and reversal, bureau dashboard, deep links/SSO | 5–7 d |
| M6 | TSD/TÖR files | XBRL GL TSD file (+ transitional CSV) validated against EMTA test cases; TÖR checklist/export | 5–8 d |
| M7 | Full i18n et/en both apps | Per §4 | 6–10 d |
| M8 | Direct government integration | X-tee via a security-server provider or own membership: TSD uploadMime/confirm/status/feedback, TÖR TOOTREG/TORRGNO, Tervisekassa TVL, Pensionikeskus check | 15–25 d plus onboarding lead time |
| M9 | Accountant UAT and pilot bureau | Parallel run versus Merit for 2 months on 2–3 clients | calendar 2 mo |

Critical path to a sellable bureau MVP (file-based TSD, no X-tee): M0 → M2 → M3 → M4 → M5 → M6, about **6–8 weeks**.

## 6. Risks
* **Two parallel payroll implementations already exist** (FastAccounts PR #2 and FastHRM 0006–0011), both by the same contributor. Without a decision, effort is wasted and the rules diverge.
* **Compliance and liability:** wrong tax hurts the bureau's clients. Mitigate with golden vectors, accountant UAT and a clear "demo/pilot" label.
* **Data-based TSD is new** (since 1.10.2026) and the XBRL GL spec is still evolving. Manual upload depends on a format we have not yet validated. Competitors already send it over m2m.
* **X-tee onboarding lead time:** membership, certificates, EMTA service opening and contracts. A provider (e.g. a bank security-server service) may be faster.
* **GDPR:** isikukood, salary and health (sick leave). Needs encryption at rest, access logs, a DPA with bureaus, and an EU data location. FastHRM API access control must be fixed first (private note).
* **SQLite single-tenant FastHRM** does not scale to bureaus. Migrating to Postgres is a prerequisite.
* **Price pressure:** Merit is free for 1–2 employees and about €5.50 per extra company.

## 7. Sample employees: blocker and local artefacts
* **Blocked on fasthr.eu**, verified 2026-10-08:
  * `GET https://fasthr.eu/api/v1/health` returns `writes_enabled:false`.
  * The OpenAPI/`web/api.py` has no `write_fields` for `employees` or `departments`, so there is no `POST /api/v1/employees`.
  * There is no employer entity: `POST /api/v1/organizations` exists (bearer token), but those are recruiting organisations that do not scope employees, so creating "Demo OÜ" there would be meaningless pollution.
  * No API key was created or stored, and `/home/box/.secrets/fasthr.env` was not created, because a token would not help without an endpoint.
  * There was no direct database write.
* **What is needed:**
  1. Julian's go-ahead to add `employers` and an authenticated employee/contract CRUD API in FastHRM (M3).
  2. Fix the FastHRM API access-control issue first (private note).
  3. Set `FASTSME_API_TOKEN` (or the new per-employer tokens) in Coolify.
  4. Then run `scripts/seed_ee_sample_employees.py --apply` against staging or a demo tenant.
* **Alternative for a demo today:** FastAccounts already has `POST /api/organisations/{oid}/employees` (session + CSRF), and its seed already creates six synthetic EE employees.
* **Artefacts:** `scripts/seed_ee_sample_employees.py` (validates isikukood checksum and birth date, computes mod-97 IBANs, calculates the expected Oct-2026 payslip, dry run by default) and `fixtures/ee_sample_employees.json`.

| Code | Name | Role | Basis | Gross (Oct 2026) | II pillar | Exemption | Net | Employer cost |
|---|---|---|---|---|---|---|---|---|
| DEMO-EE-001 | Mari Tamm | Klienditeenindaja | monthly 1.0 FTE | 946.00 (minimum wage) | 2% | yes | 865.31 | 1,265.75 |
| DEMO-EE-002 | Jaan Kask | Raamatupidaja (Tartu) | monthly | 2,400.00 | 2% | no | 1,804.61 | 3,211.20 |
| DEMO-EE-003 | Kadri Saar | Tarkvaraarendaja | monthly | 3,800.00 | 4% | no | 2,798.02 | 5,084.40 |
| DEMO-EE-004 | Andres Mets | Arendusjuht | monthly | 5,500.00 | 6% | no | 3,963.96 | 7,359.00 |
| DEMO-EE-005 | Liis Kuusk | Laotöötaja (Tartu) | monthly 0.5 FTE | 700.00 | none | yes | 688.80 | 997.98* |
| DEMO-EE-006 | Peeter Oja | Kassapidaja | hourly €8 × 176 h | 1,408.00 | 2% | yes | 1,212.70 | 1,883.90 |
| DEMO-EE-007 | Toomas Rebane | Juhatuse liige | board fee | 1,500.00 | 2% | no | 1,146.60 | 1,995.00 |

\*Social tax is calculated on the €886 minimum base (exceptions not modelled). Personal codes are checksum-valid but invented, and could still coincide with a real person. IBANs use the unassigned bank code 00 (mod-97 valid; the national check digit is not guaranteed).

## 8. Draft reply to the prospect (Estonian, NOT sent)
> Tere!
>
> Aitäh küsimast. Lühidalt: palgaarvestus mitmele kliendifirmale on meil töös ning esimene versioon on juba kasutatav, kuid täismahus raamatupidamisbüroo lahendus valmib etappidena.
>
> **Mis on olemas täna (FastAccounts, fastaccounts.org):**
> * Üks kasutaja saab hallata mitme kliendifirma raamatupidamist.
> * Eesti firmadele on demo-tasemel igakuine palgaarvestus 2026. a määradega: tulumaks 22%, maksuvaba tulu 700 € avalduse alusel, II sammas 2/4/6%, töötuskindlustus ja sotsiaalmaks; juhatuse liikme tasu eraldi.
> * Palgalehed PDF-ina.
> * Kinnitatud palgaarvestus kirjendatakse automaatselt pearaamatusse.
>
> **Mis on teekaardil (lähinädalad kuni -kuud):**
> * Puhkuse- ja haigushüvitiste arvestus.
> * Osaajaga ja tunnitasuga töötajad.
> * Palgalehtede saatmine e-postiga.
> * Pangafail palgamakseteks (SEPA XML).
> * Andmepõhise TSD fail e-MTA-sse üleslaadimiseks ning TÖR-i andmete ettevalmistus.
> * Hiljem ka otseliidesed Maksu- ja Tolliameti, Tervisekassa ja Pensionikeskusega.
>
> Praegu ei saa me veel lubada TSD otseesitamist ega TÖR-i liidest. Kui sobib, näitaksime hea meelega 30-minutilise demo ning kaasaksime Teid pilootkliendina, et lahendus vastaks büroo igapäevatööle. Kui palju kliendifirmasid ja töötajaid Teil orienteeruvalt on ning millist tarkvara praegu kasutate?
>
> Parimate soovidega,
> Julian Kaljuvee

## 9. Open questions for Julian (★ = key decisions)
1. ★ **Ownership and consolidation.** Joosep's FastAccounts payroll (merged and live today) and FastHRM payroll both exist. Do we confirm option C (shared `fastsme-payroll-ee` package, FastHRM as system of record, FastAccounts as ledger + bureau login), and keep the FastAccounts demo only as a stop-gap? Is Joosep in the loop?
2. ★ **MVP for this prospect.** Demo the live FastAccounts payroll now, or wait for the FastHRM-based flow? Which features are must-haves: holiday/sick pay, TSD file, bank file, TÖR?
3. ★ **FastHRM multi-tenancy + Postgres.** Approve adding `employers` + an authenticated employee API (M3), and fixing the FastHRM API access-control issue (private note) right away, even before the payroll work?
4. Timeline or target date for the prospect, and the pilot terms.
5. Workflow: commit straight to `main` (which autodeploys via Coolify) or use feature branches + PRs? Keep demo payroll behind a feature flag in production?
6. Do you, or any FastSME entity, have X-tee membership, a security-server provider, or EMTA m2m access? Is there an accountant for UAT?
7. Repo paths: the checkouts are at `~/dev/fastsme/` (not `~/dev/plai/`). The ThinkPad has uncommitted FastAccounts Latvia work with a colliding `0005` migration. Who owns that work?
8. Should FastAccounts' default UI language be `et` for the EE market (FastHRM already defaults to `et`)?
9. Where should the sample employees go: a staging/demo FastHRM instance, or a demo employer in production once tenancy exists?
