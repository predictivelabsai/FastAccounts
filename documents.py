"""Contacts, sales invoices, bills, payments, evidence, PDFs, and e-invoices."""
from __future__ import annotations

import os
import base64
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring

from core_utils import audit, db_number, decimal, money, new_id, sha256_bytes, utc_now
from database import Database, get_database
from ledger import LedgerService, PostingLine


class DocumentService:
    def __init__(self, db: Database | None = None):
        self.db = db or get_database()
        self.ledger = LedgerService(self.db)

    def create_contact(self, organisation_id: str, *, name: str, country_code: str,
                       contact_type: str = "both", email: str = "", vat_no: str = "",
                       registration_no: str = "", address: str = "",
                       payment_terms_days: int = 14) -> dict:
        if contact_type not in {"customer", "supplier", "both"} or not name.strip():
            raise ValueError("Valid contact name and type are required")
        contact_id, now = new_id(), utc_now()
        with self.db.transaction() as tx:
            if not tx.one("SELECT id FROM organisations WHERE id=?", (organisation_id,)):
                raise KeyError("Organisation not found")
            tx.execute(
                "INSERT INTO contacts(id,organisation_id,contact_type,name,registration_no,vat_no,email,address,country_code,payment_terms_days,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (contact_id, organisation_id, contact_type, name.strip(),
                 registration_no.strip() or None, vat_no.strip() or None,
                 email.strip() or None, address.strip() or None, country_code.upper(),
                 payment_terms_days, now, now),
            )
        return self.db.one("SELECT * FROM contacts WHERE id=?", (contact_id,)) or {}

    def create_item(self, organisation_id: str, *, code: str, name: str,
                    item_type: str = "service", description: str = "",
                    sales_account_id: str | None = None,
                    purchase_account_id: str | None = None,
                    tax_code_id: str | None = None, unit_price: object | None = None) -> dict:
        if item_type not in {"service", "product"} or not code.strip() or not name.strip():
            raise ValueError("A valid item code, name, and type are required")
        item_id, now = new_id(), utc_now()
        with self.db.transaction() as tx:
            for account_id in (sales_account_id, purchase_account_id):
                if account_id and not tx.one("SELECT id FROM accounts WHERE id=? AND organisation_id=?", (account_id, organisation_id)):
                    raise ValueError("Item account is not in this organisation")
            if tax_code_id and not tx.one("SELECT id FROM tax_codes WHERE id=? AND organisation_id=?", (tax_code_id, organisation_id)):
                raise ValueError("Item tax code is not in this organisation")
            tx.execute(
                "INSERT INTO items(id,organisation_id,code,name,description,item_type,sales_account_id,purchase_account_id,tax_code_id,unit_price,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (item_id, organisation_id, code.strip(), name.strip(), description or None,
                 item_type, sales_account_id, purchase_account_id, tax_code_id,
                 db_number(money(unit_price)) if unit_price is not None else None, now, now),
            )
        return self.db.one("SELECT * FROM items WHERE id=?", (item_id,)) or {}

    def _document_lines(self, tx, organisation_id: str, items: list[dict],
                        amount_type: str) -> tuple[list[dict], Decimal, Decimal, Decimal]:
        if amount_type not in {"exclusive", "inclusive", "no_tax"} or not items:
            raise ValueError("At least one line and a valid amount type are required")
        result, subtotal, tax_total = [], Decimal("0"), Decimal("0")
        for index, item in enumerate(items, 1):
            quantity = decimal(item.get("quantity", 1))
            unit_price = decimal(item.get("unit_price", 0))
            if quantity <= 0 or unit_price < 0:
                raise ValueError("Line quantities must be positive and prices cannot be negative")
            account = tx.one(
                "SELECT id FROM accounts WHERE id=? AND organisation_id=? AND active=1",
                (item.get("account_id"), organisation_id),
            )
            if not account:
                raise ValueError("Line account is not active in this organisation")
            tax = None
            if item.get("tax_code_id"):
                tax = tx.one(
                    "SELECT * FROM tax_codes WHERE id=? AND organisation_id=? AND active=1",
                    (item["tax_code_id"], organisation_id),
                )
                if not tax:
                    raise ValueError("Tax code is not active in this organisation")
            rate = decimal(tax["rate"] if tax else 0)
            raw = quantity * unit_price
            if amount_type == "inclusive" and rate:
                gross = money(raw)
                net = money(gross / (Decimal("1") + rate / Decimal("100")))
                tax_amount = money(gross - net)
            else:
                net = money(raw)
                tax_amount = money(net * rate / Decimal("100")) if amount_type != "no_tax" else money(0)
                gross = money(net + tax_amount)
            row = {
                "id": new_id(), "line_number": index,
                "description": str(item.get("description") or "Item").strip(),
                "quantity": quantity, "unit_price": unit_price,
                "account_id": item["account_id"], "tax_code_id": tax["id"] if tax else None,
                "tax_rate": rate, "net_amount": net, "tax_amount": tax_amount,
                "recoverable_tax": money(tax_amount * decimal(tax["recoverable_percent"] if tax else 100) / 100),
                "gross_amount": gross,
            }
            result.append(row)
            subtotal += net
            tax_total += tax_amount
        return result, money(subtotal), money(tax_total), money(subtotal + tax_total)

    def create_invoice(self, organisation_id: str, *, contact_id: str, issue_date: str,
                       lines: list[dict], actor: str, due_date: str | None = None,
                       currency: str | None = None, amount_type: str = "exclusive",
                       reference: str = "", notes: str = "", document_type: str = "invoice",
                       original_invoice_id: str | None = None) -> dict:
        if document_type not in {"invoice", "credit_note"}:
            raise ValueError("Invalid sales document type")
        invoice_id, now = new_id(), utc_now()
        with self.db.transaction() as tx:
            organisation = tx.one("SELECT * FROM organisations WHERE id=?", (organisation_id,))
            contact = tx.one("SELECT * FROM contacts WHERE id=? AND organisation_id=?", (contact_id, organisation_id))
            if not organisation or not contact or contact["contact_type"] not in {"customer", "both"}:
                raise ValueError("A customer in this organisation is required")
            calculated, subtotal, tax_total, total = self._document_lines(tx, organisation_id, lines, amount_type)
            due = due_date or (date.fromisoformat(issue_date) + timedelta(days=contact["payment_terms_days"])).isoformat()
            tx.execute(
                "INSERT INTO invoices(id,organisation_id,contact_id,document_type,issue_date,tax_point_date,due_date,currency,line_amount_type,reference,notes,original_invoice_id,subtotal,tax_total,total,created_by,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (invoice_id, organisation_id, contact_id, document_type, issue_date, issue_date,
                 due, (currency or organisation["base_currency"]).upper(), amount_type,
                 reference.strip() or None, notes.strip() or None, original_invoice_id,
                 db_number(subtotal), db_number(tax_total), db_number(total), actor, now, now),
            )
            for line in calculated:
                tx.execute(
                    "INSERT INTO invoice_lines(id,invoice_id,line_number,description,quantity,unit_price,account_id,tax_code_id,tax_rate,net_amount,tax_amount,gross_amount) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (line["id"], invoice_id, line["line_number"], line["description"],
                     db_number(line["quantity"]), db_number(line["unit_price"]), line["account_id"],
                     line["tax_code_id"], db_number(line["tax_rate"]), db_number(line["net_amount"]),
                     db_number(line["tax_amount"]), db_number(line["gross_amount"])),
                )
            audit(tx, organisation_id, actor, "invoice.created", "invoice", invoice_id,
                  {"document_type": document_type, "total": str(total)})
        return self.invoice(invoice_id, organisation_id)

    def invoice(self, invoice_id: str, organisation_id: str | None = None) -> dict:
        params = (invoice_id, organisation_id) if organisation_id else (invoice_id,)
        condition = "i.id=? AND i.organisation_id=?" if organisation_id else "i.id=?"
        row = self.db.one(
            "SELECT i.*,c.name contact_name,c.email contact_email,c.address contact_address,c.vat_no contact_vat_no "
            "FROM invoices i JOIN contacts c ON c.id=i.contact_id WHERE " + condition, params,
        )
        if not row:
            raise KeyError("Invoice not found")
        row["lines"] = self.db.rows("SELECT * FROM invoice_lines WHERE invoice_id=? ORDER BY line_number", (invoice_id,))
        return row

    def _next_number(self, tx, organisation_id: str, document_type: str) -> str:
        row = tx.one(
            "UPDATE document_sequences SET next_number=next_number+1 WHERE organisation_id=? AND document_type=? "
            "RETURNING prefix,next_number-1 AS allocated_number",
            (organisation_id, document_type),
        )
        if not row:
            raise ValueError("Document sequence is not configured")
        return f"{row['prefix']}{int(row['allocated_number']):06d}"

    def _role_account(self, tx, organisation_id: str, role: str) -> str:
        row = tx.one(
            "SELECT id FROM accounts WHERE organisation_id=? AND system_role=? AND active=1",
            (organisation_id, role),
        )
        if not row:
            raise ValueError(f"Chart of accounts is missing {role}")
        return row["id"]

    def issue_invoice(self, invoice_id: str, *, actor: str) -> dict:
        with self.db.transaction() as tx:
            invoice = tx.one("SELECT * FROM invoices WHERE id=?", (invoice_id,))
            if not invoice:
                raise KeyError("Invoice not found")
            if invoice["status"] != "Draft":
                return self.invoice(invoice_id)
            lines = tx.rows("SELECT * FROM invoice_lines WHERE invoice_id=? ORDER BY line_number", (invoice_id,))
            number = self._next_number(tx, invoice["organisation_id"], invoice["document_type"])
            ar = self._role_account(tx, invoice["organisation_id"], "AR")
            output_vat = self._role_account(tx, invoice["organisation_id"], "OUTPUT_VAT")
            grouped: dict[str, Decimal] = defaultdict(Decimal)
            for line in lines:
                grouped[line["account_id"]] += money(line["net_amount"])
            is_credit = invoice["document_type"] == "credit_note"
            posting_lines = [PostingLine(
                account_id=ar,
                debit=Decimal("0") if is_credit else money(invoice["total"]),
                credit=money(invoice["total"]) if is_credit else Decimal("0"),
                contact_id=invoice["contact_id"], due_date=invoice["due_date"],
                memo=number, source_line_type="invoice", source_line_id=invoice_id,
            )]
            for account_id, amount in grouped.items():
                posting_lines.append(PostingLine(
                    account_id=account_id, debit=amount if is_credit else Decimal("0"),
                    credit=Decimal("0") if is_credit else amount,
                    contact_id=invoice["contact_id"], memo=number,
                    source_line_type="invoice", source_line_id=invoice_id,
                ))
            if money(invoice["tax_total"]):
                posting_lines.append(PostingLine(
                    account_id=output_vat,
                    debit=money(invoice["tax_total"]) if is_credit else Decimal("0"),
                    credit=Decimal("0") if is_credit else money(invoice["tax_total"]),
                    memo=number, source_line_type="invoice", source_line_id=invoice_id,
                ))
            batch = self.ledger.post(
                organisation_id=invoice["organisation_id"], voucher_type=invoice["document_type"],
                voucher_id=invoice_id, voucher_code=number, posting_date=invoice["tax_point_date"],
                lines=posting_lines, actor=actor, currency=invoice["currency"],
                exchange_rate=decimal(invoice["exchange_rate"]), tx=tx,
            )
            now = utc_now()
            tx.execute(
                "UPDATE invoices SET number=?,status='Issued',posting_batch_id=?,issued_at=?,updated_at=? WHERE id=?",
                (number, batch["id"], now, now, invoice_id),
            )
            audit(tx, invoice["organisation_id"], actor, "invoice.issued", "invoice", invoice_id,
                  {"number": number, "posting_batch_id": batch["id"]})
        return self.invoice(invoice_id)

    def create_bill(self, organisation_id: str, *, contact_id: str, supplier_number: str,
                    bill_date: str, due_date: str, lines: list[dict], actor: str,
                    currency: str | None = None, reference: str = "", notes: str = "",
                    document_type: str = "bill") -> dict:
        if document_type not in {"bill", "supplier_credit"} or not supplier_number.strip():
            raise ValueError("Valid supplier document details are required")
        bill_id, now = new_id(), utc_now()
        with self.db.transaction() as tx:
            organisation = tx.one("SELECT * FROM organisations WHERE id=?", (organisation_id,))
            contact = tx.one("SELECT * FROM contacts WHERE id=? AND organisation_id=?", (contact_id, organisation_id))
            if not organisation or not contact or contact["contact_type"] not in {"supplier", "both"}:
                raise ValueError("A supplier in this organisation is required")
            calculated, subtotal, tax_total, total = self._document_lines(tx, organisation_id, lines, "exclusive")
            tx.execute(
                "INSERT INTO bills(id,organisation_id,contact_id,document_type,supplier_number,bill_date,due_date,currency,reference,notes,subtotal,tax_total,total,created_by,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (bill_id, organisation_id, contact_id, document_type, supplier_number.strip(), bill_date,
                 due_date, (currency or organisation["base_currency"]).upper(), reference or None,
                 notes or None, db_number(subtotal), db_number(tax_total), db_number(total), actor, now, now),
            )
            for line in calculated:
                tx.execute(
                    "INSERT INTO bill_lines(id,bill_id,line_number,description,quantity,unit_price,account_id,tax_code_id,tax_rate,net_amount,tax_amount,recoverable_tax,gross_amount) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (line["id"], bill_id, line["line_number"], line["description"],
                     db_number(line["quantity"]), db_number(line["unit_price"]), line["account_id"],
                     line["tax_code_id"], db_number(line["tax_rate"]), db_number(line["net_amount"]),
                     db_number(line["tax_amount"]), db_number(line["recoverable_tax"]), db_number(line["gross_amount"])),
                )
            audit(tx, organisation_id, actor, "bill.created", "bill", bill_id,
                  {"supplier_number": supplier_number, "total": str(total)})
        return self.bill(bill_id)

    def bill(self, bill_id: str) -> dict:
        row = self.db.one(
            "SELECT b.*,c.name contact_name FROM bills b JOIN contacts c ON c.id=b.contact_id WHERE b.id=?", (bill_id,)
        )
        if not row:
            raise KeyError("Bill not found")
        row["lines"] = self.db.rows("SELECT * FROM bill_lines WHERE bill_id=? ORDER BY line_number", (bill_id,))
        return row

    def submit_bill_for_review(self, bill_id: str, *, actor: str) -> dict:
        with self.db.transaction() as tx:
            bill = tx.one("SELECT * FROM bills WHERE id=?", (bill_id,))
            if not bill or bill["status"] != "Draft":
                raise ValueError("Only draft bills can be submitted")
            tx.execute("UPDATE bills SET status='In Review',updated_at=? WHERE id=?", (utc_now(), bill_id))
            audit(tx, bill["organisation_id"], actor, "bill.review_requested", "bill", bill_id)
        return self.bill(bill_id)

    def approve_bill(self, bill_id: str, *, actor: str) -> dict:
        with self.db.transaction() as tx:
            bill = tx.one("SELECT * FROM bills WHERE id=?", (bill_id,))
            if not bill or bill["status"] not in {"Draft", "In Review"}:
                raise ValueError("Only a draft or in-review bill can be approved")
            lines = tx.rows("SELECT * FROM bill_lines WHERE bill_id=? ORDER BY line_number", (bill_id,))
            ap = self._role_account(tx, bill["organisation_id"], "AP")
            input_vat = self._role_account(tx, bill["organisation_id"], "INPUT_VAT")
            is_credit = bill["document_type"] == "supplier_credit"
            postings: list[PostingLine] = []
            for line in lines:
                amount = money(line["net_amount"])
                postings.append(PostingLine(
                    account_id=line["account_id"], debit=Decimal("0") if is_credit else amount,
                    credit=amount if is_credit else Decimal("0"), contact_id=bill["contact_id"],
                    memo=bill["supplier_number"], source_line_type="bill", source_line_id=bill_id,
                ))
            tax = sum((money(line["recoverable_tax"]) for line in lines), Decimal("0"))
            nonrecoverable = money(bill["tax_total"]) - tax
            if nonrecoverable:
                first_expense = lines[0]["account_id"]
                postings.append(PostingLine(
                    account_id=first_expense, debit=Decimal("0") if is_credit else nonrecoverable,
                    credit=nonrecoverable if is_credit else Decimal("0"), memo="Non-recoverable tax",
                    source_line_type="bill", source_line_id=bill_id,
                ))
            if tax:
                postings.append(PostingLine(
                    account_id=input_vat, debit=Decimal("0") if is_credit else tax,
                    credit=tax if is_credit else Decimal("0"), memo=bill["supplier_number"],
                    source_line_type="bill", source_line_id=bill_id,
                ))
            postings.append(PostingLine(
                account_id=ap, debit=money(bill["total"]) if is_credit else Decimal("0"),
                credit=Decimal("0") if is_credit else money(bill["total"]),
                contact_id=bill["contact_id"], due_date=bill["due_date"],
                memo=bill["supplier_number"], source_line_type="bill", source_line_id=bill_id,
            ))
            batch = self.ledger.post(
                organisation_id=bill["organisation_id"], voucher_type=bill["document_type"],
                voucher_id=bill_id, voucher_code=bill["supplier_number"], posting_date=bill["bill_date"],
                lines=postings, actor=actor, currency=bill["currency"],
                exchange_rate=decimal(bill["exchange_rate"]), tx=tx,
            )
            now = utc_now()
            tx.execute(
                "UPDATE bills SET status='Approved',posting_batch_id=?,approved_at=?,approved_by=?,updated_at=? WHERE id=?",
                (batch["id"], now, actor, now, bill_id),
            )
            audit(tx, bill["organisation_id"], actor, "bill.approved", "bill", bill_id,
                  {"posting_batch_id": batch["id"]})
        return self.bill(bill_id)

    def create_bank_account(self, organisation_id: str, *, name: str, currency: str,
                            iban: str = "", sort_code: str = "") -> dict:
        account_id, bank_id = new_id(), new_id()
        with self.db.transaction() as tx:
            code = f"10{int(tx.scalar('SELECT COUNT(*) FROM bank_accounts WHERE organisation_id=?', (organisation_id,)) or 0) + 1:02d}"
            tx.execute(
                "INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance) VALUES (?,?,?,?,?,?)",
                (account_id, organisation_id, code, name, "Asset", "Debit"),
            )
            tx.execute(
                "INSERT INTO bank_accounts(id,organisation_id,ledger_account_id,name,currency,iban_masked,sort_code_masked) VALUES (?,?,?,?,?,?,?)",
                (bank_id, organisation_id, account_id, name, currency.upper(),
                 f"…{iban.replace(' ', '')[-4:]}" if iban else None,
                 f"…{sort_code.replace('-', '')[-2:]}" if sort_code else None),
            )
        return self.db.one("SELECT * FROM bank_accounts WHERE id=?", (bank_id,)) or {}

    def record_payment(self, organisation_id: str, *, payment_type: str, bank_account_id: str,
                       payment_date: str, amount: object, actor: str, contact_id: str | None = None,
                       reference: str = "", allocations: list[dict] | None = None) -> dict:
        if payment_type not in {"customer_receipt", "supplier_payment", "transfer"}:
            raise ValueError("Invalid payment type")
        value = money(amount)
        if value <= 0:
            raise ValueError("Payment amount must be positive")
        payment_id, now = new_id(), utc_now()
        allocations = allocations or []
        if money(sum((decimal(a["amount"]) for a in allocations), Decimal("0"))) > value:
            raise ValueError("Allocations cannot exceed the payment")
        with self.db.transaction() as tx:
            bank = tx.one("SELECT * FROM bank_accounts WHERE id=? AND organisation_id=?", (bank_account_id, organisation_id))
            organisation = tx.one("SELECT * FROM organisations WHERE id=?", (organisation_id,))
            if not bank or not organisation:
                raise ValueError("Bank account is not in this organisation")
            if payment_type == "transfer":
                raise ValueError("Transfers require two bank accounts and are not accepted by this method")
            control_role = "AR" if payment_type == "customer_receipt" else "AP"
            control = self._role_account(tx, organisation_id, control_role)
            if payment_type == "customer_receipt":
                lines = [PostingLine(bank["ledger_account_id"], debit=value, memo=reference),
                         PostingLine(control, credit=value, contact_id=contact_id, memo=reference)]
            else:
                lines = [PostingLine(control, debit=value, contact_id=contact_id, memo=reference),
                         PostingLine(bank["ledger_account_id"], credit=value, memo=reference)]
            batch = self.ledger.post(
                organisation_id=organisation_id, voucher_type="payment", voucher_id=payment_id,
                voucher_code=reference or f"PAY-{payment_id[:8]}", posting_date=payment_date,
                lines=lines, actor=actor, currency=bank["currency"], tx=tx,
            )
            tx.execute(
                "INSERT INTO payments(id,organisation_id,payment_type,contact_id,bank_account_id,payment_date,amount,currency,reference,posting_batch_id,created_by,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (payment_id, organisation_id, payment_type, contact_id, bank_account_id,
                 payment_date, db_number(value), bank["currency"], reference or None,
                 batch["id"], actor, now),
            )
            expected_type = "invoice" if payment_type == "customer_receipt" else "bill"
            for item in allocations:
                if item.get("document_type", expected_type) != expected_type:
                    raise ValueError("Allocation document type does not match payment type")
                table = "invoices" if expected_type == "invoice" else "bills"
                document = tx.one(
                    f"SELECT * FROM {table} WHERE id=? AND organisation_id=? AND contact_id=?",
                    (item["document_id"], organisation_id, contact_id),
                )
                allocated = money(item["amount"])
                if not document or allocated <= 0 or allocated > money(document["total"]) - money(document["paid_total"]):
                    raise ValueError("Allocation exceeds the open document balance")
                tx.execute(
                    "INSERT INTO payment_allocations(id,payment_id,document_type,document_id,amount) VALUES (?,?,?,?,?)",
                    (new_id(), payment_id, expected_type, document["id"], db_number(allocated)),
                )
                paid = money(document["paid_total"]) + allocated
                status = "Paid" if paid == money(document["total"]) else "Part Paid"
                tx.execute(f"UPDATE {table} SET paid_total=?,status=?,updated_at=? WHERE id=?",
                           (db_number(paid), status, now, document["id"]))
            audit(tx, organisation_id, actor, "payment.posted", "payment", payment_id,
                  {"amount": str(value), "type": payment_type})
        return self.db.one("SELECT * FROM payments WHERE id=?", (payment_id,)) or {}

    def attach_evidence(self, organisation_id: str, *, owner_type: str, owner_id: str,
                        filename: str, content_type: str, content: bytes, actor: str) -> dict:
        max_size = int(os.getenv("MAX_ATTACHMENT_BYTES", "10485760"))
        if not content or len(content) > max_size:
            raise ValueError("Attachment is empty or exceeds the configured size limit")
        safe_name = Path(filename).name
        attachment_id, digest, now = new_id(), sha256_bytes(content), utc_now()
        root = Path(os.getenv("FASTACCOUNTS_DATA_DIR", "./data")).resolve() / "attachments" / organisation_id
        root.mkdir(parents=True, exist_ok=True)
        target = root / f"{attachment_id}-{safe_name}"
        target.write_bytes(content)
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO attachments(id,organisation_id,owner_type,owner_id,filename,content_type,size_bytes,sha256,storage_path,uploaded_by,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (attachment_id, organisation_id, owner_type, owner_id, safe_name,
                 content_type, len(content), digest, str(target), actor, now),
            )
            audit(tx, organisation_id, actor, "evidence.attached", "attachment", attachment_id,
                  {"owner_type": owner_type, "owner_id": owner_id, "sha256": digest})
        return self.db.one("SELECT * FROM attachments WHERE id=?", (attachment_id,)) or {}

    def invoice_pdf(self, invoice_id: str) -> bytes:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen.canvas import Canvas

        invoice = self.invoice(invoice_id)
        organisation = self.db.one("SELECT * FROM organisations WHERE id=?", (invoice["organisation_id"],)) or {}
        output = BytesIO()
        canvas = Canvas(output, pagesize=A4)
        width, height = A4
        canvas.setTitle(invoice.get("number") or "Draft invoice")
        canvas.setFont("Helvetica-Bold", 20)
        canvas.drawString(42, height - 55, "CREDIT NOTE" if invoice["document_type"] == "credit_note" else "INVOICE")
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawString(42, height - 82, organisation.get("name", ""))
        canvas.setFont("Helvetica", 10)
        seller_details = [organisation.get("registration_no"), organisation.get("vat_no"), organisation.get("address")]
        seller_y = height - 98
        for detail in (item for item in seller_details if item):
            canvas.drawString(42, seller_y, str(detail)[:75])
            seller_y -= 14
        canvas.drawRightString(width - 42, height - 56, invoice.get("number") or "DRAFT")
        canvas.drawRightString(width - 42, height - 73, f"Issue date: {invoice['issue_date']}")
        canvas.drawRightString(width - 42, height - 90, f"Due date: {invoice['due_date']}")
        canvas.drawString(42, height - 126, f"Bill to: {invoice['contact_name']}")
        if invoice.get("contact_vat_no"):
            canvas.drawString(42, height - 141, f"VAT: {invoice['contact_vat_no']}")
        if invoice.get("contact_address"):
            canvas.drawString(42, height - 156, str(invoice["contact_address"])[:75])
        y = height - 170
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawString(42, y, "Description")
        canvas.drawRightString(width - 220, y, "Qty")
        canvas.drawRightString(width - 145, y, "Net")
        canvas.drawRightString(width - 90, y, "VAT")
        canvas.drawRightString(width - 42, y, "Total")
        canvas.setFont("Helvetica", 9)
        for line in invoice["lines"]:
            y -= 20
            if y < 85:
                canvas.showPage(); y = height - 55
            canvas.drawString(42, y, str(line["description"])[:60])
            canvas.drawRightString(width - 220, y, str(line["quantity"]))
            canvas.drawRightString(width - 145, y, f"{money(line['net_amount']):.2f}")
            canvas.drawRightString(width - 90, y, f"{money(line['tax_amount']):.2f}")
            canvas.drawRightString(width - 42, y, f"{money(line['gross_amount']):.2f}")
        y -= 35
        canvas.setFont("Helvetica-Bold", 11)
        canvas.drawRightString(width - 42, y, f"Total {invoice['currency']} {money(invoice['total']):.2f}")
        canvas.save()
        return output.getvalue()

    def invoice_xml(self, invoice_id: str) -> bytes:
        """Produce an Estonian-style 1.2 review export or generic XML elsewhere."""
        invoice = self.invoice(invoice_id)
        organisation = self.db.one("SELECT * FROM organisations WHERE id=?", (invoice["organisation_id"],)) or {}
        if organisation.get("country_code") == "EE":
            root = Element("E_Invoice")
            header = SubElement(root, "Header")
            SubElement(header, "Date").text = invoice["issue_date"]
            SubElement(header, "FileId").text = invoice.get("number") or invoice["id"]
            invoice_node = SubElement(root, "Invoice", invoiceId=invoice.get("number") or "DRAFT")
            SubElement(invoice_node, "InvoiceParties")
            content = SubElement(invoice_node, "InvoiceItem")
            group = SubElement(content, "InvoiceItemGroup")
            for item in invoice["lines"]:
                row = SubElement(group, "ItemEntry")
                SubElement(row, "Description").text = str(item["description"])
                SubElement(row, "ItemAmount").text = str(item["quantity"])
                SubElement(row, "ItemPrice").text = str(item["unit_price"])
                SubElement(row, "ItemTotal").text = str(item["net_amount"])
            total = SubElement(invoice_node, "InvoiceSumGroup")
            SubElement(total, "InvoiceSum").text = str(invoice["subtotal"])
            SubElement(total, "VAT").text = str(invoice["tax_total"])
            SubElement(total, "TotalSum").text = str(invoice["total"])
            return tostring(root, encoding="utf-8", xml_declaration=True)
        root = Element("FastAccountsInvoice", version="1.0")
        for key in ("number", "document_type", "issue_date", "due_date", "currency"):
            SubElement(root, key).text = str(invoice.get(key) or "")
        customer = SubElement(root, "Customer")
        SubElement(customer, "Name").text = invoice["contact_name"]
        SubElement(customer, "VATNumber").text = invoice.get("contact_vat_no") or ""
        lines = SubElement(root, "Lines")
        for item in invoice["lines"]:
            line = SubElement(lines, "Line")
            for key in ("description", "quantity", "unit_price", "net_amount", "tax_rate", "tax_amount", "gross_amount"):
                SubElement(line, key).text = str(item[key])
        totals = SubElement(root, "Totals")
        SubElement(totals, "Net").text = str(invoice["subtotal"])
        SubElement(totals, "Tax").text = str(invoice["tax_total"])
        SubElement(totals, "Gross").text = str(invoice["total"])
        return tostring(root, encoding="utf-8", xml_declaration=True)

    def send_invoice_email(self, invoice_id: str, *, actor: str, client=None) -> dict:
        """Send after posting through Postmark and retain a delivery audit record."""
        import httpx

        invoice = self.invoice(invoice_id)
        if invoice["status"] not in {"Issued", "Part Paid", "Paid"}:
            raise ValueError("Only issued invoices can be emailed")
        recipient = (invoice.get("contact_email") or "").strip()
        token = os.getenv("POSTMARK_API_TOKEN", "").strip()
        from_email = os.getenv("FROM_EMAIL", "").strip()
        if not recipient or not token or not from_email:
            raise RuntimeError("Recipient email, POSTMARK_API_TOKEN, and FROM_EMAIL are required")
        organisation = self.db.one("SELECT * FROM organisations WHERE id=?", (invoice["organisation_id"],)) or {}
        delivery_id, now = new_id(), utc_now()
        payload = {
            "From": from_email, "To": recipient,
            "Subject": f"Invoice {invoice['number']} from {organisation.get('name', 'FastAccounts')}",
            "TextBody": f"Please find invoice {invoice['number']} for {invoice['currency']} {money(invoice['total']):.2f} attached.",
            "MessageStream": "outbound",
            "Attachments": [{"Name": f"{invoice['number']}.pdf", "Content": base64.b64encode(self.invoice_pdf(invoice_id)).decode(),
                             "ContentType": "application/pdf"}],
        }
        http = client or httpx.Client(timeout=20)
        try:
            response = http.post("https://api.postmarkapp.com/email", json=payload,
                                 headers={"X-Postmark-Server-Token": token, "Accept": "application/json"})
            response.raise_for_status()
            result = response.json()
            status, provider_id, error = "Sent", result.get("MessageID"), None
        except Exception as exc:
            status, provider_id, error = "Failed", None, str(exc)[:500]
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO invoice_deliveries(id,organisation_id,invoice_id,channel,recipient,status,provider,provider_message_id,error_message,created_by,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (delivery_id, invoice["organisation_id"], invoice_id, "email", recipient,
                 status, "postmark", provider_id, error, actor, now),
            )
            audit(tx, invoice["organisation_id"], actor, "invoice.delivery", "invoice_delivery", delivery_id,
                  {"invoice_id": invoice_id, "status": status, "recipient": recipient})
        delivery = self.db.one("SELECT * FROM invoice_deliveries WHERE id=?", (delivery_id,)) or {}
        if status == "Failed":
            raise RuntimeError(f"Invoice delivery failed: {error}")
        return delivery


def locate_pdf_font(bold: bool = False) -> Path | None:
    """Prefer installed Unicode fonts; no proprietary font files are bundled."""
    names = (
        ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf")
        if bold else
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf")
    )
    return next((Path(name) for name in names if Path(name).is_file()), None)


def payroll_pdf(organisation: dict, run: dict) -> bytes:
    """Render localized payslips with embedded Unicode fonts when available."""
    import unicodedata
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.lib.utils import simpleSplit
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    regular_path = locate_pdf_font()
    regular, bold = 'Helvetica', 'Helvetica-Bold'
    if regular_path:
        regular, bold = 'PayrollUnicode', 'PayrollUnicodeBold'
        pdfmetrics.registerFont(TTFont(regular, str(regular_path)))
        pdfmetrics.registerFont(TTFont(bold, str(locate_pdf_font(True) or regular_path)))

    def text(value):
        value = str(value)
        if regular_path:
            return value
        return unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')

    ee = organisation.get('country_code') == 'EE'
    def label(et, en):
        return text(et if ee else en)

    output = BytesIO()
    canvas = Canvas(output, pagesize=A4)
    width, height = A4
    title = label('PALGALEHT', 'PAYSLIP') + ' ' + run['period']
    canvas.setTitle(title)
    rows = [
        ('Brutopalk', 'Gross salary', 'gross'),
        ('Kogumispension (II sammas)', 'Funded pension (II pillar)', 'funded_pension'),
        ('Töötuskindlustusmakse (töötaja)', 'Employee unemployment insurance', 'ui_employee'),
        ('Maksuvaba tulu', 'Tax-free minimum applied', 'tax_free_minimum'),
        ('Tulumaks', 'Income tax', 'income_tax'),
        ('Kinnipeetud summad kokku', 'Total employee withholdings', 'withholding_total'),
        ('Netopalk', 'Net payable', 'net'),
        ('Sotsiaalmaks (tööandja)', 'Employer social tax', 'social_tax'),
        ('Töötuskindlustusmakse (tööandja)', 'Employer unemployment insurance', 'ui_employer'),
        ('Tööandja kulu kokku', 'Total employer cost', 'employer_cost'),
    ]
    status = {'Approved': 'Kinnitatud', 'Draft': 'Kavand'}.get(run['status'], run['status']) if ee else run['status']
    for index, item in enumerate(run['items'], 1):
        canvas.setFont(bold, 20)
        canvas.drawString(42, height-55, title)
        canvas.setFont(regular, 11)
        y = height-85
        details = [organisation['name'],
                   label('Registrikood', 'Registration number') + ': ' + str(organisation.get('registration_no') or '-'),
                   label('Töötaja', 'Employee') + ': ' + item['employee_name'],
                   label('Valitud periood', 'Selected period') + ': ' + run['period'],
                   label('Kuupäev', 'Date') + ': ' + str(run.get('approved_at') or run.get('created_at') or '-')[:10],
                   label('Olek', 'Status') + ': ' + status + ' | EUR',
                   label('Juhatuse liige', 'Board member') if item['board_member'] else label('Töötaja', 'Employee')]
        for detail in details:
            for line in simpleSplit(text(detail), regular, 11, width-84):
                canvas.drawString(42, y, line)
                y -= 16
        y -= 24
        for et, en, key in rows:
            canvas.setFont(bold if key in ('net', 'employer_cost', 'withholding_total') else regular, 11)
            canvas.drawString(42, y, label(et, en))
            canvas.drawRightString(width-42, y, f"{money(item[key]):.2f}")
            y -= 28
        canvas.setFont(regular, 9)
        notes = ([
            'TSD deklaratsioon koostatakse raamatupidajale ülevaatamiseks; otse EMTA-le esitamine ootab kasutajapoolset vastuvõtutestimist (UAT).',
            'Maksmise tähtaeg: 10. kuupäev (väljamakse tegemise kuule järgneval kuul).',
        ] if ee else ['2026 accounting-bureau payroll demo - production UAT pending'])
        y -= 18
        for note in notes:
            for line in simpleSplit(text(note), regular, 9, width-84):
                canvas.drawString(42, y, line)
                y -= 14
            y -= 8
        canvas.drawRightString(width-42, 32, f"{index} / {len(run['items'])}")
        canvas.showPage()
    canvas.save()
    return output.getvalue()
