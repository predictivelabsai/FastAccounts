"""Tenant-scoped prepayment persistence and locks for accounting transactions."""
from contextlib import contextmanager

from core_utils import db_number


class PrepaymentRepository:
    def __init__(self, db):
        self.db = db

    @contextmanager
    def transaction(self, organisation_id):
        with self.db.transaction() as tx:
            if tx.dialect == "sqlite":
                tx.execute("BEGIN IMMEDIATE")
            # Serialise retries and balance changes for this organisation. This
            # also protects creation before a prepayment row exists to lock.
            suffix = " FOR UPDATE" if tx.dialect == "postgres" else ""
            if not tx.one("SELECT id FROM organisations WHERE id=?" + suffix, (organisation_id,)):
                raise KeyError("Organisation not found")
            yield tx

    @staticmethod
    def get(tx, organisation_id, prepayment_id):
        row = tx.one("SELECT p.*,c.name contact_name FROM prepayments p "
                     "JOIN contacts c ON c.id=p.contact_id AND c.organisation_id=p.organisation_id "
                     "WHERE p.organisation_id=? AND p.id=?", (organisation_id, prepayment_id))
        if not row:
            raise KeyError("Prepayment not found")
        return row

    @staticmethod
    def event(tx, table, organisation_id, key):
        assert table in {"prepayments", "prepayment_allocations", "prepayment_refunds"}
        return tx.one(f"SELECT * FROM {table} WHERE organisation_id=? AND idempotency_key=?",
                      (organisation_id, key))

    @staticmethod
    def contact(tx, organisation_id, contact_id):
        row = tx.one("SELECT * FROM contacts WHERE organisation_id=? AND id=?", (organisation_id, contact_id))
        if not row:
            raise KeyError("Contact not found")
        return row

    @staticmethod
    def bank(tx, organisation_id, bank_account_id):
        return tx.one("SELECT * FROM bank_accounts WHERE organisation_id=? AND id=?",
                      (organisation_id, bank_account_id))

    @staticmethod
    def base_currency(tx, organisation_id):
        row = tx.one("SELECT base_currency FROM organisations WHERE id=?", (organisation_id,))
        if not row:
            raise KeyError("Organisation not found")
        return row["base_currency"]

    @staticmethod
    def role_account(tx, organisation_id, role):
        row = tx.one("SELECT id FROM accounts WHERE organisation_id=? AND system_role=? AND active=1",
                     (organisation_id, role))
        if not row:
            raise ValueError("Prepayment control account is missing or inactive")
        return row["id"]

    @staticmethod
    def document(tx, organisation_id, contact_id, document_type, document_id):
        table = "invoices" if document_type == "invoice" else "bills"
        suffix = " FOR UPDATE" if tx.dialect == "postgres" else ""
        return tx.one(f"SELECT * FROM {table} WHERE organisation_id=? AND contact_id=? AND id=?" + suffix,
                      (organisation_id, contact_id, document_id))

    @staticmethod
    def insert(tx, table, row):
        assert table in {"prepayments", "prepayment_allocations", "prepayment_refunds"}
        columns = list(row)
        tx.execute(f"INSERT INTO {table}({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                   tuple(row[column] for column in columns))

    @staticmethod
    def set_balance(tx, organisation_id, prepayment_id, balance, now):
        tx.execute("UPDATE prepayments SET unallocated_balance=?,updated_at=? WHERE organisation_id=? AND id=?",
                   (db_number(balance), now, organisation_id, prepayment_id))

    @staticmethod
    def set_paid(tx, organisation_id, document_type, document_id, paid, status, now):
        table = "invoices" if document_type == "invoice" else "bills"
        tx.execute(f"UPDATE {table} SET paid_total=?,status=?,updated_at=? WHERE organisation_id=? AND id=?",
                   (db_number(paid), status, now, organisation_id, document_id))

    @staticmethod
    def history(tx, organisation_id, prepayment_id, table):
        assert table in {"prepayment_allocations", "prepayment_refunds"}
        return tx.rows(f"SELECT * FROM {table} WHERE organisation_id=? AND prepayment_id=? ORDER BY created_at,id",
                       (organisation_id, prepayment_id))

    @staticmethod
    def list(tx, organisation_id, *, side=None, contact_id=None, outstanding_only=False):
        conditions, params = ["p.organisation_id=?"], [organisation_id]
        if side:
            conditions.append("p.side=?")
            params.append(side)
        if contact_id:
            conditions.append("p.contact_id=?")
            params.append(contact_id)
        if outstanding_only:
            conditions.append("p.unallocated_balance>0")
        return tx.rows("SELECT p.*,c.name contact_name FROM prepayments p JOIN contacts c "
                       "ON c.id=p.contact_id AND c.organisation_id=p.organisation_id WHERE "
                       + " AND ".join(conditions) + " ORDER BY p.document_date DESC,p.created_at DESC,p.id", params)

    @staticmethod
    def original_entries(tx, organisation_id, batch_id):
        return tx.rows("SELECT * FROM gl_entries WHERE organisation_id=? AND posting_batch_id=? ORDER BY line_number",
                       (organisation_id, batch_id))
