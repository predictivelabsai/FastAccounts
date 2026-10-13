"""Estonian e-arve 1.2 review exports and declaration-checked purchase intake.

Not live-verified against a schema/XSD; accountant review required. No operator
submission or external calls are performed. VAT groups use Decimal line totals.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
import re
from xml.etree import ElementTree as ET

from core_utils import decimal, money, new_id

# Not live-verified against a schema/XSD; accountant review required.


def _put(parent, tag, value):
    if value is not None and str(value).strip():
        ET.SubElement(parent, tag).text = str(value)


def _party(parent, tag, row):
    party = ET.SubElement(parent, tag)
    for name, key in (("Name", "name"), ("RegulatoryNumber", "registration_no"),
                      ("VATRegNumber", "vat_no")):
        _put(party, name, row.get(key))
    if row.get("email") or row.get("telephone") or row.get("phone") or row.get("address"):
        contact = ET.SubElement(party, "ContactData")
        _put(contact, "TelephoneNumber", row.get("telephone") or row.get("phone"))
        _put(contact, "EmailAddress", row.get("email"))
        if row.get("address"):
            postal = ET.SubElement(contact, "PostalAddress")
            _put(postal, "PostalAddress1", row["address"])
            _put(postal, "Country", row.get("country_code"))
    _put(party, "PaymentRefNumber", row.get("payment_reference") or row.get("reference"))


def _vat(parent, net, rate, tax, gross):
    vat = ET.SubElement(parent, "VAT")
    for tag, value in (("SumBeforeVAT", net), ("VATRate", rate),
                       ("VATSum", tax), ("SumAfterVAT", gross)):
        _put(vat, tag, value)


def e_arve_xml(organisation: dict, contact: dict, invoice: dict,
               bank_account: dict | None) -> bytes:
    """Write one e-arve document, retaining the supplied booked line amounts."""
    root = ET.Element("E_Invoice")
    header = ET.SubElement(root, "Header")
    _put(header, "Date", date.today().isoformat())
    _put(header, "FileId", new_id())
    _put(header, "Version", "1.2")
    document = ET.SubElement(root, "Invoice", invoiceId=str(invoice["number"]),
                             regNumber=str(contact.get("registration_no") or ""),
                             sellerRegNumber=str(organisation.get("registration_no") or ""))
    parties = ET.SubElement(document, "InvoiceParties")
    _party(parties, "SellerParty", organisation)
    _party(parties, "BuyerParty", contact)
    information = ET.SubElement(document, "InvoiceInformation")
    is_credit = invoice.get("document_type") == "credit_note"
    ET.SubElement(information, "Type", type="CRE" if is_credit else "DEB")
    _put(information, "DocumentName", "Credit note" if is_credit else "Invoice")
    _put(information, "InvoiceNumber", invoice["number"])
    _put(information, "InvoiceDate", invoice["issue_date"])
    _put(information, "DueDate", invoice.get("due_date"))
    groups = defaultdict(lambda: [money(0), money(0), money(0)])
    summary = ET.SubElement(document, "InvoiceSumGroup")
    items = ET.SubElement(document, "InvoiceItem")
    group = ET.SubElement(items, "InvoiceItemGroup")
    for line in invoice["lines"]:
        entry = ET.SubElement(group, "ItemEntry")
        _put(entry, "ItemDescription", line["description"])
        detail = ET.SubElement(entry, "ItemDetailInfo")
        _put(detail, "ItemUnit", line.get("unit") or "tk")
        _put(detail, "ItemAmount", line.get("quantity"))
        net, tax, gross = (money(line[key]) for key in ("net_amount", "tax_amount", "gross_amount"))
        price = decimal(line["unit_price"])
        if invoice.get("line_amount_type") == "inclusive" and line.get("quantity"):
            price = net / decimal(line["quantity"])
        _put(detail, "ItemPrice", price)
        rate = decimal(line["tax_rate"]) if invoice.get("line_amount_type") != "no_tax" else Decimal(0)
        _put(entry, "ItemSum", net)
        _vat(entry, net, rate, tax, gross)
        _put(entry, "ItemTotalSum", gross)
        for index, amount in enumerate((net, tax, gross)):
            groups[rate][index] += amount
    net = money(sum((amounts[0] for amounts in groups.values()), Decimal(0)))
    tax = money(sum((amounts[1] for amounts in groups.values()), Decimal(0)))
    gross = money(net + tax)
    _put(summary, "InvoiceSum", net)
    for rate, amounts in sorted(groups.items()):
        _vat(summary, amounts[0], rate, amounts[1], amounts[2])
    _put(summary, "TotalVATSum", tax)
    _put(summary, "TotalSum", gross)
    _put(summary, "Currency", invoice.get("currency") or "EUR")
    if bank_account and bank_account.get("iban"):
        payment = ET.SubElement(document, "PaymentInfo")
        _put(payment, "Currency", invoice.get("currency") or "EUR")
        _put(payment, "PaymentDescription", invoice["number"])
        _put(payment, "Payable", "YES")
        _put(payment, "PaymentTotalSum", gross)
        _put(payment, "PaymentDueDate", invoice.get("due_date"))
        _put(payment, "PaymentReferenceNumber", invoice.get("reference") or contact.get("payment_reference") or contact.get("reference"))
        _put(payment, "PaymentId", invoice["number"])
        _put(payment, "PayToAccount", bank_account["iban"])
        _put(payment, "PayToName", organisation["name"])
    footer = ET.SubElement(root, "Footer")
    _put(footer, "TotalNumberInvoices", 1)
    _put(footer, "TotalAmount", gross)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _find(node, *paths):
    if node is None:
        return None
    for path in paths:
        element = node.find("/".join("{*}" + part for part in path.split("/")))
        if element is not None and element.text and element.text.strip():
            return element.text.strip()
    return None


def _number(value, label):
    try:
        result = decimal(value)
        if not result.is_finite():
            raise InvalidOperation
        return result
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid e-invoice number for {label}") from exc


def _check(label, declared, expected):
    difference = money(declared) - money(expected)
    if difference:
        raise ValueError(f"E-invoice {label} mismatch: difference {difference:.2f}")


def parse_purchase(content: bytes) -> dict:
    """Turn malformed or unrepresentable monetary input into an intake error."""
    try:
        return _parse_purchase(content)
    except (InvalidOperation, OverflowError) as exc:
        raise ValueError("Invalid or unrepresentable e-invoice monetary amount") from exc


def _parse_purchase(content: bytes) -> dict:
    """Parse exactly one namespace-independent invoice without losing declarations."""
    markup = content.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in markup or b"<!ENTITY" in markup:
        raise ValueError("E-invoice XML must not contain a DTD or entities")
    try:
        root = ET.fromstring(content)
    except (ET.ParseError, ValueError) as exc:
        raise ValueError("Invalid e-invoice XML") from exc
    tag = root.tag.split("}")[-1]
    if tag == "Invoice":
        document = root
    elif tag == "E_Invoice":
        documents = root.findall("{*}Invoice")
        if len(documents) != 1:
            raise ValueError("Import requires exactly one e-arve Invoice per file")
        document = documents[0]
    else:
        raise ValueError("XML is not a recognisable Estonian e-arve invoice")
    document_type = document.find("{*}InvoiceInformation/{*}Type")
    if document_type is not None and document_type.get("type") == "CRE":
        raise ValueError("Purchase credit notes require a supplier credit workflow")
    seller = document.find("{*}InvoiceParties/{*}SellerParty")
    number = _find(document, "InvoiceInformation/InvoiceNumber", "InvoiceNumber") or document.get("invoiceId")
    invoice_date = _find(document, "InvoiceInformation/InvoiceDate", "InvoiceDate")
    entries = document.findall("{*}InvoiceItem/{*}InvoiceItemGroup/{*}ItemEntry")
    if seller is None or not _find(seller, "Name") or not number or not invoice_date or not entries:
        raise ValueError("XML is not a recognisable e-arve invoice: seller, number, date and items are required")
    due_date = _find(document, "InvoiceInformation/DueDate", "DueDate", "PaymentInfo/PaymentDueDate") or invoice_date
    try:
        date.fromisoformat(invoice_date)
        date.fromisoformat(due_date)
    except ValueError as exc:
        raise ValueError("Invalid e-invoice invoice date or due date") from exc
    items = []
    groups = defaultdict(lambda: [money(0), money(0), money(0)])
    for index, entry in enumerate(entries, 1):
        label = f"item {index}"
        quantity = _number(_find(entry, "ItemDetailInfo/ItemAmount", "ItemQuantity", "ItemAmount") or "1", label + " quantity")
        price_text = _find(entry, "ItemDetailInfo/ItemPrice", "ItemPrice")
        net_text = _find(entry, "ItemSum", "VAT/SumBeforeVAT")
        if net_text is None and price_text is None:
            raise ValueError(f"E-invoice {label} requires ItemSum or ItemPrice")
        net = money(_number(net_text, label + " net")) if net_text is not None else money(_number(price_text, label + " price") * quantity)
        rate = _number(_find(entry, "VAT/VATRate", "ItemVatRate") or "0", label + " VAT rate")
        tax_text = _find(entry, "VAT/VATSum", "ItemVatSum")
        expected_tax = money(net * rate / Decimal(100))
        tax = money(_number(tax_text, label + " VAT")) if tax_text is not None else expected_tax
        gross_text = _find(entry, "ItemTotalSum", "VAT/SumAfterVAT")
        gross = money(_number(gross_text, label + " gross")) if gross_text is not None else money(net + tax)
        if quantity <= 0 or net < 0 or rate < 0:
            raise ValueError(f"E-invoice {label} quantity must be positive and amounts cannot be negative")
        if tax != expected_tax:
            inclusive_net = money(gross / (Decimal(1) + rate / Decimal(100)))
            inclusive_tax = money(gross - inclusive_net)
            if net != inclusive_net or tax != inclusive_tax:
                _check(label + " VAT", tax, expected_tax)
        _check(label + " gross", gross, net + tax)
        for path, expected in (("VAT/SumBeforeVAT", net), ("VAT/SumAfterVAT", gross)):
            declaration = _find(entry, path)
            if declaration is not None:
                _check(label + " " + path, _number(declaration, label), expected)
        price = _number(price_text, label + " price") if price_text is not None else net / quantity
        _check(label + " price × quantity", price * quantity, net)
        aliases = (
            (("ItemDetailInfo/ItemAmount", "ItemQuantity", "ItemAmount"), quantity, False),
            (("ItemDetailInfo/ItemPrice", "ItemPrice"), price, False),
            (("ItemSum", "VAT/SumBeforeVAT"), net, True),
            (("VAT/VATRate", "ItemVatRate"), rate, False),
            (("VAT/VATSum", "ItemVatSum"), tax, True),
            (("ItemTotalSum", "VAT/SumAfterVAT"), gross, True),
        )
        for paths, expected, monetary in aliases:
            for path in paths:
                value = _find(entry, path)
                if value is not None:
                    declared = _number(value, label + " " + path)
                    if monetary:
                        _check(label + " " + path, declared, expected)
                    elif declared != expected:
                        raise ValueError(f"E-invoice {label} {path} mismatch: difference {declared - expected}")
        items.append(dict(description=_find(entry, "ItemDescription") or "Item", price=price,
                          unit_price=price, amount=quantity, quantity=quantity, vat_rate=rate,
                          net_amount=net, tax_amount=tax, gross_amount=gross))
        for idx, amount in enumerate((net, tax, gross)):
            groups[rate][idx] += amount
    totals = {key: money(sum((amounts[index] for amounts in groups.values()), Decimal(0)))
              for index, key in enumerate(("net", "vat", "gross"))}
    summaries = document.findall("{*}InvoiceSumGroup")
    for key, paths in (("net", ("InvoiceSum",)), ("vat", ("TotalVATSum", "TotalTaxSum", "VatSum", "TaxSum")),
                       ("gross", ("TotalSum", "InvoiceSumVAT"))):
        for path in paths:
            declarations = [_find(summary, path) for summary in summaries]
            if any(value is not None for value in declarations):
                if any(value is None for value in declarations):
                    raise ValueError(f"E-invoice {key} declaration missing from an InvoiceSumGroup")
                _check("declared " + key, sum((_number(value, key) for value in declarations), Decimal(0)), totals[key])
    declared_groups = defaultdict(lambda: [money(0), money(0), money(0)])
    for summary in summaries:
        for vat in summary.findall("{*}VAT"):
            rate = _number(_find(vat, "VATRate") or "0", "VAT group rate")
            expected = groups.get(rate)
            if expected is None:
                raise ValueError(f"E-invoice VAT group has no items at rate {rate}")
            for idx, path in enumerate(("SumBeforeVAT", "VATSum", "SumAfterVAT")):
                value = _find(vat, path)
                if value is None:
                    raise ValueError(f"E-invoice VAT group requires {path}")
                declared_groups[rate][idx] += _number(value, path)
    if declared_groups:
        if set(declared_groups) != set(groups):
            raise ValueError("E-invoice declared VAT groups do not match item VAT rates")
        for rate, amounts in declared_groups.items():
            for idx, key in enumerate(("net", "vat", "gross")):
                _check(f"VAT group {rate} {key}", amounts[idx], groups[rate][idx])
    payment_total = _find(document, "PaymentInfo/PaymentTotalSum")
    if payment_total is not None:
        _check("payment gross", _number(payment_total, "payment gross"), totals["gross"])
    currency = _find(document, "InvoiceSumGroup/Currency", "Currency", "PaymentInfo/Currency") or "EUR"
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("E-invoice currency must be a three-letter uppercase code")
    return dict(seller=dict(name=_find(seller, "Name"), registration_no=_find(seller, "RegulatoryNumber") or "",
                            vat_no=_find(seller, "VATRegNumber") or "", email=_find(seller, "ContactData/EmailAddress") or "",
                            address=_find(seller, "ContactData/PostalAddress/PostalAddress1") or "",
                            country_code=_find(seller, "ContactData/PostalAddress/Country") or ""),
                buyer_reference=_find(document, "InvoiceParties/BuyerParty/PaymentRefNumber", "PaymentInfo/PaymentReferenceNumber") or "",
                invoice_number=number, invoice_date=invoice_date, due_date=due_date,
                currency=currency,
                items=items, totals=totals)
