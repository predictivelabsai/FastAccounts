"""Customer and supplier prepayments, invoice offsets and unallocated refunds."""
from datetime import date
from decimal import Decimal, InvalidOperation

from core_utils import audit, db_number, decimal, money, new_id, utc_now
from database import Database, get_database
from ledger import LedgerService, PostingLine
from prepayment_repository import PrepaymentRepository


class PrepaymentService:
    def __init__(self, db: Database | None = None):
        self.db = db or get_database()
        self.repo = PrepaymentRepository(self.db)
        self.ledger = LedgerService(self.db)

    @staticmethod
    def _side(side):
        if side not in {"customer", "supplier"}:
            raise ValueError("Prepayment side must be customer or supplier")

    @staticmethod
    def _value(amount):
        try:
            raw = decimal(amount)
            if not raw.is_finite():
                raise ValueError("Prepayment amount must be positive and finite")
            value = money(raw)
        except (InvalidOperation, TypeError):
            raise ValueError("Prepayment amount must be positive and finite") from None
        if value <= 0:
            raise ValueError("Prepayment amount must be positive and finite")
        return value

    @staticmethod
    def _date(value):
        try:
            return date.fromisoformat(value).isoformat()
        except (TypeError, ValueError):
            raise ValueError("Prepayment dates must be ISO dates") from None

    @staticmethod
    def _key(key):
        if not isinstance(key, str) or not key.strip() or len(key) > 160:
            raise ValueError("A prepayment idempotency key is required")
        return key.strip()

    @staticmethod
    def _replay(existing, expected):
        for key, value in expected.items():
            stored = money(existing[key]) if isinstance(value, Decimal) else existing[key]
            if stored != value:
                raise ValueError("Prepayment idempotency key was already used for different details")

    @staticmethod
    def _amounts(row):
        for key in ("amount", "unallocated_balance"):
            if key in row:
                row[key] = money(row[key])
        return row

    def _get(self, tx, organisation_id, prepayment_id):
        row = self._amounts(self.repo.get(tx, organisation_id, prepayment_id))
        row["allocations"] = [self._amounts(r) for r in self.repo.history(
            tx, organisation_id, prepayment_id, "prepayment_allocations")]
        row["refunds"] = [self._amounts(r) for r in self.repo.history(
            tx, organisation_id, prepayment_id, "prepayment_refunds")]
        return row

    def get(self, organisation_id, prepayment_id):
        with self.db.transaction() as tx:
            return self._get(tx, organisation_id, prepayment_id)

    def list(self, organisation_id, *, side=None, contact_id=None, outstanding_only=False):
        if side is not None:
            self._side(side)
        with self.db.transaction() as tx:
            if contact_id is not None:
                self.repo.contact(tx, organisation_id, contact_id)
            return [self._amounts(r) for r in self.repo.list(tx, organisation_id, side=side,
                contact_id=contact_id, outstanding_only=outstanding_only)]

    def outstanding(self, organisation_id, contact_id):
        rows = self.list(organisation_id, contact_id=contact_id, outstanding_only=True)
        totals = {side: sum((r["unallocated_balance"] for r in rows if r["side"] == side), Decimal("0.00"))
                  for side in ("customer", "supplier")}
        return {"contact_id": contact_id, "items": rows, "totals": totals}

    def create(self, organisation_id, *, side, contact_id, bank_account_id, document_date,
               amount, idempotency_key, actor, reference="", currency=None):
        self._side(side)
        value, day, key = self._value(amount), self._date(document_date), self._key(idempotency_key)
        reference = reference.strip()
        with self.repo.transaction(organisation_id) as tx:
            expected = dict(side=side, contact_id=contact_id, bank_account_id=bank_account_id,
                            document_date=day, amount=value, reference=reference)
            existing = self.repo.event(tx, "prepayments", organisation_id, key)
            if existing:
                self._replay(existing, expected)
                if currency is not None:
                    self._replay(existing, {"currency": currency.upper()})
                return self._get(tx, organisation_id, existing["id"])
            contact = self.repo.contact(tx, organisation_id, contact_id)
            if contact["contact_type"] not in {side, "both"}:
                raise ValueError("Contact type does not match prepayment side")
            bank = self.repo.bank(tx, organisation_id, bank_account_id)
            base_currency = self.repo.base_currency(tx, organisation_id)
            if not bank:
                raise ValueError("Prepayment bank account is not in this organisation")
            currency = (currency or bank["currency"]).upper()
            if currency != bank["currency"] or currency != base_currency:
                raise ValueError("Prepayments require the organisation base currency")
            control = self.repo.role_account(tx, organisation_id,
                "CUSTOMER_PREPAYMENTS" if side == "customer" else "SUPPLIER_PREPAYMENTS")
            prepayment_id, now = new_id(), utc_now()
            debit, credit = (bank["ledger_account_id"], control) if side == "customer" else (control, bank["ledger_account_id"])
            lines = [PostingLine(debit, debit=value, contact_id=contact_id, memo=reference,
                                 source_line_type="prepayment", source_line_id=prepayment_id),
                     PostingLine(credit, credit=value, contact_id=contact_id, memo=reference,
                                 source_line_type="prepayment", source_line_id=prepayment_id)]
            batch = self.ledger.post(organisation_id=organisation_id, voucher_type="prepayment",
                voucher_id=prepayment_id, voucher_code=reference or f"PRE-{prepayment_id[:8]}",
                posting_date=day, lines=lines, actor=actor, currency=currency, tx=tx)
            self.repo.insert(tx, "prepayments", dict(id=prepayment_id, organisation_id=organisation_id,
                **{**expected, "amount": db_number(value)}, currency=currency,
                unallocated_balance=db_number(value), idempotency_key=key, posting_batch_id=batch["id"],
                created_by=actor, created_at=now, updated_at=now))
            audit(tx, organisation_id, actor, "prepayment.created", "prepayment", prepayment_id,
                  {"side": side, "amount": str(value), "posting_batch_id": batch["id"]})
            return self._get(tx, organisation_id, prepayment_id)

    def allocate(self, organisation_id, prepayment_id, *, document_type, document_id,
                 allocation_date, amount, idempotency_key, actor):
        if document_type not in {"invoice", "bill"}:
            raise ValueError("Prepayment allocation document type is invalid")
        value, day, key = self._value(amount), self._date(allocation_date), self._key(idempotency_key)
        with self.repo.transaction(organisation_id) as tx:
            prepayment = self.repo.get(tx, organisation_id, prepayment_id)
            expected = dict(prepayment_id=prepayment_id, document_type=document_type,
                            document_id=document_id, allocation_date=day, amount=value)
            existing = self.repo.event(tx, "prepayment_allocations", organisation_id, key)
            if existing:
                self._replay(existing, expected)
                return self._amounts(existing)
            customer = prepayment["side"] == "customer"
            if document_type != ("invoice" if customer else "bill"):
                raise ValueError("Prepayment allocation document type does not match side")
            document = self.repo.document(tx, organisation_id, prepayment["contact_id"], document_type, document_id)
            open_statuses = {"Issued", "Part Paid"} if customer else {"Approved", "Part Paid"}
            if (not document or document["document_type"] != document_type
                    or document["status"] not in open_statuses):
                raise ValueError("Prepayment allocation requires an open document for the same contact")
            if document["currency"] != prepayment["currency"] or decimal(document["exchange_rate"]) != 1:
                raise ValueError("Prepayments require the organisation base currency")
            document_day = document["issue_date"] if customer else document["bill_date"]
            if day < max(prepayment["document_date"], document_day):
                raise ValueError("Allocation date cannot precede the prepayment or document")
            if value > money(prepayment["unallocated_balance"]):
                raise ValueError("Amount exceeds the unallocated prepayment balance")
            paid = money(document["paid_total"])
            if value > money(document["total"]) - paid:
                raise ValueError("Allocation exceeds the open document balance")
            control = self.repo.role_account(tx, organisation_id,
                "CUSTOMER_PREPAYMENTS" if customer else "SUPPLIER_PREPAYMENTS")
            trade = self.repo.role_account(tx, organisation_id, "AR" if customer else "AP")
            debit, credit = (control, trade) if customer else (trade, control)
            allocation_id, now = new_id(), utc_now()
            memo = document.get("number") or document.get("supplier_number") or document_id
            batch = self.ledger.post(organisation_id=organisation_id, voucher_type="prepayment_allocation",
                voucher_id=allocation_id, voucher_code=f"PRE-ALLOC-{allocation_id[:8]}", posting_date=day,
                lines=[PostingLine(debit, debit=value, contact_id=prepayment["contact_id"], memo=memo,
                                   source_line_type=document_type, source_line_id=document_id),
                       PostingLine(credit, credit=value, contact_id=prepayment["contact_id"], memo=memo,
                                   source_line_type=document_type, source_line_id=document_id)],
                actor=actor, currency=prepayment["currency"], tx=tx)
            row = dict(id=allocation_id, organisation_id=organisation_id,
                       **{**expected, "amount": db_number(value)}, idempotency_key=key,
                       posting_batch_id=batch["id"], created_by=actor, created_at=now)
            self.repo.insert(tx, "prepayment_allocations", row)
            self.repo.set_balance(tx, organisation_id, prepayment_id, money(prepayment["unallocated_balance"])-value, now)
            paid += value
            self.repo.set_paid(tx, organisation_id, document_type, document_id, paid,
                               "Paid" if paid == money(document["total"]) else "Part Paid", now)
            audit(tx, organisation_id, actor, "prepayment.allocated", "prepayment", prepayment_id,
                  {"allocation_id": allocation_id, "document_id": document_id, "amount": str(value)})
            return self._amounts(row)

    def refund(self, organisation_id, prepayment_id, *, refund_date, amount, idempotency_key,
               actor, reference=""):
        value, day, key = self._value(amount), self._date(refund_date), self._key(idempotency_key)
        reference = reference.strip()
        with self.repo.transaction(organisation_id) as tx:
            prepayment = self.repo.get(tx, organisation_id, prepayment_id)
            expected = dict(prepayment_id=prepayment_id, refund_date=day, amount=value, reference=reference)
            existing = self.repo.event(tx, "prepayment_refunds", organisation_id, key)
            if existing:
                self._replay(existing, expected)
                return self._amounts(existing)
            if day < prepayment["document_date"]:
                raise ValueError("Refund date cannot precede the prepayment")
            if value > money(prepayment["unallocated_balance"]):
                raise ValueError("Amount exceeds the unallocated prepayment balance")
            refund_id, now = new_id(), utc_now()
            # An explicit compensating event, linked to both the original batch
            # and its legs. Partial refunds do not mark the whole batch reversed.
            entries = self.repo.original_entries(tx, organisation_id, prepayment["posting_batch_id"])
            lines = [PostingLine(row["account_id"], debit=value if money(row["credit"]) else Decimal("0"),
                credit=value if money(row["debit"]) else Decimal("0"), contact_id=prepayment["contact_id"],
                memo=reference, source_line_type="prepayment_refund", source_line_id=refund_id,
                reverses_entry_id=row["id"]) for row in entries]
            batch = self.ledger.post(organisation_id=organisation_id, voucher_type="prepayment_refund",
                voucher_id=refund_id, voucher_code=reference or f"PRE-REF-{refund_id[:8]}", posting_date=day,
                lines=lines, actor=actor, currency=prepayment["currency"],
                reverses_batch_id=prepayment["posting_batch_id"], tx=tx)
            row = dict(id=refund_id, organisation_id=organisation_id,
                       **{**expected, "amount": db_number(value)}, idempotency_key=key,
                       posting_batch_id=batch["id"], created_by=actor, created_at=now)
            self.repo.insert(tx, "prepayment_refunds", row)
            self.repo.set_balance(tx, organisation_id, prepayment_id, money(prepayment["unallocated_balance"])-value, now)
            audit(tx, organisation_id, actor, "prepayment.refunded", "prepayment", prepayment_id,
                  {"refund_id": refund_id, "amount": str(value), "posting_batch_id": batch["id"]})
            return self._amounts(row)
