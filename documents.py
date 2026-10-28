"""Contacts, sales invoices, bills, payments, evidence, PDFs, and e-invoices."""
from __future__ import annotations

import os
import base64
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
import sqlite3
from xml.etree.ElementTree import Element, SubElement, tostring

from psycopg import IntegrityError as PostgresIntegrityError

import einvoice

from core_utils import audit, db_number, decimal, money, new_id, sha256_bytes, utc_now
from database import Database, get_database
from delivery_repository import DeliveryRepository
from exchange_rates import booking_rate
from fx_settlement import effective_rate, booked_portion, add_fx_line, control_line
from fx_settlement_repository import revaluation_control
from ledger import LedgerService, PostingLine
from periodisation_repository import PeriodisationRepository
from objects import dimensions, validate_dimensions
from objects_repository import ObjectRepository, DIMENSIONS


class EInvoiceAlreadyImported(ValueError):
    """A supplier invoice number already exists within this organisation."""


class InvoiceDeliveryFailed(RuntimeError):
    def __init__(self, delivery):
        self.delivery = delivery
        super().__init__(delivery.get('error_message') or
                         'Delivery outcome is unknown. Review delivery history before retrying.')


class DocumentService:
    def __init__(self, db: Database | None = None):
        self.db = db or get_database()
        self.ledger = LedgerService(self.db)

    def create_contact(self, organisation_id: str, *, name: str, country_code: str,
                       contact_type: str = "both", email: str = "", vat_no: str = "",
                       registration_no: str = "", address: str = "",
                       payment_terms_days: int = 14, iban: str = "", tx=None) -> dict:
        if contact_type not in {"customer", "supplier", "both"} or not name.strip():
            raise ValueError("Valid contact name and type are required")
        if tx is None:
            with self.db.transaction() as owned_tx:
                return self.create_contact(
                    organisation_id, name=name, country_code=country_code,
                    contact_type=contact_type, email=email, vat_no=vat_no,
                    registration_no=registration_no, address=address,
                    payment_terms_days=payment_terms_days, iban=iban, tx=owned_tx,
                )
        contact_id, now = new_id(), utc_now()
        if not tx.one("SELECT id FROM organisations WHERE id=?", (organisation_id,)):
            raise KeyError("Organisation not found")
        tx.execute(
            "INSERT INTO contacts(id,organisation_id,contact_type,name,registration_no,vat_no,email,address,country_code,payment_terms_days,created_at,updated_at,iban) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (contact_id, organisation_id, contact_type, name.strip(),
             registration_no.strip() or None, vat_no.strip() or None,
             email.strip() or None, address.strip() or None, country_code.upper(),
             payment_terms_days, now, now, iban.replace(" ", "").upper() or None),
        )
        return tx.one("SELECT * FROM contacts WHERE id=?", (contact_id,)) or {}

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
                        amount_type: str, declared_vat: list[object] | None = None
                        ) -> tuple[list[dict], Decimal, Decimal, Decimal]:
        if amount_type not in {"exclusive", "inclusive", "no_tax"} or not items:
            raise ValueError("At least one line and a valid amount type are required")
        if declared_vat is not None and len(declared_vat) != len(items):
            raise ValueError("Declared VAT must correspond to every bill line")
        result, subtotal, tax_total = [], Decimal("0"), Decimal("0")
        objects = ObjectRepository(tx, organisation_id)
        if any(any(dimensions(item).values()) for item in items):
            objects.lock_organisation()
        for index, item in enumerate(items, 1):
            tags = validate_dimensions(objects, item)
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
            if declared_vat is not None:
                declared_tax = money(declared_vat[index - 1])
                declared_gross = money(net + declared_tax)
                # Suppliers may round VAT from a gross price. Preserve that
                # cent only when it reconciles exactly to the same net amount.
                if declared_tax < 0 or (declared_tax != tax_amount and
                        money(declared_gross / (Decimal(1) + rate / 100)) != net):
                    raise ValueError("Declared bill VAT does not match exclusive or inclusive rounding")
                tax_amount, gross = declared_tax, declared_gross
            row = {
                "id": new_id(), "line_number": index,
                "description": str(item.get("description") or "Item").strip(),
                "quantity": quantity, "unit_price": unit_price,
                "account_id": item["account_id"], "tax_code_id": tax["id"] if tax else None,
                "tax_rate": rate, "net_amount": net, "tax_amount": tax_amount,
                "recoverable_tax": money(tax_amount * decimal(tax["recoverable_percent"] if tax else 100) / 100),
                "gross_amount": gross,
                **tags,
            }
            result.append(row)
            subtotal += net
            tax_total += tax_amount
        return result, money(subtotal), money(tax_total), money(subtotal + tax_total)

    def create_invoice(self, organisation_id: str, *, contact_id: str, issue_date: str,
                       lines: list[dict], actor: str, due_date: str | None = None,
                       currency: str | None = None, amount_type: str = "exclusive",
                       reference: str = "", notes: str = "", document_type: str = "invoice",
                       original_invoice_id: str | None = None, exchange_rate: Decimal | None = None, tx=None) -> dict:
        if document_type not in {"invoice", "credit_note"}:
            raise ValueError("Invalid sales document type")
        if tx is None:
            with self.db.transaction() as owned_tx:
                return self.create_invoice(
                    organisation_id, contact_id=contact_id, issue_date=issue_date,
                    lines=lines, actor=actor, due_date=due_date, currency=currency,
                    amount_type=amount_type, reference=reference, notes=notes,
                    document_type=document_type, original_invoice_id=original_invoice_id,
                    exchange_rate=exchange_rate, tx=owned_tx,
                )
        invoice_id, now = new_id(), utc_now()
        organisation = tx.one("SELECT * FROM organisations WHERE id=?", (organisation_id,))
        contact = tx.one("SELECT * FROM contacts WHERE id=? AND organisation_id=?", (contact_id, organisation_id))
        if not organisation or not contact or contact["contact_type"] not in {"customer", "both"}:
            raise ValueError("A customer in this organisation is required")
        currency = (currency or organisation["base_currency"]).upper()
        exchange_rate = booking_rate(tx, organisation_id, currency, organisation["base_currency"], issue_date, exchange_rate)
        calculated, subtotal, tax_total, total = self._document_lines(tx, organisation_id, lines, amount_type)
        due = due_date or (date.fromisoformat(issue_date) + timedelta(days=contact["payment_terms_days"])).isoformat()
        tx.execute(
            "INSERT INTO invoices(id,organisation_id,contact_id,document_type,issue_date,tax_point_date,due_date,currency,line_amount_type,reference,notes,original_invoice_id,subtotal,tax_total,total,created_by,created_at,updated_at,exchange_rate) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (invoice_id, organisation_id, contact_id, document_type, issue_date, issue_date,
             due, (currency or organisation["base_currency"]).upper(), amount_type,
             reference.strip() or None, notes.strip() or None, original_invoice_id,
             db_number(subtotal), db_number(tax_total), db_number(total), actor, now, now, db_number(exchange_rate)),
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
            ObjectRepository(tx, organisation_id).save_dimensions('invoice', invoice_id, line['id'], dimensions(line))
        audit(tx, organisation_id, actor, "invoice.created", "invoice", invoice_id,
              {"document_type": document_type, "total": str(total)})
        row = tx.one(
            "SELECT i.*,c.name contact_name,c.email contact_email,c.address contact_address,c.vat_no contact_vat_no "
            "FROM invoices i JOIN contacts c ON c.id=i.contact_id "
            "WHERE i.id=? AND i.organisation_id=?", (invoice_id, organisation_id),
        ) or {}
        row["lines"] = ObjectRepository(tx, organisation_id).document_lines('invoice', invoice_id)
        return row

    def invoice(self, invoice_id: str, organisation_id: str | None = None, tx=None) -> dict:
        if tx is None:
            with self.db.transaction() as owned_tx:
                return self.invoice(invoice_id, organisation_id, tx=owned_tx)
        params = (invoice_id, organisation_id) if organisation_id else (invoice_id,)
        condition = "i.id=? AND i.organisation_id=?" if organisation_id else "i.id=?"
        row = tx.one(
            "SELECT i.*,c.name contact_name,c.email contact_email,c.address contact_address,c.vat_no contact_vat_no "
            "FROM invoices i JOIN contacts c ON c.id=i.contact_id AND c.organisation_id=i.organisation_id WHERE " + condition, params,
        )
        if not row:
            raise KeyError("Invoice not found")
        row["lines"] = ObjectRepository(tx, row['organisation_id']).document_lines('invoice', invoice_id)
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

    def issue_invoice(self, invoice_id: str, *, actor: str, tx=None) -> dict:
        if tx is not None:
            return self._issue_invoice_tx(tx, invoice_id, actor)
        with self.db.transaction() as tx:
            return self._issue_invoice_tx(tx, invoice_id, actor)

    def _issue_invoice_tx(self, tx, invoice_id: str, actor: str) -> dict:
        def result():
            row = tx.one(
                "SELECT i.*,c.name contact_name,c.email contact_email,c.address contact_address,c.vat_no contact_vat_no "
                "FROM invoices i JOIN contacts c ON c.id=i.contact_id WHERE i.id=?", (invoice_id,),
            )
            row["lines"] = ObjectRepository(tx, row['organisation_id']).document_lines('invoice', invoice_id)
            return row

        invoice = tx.one("SELECT * FROM invoices WHERE id=?", (invoice_id,))
        if not invoice:
            raise KeyError("Invoice not found")
        if invoice["status"] != "Draft":
            return result()
        lines = ObjectRepository(tx, invoice['organisation_id']).document_lines('invoice', invoice_id)
        number = self._next_number(tx, invoice["organisation_id"], invoice["document_type"])
        ar = self._role_account(tx, invoice["organisation_id"], "AR")
        output_vat = self._role_account(tx, invoice["organisation_id"], "OUTPUT_VAT")
        grouped = defaultdict(Decimal)
        for line in lines:
            grouped[(line['account_id'], *dimensions(line).values())] += money(line["net_amount"])
        is_credit = invoice["document_type"] == "credit_note"
        posting_lines = [PostingLine(
            account_id=ar,
            debit=Decimal("0") if is_credit else money(invoice["total"]),
            credit=money(invoice["total"]) if is_credit else Decimal("0"),
            contact_id=invoice["contact_id"], due_date=invoice["due_date"],
            memo=number, source_line_type="invoice", source_line_id=invoice_id,
        )]
        for (account_id, *tags), amount in grouped.items():
            if not amount:
                continue
            posting_lines.append(PostingLine(
                account_id=account_id, debit=amount if is_credit else Decimal("0"),
                credit=Decimal("0") if is_credit else amount,
                contact_id=invoice["contact_id"], memo=number,
                source_line_type="invoice", source_line_id=invoice_id,
                **dict(zip(DIMENSIONS, tags)),
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
            allow_inactive_objects=True,
        )
        now = utc_now()
        tx.execute(
            "UPDATE invoices SET number=?,status='Issued',posting_batch_id=?,issued_at=?,updated_at=? WHERE id=?",
            (number, batch["id"], now, now, invoice_id),
        )
        audit(tx, invoice["organisation_id"], actor, "invoice.issued", "invoice", invoice_id,
              {"number": number, "posting_batch_id": batch["id"]})
        return result()

    def create_bill(self, organisation_id: str, *, contact_id: str, supplier_number: str,
                    bill_date: str, due_date: str, lines: list[dict], actor: str,
                    currency: str | None = None, reference: str = "", notes: str = "",
                    document_type: str = "bill", declared_vat: list[object] | None = None, exchange_rate: Decimal | None = None, tx=None) -> dict:
        if document_type not in {"bill", "supplier_credit"} or not supplier_number.strip():
            raise ValueError("Valid supplier document details are required")
        if tx is None:
            with self.db.transaction() as owned_tx:
                return self.create_bill(
                    organisation_id, contact_id=contact_id, supplier_number=supplier_number,
                    bill_date=bill_date, due_date=due_date, lines=lines, actor=actor,
                    currency=currency, reference=reference, notes=notes,
                    document_type=document_type, declared_vat=declared_vat, exchange_rate=exchange_rate, tx=owned_tx,
                )
        bill_id, now = new_id(), utc_now()
        organisation = tx.one("SELECT * FROM organisations WHERE id=?", (organisation_id,))
        contact = tx.one("SELECT * FROM contacts WHERE id=? AND organisation_id=?", (contact_id, organisation_id))
        if not organisation or not contact or contact["contact_type"] not in {"supplier", "both"}:
            raise ValueError("A supplier in this organisation is required")
        currency = (currency or organisation["base_currency"]).upper()
        exchange_rate = booking_rate(tx, organisation_id, currency, organisation["base_currency"], bill_date, exchange_rate)
        calculated, subtotal, tax_total, total = self._document_lines(
            tx, organisation_id, lines, "exclusive", declared_vat=declared_vat)
        tx.execute(
            "INSERT INTO bills(id,organisation_id,contact_id,document_type,supplier_number,bill_date,due_date,currency,reference,notes,subtotal,tax_total,total,created_by,created_at,updated_at,exchange_rate) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (bill_id, organisation_id, contact_id, document_type, supplier_number.strip(), bill_date,
             due_date, (currency or organisation["base_currency"]).upper(), reference or None,
             notes or None, db_number(subtotal), db_number(tax_total), db_number(total), actor, now, now, db_number(exchange_rate)),
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
            ObjectRepository(tx, organisation_id).save_dimensions('bill', bill_id, line['id'], dimensions(line))
        audit(tx, organisation_id, actor, "bill.created", "bill", bill_id,
              {"supplier_number": supplier_number, "total": str(total)})
        row = tx.one(
            "SELECT b.*,c.name contact_name FROM bills b JOIN contacts c ON c.id=b.contact_id WHERE b.id=?",
            (bill_id,),
        ) or {}
        row["lines"] = ObjectRepository(tx, organisation_id).document_lines('bill', bill_id)
        return row

    def bill(self, bill_id: str) -> dict:
        row = self.db.one(
            "SELECT b.*,c.name contact_name FROM bills b JOIN contacts c ON c.id=b.contact_id WHERE b.id=?", (bill_id,)
        )
        if not row:
            raise KeyError("Bill not found")
        with self.db.transaction() as tx:
            row["lines"] = ObjectRepository(tx, row['organisation_id']).document_lines('bill', bill_id)
        return row

    def import_einvoice(self, organisation_id: str, *, content: bytes,
                        filename: str, actor: str) -> dict:
        """Validate and retain an XML purchase as a draft, without ledger posting."""
        if not content or len(content) > int(os.getenv("MAX_ATTACHMENT_BYTES", "10485760")):
            raise ValueError("E-invoice is empty or exceeds the configured size limit")
        purchase = einvoice.parse_purchase(content)
        evidence = None
        try:
            with self.db.transaction() as tx:
                organisation = tx.one("SELECT * FROM organisations WHERE id=?", (organisation_id,))
                if not organisation:
                    raise KeyError("Organisation not found")
                taxes = tx.rows(
                    "SELECT * FROM tax_codes WHERE organisation_id=? AND active=1 "
                    "AND country_code=? ORDER BY CASE kind WHEN 'standard' THEN 0 "
                    "WHEN 'reduced' THEN 1 WHEN 'zero' THEN 2 ELSE 3 END,code,valid_from DESC,id",
                    (organisation_id, organisation["country_code"]))
                by_rate = {}
                for tax in taxes:
                    by_rate.setdefault(decimal(tax["rate"]), tax["id"])
                unknown = sorted({item["vat_rate"] for item in purchase["items"]} - by_rate.keys())
                if unknown:
                    raise ValueError("Unknown VAT rates: " + ", ".join(format(rate, "f") for rate in unknown))
                account_id = self._role_account(tx, organisation_id, "EXPENSE")
                seller = purchase["seller"]
                supplier = None
                if seller.get("registration_no"):
                    supplier = tx.one(
                        "SELECT * FROM contacts WHERE organisation_id=? AND registration_no=? "
                        "AND contact_type IN ('supplier','both') ORDER BY created_at,id LIMIT 1",
                        (organisation_id, seller["registration_no"]))
                # Registry matches retain the existing name. Without a registry code,
                # reuse an exact name/VAT match so a repeated upload stays idempotent.
                else:
                    supplier = tx.one(
                        "SELECT * FROM contacts WHERE organisation_id=? AND name=? "
                        "AND COALESCE(vat_no,'')=? AND COALESCE(registration_no,'')='' "
                        "AND contact_type IN ('supplier','both') ORDER BY created_at,id LIMIT 1",
                        (organisation_id, seller["name"], seller.get("vat_no") or ""))
                note = f"Imported from e-invoice {purchase['invoice_number']}"
                if not supplier:
                    supplier = self.create_contact(
                        organisation_id, name=seller["name"], contact_type="supplier",
                        registration_no=seller.get("registration_no") or "",
                        vat_no=seller.get("vat_no") or "", email=seller.get("email") or "",
                        address=seller.get("address") or "",
                        country_code=seller.get("country_code") or "EE", tx=tx)
                    audit(tx, organisation_id, actor, "contact.einvoice_imported", "contact", supplier["id"], {"note": note})
                if tx.one("SELECT id FROM bills WHERE organisation_id=? AND contact_id=? AND supplier_number=?",
                          (organisation_id, supplier["id"], purchase["invoice_number"])):
                    raise EInvoiceAlreadyImported("Supplier invoice already imported")
                lines = [dict(description=item["description"], quantity=item["quantity"],
                              unit_price=item["unit_price"], account_id=account_id,
                              tax_code_id=by_rate[item["vat_rate"]]) for item in purchase["items"]]
                try:
                    bill = self.create_bill(
                        organisation_id, contact_id=supplier["id"], supplier_number=purchase["invoice_number"],
                        bill_date=purchase["invoice_date"], due_date=purchase["due_date"] or purchase["invoice_date"],
                        currency=purchase["currency"], reference=purchase["buyer_reference"],
                        notes=note, lines=lines, actor=actor,
                        declared_vat=[item["tax_amount"] for item in purchase["items"]], tx=tx)
                except (sqlite3.IntegrityError, PostgresIntegrityError) as error:
                    if (getattr(error, "sqlstate", None) == "23505" or
                            getattr(error, "sqlite_errorname", "") == "SQLITE_CONSTRAINT_UNIQUE"):
                        raise EInvoiceAlreadyImported("Supplier invoice already imported") from error
                    raise
                for source, stored in zip(purchase["items"], bill["lines"]):
                    for key in ("net_amount", "tax_amount", "gross_amount"):
                        difference = money(stored[key]) - money(source[key])
                        if difference:
                            raise ValueError(f"Imported line {key} differs by {difference:.2f}")
                evidence = self.attach_evidence(
                    organisation_id, owner_type="bill", owner_id=bill["id"],
                    filename=filename, content_type="application/xml", content=content, actor=actor, tx=tx)
                result = {"bill_id": bill["id"], "supplier": supplier["name"],
                          "total": format(money(bill["total"]), ".2f"), "warnings": []}
            return result
        except Exception:
            if evidence:
                Path(evidence["storage_path"]).unlink(missing_ok=True)
            raise

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
            if bill:
                period_repo = PeriodisationRepository(tx, bill['organisation_id'])
                period_repo.lock_organisation()
                bill = tx.one("SELECT * FROM bills WHERE id=? AND organisation_id=?", (bill_id, bill['organisation_id']))
            if not bill or bill["status"] not in {"Draft", "In Review"}:
                raise ValueError("Only a draft or in-review bill can be approved")
            lines = ObjectRepository(tx, bill['organisation_id']).document_lines('bill', bill_id)
            schedule = period_repo.for_bill(bill_id)
            if schedule and schedule['status'] == 'Cancelled':
                schedule = None
            if schedule:
                if (money(schedule['net_amount']) != money(bill['subtotal']) or schedule['currency'] != bill['currency']
                        or bill['document_type'] != 'bill'
                        or sum((money(l['recoverable_tax']) for l in lines), Decimal(0)) != money(bill['tax_total'])):
                    raise ValueError('Bill no longer matches its purchase schedule')
                deferred = period_repo.account(schedule['deferred_account_id'])
                if not deferred or deferred['account_type'] != 'Asset':
                    raise ValueError('Active deferred account is required')
            ap = self._role_account(tx, bill["organisation_id"], "AP")
            input_vat = self._role_account(tx, bill["organisation_id"], "INPUT_VAT")
            is_credit = bill["document_type"] == "supplier_credit"
            postings: list[PostingLine] = []
            for line in lines:
                amount = money(line["net_amount"])
                postings.append(PostingLine(
                    account_id=schedule['deferred_account_id'] if schedule else line["account_id"], debit=Decimal("0") if is_credit else amount,
                    credit=amount if is_credit else Decimal("0"), contact_id=bill["contact_id"],
                    memo=bill["supplier_number"], source_line_type="bill", source_line_id=bill_id,
                    **dimensions(line),
                ))
            tax = sum((money(line["recoverable_tax"]) for line in lines), Decimal("0"))
            nonrecoverable = money(bill["tax_total"]) - tax
            if nonrecoverable:
                for line in lines:
                    amount = money(line['tax_amount']) - money(line['recoverable_tax'])
                    if amount:
                        postings.append(PostingLine(
                            account_id=line['account_id'], debit=Decimal('0') if is_credit else amount,
                            credit=amount if is_credit else Decimal('0'), memo='Non-recoverable tax',
                            source_line_type='bill', source_line_id=bill_id, **dimensions(line)))
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
                exchange_rate=(effective_rate(bill['currency'], tx.scalar(
                    'SELECT base_currency FROM organisations WHERE id=?', (bill['organisation_id'],)), bill['exchange_rate'])
                    if schedule else decimal(bill['exchange_rate'])), tx=tx,
                allow_inactive_objects=True,
            )
            now = utc_now()
            if schedule:
                period_repo.funding(schedule['id'], batch['id'])
            tx.execute(
                "UPDATE bills SET status='Approved',posting_batch_id=?,approved_at=?,approved_by=?,updated_at=? WHERE id=?",
                (batch["id"], now, actor, now, bill_id),
            )
            audit(tx, bill["organisation_id"], actor, "bill.approved", "bill", bill_id,
                  {"posting_batch_id": batch["id"]})
        return self.bill(bill_id)

    def create_bank_account(self, organisation_id: str, *, name: str, currency: str,
                            iban: str = "", sort_code: str = "", bic: str = "") -> dict:
        bic = bic.strip().upper()
        if bic and (len(bic) not in (8, 11) or not bic.isalnum()):
            raise ValueError('Enter a valid 8 or 11 character BIC')
        account_id, bank_id = new_id(), new_id()
        with self.db.transaction() as tx:
            code = f"10{int(tx.scalar('SELECT COUNT(*) FROM bank_accounts WHERE organisation_id=?', (organisation_id,)) or 0) + 1:02d}"
            tx.execute(
                "INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance) VALUES (?,?,?,?,?,?)",
                (account_id, organisation_id, code, name, "Asset", "Debit"),
            )
            tx.execute(
                "INSERT INTO bank_accounts(id,organisation_id,ledger_account_id,name,currency,iban_masked,sort_code_masked,iban) VALUES (?,?,?,?,?,?,?,?)",
                (bank_id, organisation_id, account_id, name, currency.upper(),
                 f"…{iban.replace(' ', '')[-4:]}" if iban else None,
                 f"…{sort_code.replace('-', '')[-2:]}" if sort_code else None,
                 iban.replace(" ", "").upper() or None),
            )
            if self.db.dialect == 'sqlite':
                has_bic = any(row['name'] == 'bic' for row in tx.rows('PRAGMA table_info(bank_accounts)'))
            else:
                has_bic = bool(tx.one("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='bank_accounts' AND column_name='bic'"))
            if bic and not has_bic:
                raise ValueError('BIC storage is unavailable until the bank account migration is applied')
            if has_bic:
                tx.execute('UPDATE bank_accounts SET bic=? WHERE organisation_id=? AND id=?', (bic or None, organisation_id, bank_id))
        return self.db.one("SELECT * FROM bank_accounts WHERE id=?", (bank_id,)) or {}

    def record_payment(self, organisation_id: str, *, payment_type: str, bank_account_id: str,
                       payment_date: str, amount: object, actor: str, contact_id: str | None = None,
                       reference: str = "", allocations: list[dict] | None = None, exchange_rate: Decimal | None = None, tx=None) -> dict:
        if payment_type not in {"customer_receipt", "supplier_payment", "transfer"}:
            raise ValueError("Invalid payment type")
        value = money(amount)
        if value <= 0:
            raise ValueError("Payment amount must be positive")
        payment_id, now = new_id(), utc_now()
        allocations = allocations or []
        if money(sum((decimal(a["amount"]) for a in allocations), Decimal("0"))) > value:
            raise ValueError("Allocations cannot exceed the payment")
        if tx is None:
            with self.db.transaction() as owned_tx:
                return self.record_payment(
                    organisation_id, payment_type=payment_type,
                    bank_account_id=bank_account_id, payment_date=payment_date,
                    amount=amount, actor=actor, contact_id=contact_id,
                    reference=reference, allocations=allocations, exchange_rate=exchange_rate, tx=owned_tx,
                )
        bank = tx.one("SELECT * FROM bank_accounts WHERE id=? AND organisation_id=?", (bank_account_id, organisation_id))
        organisation = tx.one("SELECT * FROM organisations WHERE id=?", (organisation_id,))
        if not bank or not organisation:
            raise ValueError("Bank account is not in this organisation")
        if payment_type == "transfer":
            raise ValueError("Transfers require two bank accounts and are not accepted by this method")
        control_role = "AR" if payment_type == "customer_receipt" else "AP"
        control = self._role_account(tx, organisation_id, control_role)
        rate = booking_rate(tx, organisation_id, bank["currency"], organisation["base_currency"], payment_date, exchange_rate)
        base = organisation["base_currency"]
        paid_rate = effective_rate(bank["currency"], base, rate)
        expected_type = "invoice" if payment_type == "customer_receipt" else "bill"
        table = "invoices" if expected_type == "invoice" else "bills"
        documents, booked_amounts = {}, {}
        booked_total, allocated_total, differing_rates, final_rounding = Decimal('0'), Decimal('0'), False, False
        for item in allocations:
            if item.get("document_type", expected_type) != expected_type:
                raise ValueError("Allocation document type does not match payment type")
            document_id = item["document_id"]
            if document_id in documents:
                raise ValueError('Allocation exceeds the open document balance')
            documents[document_id] = tx.one(
                f"SELECT * FROM {table} WHERE id=? AND organisation_id=? AND contact_id=?",
                (document_id, organisation_id, contact_id))
            document = documents[document_id]
            allocated = money(item["amount"])
            if not document or allocated <= 0 or allocated > money(document["total"]) - money(document["paid_total"]):
                raise ValueError("Allocation exceeds the open document balance")
            differing_rates |= effective_rate(document['currency'], base, document['exchange_rate']) != paid_rate
            booked_amounts[document_id] = booked_portion(tx, organisation_id, document, control, allocated, base)
            differing_rates |= revaluation_control(tx, organisation_id, document, control) is not None
            booked_total += booked_amounts[document_id]
            final_rounding |= (money(document['paid_total']) + allocated == money(document['total'])
                               and booked_amounts[document_id] != money(allocated * paid_rate))
            allocated_total += allocated
            document['paid_total'] = money(document['paid_total']) + allocated
        if allocated_total > value:
            raise ValueError('Allocations cannot exceed the payment')
        fully_settled = any(money(row['paid_total']) == money(row['total']) for row in documents.values())
        final_rounding |= (fully_settled
                           and booked_total + money((value - allocated_total) * paid_rate) != money(value * paid_rate))
        # Preserve equal-rate aggregates, except a final stored-base cent must
        # clear exactly rather than reproduce the historical rounding residual.
        posting_currency = bank['currency']
        bank_value, control_value = value, value
        if differing_rates or final_rounding:
            posting_currency = base
            bank_value = money(value * paid_rate)
            control_value = booked_total + money((value - allocated_total) * paid_rate)
        if payment_type == "customer_receipt":
            lines = [PostingLine(bank["ledger_account_id"], debit=bank_value, memo=reference),
                     control_line(control, control_value, debit=False, contact_id=contact_id, memo=reference)]
        else:
            lines = [control_line(control, control_value, debit=True, contact_id=contact_id, memo=reference),
                     PostingLine(bank["ledger_account_id"], credit=bank_value, memo=reference)]
        add_fx_line(tx, organisation_id, lines, memo=reference)
        batch = self.ledger.post(
            organisation_id=organisation_id, voucher_type="payment", voucher_id=payment_id,
            voucher_code=reference or f"PAY-{payment_id[:8]}", posting_date=payment_date,
            lines=lines, actor=actor, currency=posting_currency, exchange_rate=rate, tx=tx,
        )
        tx.execute(
            "INSERT INTO payments(id,organisation_id,payment_type,contact_id,bank_account_id,payment_date,amount,currency,reference,posting_batch_id,created_by,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (payment_id, organisation_id, payment_type, contact_id, bank_account_id,
             payment_date, db_number(value), bank["currency"], reference or None,
             batch["id"], actor, now),
        )
        expected_type = "invoice" if payment_type == "customer_receipt" else "bill"
        allocated_running = Decimal('0')
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
            relief = booked_amounts[document['id']] if differing_rates or final_rounding else (
                money((allocated_running + allocated) * paid_rate) - money(allocated_running * paid_rate))
            allocated_running += allocated
            tx.execute(
                'INSERT INTO payment_allocations(id,payment_id,document_type,document_id,amount,booked_base_amount) '
                'VALUES (?,?,?,?,?,?)',
                (new_id(), payment_id, expected_type, document['id'], db_number(allocated), db_number(relief)),
            )
            paid = money(document["paid_total"]) + allocated
            status = "Paid" if paid == money(document["total"]) else "Part Paid"
            tx.execute(f"UPDATE {table} SET paid_total=?,status=?,updated_at=? WHERE id=?",
                       (db_number(paid), status, now, document["id"]))
        audit(tx, organisation_id, actor, "payment.posted", "payment", payment_id,
              {"amount": str(value), "type": payment_type})
        return tx.one("SELECT * FROM payments WHERE id=?", (payment_id,)) or {}

    def attach_evidence(self, organisation_id: str, *, owner_type: str, owner_id: str,
                        filename: str, content_type: str, content: bytes, actor: str, tx=None) -> dict:
        if tx is None:
            result = None
            try:
                with self.db.transaction() as owned_tx:
                    result = self.attach_evidence(
                        organisation_id, owner_type=owner_type, owner_id=owner_id,
                        filename=filename, content_type=content_type, content=content,
                        actor=actor, tx=owned_tx)
                return result
            except Exception:
                if result:
                    Path(result["storage_path"]).unlink(missing_ok=True)
                raise
        max_size = int(os.getenv("MAX_ATTACHMENT_BYTES", "10485760"))
        if not content or len(content) > max_size:
            raise ValueError("Attachment is empty or exceeds the configured size limit")
        safe_name = Path(filename.replace("\\", "/")).name
        safe_name = "".join(c for c in safe_name if c.isalnum() or c in " ._-")[:180].strip(" .") or "attachment"
        attachment_id, digest, now = new_id(), sha256_bytes(content), utc_now()
        root = Path(os.getenv("FASTACCOUNTS_DATA_DIR", "./data")).resolve() / "attachments" / organisation_id
        target = root / f"{attachment_id}-{safe_name}"
        try:
            self._evidence_owner(tx, organisation_id, owner_type, owner_id)
            if tx.one("SELECT id FROM attachments WHERE organisation_id=? AND owner_type=? AND owner_id=? AND sha256=?",
                      (organisation_id, owner_type, owner_id, digest)):
                raise ValueError("This evidence is already attached to this document")
            root.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            tx.execute(
                "INSERT INTO attachments(id,organisation_id,owner_type,owner_id,filename,content_type,size_bytes,sha256,storage_path,uploaded_by,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (attachment_id, organisation_id, owner_type, owner_id, safe_name,
                 content_type, len(content), digest, str(target), actor, now),
            )
            audit(tx, organisation_id, actor, "evidence.attached", "attachment", attachment_id,
                  {"owner_type": owner_type, "owner_id": owner_id, "sha256": digest})
            return tx.one("SELECT * FROM attachments WHERE id=?", (attachment_id,)) or {}
        except Exception:
            target.unlink(missing_ok=True)
            raise

    @staticmethod
    def _evidence_owner(tx, organisation_id, owner_type, owner_id):
        tables = {"invoice": "invoices", "bill": "bills", "journal": "posting_batches", "organisation": "organisations"}
        if owner_type not in tables:
            raise ValueError("Evidence owner must be invoice, bill, journal or organisation")
        query = ("SELECT id FROM organisations WHERE id=? AND id=?" if owner_type == "organisation" else
                 f"SELECT id FROM {tables[owner_type]} WHERE organisation_id=? AND id=?")
        if owner_type == "journal":
            query += " AND voucher_type='manual_journal'"
        if not tx.one(query, (organisation_id, owner_id)):
            raise KeyError("Evidence owner not found")

    def attachments(self, organisation_id, *, owner_type, owner_id):
        with self.db.transaction() as tx:
            self._evidence_owner(tx, organisation_id, owner_type, owner_id)
            return tx.rows(
                "SELECT id,owner_type,owner_id,filename,content_type,size_bytes,sha256,uploaded_by,created_at "
                "FROM attachments WHERE organisation_id=? AND owner_type=? AND owner_id=? ORDER BY created_at,id",
                (organisation_id, owner_type, owner_id))

    def evidence_download(self, organisation_id, attachment_id):
        with self.db.transaction() as tx:
            attachment = tx.one("SELECT * FROM attachments WHERE organisation_id=? AND id=?",
                                (organisation_id, attachment_id))
            if not attachment:
                raise KeyError("Attachment not found")
            self._evidence_owner(tx, organisation_id, attachment["owner_type"], attachment["owner_id"])
        try:
            content = Path(attachment["storage_path"]).read_bytes()
        except OSError:
            raise KeyError("Attachment file not found") from None
        if sha256_bytes(content) != attachment["sha256"] or len(content) != attachment["size_bytes"]:
            raise ValueError("Attachment integrity check failed")
        return attachment, content

    def invoice_pdf(self, invoice_id: str, tx=None) -> bytes:
        from reportlab.lib.colors import Color, HexColor
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.utils import ImageReader, simpleSplit
        from reportlab.pdfgen.canvas import Canvas
        from document_settings import DocumentSettingsService
        from organisations import OrganisationService

        if tx is None:
            with self.db.transaction() as owned_tx:
                return self.invoice_pdf(invoice_id, tx=owned_tx)
        invoice = self.invoice(invoice_id, tx=tx)
        oid = invoice['organisation_id']
        organisation = tx.one("SELECT * FROM organisations WHERE id=?", (oid,)) or {}
        settings = OrganisationService(self.db).document_settings(oid, tx=tx)
        output = BytesIO()
        canvas = Canvas(output, pagesize=A4, invariant=1)
        width, height = A4

        def footer():
            if not settings['footer_text']:
                return
            canvas.saveState()
            canvas.setFont('Helvetica', 7.5)
            canvas.setFillColor(Color(0.45, 0.45, 0.45))
            lines = simpleSplit(' '.join(settings['footer_text'].split()), 'Helvetica', 7.5, width - 84)
            for index, line in enumerate(lines):
                canvas.drawString(42, 40 + (len(lines) - index - 1) * 9, line)
            canvas.restoreState()

        canvas.setTitle(invoice.get("number") or "Draft invoice")
        canvas.setFont("Helvetica-Bold", 20)
        if settings['accent_colour']:
            canvas.saveState()
            canvas.setFillColor(HexColor(settings['accent_colour']))
        canvas.drawString(42, height - 55, "CREDIT NOTE" if invoice["document_type"] == "credit_note" else "INVOICE")
        if settings['accent_colour']:
            canvas.restoreState()
        if settings['logo_attachment_id']:
            try:
                attachment, content = DocumentSettingsService(self.db).logo(oid, tx=tx)
                if attachment['content_type'] in {'image/png', 'image/jpeg'}:
                    image = ImageReader(BytesIO(content))
                    image_width, image_height = image.getSize()
                    scale = min(140 / image_width, 40 / image_height)
                    logo_width, logo_height = image_width * scale, image_height * scale
                    canvas.drawImage(image, width - 42 - logo_width, height - 49,
                                     width=logo_width, height=logo_height, mask='auto')
            except Exception:
                pass
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
                footer()
                canvas.showPage(); y = height - 55
            canvas.drawString(42, y, str(line["description"])[:60])
            canvas.drawRightString(width - 220, y, str(line["quantity"]))
            canvas.drawRightString(width - 145, y, f"{money(line['net_amount']):.2f}")
            canvas.drawRightString(width - 90, y, f"{money(line['tax_amount']):.2f}")
            canvas.drawRightString(width - 42, y, f"{money(line['gross_amount']):.2f}")
        y -= 35
        canvas.setFont("Helvetica-Bold", 11)
        canvas.drawRightString(width - 42, y, f"Total {invoice['currency']} {money(invoice['total']):.2f}")
        footer()
        canvas.save()
        return output.getvalue()

    def invoice_xml(self, invoice_id: str) -> bytes:
        """Produce an Estonian-style 1.2 review export or generic XML elsewhere."""
        invoice = self.invoice(invoice_id)
        organisation = self.db.one("SELECT * FROM organisations WHERE id=?", (invoice["organisation_id"],)) or {}
        if invoice["status"] not in {"Issued", "Part Paid", "Paid"}:
            raise ValueError("Only issued invoices can be exported as XML")
        if organisation.get("country_code") == "EE":
            contact = self.db.one(
                "SELECT * FROM contacts WHERE id=? AND organisation_id=?",
                (invoice["contact_id"], invoice["organisation_id"])) or {}
            bank_account = self.db.one(
                "SELECT * FROM bank_accounts WHERE organisation_id=? AND active=1 "
                "AND iban IS NOT NULL AND TRIM(iban)<>'' ORDER BY name,id LIMIT 1",
                (invoice["organisation_id"],))
            return einvoice.e_arve_xml(organisation, contact, invoice, bank_account)
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

    def invoice_deliveries(self, organisation_id, invoice_id):
        self.invoice(invoice_id, organisation_id)
        with self.db.transaction() as tx:
            return [{k: v for k, v in row.items() if k != 'request_key'}
                    for row in DeliveryRepository(tx, organisation_id).history(invoice_id)]

    def send_invoice_email(self, invoice_id: str, *, actor: str, client=None,
                           subject=None, text_body=None, organisation_id=None,
                           bulk=False, idempotency_key=None) -> dict:
        """Reserve evidence and audit before Postmark, then commit its outcome."""
        import httpx

        invoice = self.invoice(invoice_id, organisation_id)
        oid = invoice['organisation_id']
        request_key = sha256_bytes(f'{actor}:{idempotency_key}'.encode()) if idempotency_key else None
        attachment = None
        new_attachment = False
        try:
            with self.db.transaction() as tx:
                repo = DeliveryRepository(tx, oid)
                repo.lock()
                if request_key:
                    previous = next((row for row in repo.history(invoice_id)
                                     if row['request_key'] == request_key), None)
                    if previous:
                        if previous['status'] != 'Sent':
                            raise InvoiceDeliveryFailed(previous)
                        return previous
                # Re-read under the reservation lock so payment/status changes are
                # reflected before reserving a new send.
                invoice = tx.one(
                    'SELECT i.*,c.email contact_email FROM invoices i JOIN contacts c '
                    'ON c.id=i.contact_id AND c.organisation_id=i.organisation_id '
                    'WHERE i.id=? AND i.organisation_id=?', (invoice_id, oid))
                if not invoice:
                    raise KeyError('Invoice not found')
                if bulk and invoice['document_type'] != 'invoice':
                    raise ValueError('Only sales invoices can be sent in bulk')
                allowed = {'Issued', 'Part Paid'} if bulk else {'Issued', 'Part Paid', 'Paid'}
                if invoice['status'] not in allowed:
                    raise ValueError('Only Issued or Part Paid invoices can be sent in bulk' if bulk
                                     else 'Only issued invoices can be emailed')
                recipient = (invoice.get('contact_email') or '').strip()
                if not recipient:
                    raise ValueError('Contact has no email address')
                token = os.getenv('POSTMARK_API_TOKEN', '').strip()
                from_email = os.getenv('FROM_EMAIL', '').strip()
                if not token or not from_email:
                    raise RuntimeError('Email delivery is not connected')
                organisation = tx.one('SELECT * FROM organisations WHERE id=?', (oid,)) or {}
                pdf = self.invoice_pdf(invoice_id, tx=tx)
                attachment = tx.one(
                    "SELECT * FROM attachments WHERE organisation_id=? AND owner_type='invoice' AND owner_id=? AND sha256=?",
                    (oid, invoice_id, sha256_bytes(pdf)))
                if not attachment:
                    attachment = self.attach_evidence(
                        oid, owner_type='invoice', owner_id=invoice_id,
                        filename=f"{invoice['number']}.pdf", content_type='application/pdf',
                        content=pdf, actor=actor, tx=tx)
                    new_attachment = True
                delivery_id = repo.reserve(invoice, recipient, actor, attachment['id'], request_key)
        except Exception:
            if new_attachment:
                Path(attachment['storage_path']).unlink(missing_ok=True)
            raise
        payload = {
            'From': from_email, 'To': recipient,
            'Subject': subject if subject is not None else f"Invoice {invoice['number']} from {organisation.get('name', 'FastAccounts')}",
            'TextBody': text_body if text_body is not None else f"Please find invoice {invoice['number']} for {invoice['currency']} {money(invoice['total']):.2f} attached.",
            'MessageStream': 'outbound',
            'Attachments': [{'Name': f"{invoice['number']}.pdf", 'Content': base64.b64encode(pdf).decode(),
                             'ContentType': 'application/pdf'}],
        }
        http = client or httpx.Client(timeout=20)
        try:
            response = http.post('https://api.postmarkapp.com/email', json=payload,
                                 headers={'X-Postmark-Server-Token': token, 'Accept': 'application/json'})
            response.raise_for_status()
            result = response.json()
            if result.get('ErrorCode', 0):
                raise RuntimeError(result.get('Message') or 'Email provider rejected the message')
            status, provider_id, error = 'Sent', result.get('MessageID'), None
        except Exception as exc:
            status, provider_id, error = 'Failed', None, str(exc)[:500]
        finally:
            if client is None:
                http.close()
        with self.db.transaction() as tx:
            repo = DeliveryRepository(tx, oid)
            repo.finish(delivery_id, invoice_id, actor, status, recipient, attachment['id'],
                        request_key, provider_id, error)
            delivery = next(row for row in repo.history(invoice_id) if row['id'] == delivery_id)
        if status == 'Failed':
            raise InvoiceDeliveryFailed(delivery)
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

    from web import i18n
    from payroll import SOCIAL_TAX_MINIMUM_EXEMPTION_LABELS
    def catalogue(key):
        return text(i18n.catalog('et' if ee else 'en')['workspace'].get(key, key))

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
        (None, 'Social tax base', 'social_tax_base'),
        (None, 'Social tax minimum top-up', 'social_tax_minimum_topup'),
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
        if item.get('pay_basis') == 'hourly' and item.get('hours') is not None:
            details.append(f"{catalogue('Hourly rate')}: {item['hourly_rate']} EUR × {item['hours']} {catalogue('Hours').lower()}")
        if item.get('pay_basis') == 'monthly' and item.get('worked_days') is not None:
            details.append(f"{catalogue('Worked days / norm days')}: {item['worked_days']} / {item['norm_days']}")
        if item.get('fte') not in (None, '1'):
            details.append(f"{catalogue('Work-time fraction (FTE)')}: {item['fte']}")
        reason = item.get('social_tax_minimum_exemption')
        if reason in SOCIAL_TAX_MINIMUM_EXEMPTION_LABELS:
            details.append(f"{catalogue('Social tax minimum exemption')}: {catalogue(SOCIAL_TAX_MINIMUM_EXEMPTION_LABELS[reason])}")
        for detail in details:
            for line in simpleSplit(text(detail), regular, 11, width-84):
                canvas.drawString(42, y, line)
                y -= 16
        y -= 24
        for et, en, key in rows:
            if key == 'social_tax_minimum_topup' and not money(item.get(key)):
                continue
            canvas.setFont(bold if key in ('net', 'employer_cost', 'withholding_total') else regular, 11)
            canvas.drawString(42, y, catalogue(en) if et is None else label(et, en))
            canvas.drawRightString(width-42, y, f"{money(item.get(key)):.2f}")
            y -= 26
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
    # Keep the first page per employee stable for existing payslip download links.
    from payroll_components import FLAGS, FLAG_LABELS
    for item in run['items']:
        if not item.get('components'):
            continue
        y = 0
        for component in item['components']:
            lines = simpleSplit(catalogue(component['name']), regular, 11, width-235)
            flags = ', '.join(catalogue(label) for key, label in zip(FLAGS, FLAG_LABELS) if component[key])
            detail = catalogue('Income' if component['direction'] == 'income' else 'Deduction') + ': ' + (flags or catalogue('No levies'))
            details = simpleSplit(detail, regular, 9, width-84)
            if y < 70 + 16 * (len(lines) + len(details)):
                if y:
                    canvas.showPage()
                canvas.setFont(bold, 16)
                canvas.drawString(42, height-50, catalogue('Payment components') + ' ' + run['period'])
                canvas.setFont(regular, 11)
                y = height-75
                for name_line in simpleSplit(text(item['employee_name']), regular, 11, width-84):
                    canvas.drawString(42, y, name_line)
                    y -= 16
                y -= 19
            canvas.setFont(regular, 11)
            canvas.drawRightString(width-42, y, f"{money(component['amount']):.2f} EUR")
            for line in lines:
                canvas.drawString(42, y, line)
                y -= 16
            canvas.setFont(regular, 9)
            for line in details:
                canvas.drawString(42, y, line)
                y -= 14
            y -= 14
        canvas.showPage()
    canvas.save()
    return output.getvalue()
