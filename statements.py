"""Contact statements from immutable receivable and payable ledger movements."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO
import re
from xml.sax.saxutils import escape

from core_utils import decimal, money
from database import Database, get_database
from documents import locate_pdf_font


class StatementService:
    def __init__(self, db: Database | None = None):
        self.db = db or get_database()

    def statement(self, organisation_id: str, contact_id: str, *, date_from: str,
                  date_to: str, side: str = "customer", eur_rate: object | None = None) -> dict:
        """Opening excludes date_from; movements include both range endpoints.

        Customer debts and supplier liabilities are positive on their respective
        statements. EUR conversion is presentation only, using an explicit rate
        per unit of organisation base currency when that currency is not EUR.
        Transaction currencies are never added together.
        """
        try:
            start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
        except (TypeError, ValueError):
            raise ValueError("Statement dates must be ISO dates") from None
        if start > end:
            raise ValueError("Statement start must be on or before its end")
        if side not in {"customer", "supplier"}:
            raise ValueError("Statement side must be customer or supplier")
        with self.db.transaction() as tx:
            organisation = tx.one("SELECT * FROM organisations WHERE id=?", (organisation_id,))
            contact = tx.one("SELECT * FROM contacts WHERE organisation_id=? AND id=?",
                             (organisation_id, contact_id))
            if not organisation or not contact:
                raise KeyError("Contact not found")
            try:
                rate = Decimal("1") if organisation["base_currency"] == "EUR" else decimal(eur_rate)
                if not rate.is_finite() or rate <= 0:
                    raise ValueError("A positive base-currency-to-EUR presentation rate is required")
            except (InvalidOperation, TypeError):
                raise ValueError("Invalid EUR presentation rate") from None
            entries = tx.rows(
                "SELECT g.*,p.voucher_code,p.voucher_type FROM gl_entries g "
                "JOIN accounts a ON a.id=g.account_id AND a.organisation_id=g.organisation_id "
                "JOIN posting_batches p ON p.id=g.posting_batch_id AND p.organisation_id=g.organisation_id "
                "WHERE g.organisation_id=? AND g.contact_id=? AND a.system_role=? "
                "AND g.entry_date<=? AND p.status IN ('Posted','Reversed') "
                "ORDER BY g.entry_date,p.created_at,p.id,g.line_number,g.id",
                (organisation_id, contact_id, "AR" if side == "customer" else "AP", end.isoformat()))
        sign = Decimal("1") if side == "customer" else Decimal("-1")
        opening, balance = Decimal("0"), Decimal("0")
        eur_opening, eur_balance = Decimal("0"), Decimal("0")
        currency_opening = defaultdict(lambda: Decimal("0"))
        currency_balances = defaultdict(lambda: Decimal("0"))
        movements = []
        for entry in entries:
            amount = money(sign * (decimal(entry["debit"]) - decimal(entry["credit"])))
            eur_amount = money(amount * rate)
            currency = entry["transaction_currency"]
            transaction_amount = money(sign * decimal(entry["transaction_amount"]))
            balance += amount
            eur_balance += eur_amount
            currency_balances[currency] += transaction_amount
            if entry["entry_date"] < start.isoformat():
                opening += amount
                eur_opening += eur_amount
                currency_opening[currency] += transaction_amount
                continue
            movements.append({"date": entry["entry_date"], "entry_id": entry["id"],
                "document_number": entry["voucher_code"], "description": entry["memo"],
                "voucher_type": entry["voucher_type"], "debit": money(entry["debit"]),
                "credit": money(entry["credit"]), "amount": amount, "balance": money(balance),
                "eur_amount": eur_amount, "eur_balance": money(eur_balance),
                "currency": currency, "transaction_amount": transaction_amount,
                "transaction_balance": money(currency_balances[currency])})
        return {"organisation": organisation, "contact": contact, "side": side,
            "date_from": start.isoformat(), "date_to": end.isoformat(),
            "base_currency": organisation["base_currency"], "eur_rate": rate,
            "opening_balance": money(opening), "closing_balance": money(balance),
            "eur_opening_balance": money(eur_opening), "eur_closing_balance": money(eur_balance),
            "currencies": {currency: {"opening_balance": money(currency_opening[currency]),
                "closing_balance": money(value)} for currency, value in sorted(currency_balances.items())},
            "movements": movements}

    @staticmethod
    def filename(statement: dict) -> str:
        contact = re.sub(r"[^a-zA-Z0-9_-]+", "-", statement["contact"]["name"]).strip("-")[:60]
        return f"statement-{contact or statement['contact']['id']}-{statement['date_from']}-{statement['date_to']}.pdf"

    @staticmethod
    def pdf(statement: dict) -> bytes:
        """Render Unicode labels and wrapped, paginated statement tables."""
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        regular, bold = "Helvetica", "Helvetica-Bold"
        font = locate_pdf_font()
        if font:
            regular, bold = "StatementUnicode", "StatementUnicodeBold"
            pdfmetrics.registerFont(TTFont(regular, str(font)))
            pdfmetrics.registerFont(TTFont(bold, str(locate_pdf_font(True) or font)))
        ee = statement["organisation"]["country_code"] == "EE"
        def label(et, en):
            return et if ee else en
        styles = getSampleStyleSheet()
        for style in styles.byName.values():
            style.fontName = regular
        styles["Title"].fontName = bold
        styles["BodyText"].fontSize = 8
        styles["BodyText"].leading = 11
        def paragraph(value):
            return Paragraph(escape(str(value)), styles["BodyText"])
        title = label("SALDOTEATIS", "STATEMENT OF ACCOUNT")
        story = [Paragraph(title, styles["Title"])]
        for value in (statement["organisation"]["name"], statement["contact"]["name"],
                      label("Klient", "Customer") if statement["side"] == "customer" else label("Tarnija", "Supplier"),
                      f"{statement['date_from']} / {statement['date_to']}",
                      f"{label('EUR esitluskurss', 'EUR presentation rate')}: {statement['eur_rate']} EUR / {statement['base_currency']}"):
            story.append(paragraph(value))
        story.append(Spacer(1, 14))
        opening_label = label("Algsaldo", "Opening balance")
        closing_label = label("Lõppsaldo", "Closing balance")
        headers = [label("Kuupäev", "Date"), label("Dokument / kirjeldus", "Document / description"),
                   label("Valuuta", "Currency"), label("Summa", "Amount"), label("Saldo", "Balance"),
                   label("Summa EUR", "Amount EUR"), label("Saldo EUR", "Balance EUR")]
        rows = [[paragraph(x) for x in headers],
                ["", paragraph(opening_label), "EUR", "", "", "", f"{statement['eur_opening_balance']:.2f}"]]
        for currency, balances in statement["currencies"].items():
            rows.append(["", paragraph(opening_label), currency, "", f"{balances['opening_balance']:.2f}", "", ""])
        for item in statement["movements"]:
            rows.append([item["date"], paragraph(f"{item['document_number']} / {item['description']}"),
                         item["currency"], f"{item['transaction_amount']:.2f}", f"{item['transaction_balance']:.2f}",
                         f"{item['eur_amount']:.2f}", f"{item['eur_balance']:.2f}"])
        for currency, balances in statement["currencies"].items():
            rows.append(["", paragraph(closing_label), currency, "", f"{balances['closing_balance']:.2f}", "", ""])
        rows.append(["", paragraph(closing_label), "EUR", "", "", "", f"{statement['eur_closing_balance']:.2f}"])
        table = Table(rows, colWidths=[65, 285, 50, 75, 75, 75, 75], repeatRows=1)
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), regular), ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.grey),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
        story.append(table)
        output = BytesIO()
        SimpleDocTemplate(output, pagesize=landscape(A4), rightMargin=42, leftMargin=42,
                          topMargin=42, bottomMargin=42, title=title).build(story)
        return output.getvalue()
