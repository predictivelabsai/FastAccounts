"""Master-data maintenance: find and clean up loose counterparties.

Read-only analysis reports contacts that carry no documents or payments,
duplicate contacts that share a normalised name or an identifier, in-use
contacts missing both a VAT number and a registry number, and supplier
numbers reused across different suppliers (the database only guards
duplicates within one supplier). Write actions deactivate or, for contacts
with no references at all, delete master data under an organisation lock,
both audited. Items are catalogue only (no schema references them), so an
unused-item report is not determinable and items are deactivated or deleted
directly.
"""
from __future__ import annotations

import re

from core_utils import audit, new_id, utc_now
from database import get_database


def _normalised(value):
    return re.sub(r"\s+", " ", (value or "")).strip().casefold()


class MasterDataMaintenanceService:
    def __init__(self, db=None):
        self.db = db or get_database()

    # analysis -------------------------------------------------------------

    def analyse(self, organisation_id):
        with self.db.transaction() as tx:
            unused_contacts = [self._contact(row) for row in tx.rows(
                "SELECT * FROM contacts c WHERE c.organisation_id=? AND NOT EXISTS "
                "(SELECT 1 FROM invoices i WHERE i.contact_id=c.id AND i.organisation_id=c.organisation_id) "
                "AND NOT EXISTS (SELECT 1 FROM bills b WHERE b.contact_id=c.id AND b.organisation_id=c.organisation_id) "
                "AND NOT EXISTS (SELECT 1 FROM quotes q WHERE q.contact_id=c.id AND q.organisation_id=c.organisation_id) "
                "AND NOT EXISTS (SELECT 1 FROM prepayments p WHERE p.contact_id=c.id AND p.organisation_id=c.organisation_id) "
                "AND NOT EXISTS (SELECT 1 FROM gl_entries g WHERE g.contact_id=c.id AND g.organisation_id=c.organisation_id) "
                "ORDER BY c.name", (organisation_id,))]
            duplicates = self._duplicates(organisation_id)
            missing_identifiers = [self._contact(row) for row in tx.rows(
                "SELECT * FROM contacts c WHERE c.organisation_id=? AND c.active=1 AND "
                "(c.vat_no IS NULL OR c.vat_no='') AND (c.registration_no IS NULL OR c.registration_no='') AND "
                "(EXISTS (SELECT 1 FROM invoices i WHERE i.contact_id=c.id) OR "
                "EXISTS (SELECT 1 FROM bills b WHERE b.contact_id=c.id)) ORDER BY c.name",
                (organisation_id,))]
            numbers = []
            for row in tx.rows(
                    "SELECT b.supplier_number, COUNT(DISTINCT b.contact_id) suppliers "
                    "FROM bills b WHERE b.organisation_id=? AND b.status!='Voided' "
                    "GROUP BY b.supplier_number HAVING COUNT(DISTINCT b.contact_id)>1 "
                    "ORDER BY b.supplier_number", (organisation_id,)):
                numbers.append({
                    "supplier_number": row["supplier_number"],
                    "suppliers": int(row["suppliers"]),
                })
        return {"unused_contacts": unused_contacts, "duplicate_contacts": duplicates,
                "contacts_missing_identifiers": missing_identifiers,
                "reused_supplier_numbers": numbers}

    def _duplicates(self, organisation_id):
        seen, duplicates = {}, []
        for row in self.db.rows(
                "SELECT * FROM contacts WHERE organisation_id=? ORDER BY name",
                (organisation_id,)):
            for key in ("name:" + _normalised(row["name"]),
                        "vat:" + (row["vat_no"] or "").strip().upper(),
                        "reg:" + (row["registration_no"] or "").strip()):
                if not key.partition(":")[2]:
                    continue
                prior = seen.get(key)
                if prior and prior["id"] != row["id"]:
                    duplicates.append(prior)
                    duplicates.append(row)
                    break
                if not prior:
                    seen[key] = row
        return [self._contact(row) for row in {row["id"]: row for row in duplicates}.values()]

    @staticmethod
    def _contact(row):
        return {"id": row["id"], "name": row["name"], "contact_type": row["contact_type"],
                "vat_no": row["vat_no"], "registration_no": row["registration_no"],
                "active": int(row.get("active", 1) or 0),
                "created_at": row["created_at"]}

    # writes ---------------------------------------------------------------

    def deactivate_contact(self, organisation_id, contact_id, *, actor):
        self._contact_write(organisation_id, contact_id, "UPDATE contacts SET active=0 WHERE id=?",
                            (contact_id,), 'contact.deactivated', actor)

    def reactivate_contact(self, organisation_id, contact_id, *, actor):
        self._contact_write(organisation_id, contact_id, "UPDATE contacts SET active=1 WHERE id=?",
                            (contact_id,), 'contact.reactivated', actor)

    def _contact_write(self, organisation_id, contact_id, statement, params, action, actor):
        with self.db.transaction() as tx:
            locked = tx.execute("UPDATE organisations SET name=name WHERE id=?", (organisation_id,))
            if not locked.rowcount:
                raise KeyError("Organisation not found")
            row = tx.one("SELECT * FROM contacts WHERE id=? AND organisation_id=?",
                         (contact_id, organisation_id))
            if not row:
                raise KeyError("Contact not found")
            tx.execute(statement, params)
            audit(tx, organisation_id, actor, action, "contact", contact_id,
                  {"name": row["name"]})

    def delete_contact(self, organisation_id, contact_id, *, actor):
        with self.db.transaction() as tx:
            locked = tx.execute("UPDATE organisations SET name=name WHERE id=?", (organisation_id,))
            if not locked.rowcount:
                raise KeyError("Organisation not found")
            row = tx.one("SELECT * FROM contacts WHERE id=? AND organisation_id=?",
                         (contact_id, organisation_id))
            if not row:
                raise KeyError("Contact not found")
            referenced = self._contact_reference_count(tx, organisation_id, contact_id)
            if referenced:
                raise ValueError("Only contacts without documents or payments can be deleted")
            tx.execute("DELETE FROM contacts WHERE id=?", (contact_id,))
            audit(tx, organisation_id, actor, "contact.deleted", "contact", contact_id,
                  {"name": row["name"]})

    @staticmethod
    def _contact_reference_count(tx, organisation_id, contact_id):
        return int(tx.scalar(
            "SELECT (EXISTS (SELECT 1 FROM invoices WHERE contact_id=? AND organisation_id=?)) + "
            "(EXISTS (SELECT 1 FROM bills WHERE contact_id=? AND organisation_id=?)) + "
            "(EXISTS (SELECT 1 FROM quotes WHERE contact_id=? AND organisation_id=?)) + "
            "(EXISTS (SELECT 1 FROM prepayments WHERE contact_id=? AND organisation_id=?)) + "
            "(EXISTS (SELECT 1 FROM gl_entries WHERE contact_id=? AND organisation_id=?))",
            (contact_id, organisation_id, contact_id, organisation_id,
             contact_id, organisation_id, contact_id, organisation_id,
             contact_id, organisation_id)))

    def deactivate_item(self, organisation_id, item_id, *, actor):
        with self.db.transaction() as tx:
            locked = tx.execute("UPDATE organisations SET name=name WHERE id=?", (organisation_id,))
            if not locked.rowcount:
                raise KeyError("Organisation not found")
            row = tx.one("SELECT * FROM items WHERE id=? AND organisation_id=?",
                         (item_id, organisation_id))
            if not row:
                raise KeyError("Item not found")
            tx.execute("UPDATE items SET active=0 WHERE id=?", (item_id,))
            audit(tx, organisation_id, actor, "item.deactivated", "item", item_id,
                  {"code": row["code"]})

    def delete_item(self, organisation_id, item_id, *, actor):
        with self.db.transaction() as tx:
            locked = tx.execute("UPDATE organisations SET name=name WHERE id=?", (organisation_id,))
            if not locked.rowcount:
                raise KeyError("Organisation not found")
            row = tx.one("SELECT * FROM items WHERE id=? AND organisation_id=?",
                         (item_id, organisation_id))
            if not row:
                raise KeyError("Item not found")
            tx.execute("DELETE FROM items WHERE id=?", (item_id,))
            audit(tx, organisation_id, actor, "item.deleted", "item", item_id,
                  {"code": row["code"]})