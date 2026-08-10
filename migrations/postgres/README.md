# PostgreSQL migration path

FastAccounts keeps one canonical set of portable DDL files under `migrations/sqlite/` so
schema changes cannot drift between development and production. `Database.migrate()`
applies those numbered files directly to PostgreSQL and replaces the two SQLite-specific
trigger migrations with equivalent PL/pgSQL functions and triggers.

Every migration is recorded in the target schema's `schema_migrations` table. The
PostgreSQL schema is selected with `DB_SCHEMA` (default `fast_accounts`) and is validated
before interpolation. CI runs SQLite migrations by default; a real PostgreSQL migration
suite runs when `TEST_POSTGRES_URL` is available.
