"""Frozen payment instructions. Exporting instructions never posts a payment."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import re
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

    @staticmethod
    def _valid_iban(value):
        iban = re.sub(r'\s+', '', value or '').upper()
        if not re.fullmatch(r'[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}', iban):
            return False
        expanded = ''.join(str(ord(char) - 55) if char.isalpha() else char for char in iban[4:] + iban[:4])
        return int(expanded) % 97 == 1

    @staticmethod
    def _salary_remittance(period, language):
        year, month = map(int, period.split('-'))
        month_names = {
            'en': ('January','February','March','April','May','June','July','August','September','October','November','December'),
            'et': ('jaanuar','veebruar','märts','aprill','mai','juuni','juuli','august','september','oktoober','november','detsember'),
            'lv': ('janvāris','februāris','marts','aprīlis','maijs','jūnijs','jūlijs','augusts','septembris','oktobris','novembris','decembris'),
            'lt': ('sausis','vasaris','kovas','balandis','gegužė','birželis','liepa','rugpjūtis','rugsėjis','spalis','lapkritis','gruodis'),
        }
        name = month_names.get(language, month_names['en'])[month - 1]
        if language == 'en':
            return f'{name} {year} salary'
        if language == 'et':
            return f'{name} {year} töötasu'
        if language == 'lv':
            return f'{year}. gada {name} alga'
        return f'{year} m. {name} mėn. atlyginimas'

    def payroll_payout_xml(self, organisation_id, payout_id) -> bytes:
        """Create pain.001.001.03 directly from frozen payroll payout lines."""
        with self.db.transaction() as tx:
            batch = tx.one('SELECT * FROM payroll_payout_batches WHERE organisation_id=? AND id=?', (organisation_id, payout_id))
            if not batch:
                raise KeyError('Payroll payout not found')
            if batch['status'] not in {'Draft', 'Paid'}:
                raise ValueError('A cancelled payroll payout cannot be exported')
            org = self._organisation(tx, organisation_id)
            bank = tx.one('SELECT * FROM bank_accounts WHERE organisation_id=? AND id=? AND active=1',
                          (organisation_id, batch['bank_account_id'])) if batch['bank_account_id'] else None
            if not bank or not self._valid_iban(bank['iban']):
                raise ValueError('Choose an active debtor bank account with a valid IBAN')
            run = tx.one('SELECT period FROM pay_runs WHERE organisation_id=? AND id=?',
                         (organisation_id, batch['pay_run_id']))
            lines = tx.rows('SELECT l.*,e.name employee_name FROM payroll_payout_lines l '
                            'JOIN employees e ON e.organisation_id=l.organisation_id AND e.id=l.employee_id '
                            'WHERE l.organisation_id=? AND l.payout_batch_id=? ORDER BY l.employee_id,l.id',
                            (organisation_id, payout_id))
        invalid = [f"{line['account_owner'] or line['employee_name']} ({'missing' if not line['iban'] else 'invalid'} IBAN)"
                   for line in lines if not self._valid_iban(line['iban'])]
        if invalid:
            raise ValueError('Missing or invalid employee IBANs: ' + ', '.join(invalid))
        if not lines:
            raise ValueError('Payroll payout has no payment lines')
        total = sum((money(line['amount']) for line in lines), Decimal('0'))
        remittance = self._salary_remittance(run['period'], org.get('language') or 'en')
        ET.register_namespace('', PAIN_NS)
        root = ET.Element(f'{{{PAIN_NS}}}Document')
        initiation = _element(root, 'CstmrCdtTrfInitn')
        header = _element(initiation, 'GrpHdr')
        _element(header, 'MsgId', payout_id.replace('-', '')[:35])
        _element(header, 'CreDtTm', utc_now())
        _element(header, 'NbOfTxs', len(lines))
        _element(header, 'CtrlSum', f'{total:.2f}')
        _element(_element(header, 'InitgPty'), 'Nm', org['name'])
        info = _element(initiation, 'PmtInf')
        _element(info, 'PmtInfId', payout_id.replace('-', '')[:35])
        _element(info, 'PmtMtd', 'TRF')
        _element(info, 'NbOfTxs', len(lines))
        _element(info, 'CtrlSum', f'{total:.2f}')
        _element(info, 'ReqdExctnDt', batch['payout_date'])
        _element(_element(info, 'Dbtr'), 'Nm', org['name'])
        _element(_element(_element(info, 'DbtrAcct'), 'Id'), 'IBAN', re.sub(r'\s+', '', bank['iban']).upper())
        debtor_agent = _element(_element(info, 'DbtrAgt'), 'FinInstnId')
        if bank.get('bic'):
            _element(debtor_agent, 'BIC', bank['bic'])
        else:
            _element(_element(debtor_agent, 'Othr'), 'Id', 'NOTPROVIDED')
        for line in lines:
            transfer = _element(info, 'CdtTrfTxInf')
            _element(_element(transfer, 'PmtId'), 'EndToEndId', line['id'].replace('-', '')[:35])
            _element(_element(transfer, 'Amt'), 'InstdAmt', f"{money(line['amount']):.2f}", Ccy='EUR')
            _element(_element(transfer, 'Cdtr'), 'Nm', line['account_owner'] or line['employee_name'])
            _element(_element(_element(transfer, 'CdtrAcct'), 'Id'), 'IBAN', re.sub(r'\s+', '', line['iban']).upper())
            _element(_element(transfer, 'RmtInf'), 'Ustrd', remittance)
        return ET.tostring(root, encoding='utf-8', xml_declaration=True)
