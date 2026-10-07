# Repository Guidelines

## Product boundary

FastAccounts is bookkeeping software for UK and Estonian small businesses, not
an ERP. Estonian accounting-bureau payroll for client books is in demo scope;
production UAT is pending. Keep inventory, order management, manufacturing, CRM,
and HR outside this repository. Integrate with sister products for those workflows.

## Architecture and accounting invariants

Use Python 3.12, server-rendered FastHTML/HTMX pages, and FastAPI for the public
API. Keep route handlers thin. Domain services own workflows and PostgreSQL
transactions; repository modules own parameterized queries. Use numbered,
additive SQL migrations and deterministic synthetic seeds.

Every posted business event must create one immutable, balanced double-entry
batch in the same database transaction. Never edit or delete posted ledger
lines. Correct mistakes with an explicit credit note, void, or reversal linked
to the original. Use `Decimal` and database `NUMERIC`, never binary floats, for
money and tax. All business data must be scoped to an organisation.

## Configuration and security

Load local configuration from `.env` and keep `.env` ignored. Update
`.env.sample` whenever configuration changes. Never commit credentials, OAuth
tokens, real accounting data, bank transactions, uploaded evidence, or
production databases. Encrypt provider credentials at rest with key-versioned
encryption and keep plaintext out of logs and browser responses.

## Testing

Use pytest. Cover balance invariants, reversals, locked periods, tax rounding,
document sequencing, idempotency, tenant isolation, migrations, sync retries,
and data preservation. Provider tests use fakes or recorded redacted fixtures;
live network tests must be explicit opt-ins. Use Playwright for critical browser
flows. Seed data must be synthetic.

## Roadmap and change log

Treat `docs/product_roadmap.md` and `docs/change_log.md` as a synchronized pair.
Any implementation that changes roadmap status or scope must update both in the
same change. Do not mark work complete until its tests and acceptance criteria
pass.
