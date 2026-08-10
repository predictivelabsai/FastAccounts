"""Accountant-reviewed UK VAT and Estonian KMD workpapers and exports."""
from __future__ import annotations

import csv
import io
import json
from decimal import Decimal

from core_utils import audit, canonical_json, db_number, money, new_id, utc_now
from database import Database, get_database


class TaxService:
    def __init__(self, db: Database | None = None):
        self.db = db or get_database()

    def prepare(self, organisation_id: str, *, period_start: str, period_end: str,
                basis: str = "accrual") -> dict:
        if basis not in {"accrual", "cash"}:
            raise ValueError("VAT basis must be accrual or cash")
        organisation = self.db.one("SELECT * FROM organisations WHERE id=?", (organisation_id,))
        if not organisation:
            raise KeyError("Organisation not found")
        country = organisation["country_code"]
        sales = self.db.rows(
            "SELECT i.id,i.number,i.document_type,i.issue_date document_date,i.subtotal,i.tax_total,i.total,i.paid_total,c.name contact_name "
            "FROM invoices i JOIN contacts c ON c.id=i.contact_id WHERE i.organisation_id=? "
            "AND i.status IN ('Issued','Part Paid','Paid','Credited') AND i.tax_point_date BETWEEN ? AND ?",
            (organisation_id, period_start, period_end),
        )
        purchases = self.db.rows(
            "SELECT b.id,b.supplier_number number,b.document_type,b.bill_date document_date,b.subtotal,b.tax_total,b.total,b.paid_total,c.name contact_name,"
            "COALESCE((SELECT SUM(recoverable_tax) FROM bill_lines bl WHERE bl.bill_id=b.id),0) recoverable_tax "
            "FROM bills b JOIN contacts c ON c.id=b.contact_id WHERE b.organisation_id=? "
            "AND b.status IN ('Approved','Part Paid','Paid') AND b.bill_date BETWEEN ? AND ?",
            (organisation_id, period_start, period_end),
        )
        sales_lines = self.db.rows(
            "SELECT i.id document_id,i.document_type,i.total,i.paid_total,l.net_amount,l.tax_amount,l.tax_rate,"
            "COALESCE(t.kind,'out_of_scope') tax_kind FROM invoice_lines l JOIN invoices i ON i.id=l.invoice_id "
            "LEFT JOIN tax_codes t ON t.id=l.tax_code_id WHERE i.organisation_id=? "
            "AND i.status IN ('Issued','Part Paid','Paid','Credited') AND i.tax_point_date BETWEEN ? AND ?",
            (organisation_id, period_start, period_end),
        )
        purchase_lines = self.db.rows(
            "SELECT b.id document_id,b.document_type,b.total,b.paid_total,l.net_amount,l.tax_amount,l.recoverable_tax,l.tax_rate,"
            "COALESCE(t.kind,'out_of_scope') tax_kind FROM bill_lines l JOIN bills b ON b.id=l.bill_id "
            "LEFT JOIN tax_codes t ON t.id=l.tax_code_id WHERE b.organisation_id=? "
            "AND b.status IN ('Approved','Part Paid','Paid') AND b.bill_date BETWEEN ? AND ?",
            (organisation_id, period_start, period_end),
        )

        def weighted(row: dict, field: str, credit_type: str) -> Decimal:
            sign = Decimal("-1") if row["document_type"] == credit_type else Decimal("1")
            ratio = Decimal("1")
            if basis == "cash":
                total = money(row["total"])
                ratio = min(Decimal("1"), money(row["paid_total"]) / total) if total else Decimal("0")
            return money(sign * money(row[field]) * ratio)

        output_tax = sum((weighted(r, "tax_amount", "credit_note") for r in sales_lines), Decimal("0"))
        input_tax = sum((weighted(r, "recoverable_tax", "supplier_credit") for r in purchase_lines), Decimal("0"))
        reverse_output = sum((weighted(r, "tax_amount", "supplier_credit") for r in purchase_lines if r["tax_kind"] == "reverse_charge"), Decimal("0"))
        output_tax += reverse_output
        sales_net = sum((weighted(r, "net_amount", "credit_note") for r in sales_lines if r["tax_kind"] != "out_of_scope"), Decimal("0"))
        purchase_net = sum((weighted(r, "net_amount", "supplier_credit") for r in purchase_lines if r["tax_kind"] != "out_of_scope"), Decimal("0"))
        if country == "UK":
            boxes = {
                "box1_vat_due_sales": money(output_tax), "box2_vat_due_acquisitions": money(0),
                "box3_total_vat_due": money(output_tax), "box4_vat_reclaimed": money(input_tax),
                "box5_net_vat_due": money(abs(output_tax - input_tax)),
                "box6_total_sales_ex_vat": money(sales_net), "box7_total_purchases_ex_vat": money(purchase_net),
                "box8_goods_to_eu": money(0), "box9_goods_from_eu": money(0),
            }
        else:
            standard_supply = sum((weighted(r, "net_amount", "credit_note") for r in sales_lines
                                   if money(r["tax_rate"]) == Decimal("24.00")), Decimal("0"))
            reduced_supply = sum((weighted(r, "net_amount", "credit_note") for r in sales_lines
                                  if money(r["tax_rate"]) in {Decimal("13.00"), Decimal("9.00")}), Decimal("0"))
            zero_supply = sum((weighted(r, "net_amount", "credit_note") for r in sales_lines
                               if r["tax_kind"] == "zero"), Decimal("0"))
            boxes = {
                "kmd_1_taxable_supply_24": money(standard_supply),
                "kmd_2_reduced_rate_supply": money(reduced_supply), "kmd_3_zero_rate_supply": money(zero_supply),
                "kmd_4_output_vat": money(output_tax), "kmd_5_input_vat": money(input_tax),
                "kmd_12_vat_payable": money(output_tax - input_tax),
            }
        existing = self.db.one(
            "SELECT id FROM vat_returns WHERE organisation_id=? AND country_code=? AND period_start=? AND period_end=? AND basis=?",
            (organisation_id, country, period_start, period_end, basis),
        )
        return_id = existing["id"] if existing else new_id()
        with self.db.transaction() as tx:
            if existing:
                tx.execute("UPDATE vat_returns SET boxes_json=?,status='Draft',reviewed_by=NULL,reviewed_at=NULL WHERE id=?",
                           (canonical_json(boxes), return_id))
            else:
                tx.execute(
                    "INSERT INTO vat_returns(id,organisation_id,country_code,period_start,period_end,basis,status,boxes_json,created_at) "
                    "VALUES (?,?,?,?,?,?,'Draft',?,?)",
                    (return_id, organisation_id, country, period_start, period_end, basis,
                     canonical_json(boxes), utc_now()),
                )
        return {"id": return_id, "country_code": country, "period_start": period_start,
                "period_end": period_end, "basis": basis, "status": "Draft", "boxes": boxes,
                "sales": sales, "purchases": purchases,
                "warnings": ["Cash-basis values are weighted by allocated payment and require accountant review"] if basis == "cash" else []}

    def get(self, return_id: str) -> dict:
        row = self.db.one("SELECT * FROM vat_returns WHERE id=?", (return_id,))
        if not row:
            raise KeyError("VAT return not found")
        row["boxes"] = json.loads(row["boxes_json"])
        return row

    def review(self, return_id: str, *, actor: str) -> dict:
        with self.db.transaction() as tx:
            row = tx.one("SELECT * FROM vat_returns WHERE id=?", (return_id,))
            if not row or row["status"] not in {"Draft", "Exported"}:
                raise ValueError("Only a draft/exported workpaper can be reviewed")
            now = utc_now()
            tx.execute("UPDATE vat_returns SET status='Reviewed',reviewed_by=?,reviewed_at=? WHERE id=?",
                       (actor, now, return_id))
            audit(tx, row["organisation_id"], actor, "tax.reviewed", "vat_return", return_id)
        return self.get(return_id)

    def export_csv(self, return_id: str, *, actor: str) -> bytes:
        row = self.get(return_id)
        if row["status"] != "Reviewed":
            raise ValueError("An accountant must review the workpaper before export")
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["field", "value"])
        for key, value in row["boxes"].items():
            writer.writerow([key, value])
        with self.db.transaction() as tx:
            tx.execute("UPDATE vat_returns SET status='Exported' WHERE id=?", (return_id,))
            tx.execute(
                "INSERT INTO filing_attempts(id,organisation_id,vat_return_id,provider,mode,status,message,created_by,created_at) "
                "VALUES (?,?,?,?,?,'Prepared',?,?,?)",
                (new_id(), row["organisation_id"], return_id,
                 "hmrc" if row["country_code"] == "UK" else "emta", "export",
                 "Accountant-reviewed CSV export; no direct filing occurred", actor, utc_now()),
            )
            audit(tx, row["organisation_id"], actor, "tax.exported", "vat_return", return_id,
                  {"format": "csv"})
        return output.getvalue().encode("utf-8")

    def plan_direct_filing(self, return_id: str, *, actor: str, mode: str = "stub") -> dict:
        row = self.get(return_id)
        if row["status"] not in {"Reviewed", "Exported"}:
            raise ValueError("Review is mandatory before creating a filing plan")
        attempt_id = new_id()
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO filing_attempts(id,organisation_id,vat_return_id,provider,mode,status,message,created_by,created_at) "
                "VALUES (?,?,?,?,?,'Planned',?,?,?)",
                (attempt_id, row["organisation_id"], return_id,
                 "hmrc" if row["country_code"] == "UK" else "emta", mode,
                 "Direct submission disabled pending provider approval, accountant UAT, and final confirmation UX",
                 actor, utc_now()),
            )
        return self.db.one("SELECT * FROM filing_attempts WHERE id=?", (attempt_id,)) or {}

    def prepare_estonian_vd(self, organisation_id: str, *, period_start: str,
                            period_end: str) -> dict:
        organisation = self.db.one("SELECT * FROM organisations WHERE id=?", (organisation_id,))
        if not organisation or organisation["country_code"] != "EE":
            raise ValueError("VD preparation is available only for Estonian organisations")
        rows = self.db.rows(
            "SELECT c.name,c.vat_no,c.country_code,i.number,i.tax_point_date,"
            "SUM(CASE WHEN i.document_type='credit_note' THEN -l.net_amount ELSE l.net_amount END) amount "
            "FROM invoice_lines l JOIN invoices i ON i.id=l.invoice_id JOIN contacts c ON c.id=i.contact_id "
            "JOIN tax_codes t ON t.id=l.tax_code_id WHERE i.organisation_id=? AND t.kind='intra_eu' "
            "AND i.status IN ('Issued','Part Paid','Paid','Credited') AND i.tax_point_date BETWEEN ? AND ? "
            "GROUP BY c.id,c.name,c.vat_no,c.country_code,i.id,i.number,i.tax_point_date ORDER BY c.name,i.number",
            (organisation_id, period_start, period_end),
        )
        warnings = []
        for row in rows:
            row["amount"] = money(row["amount"])
            if not row.get("vat_no"):
                warnings.append(f"{row['name']} is missing an EU VAT number")
        return {"country_code": "EE", "declaration": "VD", "period_start": period_start,
                "period_end": period_end, "rows": rows, "warnings": warnings,
                "status": "Prepared for accountant review"}
