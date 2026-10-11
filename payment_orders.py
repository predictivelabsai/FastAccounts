"""Frozen payment instructions. Exporting instructions never posts a payment."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

from core_utils import audit, db_number, decimal, money, new_id, utc_now
from database import Database, get_database


PAIN_NS = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.03"


def _element(parent, name, value=None, **attributes):
    element = ET.SubElement(parent, f"{{{PAIN_NS}}}{name}", attributes)
    if value is not None:
        element.text = str(value)
    return element


class PaymentOrderService:
    def __init__(self, db: Database | None = None):
        self.db = db or get_database()

    @staticmethod
    def _organisation(tx, organisation_id):
        organisation = tx.one("SELECT * FROM organisations WHERE id=?", (organisation_id,))
        if not organisation:
            raise KeyError("Organisation not found")
        return organisation

    def _candidates(self, tx, organisation_id, due_before, *, for_update=False):
        self._organisation(tx, organisation_id)
        if due_before is not None:
            due_before = date.fromisoformat(due_before).isoformat()
        query = (
            "SELECT b.*,c.name contact_name,c.iban supplier_iban FROM bills b "
            "JOIN contacts c ON c.id=b.contact_id AND c.organisation_id=b.organisation_id "
            "WHERE b.organisation_id=? ORDER BY b.due_date,b.id")
        if for_update and self.db.dialect == "postgres":
            query += " FOR UPDATE OF b"
        rows = tx.rows(query, (organisation_id,))
        candidates, excluded, totals = [], [], {}
        for bill in rows:
            if due_before and bill["due_date"] > due_before:
                continue
            amount = money(decimal(bill["total"]) - decimal(bill["paid_total"]))
            reason = None
            if bill["document_type"] != "bill":
                reason = "Supplier credit"
            elif bill["status"] == "Paid":
                reason = "Paid"
            elif bill["status"] not in {"Approved", "Part Paid"}:
                reason = "Draft" if bill["status"] == "Draft" else "Not approved"
            elif amount <= 0:
                reason = "No outstanding balance"
            elif not (bill["supplier_iban"] or "").strip():
                reason = "No supplier IBAN"
            bill["outstanding"] = f"{amount:.2f}"
            if reason:
                bill["reason"] = reason
                excluded.append(bill)
            else:
                candidates.append(bill)
                currency = bill["currency"]
                totals[currency] = totals.get(currency, Decimal("0")) + amount
        return {"candidates": candidates, "excluded": excluded,
                "totals": {currency: f"{money(total):.2f}" for currency, total in totals.items()}}

    def candidates(self, organisation_id, *, due_before=None):
        with self.db.transaction() as tx:
            return self._candidates(tx, organisation_id, due_before)

    def create(self, organisation_id, bank_account_id, *, execution_date,
               due_before=None, bill_ids=None, actor):
        execution_date = date.fromisoformat(execution_date).isoformat()
        with self.db.transaction() as tx:
            organisation = self._organisation(tx, organisation_id)
            bank = tx.one("SELECT * FROM bank_accounts WHERE organisation_id=? AND id=?",
                          (organisation_id, bank_account_id))
            if not bank:
                raise KeyError("Bank account not found")
            if not bank["active"] or not (bank["iban"] or "").strip():
                raise ValueError("An active bank account with an IBAN is required")
            preview = self._candidates(tx, organisation_id, due_before, for_update=True)
            bills = preview["candidates"]
            if bill_ids is not None:
                requested = set(bill_ids)
                # Missing and other-tenant IDs have the same response.
                for bill_id in requested:
                    if not tx.one("SELECT id FROM bills WHERE organisation_id=? AND id=?",
                                  (organisation_id, bill_id)):
                        raise KeyError("Bill not found")
                bills = [bill for bill in bills if bill["id"] in requested]
                if {bill["id"] for bill in bills} != requested:
                    raise ValueError("Selected bills are no longer eligible for payment")
            if not bills:
                raise ValueError("Select at least one eligible bill")
            if any(bill["currency"] != bank["currency"] for bill in bills):
                raise ValueError("Bill currency must match the paying bank account")
            order_id, now = new_id().replace("-", ""), utc_now()
            total = money(sum((money(bill["outstanding"]) for bill in bills), Decimal("0")))
            tx.execute(
                "INSERT INTO payment_orders(id,organisation_id,bank_account_id,execution_date,"
                "bill_count,total,created_by,created_at,debtor_name,debtor_iban) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (order_id, organisation_id, bank_account_id, execution_date, len(bills),
                 db_number(total), actor, now, organisation["name"], bank["iban"]))
            for bill in bills:
                tx.execute(
                    "INSERT INTO payment_order_lines(id,organisation_id,payment_order_id,bill_id,amount,"
                    "currency,created_at,creditor_name,creditor_iban,reference) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (new_id(), organisation_id, order_id, bill["id"], bill["outstanding"],
                     bill["currency"], now, bill["contact_name"], bill["supplier_iban"],
                     bill["reference"] or bill["supplier_number"]))
            audit(tx, organisation_id, actor, "payment_order.created", "payment_order", order_id,
                  {"bill_ids": [bill["id"] for bill in bills], "total": f"{total:.2f}"})
            return self._get(tx, organisation_id, order_id)

    @staticmethod
    def _get(tx, organisation_id, order_id):
        order = tx.one("SELECT * FROM payment_orders WHERE organisation_id=? AND id=?",
                       (organisation_id, order_id))
        if not order:
            raise KeyError("Payment order not found")
        order["total"] = f"{money(order['total']):.2f}"
        order["lines"] = tx.rows(
            "SELECT * FROM payment_order_lines WHERE organisation_id=? AND payment_order_id=? ORDER BY currency,bill_id",
            (organisation_id, order_id))
        for line in order["lines"]:
            line["amount"] = f"{money(line['amount']):.2f}"
        return order

    def list(self, organisation_id):
        with self.db.transaction() as tx:
            self._organisation(tx, organisation_id)
            return [self._get(tx, organisation_id, row["id"]) for row in tx.rows(
                "SELECT id FROM payment_orders WHERE organisation_id=? ORDER BY created_at DESC,id DESC",
                (organisation_id,))]

    def xml(self, organisation_id, order_id) -> bytes:
        with self.db.transaction() as tx:
            order = self._get(tx, organisation_id, order_id)
        ET.register_namespace("", PAIN_NS)
        root = ET.Element(f"{{{PAIN_NS}}}Document")
        initiation = _element(root, "CstmrCdtTrfInitn")
        header = _element(initiation, "GrpHdr")
        _element(header, "MsgId", order["id"])
        _element(header, "CreDtTm", order["created_at"])
        _element(header, "NbOfTxs", order["bill_count"])
        _element(header, "CtrlSum", f"{money(order['total']):.2f}")
        _element(_element(header, "InitgPty"), "Nm", order["debtor_name"])
        groups = {}
        for line in order["lines"]:
            groups.setdefault(line["currency"], []).append(line)
        for currency, lines in groups.items():
            info = _element(initiation, "PmtInf")
            _element(info, "PmtInfId", f"{order['id']}{currency}")
            _element(info, "PmtMtd", "TRF")
            _element(info, "NbOfTxs", len(lines))
            total = sum((money(line["amount"]) for line in lines), Decimal("0"))
            _element(info, "CtrlSum", f"{money(total):.2f}")
            _element(info, "ReqdExctnDt", order["execution_date"])
            _element(_element(info, "Dbtr"), "Nm", order["debtor_name"])
            _element(_element(_element(info, "DbtrAcct"), "Id"), "IBAN", order["debtor_iban"])
            agent = _element(_element(info, "DbtrAgt"), "FinInstnId")
            _element(_element(agent, "Othr"), "Id", "NOTPROVIDED")
            for line in lines:
                transfer = _element(info, "CrdtTrfTxInf")
                # UUID hex is reversible and fits pain.001's Max35Text.
                _element(_element(transfer, "PmtId"), "EndToEndId", line["bill_id"].replace("-", ""))
                _element(_element(transfer, "Amt"), "InstdAmt", f"{money(line['amount']):.2f}", Ccy=currency)
                _element(_element(transfer, "Cdtr"), "Nm", line["creditor_name"])
                _element(_element(_element(transfer, "CdtrAcct"), "Id"), "IBAN", line["creditor_iban"])
                _element(_element(transfer, "RmtInf"), "Ustrd", line["reference"])
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)
