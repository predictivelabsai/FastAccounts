"""Idempotent bank imports and review-first reconciliation."""
from __future__ import annotations

import csv
import io
import json
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree

from core_utils import audit, canonical_json, db_number, decimal, money, new_id, sha256_bytes, utc_now
from database import Database, get_database
from documents import DocumentService


def _fingerprint(bank_account_id: str, external_id: str, booking_date: str,
                 amount: Decimal, currency: str, reference: str) -> str:
    raw = "|".join((bank_account_id, external_id, booking_date, format(amount, "f"), currency, reference.strip()))
    return sha256_bytes(raw.encode())


class BankingService:
    def __init__(self, db: Database | None = None):
        self.db = db or get_database()
        self.documents = DocumentService(self.db)

    def import_csv(self, organisation_id: str, bank_account_id: str, content: bytes,
                   *, actor: str) -> dict:
        text = content.decode("utf-8-sig")
        rows = []
        for source in csv.DictReader(io.StringIO(text)):
            normal = {str(k).strip().lower(): (v or "").strip() for k, v in source.items()}
            rows.append({
                "external_id": normal.get("id") or normal.get("transaction_id") or "",
                "booking_date": normal.get("date") or normal.get("booking_date"),
                "value_date": normal.get("value_date") or None,
                "amount": normal.get("amount"),
                "currency": normal.get("currency"),
                "counterparty": normal.get("counterparty") or normal.get("name") or "",
                "reference": normal.get("reference") or normal.get("description") or "",
                "raw": normal,
            })
        return self._import(organisation_id, bank_account_id, content, "csv", rows, actor)

    def import_camt053(self, organisation_id: str, bank_account_id: str, content: bytes,
                       *, actor: str) -> dict:
        root = ElementTree.fromstring(content)
        rows = []
        for entry in root.findall(".//{*}Ntry"):
            amount_node = entry.find("./{*}Amt")
            indicator = entry.findtext("./{*}CdtDbtInd", "CRDT")
            amount = decimal(amount_node.text if amount_node is not None else 0)
            if indicator == "DBIT":
                amount = -amount
            rows.append({
                "external_id": entry.findtext(".//{*}AcctSvcrRef", ""),
                "booking_date": entry.findtext("./{*}BookgDt/{*}Dt", ""),
                "value_date": entry.findtext("./{*}ValDt/{*}Dt", "") or None,
                "amount": str(amount),
                "currency": amount_node.attrib.get("Ccy", "") if amount_node is not None else "",
                "counterparty": entry.findtext(".//{*}RltdPties/{*}Dbtr/{*}Nm", "") or entry.findtext(".//{*}RltdPties/{*}Cdtr/{*}Nm", ""),
                "reference": entry.findtext(".//{*}RmtInf/{*}Ustrd", ""),
                "raw": {"xml_tag": entry.tag},
            })
        return self._import(organisation_id, bank_account_id, content, "camt053", rows, actor)

    def _import(self, organisation_id: str, bank_account_id: str, content: bytes,
                file_format: str, rows: list[dict], actor: str) -> dict:
        source_hash, import_id, now = sha256_bytes(content), new_id(), utc_now()
        with self.db.transaction() as tx:
            bank = tx.one("SELECT * FROM bank_accounts WHERE id=? AND organisation_id=?", (bank_account_id, organisation_id))
            if not bank:
                raise ValueError("Bank account is not in this organisation")
            previous = tx.one(
                "SELECT id FROM bank_imports WHERE organisation_id=? AND bank_account_id=? AND source_hash=?",
                (organisation_id, bank_account_id, source_hash),
            )
            if previous:
                return {"id": previous["id"], "duplicate": True, "imported": 0, "skipped": len(rows)}
            tx.execute(
                "INSERT INTO bank_imports(id,organisation_id,bank_account_id,format,source_hash,imported_by,imported_at) VALUES (?,?,?,?,?,?,?)",
                (import_id, organisation_id, bank_account_id, file_format, source_hash, actor, now),
            )
            imported = skipped = 0
            for row in rows:
                if not row.get("booking_date") or not row.get("amount") or not row.get("currency"):
                    raise ValueError("Each bank row needs date, amount, and currency")
                value = money(row["amount"])
                if value == 0:
                    raise ValueError("Zero-value bank transactions are not supported")
                fingerprint = _fingerprint(bank_account_id, row.get("external_id", ""), row["booking_date"], value,
                                           row["currency"].upper(), row.get("reference", ""))
                try:
                    tx.execute(
                        "INSERT INTO bank_transactions(id,organisation_id,bank_account_id,import_id,external_id,fingerprint,booking_date,value_date,amount,currency,counterparty,reference,raw_payload) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (new_id(), organisation_id, bank_account_id, import_id, row.get("external_id") or None,
                         fingerprint, row["booking_date"], row.get("value_date"), db_number(value),
                         row["currency"].upper(), row.get("counterparty") or None,
                         row.get("reference") or None, canonical_json(row.get("raw") or {})),
                    )
                    imported += 1
                except Exception as error:
                    if "unique" not in str(error).lower() and "duplicate" not in str(error).lower():
                        raise
                    skipped += 1
            audit(tx, organisation_id, actor, "bank.imported", "bank_import", import_id,
                  {"format": file_format, "imported": imported, "skipped": skipped})
            return {"id": import_id, "duplicate": False, "imported": imported, "skipped": skipped}

    def suggest(self, bank_transaction_id: str) -> list[dict]:
        transaction = self.db.one("SELECT * FROM bank_transactions WHERE id=?", (bank_transaction_id,))
        if not transaction:
            raise KeyError("Bank transaction not found")
        value = money(transaction["amount"])
        table = "invoices" if value > 0 else "bills"
        date_field = "issue_date" if value > 0 else "bill_date"
        number_field = "number" if value > 0 else "supplier_number"
        target_type = "invoice" if value > 0 else "bill"
        candidates = self.db.rows(
            f"SELECT id,{number_field} document_number,total-paid_total open_amount,{date_field} document_date,contact_id "
            f"FROM {table} WHERE organisation_id=? AND status IN ('Issued','Approved','Part Paid')",
            (transaction["organisation_id"],),
        )
        suggestions = []
        for row in candidates:
            open_amount = money(row["open_amount"])
            difference = abs(open_amount - abs(value))
            if difference > Decimal("1.00"):
                continue
            reasons, confidence = [], Decimal("0.50")
            if difference == 0:
                reasons.append("exact amount")
                confidence += Decimal("0.35")
            reference = (transaction.get("reference") or "").lower()
            if row["document_number"] and str(row["document_number"]).lower() in reference:
                reasons.append("document number in reference")
                confidence += Decimal("0.14")
            days = abs((date.fromisoformat(transaction["booking_date"]) - date.fromisoformat(row["document_date"])).days)
            if days <= 45:
                reasons.append("date proximity")
                confidence += Decimal("0.05")
            suggestions.append({
                "target_type": target_type, "target_id": row["id"],
                "document_number": row["document_number"], "amount": min(open_amount, abs(value)),
                "confidence": min(confidence, Decimal("0.99")), "reasons": reasons,
                "contact_id": row["contact_id"],
            })
        suggestions.sort(key=lambda item: item["confidence"], reverse=True)
        with self.db.transaction() as tx:
            for suggestion in suggestions[:5]:
                existing = tx.one(
                    "SELECT id FROM reconciliation_matches WHERE bank_transaction_id=? AND target_type=? AND target_id=?",
                    (bank_transaction_id, suggestion["target_type"], suggestion["target_id"]),
                )
                if not existing:
                    tx.execute(
                        "INSERT INTO reconciliation_matches(id,organisation_id,bank_transaction_id,target_type,target_id,amount,confidence,reasons,status) "
                        "VALUES (?,?,?,?,?,?,?,?,?)",
                        (new_id(), transaction["organisation_id"], bank_transaction_id,
                         suggestion["target_type"], suggestion["target_id"], db_number(suggestion["amount"]),
                         db_number(suggestion["confidence"]), canonical_json(suggestion["reasons"]), "Suggested"),
                    )
            if suggestions:
                tx.execute("UPDATE bank_transactions SET status='Suggested' WHERE id=?", (bank_transaction_id,))
        return suggestions[:5]

    def reconcile_to_document(self, bank_transaction_id: str, *, target_type: str,
                              target_id: str, actor: str) -> dict:
        transaction = self.db.one("SELECT * FROM bank_transactions WHERE id=?", (bank_transaction_id,))
        if not transaction or transaction["status"] == "Reconciled":
            raise ValueError("Bank transaction is missing or already reconciled")
        if target_type not in {"invoice", "bill"}:
            raise ValueError("Only invoice and bill reconciliation is currently supported")
        table = "invoices" if target_type == "invoice" else "bills"
        document = self.db.one(
            f"SELECT * FROM {table} WHERE id=? AND organisation_id=?",
            (target_id, transaction["organisation_id"]),
        )
        if not document:
            raise ValueError("Document is not in this organisation")
        amount = min(abs(money(transaction["amount"])), money(document["total"]) - money(document["paid_total"]))
        payment_type = "customer_receipt" if target_type == "invoice" else "supplier_payment"
        payment = self.documents.record_payment(
            transaction["organisation_id"], payment_type=payment_type,
            bank_account_id=transaction["bank_account_id"], payment_date=transaction["booking_date"],
            amount=amount, actor=actor, contact_id=document["contact_id"],
            reference=transaction.get("reference") or transaction.get("external_id") or "Bank reconciliation",
            allocations=[{"document_type": target_type, "document_id": target_id, "amount": amount}],
        )
        with self.db.transaction() as tx:
            match = tx.one(
                "SELECT id FROM reconciliation_matches WHERE bank_transaction_id=? AND target_type=? AND target_id=?",
                (bank_transaction_id, target_type, target_id),
            )
            match_id = match["id"] if match else new_id()
            if match:
                tx.execute(
                    "UPDATE reconciliation_matches SET status='Confirmed',confirmed_by=?,confirmed_at=?,amount=? WHERE id=?",
                    (actor, utc_now(), db_number(amount), match_id),
                )
            else:
                tx.execute(
                    "INSERT INTO reconciliation_matches(id,organisation_id,bank_transaction_id,target_type,target_id,amount,reasons,status,confirmed_by,confirmed_at) "
                    "VALUES (?,?,?,?,?,?,?,'Confirmed',?,?)",
                    (match_id, transaction["organisation_id"], bank_transaction_id, target_type,
                     target_id, db_number(amount), '["manual confirmation"]', actor, utc_now()),
                )
            tx.execute("UPDATE bank_transactions SET status='Reconciled' WHERE id=?", (bank_transaction_id,))
            audit(tx, transaction["organisation_id"], actor, "bank.reconciled", "bank_transaction", bank_transaction_id,
                  {"target_type": target_type, "target_id": target_id, "payment_id": payment["id"]})
        return {"match_id": match_id, "payment_id": payment["id"], "amount": amount}

    def reconcile_split(self, bank_transaction_id: str, *, allocations: list[dict], actor: str) -> dict:
        """Confirm one statement line against multiple documents for one counterparty."""
        transaction = self.db.one("SELECT * FROM bank_transactions WHERE id=?", (bank_transaction_id,))
        if not transaction or transaction["status"] == "Reconciled" or not allocations:
            raise ValueError("An unreconciled bank transaction and allocations are required")
        expected_type = "invoice" if money(transaction["amount"]) > 0 else "bill"
        table = "invoices" if expected_type == "invoice" else "bills"
        documents, contact_ids, total = [], set(), Decimal("0")
        for item in allocations:
            if item.get("target_type", expected_type) != expected_type:
                raise ValueError("Split allocation direction does not match the bank transaction")
            document = self.db.one(
                f"SELECT * FROM {table} WHERE id=? AND organisation_id=?",
                (item["target_id"], transaction["organisation_id"]),
            )
            amount = money(item["amount"])
            if not document or amount <= 0 or amount > money(document["total"]) - money(document["paid_total"]):
                raise ValueError("Split allocation exceeds an open document balance")
            documents.append((document, amount)); contact_ids.add(document["contact_id"]); total += amount
        if len(contact_ids) != 1:
            raise ValueError("One bank payment can only be split across documents for the same contact")
        if money(total) != abs(money(transaction["amount"])):
            raise ValueError("Split allocations must account for the complete bank transaction")
        payment = self.documents.record_payment(
            transaction["organisation_id"],
            payment_type="customer_receipt" if expected_type == "invoice" else "supplier_payment",
            bank_account_id=transaction["bank_account_id"], payment_date=transaction["booking_date"],
            amount=total, actor=actor, contact_id=next(iter(contact_ids)),
            reference=transaction.get("reference") or "Split bank reconciliation",
            allocations=[{"document_type": expected_type, "document_id": doc["id"], "amount": amount}
                         for doc, amount in documents],
        )
        match_ids = []
        with self.db.transaction() as tx:
            for document, amount in documents:
                match_id = new_id(); match_ids.append(match_id)
                tx.execute(
                    "INSERT INTO reconciliation_matches(id,organisation_id,bank_transaction_id,target_type,target_id,amount,reasons,status,confirmed_by,confirmed_at) "
                    "VALUES (?,?,?,?,?,?,?,'Confirmed',?,?)",
                    (match_id, transaction["organisation_id"], bank_transaction_id, expected_type,
                     document["id"], db_number(amount), '["confirmed split"]', actor, utc_now()),
                )
            tx.execute("UPDATE bank_transactions SET status='Reconciled' WHERE id=?", (bank_transaction_id,))
            audit(tx, transaction["organisation_id"], actor, "bank.split_reconciled", "bank_transaction", bank_transaction_id,
                  {"payment_id": payment["id"], "match_ids": match_ids})
        return {"payment_id": payment["id"], "match_ids": match_ids, "amount": money(total)}
