# FastAccounts

FastAccounts is an open-source bookkeeping and small-business accounting system
for UK companies/sole traders and Estonian OÜs/FIEs. It is deliberately not an
ERP. The modular monolith covers invoices and credit notes, bills and evidence,
payments, statement import/reconciliation, an immutable double-entry ledger,
financial reports, and accountant-reviewed UK VAT/Estonian KMD workpapers.

Version 0.2 is an engineering-complete pilot. UK and Estonian accountant UAT is
the remaining country-validation gate; direct tax filing is intentionally
disabled until that UAT and the relevant provider approvals are complete.

## Run locally

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.sample .env
# Set stable FASTACCOUNTS_SECRET and FASTACCOUNTS_ENCRYPTION_KEY values.
.venv/bin/python web_app.py
```

Open `http://localhost:5012`. Google OAuth is the normal workspace sign-in. For
synthetic local UAT only, set `FASTACCOUNTS_ALLOW_TEST_AUTH=true`, run
`.venv/bin/python seed.py`, then open `/auth/test`.

Run the tests with:

```bash
.venv/bin/python -m pytest tests/ -q
```

## What is implemented

- FastHTML workspace and typed FastAPI/OpenAPI surface with Google sign-in,
  CSRF, organisation membership, and owner/admin/accountant/approver/viewer roles.
- Portable numbered migrations for SQLite demos and schema-isolated PostgreSQL
  production, plus deterministic synthetic UK/EE seed books.
- Country-aware starter charts and effective tax codes; line-level `Decimal`
  rounding; atomic invoice and credit numbering.
- Invoice PDF/email/review XML, purchase approvals/evidence hashes, payments and
  allocations, CSV/CAMT.053 import, explainable match suggestions, and manual
  confirmation.
- Database-enforced balanced/immutable postings, linked reversals, locks, audit
  events, trial balance, general ledger, P&L, balance sheet, AR/AP aging, and
  cash summary.
- UK nine-box VAT and Estonian KMD workpapers with review-before-export gates.
- Encrypted, key-versioned integration state; explicit ownership/direction,
  mappings, cursors, conflicts, outbox, and replay-safe webhook receipts.
- Live-ready HTTP adapters with mocked contract tests for QuickBooks, Xero,
  Merit, HMRC sandbox, and read-only GoCardless Bank Account Data. e-MTA remains
  export-only pending an X-Road agreement.

Normal tests make no provider network calls and use no real business data.

## Database and deployment

If `DB_URL` is set, FastAccounts uses PostgreSQL and `DB_SCHEMA` (default
`fast_accounts`). Otherwise it uses `FASTACCOUNTS_DB` SQLite. Migrations run on
startup. Evidence is stored below `FASTACCOUNTS_DATA_DIR`; managed deployments
must attach persistent storage and add malware scanning.

The Docker image exposes port 5012 and `/healthz`. Deployment is registered in
the sibling FastDevOps catalogue for `https://accounts.fastsme.com`:

```bash
python scripts/coolify.py validate
python scripts/coolify.py doctor
python scripts/coolify.py provision --yes
python scripts/coolify.py env --sync --yes
python scripts/coolify.py deploy --yes
python scripts/coolify.py status
```

Pushes to `main` run the GitHub Actions test/build workflow and, after they are
accepted by GitHub, a signed push-only webhook asks Coolify to deploy the same
commit. FastDevOps remains the local control plane for status checks, explicit
deployments, and environment synchronization; it is not a separate runtime
service.

See [product roadmap](docs/product_roadmap.md),
[accounting invariants](docs/accounting_invariants.md),
[threat model](docs/threat_model.md), and [accountant UAT plan](docs/uat_plan.md).

No provider credential, real company record, invoice, receipt, bank transaction,
or production database may be committed to this repository.
