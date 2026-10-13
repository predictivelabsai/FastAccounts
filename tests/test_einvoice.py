"""Offline declaration and round-trip checks, not XSD certification."""
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from einvoice import e_arve_xml, parse_purchase


FIXTURES = Path(__file__).parent / "fixtures"


def writer_rows():
    organisation = dict(name="Synthetic Seller OÜ", registration_no="12345678", vat_no="EE101234567",
                        email="seller@example.test", address="Näidise tee 1", country_code="EE")
    contact = dict(name="Synthetic Buyer OÜ", registration_no="87654321", vat_no="EE108765432", reference="10013")
    invoice = dict(number="INV-000041", issue_date="2026-10-01", due_date="2026-10-15", currency="EUR",
                   reference="10013", lines=[
                       dict(description="Consulting", quantity="2", unit_price="50.00", tax_rate="24",
                            net_amount="100.00", tax_amount="24.00", gross_amount="124.00"),
                       dict(description="Book", quantity="3", unit_price="10.00", tax_rate="9",
                            net_amount="30.00", tax_amount="2.70", gross_amount="32.70"),
                       dict(description="Extra consulting", quantity="1", unit_price="0.03", tax_rate="24",
                            net_amount="0.03", tax_amount="0.01", gross_amount="0.04")])
    return organisation, contact, invoice


@pytest.mark.parametrize("filename", ["einvoicing_sale.xml", "einvoicing_purchase.xml"])
def test_realistic_two_rate_fixtures(filename):
    result = parse_purchase((FIXTURES / filename).read_bytes())
    assert result["seller"]["registration_no"]
    assert result["buyer_reference"] == "10013"
    assert result["totals"] == dict(net=Decimal("130.00"), vat=Decimal("26.70"), gross=Decimal("156.70"))
    assert {line["vat_rate"] for line in result["items"]} == {Decimal("24"), Decimal("9")}


def test_writer_round_trip_groups_and_payment():
    content = e_arve_xml(*writer_rows(), dict(iban="EE471000001020145685"))
    result = parse_purchase(content)
    assert result["totals"] == dict(net=Decimal("130.03"), vat=Decimal("26.71"), gross=Decimal("156.74"))
    assert result["invoice_number"] == "INV-000041"
    root = ET.fromstring(content)
    assert root.findtext("Header/Version") == "1.2"
    assert root.findtext("Invoice/PaymentInfo/PayToAccount") == "EE471000001020145685"
    groups = root.findall("Invoice/InvoiceSumGroup/VAT")
    assert len(groups) == 2
    assert {group.findtext("VATRate"): group.findtext("VATSum") for group in groups} == {"9": "2.70", "24": "24.01"}


def test_writer_bank_absent_and_foreign_currency():
    organisation, contact, invoice = writer_rows()
    invoice["currency"] = "GBP"
    content = e_arve_xml(organisation, contact, invoice, None)
    assert ET.fromstring(content).find("Invoice/PaymentInfo") is None
    assert parse_purchase(content)["currency"] == "GBP"


@pytest.mark.parametrize("old,new,label", [
    (b"<ItemTotalSum>124.00", b"<ItemTotalSum>124.01", "item 1 gross"),
    (b"<InvoiceSum>130.00", b"<InvoiceSum>130.01", "declared net"),
    (b"<TotalVATSum>26.70", b"<TotalVATSum>26.71", "declared vat"),
    (b"<TotalSum>156.70", b"<TotalSum>156.71", "declared gross"),
    (b"<VATSum>24.00", b"<VATSum>24.01", "VAT group 24 vat"),
    (b"<ItemPrice>50.00", b"<ItemPrice>50.01", "price × quantity"),
])
def test_reject_arithmetic_mismatches(old, new, label):
    content = (FIXTURES / "einvoicing_purchase.xml").read_bytes().replace(old, new, 1)
    with pytest.raises(ValueError, match=label + ".*difference"):
        parse_purchase(content)


@pytest.mark.parametrize("content", [b"garbage", b"<html/>", b"<Invoice/>",
                                      b'<!DOCTYPE Invoice [<!ENTITY x "bad">]><Invoice/>'])
def test_reject_non_invoice_or_unsafe_xml(content):
    with pytest.raises(ValueError):
        parse_purchase(content)


def test_reject_multi_invoice_file():
    root = ET.fromstring((FIXTURES / "einvoicing_purchase.xml").read_bytes())
    root.append(ET.fromstring(ET.tostring(root.find("Invoice"))))
    with pytest.raises(ValueError, match="exactly one"):
        parse_purchase(ET.tostring(root))


def test_line_totals_fallback_and_direct_tag_compatibility():
    root = ET.fromstring((FIXTURES / "einvoicing_purchase.xml").read_bytes())
    document = root.find("Invoice")
    document.remove(document.find("InvoiceSumGroup"))
    for entry in document.findall("InvoiceItem/InvoiceItemGroup/ItemEntry"):
        vat = entry.find("VAT")
        ET.SubElement(entry, "ItemVatRate").text = vat.findtext("VATRate")
        ET.SubElement(entry, "ItemVatSum").text = vat.findtext("VATSum")
        entry.remove(vat)
    assert parse_purchase(ET.tostring(root))["totals"]["gross"] == Decimal("156.70")


@pytest.mark.parametrize("value", [b"1e100", b"NaN", b"Infinity", b"invalid"])
def test_reject_unrepresentable_money(value):
    content = (FIXTURES / "einvoicing_purchase.xml").read_bytes().replace(b"<ItemSum>100.00", b"<ItemSum>" + value, 1)
    with pytest.raises(ValueError, match="Invalid"):
        parse_purchase(content)


def test_validate_conflicting_total_aliases():
    root = ET.fromstring((FIXTURES / "einvoicing_purchase.xml").read_bytes())
    ET.SubElement(root.find("Invoice/InvoiceSumGroup"), "InvoiceSumVAT").text = "156.71"
    with pytest.raises(ValueError, match="declared gross.*difference 0.01"):
        parse_purchase(ET.tostring(root))


def test_namespaced_single_invoice():
    root = ET.fromstring((FIXTURES / "einvoicing_purchase.xml").read_bytes())
    document = root.find("Invoice")
    for node in document.iter():
        node.tag = "{urn:synthetic:einvoice}" + node.tag
    result = parse_purchase(ET.tostring(document))
    assert result["invoice_number"] == "SUP-2026-0041"
    assert result["totals"]["gross"] == Decimal("156.70")


def test_item_vat_mismatch():
    root = ET.fromstring((FIXTURES / "einvoicing_purchase.xml").read_bytes())
    root.find("Invoice/InvoiceItem/InvoiceItemGroup/ItemEntry/VAT/VATSum").text = "24.01"
    with pytest.raises(ValueError, match="item 1 VAT.*difference 0.01"):
        parse_purchase(ET.tostring(root))


def test_purchase_credit_rejected():
    root = ET.fromstring((FIXTURES / "einvoicing_purchase.xml").read_bytes())
    root.find("Invoice/InvoiceInformation/Type").set("type", "CRE")
    with pytest.raises(ValueError, match="credit"):
        parse_purchase(ET.tostring(root))


def test_tax_inclusive_writer_emits_net_unit_price():
    organisation, contact, invoice = writer_rows()
    invoice["line_amount_type"] = "inclusive"
    invoice["lines"] = [dict(description="Inclusive service", quantity="2", unit_price="62",
                             net_amount="100", tax_amount="24", gross_amount="124", tax_rate="24")]
    result = parse_purchase(e_arve_xml(organisation, contact, invoice, None))
    assert result["items"][0]["unit_price"] == Decimal("50")
    assert result["totals"]["gross"] == Decimal("124")


def test_tax_inclusive_writer_preserves_declared_rounding():
    organisation, contact, invoice = writer_rows()
    invoice["line_amount_type"] = "inclusive"
    invoice["lines"] = [dict(description="Inclusive service", quantity="1", unit_price="100",
                             net_amount="80.65", tax_amount="19.35", gross_amount="100", tax_rate="24")]
    result = parse_purchase(e_arve_xml(organisation, contact, invoice, None))
    assert result["totals"] == dict(net=Decimal("80.65"), vat=Decimal("19.35"), gross=Decimal("100.00"))


@pytest.mark.parametrize("tag,value", [("ItemVatSum", "99"), ("ItemVatRate", "9"),
                                       ("ItemQuantity", "3"), ("ItemAmount", "4"), ("ItemPrice", "51")])
def test_reject_conflicting_item_aliases(tag, value):
    root = ET.fromstring((FIXTURES / "einvoicing_purchase.xml").read_bytes())
    ET.SubElement(root.find("Invoice/InvoiceItem/InvoiceItemGroup/ItemEntry"), tag).text = value
    with pytest.raises(ValueError, match=tag + ".*difference"):
        parse_purchase(ET.tostring(root))


def test_reject_utf16_dtd():
    content = '<!DOCTYPE Invoice [<!ENTITY x "bad">]><Invoice/>'.encode("utf-16")
    with pytest.raises(ValueError, match="DTD"):
        parse_purchase(content)


@pytest.mark.parametrize("currency", ["EURO", "eur", "12X", "€"])
def test_reject_invalid_currency(currency):
    root = ET.fromstring((FIXTURES / "einvoicing_purchase.xml").read_bytes())
    root.find("Invoice/InvoiceSumGroup/Currency").text = currency
    with pytest.raises(ValueError, match="currency"):
        parse_purchase(ET.tostring(root))
