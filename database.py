"""Portable SQLite/PostgreSQL connections and numbered migration runner."""
from __future__ import annotations

import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence


ROOT = Path(__file__).parent
MIGRATIONS = ROOT / "migrations"
SCHEMA_PATTERN = re.compile(r"^[a-z_][a-z0-9_]*$")


class Transaction:
    """Small parameterized-query adapter shared by both supported databases."""

    def __init__(self, connection, dialect: str):
        self.connection = connection
        self.dialect = dialect

    def _sql(self, query: str) -> str:
        return query.replace("?", "%s") if self.dialect == "postgres" else query

    def execute(self, query: str, params: Sequence[Any] = ()):
        return self.connection.execute(self._sql(query), tuple(params))

    def one(self, query: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        row = self.execute(query, params).fetchone()
        return dict(row) if row else None

    def rows(self, query: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        return [dict(row) for row in self.execute(query, params).fetchall()]

    def scalar(self, query: str, params: Sequence[Any] = ()) -> Any:
        row = self.execute(query, params).fetchone()
        if not row:
            return None
        if isinstance(row, sqlite3.Row):
            return row[0]
        return next(iter(row.values()))


class Database:
    def __init__(self, *, url: str = "", path: str = "", schema: str = "fast_accounts"):
        self.url = url.strip()
        self.path = path or str(ROOT / "fastaccounts.sqlite")
        self.schema = schema.strip() or "fast_accounts"
        self.dialect = "postgres" if self.url else "sqlite"
        if not SCHEMA_PATTERN.fullmatch(self.schema):
            raise ValueError("DB_SCHEMA contains an unsafe PostgreSQL identifier")

    @classmethod
    def from_env(cls) -> "Database":
        return cls(
            url=os.getenv("DB_URL", ""),
            path=os.getenv("FASTACCOUNTS_DB", "") or str(ROOT / "fastaccounts.sqlite"),
            schema=os.getenv("DB_SCHEMA", "fast_accounts"),
        )

    def connect(self):
        if self.dialect == "sqlite":
            connection = sqlite3.connect(self.path, timeout=15)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=5000")
            return connection
        from psycopg import connect
        from psycopg.rows import dict_row

        connection = connect(self.url, row_factory=dict_row)
        connection.execute(f'SET search_path TO "{self.schema}", public')
        return connection

    @contextmanager
    def transaction(self) -> Iterator[Transaction]:
        connection = self.connect()
        try:
            yield Transaction(connection, self.dialect)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def one(self, query: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        with self.transaction() as tx:
            return tx.one(query, params)

    def rows(self, query: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self.transaction() as tx:
            return tx.rows(query, params)

    def scalar(self, query: str, params: Sequence[Any] = ()) -> Any:
        with self.transaction() as tx:
            return tx.scalar(query, params)

    def migrate(self) -> list[str]:
        directory = MIGRATIONS / ("sqlite" if self.dialect == "postgres" else self.dialect)
        applied: list[str] = []
        if self.dialect == "sqlite":
            connection = self.connect()
            try:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS schema_migrations "
                    "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
                )
                done = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
                for path in sorted(directory.glob("*.sql")):
                    if path.stem in done:
                        continue
                    connection.executescript(path.read_text(encoding="utf-8"))
                    connection.execute(
                        "INSERT INTO schema_migrations(version,applied_at) VALUES (?,datetime('now'))",
                        (path.stem,),
                    )
                    applied.append(path.stem)
                connection.commit()
            finally:
                connection.close()
            return applied

        from psycopg import connect
        from psycopg.rows import dict_row

        connection = connect(self.url, row_factory=dict_row)
        try:
            connection.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
            connection.execute(f'SET search_path TO "{self.schema}", public')
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            done = {row["version"] for row in connection.execute("SELECT version FROM schema_migrations")}
            for path in sorted(directory.glob("*.sql")):
                if path.stem in done:
                    continue
                script = path.read_text(encoding="utf-8")
                if path.stem == "0001_accounting_core":
                    marker = "CREATE TRIGGER IF NOT EXISTS gl_entries_immutable_update"
                    script = script.split(marker, 1)[0] + _POSTGRES_LEDGER_TRIGGERS
                elif path.stem == "0004_document_immutability":
                    script = _POSTGRES_DOCUMENT_TRIGGERS
                connection.execute(script)
                connection.execute(
                    "INSERT INTO schema_migrations(version) VALUES (%s)",
                    (path.stem,),
                )
                applied.append(path.stem)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return applied


_cached: tuple[tuple[str, str, str], Database] | None = None


def get_database() -> Database:
    global _cached
    signature = (
        os.getenv("DB_URL", ""),
        os.getenv("FASTACCOUNTS_DB", ""),
        os.getenv("DB_SCHEMA", "fast_accounts"),
    )
    if _cached is None or _cached[0] != signature:
        _cached = (signature, Database.from_env())
    return _cached[1]


def reset_database_cache() -> None:
    global _cached
    _cached = None


_POSTGRES_LEDGER_TRIGGERS = r"""
CREATE OR REPLACE FUNCTION reject_gl_entry_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'posted ledger entries are immutable';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS gl_entries_immutable_update ON gl_entries;
CREATE TRIGGER gl_entries_immutable_update BEFORE UPDATE ON gl_entries
FOR EACH ROW EXECUTE FUNCTION reject_gl_entry_mutation();

DROP TRIGGER IF EXISTS gl_entries_immutable_delete ON gl_entries;
CREATE TRIGGER gl_entries_immutable_delete BEFORE DELETE ON gl_entries
FOR EACH ROW EXECUTE FUNCTION reject_gl_entry_mutation();

CREATE OR REPLACE FUNCTION assert_posting_batch_balance() RETURNS trigger AS $$
DECLARE
    line_count integer;
    imbalance numeric;
BEGIN
    IF NEW.status = 'Posted' AND OLD.status <> 'Posted' THEN
        SELECT COUNT(*), COALESCE(SUM(debit),0)-COALESCE(SUM(credit),0)
          INTO line_count, imbalance FROM gl_entries WHERE posting_batch_id=NEW.id;
        IF line_count < 2 THEN RAISE EXCEPTION 'posting batch needs at least two lines'; END IF;
        IF ROUND(imbalance,4) <> 0 THEN RAISE EXCEPTION 'posting batch is not balanced'; END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS posting_batch_balance_check ON posting_batches;
CREATE TRIGGER posting_batch_balance_check BEFORE UPDATE OF status ON posting_batches
FOR EACH ROW EXECUTE FUNCTION assert_posting_batch_balance();
"""


_POSTGRES_DOCUMENT_TRIGGERS = r"""
CREATE OR REPLACE FUNCTION protect_issued_invoice() RETURNS trigger AS $$
BEGIN
    IF TG_OP='DELETE' THEN RAISE EXCEPTION 'issued invoices cannot be deleted'; END IF;
    IF NEW.organisation_id IS DISTINCT FROM OLD.organisation_id OR NEW.contact_id IS DISTINCT FROM OLD.contact_id
       OR NEW.document_type IS DISTINCT FROM OLD.document_type OR NEW.number IS DISTINCT FROM OLD.number
       OR NEW.issue_date IS DISTINCT FROM OLD.issue_date OR NEW.tax_point_date IS DISTINCT FROM OLD.tax_point_date
       OR NEW.due_date IS DISTINCT FROM OLD.due_date OR NEW.currency IS DISTINCT FROM OLD.currency
       OR NEW.exchange_rate IS DISTINCT FROM OLD.exchange_rate OR NEW.subtotal IS DISTINCT FROM OLD.subtotal
       OR NEW.tax_total IS DISTINCT FROM OLD.tax_total OR NEW.total IS DISTINCT FROM OLD.total
    THEN RAISE EXCEPTION 'issued invoice accounting fields are immutable'; END IF;
    RETURN NEW;
END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS invoices_issued_core_immutable ON invoices;
CREATE TRIGGER invoices_issued_core_immutable BEFORE UPDATE ON invoices FOR EACH ROW
WHEN (OLD.status<>'Draft') EXECUTE FUNCTION protect_issued_invoice();
DROP TRIGGER IF EXISTS invoices_issued_delete ON invoices;
CREATE TRIGGER invoices_issued_delete BEFORE DELETE ON invoices FOR EACH ROW
WHEN (OLD.status<>'Draft') EXECUTE FUNCTION protect_issued_invoice();

CREATE OR REPLACE FUNCTION protect_invoice_line() RETURNS trigger AS $$
DECLARE parent_id text; parent_status text;
BEGIN
    parent_id := CASE WHEN TG_OP='DELETE' THEN OLD.invoice_id ELSE NEW.invoice_id END;
    SELECT status INTO parent_status FROM invoices WHERE id=parent_id;
    IF parent_status<>'Draft' THEN RAISE EXCEPTION 'issued invoice lines are immutable'; END IF;
    RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS invoice_lines_issued_update ON invoice_lines;
CREATE TRIGGER invoice_lines_issued_update BEFORE UPDATE ON invoice_lines FOR EACH ROW EXECUTE FUNCTION protect_invoice_line();
DROP TRIGGER IF EXISTS invoice_lines_issued_delete ON invoice_lines;
CREATE TRIGGER invoice_lines_issued_delete BEFORE DELETE ON invoice_lines FOR EACH ROW EXECUTE FUNCTION protect_invoice_line();

CREATE OR REPLACE FUNCTION protect_approved_bill() RETURNS trigger AS $$
BEGIN
    IF TG_OP='DELETE' THEN RAISE EXCEPTION 'approved bills cannot be deleted'; END IF;
    IF NEW.organisation_id IS DISTINCT FROM OLD.organisation_id OR NEW.contact_id IS DISTINCT FROM OLD.contact_id
       OR NEW.document_type IS DISTINCT FROM OLD.document_type OR NEW.supplier_number IS DISTINCT FROM OLD.supplier_number
       OR NEW.bill_date IS DISTINCT FROM OLD.bill_date OR NEW.due_date IS DISTINCT FROM OLD.due_date
       OR NEW.currency IS DISTINCT FROM OLD.currency OR NEW.exchange_rate IS DISTINCT FROM OLD.exchange_rate
       OR NEW.subtotal IS DISTINCT FROM OLD.subtotal OR NEW.tax_total IS DISTINCT FROM OLD.tax_total
       OR NEW.total IS DISTINCT FROM OLD.total
    THEN RAISE EXCEPTION 'approved bill accounting fields are immutable'; END IF;
    RETURN NEW;
END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS bills_approved_core_immutable ON bills;
CREATE TRIGGER bills_approved_core_immutable BEFORE UPDATE ON bills FOR EACH ROW
WHEN (OLD.status IN ('Approved','Part Paid','Paid')) EXECUTE FUNCTION protect_approved_bill();
DROP TRIGGER IF EXISTS bills_approved_delete ON bills;
CREATE TRIGGER bills_approved_delete BEFORE DELETE ON bills FOR EACH ROW
WHEN (OLD.status IN ('Approved','Part Paid','Paid')) EXECUTE FUNCTION protect_approved_bill();

CREATE OR REPLACE FUNCTION protect_bill_line() RETURNS trigger AS $$
DECLARE parent_id text; parent_status text;
BEGIN
    parent_id := CASE WHEN TG_OP='DELETE' THEN OLD.bill_id ELSE NEW.bill_id END;
    SELECT status INTO parent_status FROM bills WHERE id=parent_id;
    IF parent_status IN ('Approved','Part Paid','Paid') THEN RAISE EXCEPTION 'approved bill lines are immutable'; END IF;
    RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS bill_lines_approved_update ON bill_lines;
CREATE TRIGGER bill_lines_approved_update BEFORE UPDATE ON bill_lines FOR EACH ROW EXECUTE FUNCTION protect_bill_line();
DROP TRIGGER IF EXISTS bill_lines_approved_delete ON bill_lines;
CREATE TRIGGER bill_lines_approved_delete BEFORE DELETE ON bill_lines FOR EACH ROW EXECUTE FUNCTION protect_bill_line();
"""
