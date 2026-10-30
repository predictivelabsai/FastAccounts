"""Deterministic APA TSD XBRL GL serialisation for a single payout."""
from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
from xml.etree import ElementTree as ET

XBRLI = "http://www.xbrl.org/2003/instance"
XLINK = "http://www.w3.org/1999/xlink"
XBRLL = "http://www.xbrl.org/2003/linkbase"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
GL_USK = "http://www.xbrl.org/int/gl/usk/2015-03-25"
GL_COR = "http://www.xbrl.org/int/gl/cor/2015-03-25"
GL_EXT = "http://www.xbrl.org/int/gl/ext/2015-03-25"
GL_PLT = "http://www.xbrl.org/int/gl/plt/2015-03-25"
GL_BUS = "http://www.xbrl.org/int/gl/bus/2015-03-25"
GL_MUC = "http://www.xbrl.org/int/gl/muc/2015-03-25"
ISO639 = "http://www.xbrl.org/2005/iso639"
ISO4217 = "http://www.xbrl.org/2003/iso4217"

NS = {"xbrli": XBRLI, "xlink": XLINK, "xbrll": XBRLL, "xsi": XSI,
      "gl-usk": GL_USK, "gl-cor": GL_COR, "gl-ext": GL_EXT,
      "gl-plt": GL_PLT, "gl-bus": GL_BUS, "gl-muc": GL_MUC,
      "iso639": ISO639, "iso4217": ISO4217}
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)

TAX_CODES = {
    "social_tax": "TSD_SM",
    "funded_pension": "TSD_KP",
    "employee_unemployment_insurance": "TSD_TK",
    "employer_unemployment_insurance": "TSD_TTK",
    "income_tax": "TSD_KTM",
}


def _tag(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}"


def _element(parent, namespace, name, value, **attrs):
    node = ET.SubElement(parent, _tag(namespace, name), attrs)
    node.text = str(value)
    return node


def amount(value: Decimal | str | int) -> str:
    """Render money without binary floats and retain two decimal places."""
    return f"{Decimal(str(value)).quantize(Decimal('0.01')):.2f}"


def transaction_id(organisation_id: str, payout_id: str, version: int = 1) -> str:
    raw = f"{organisation_id}:{payout_id}:{version}".encode("utf-8")
    return "FA-" + sha256(raw).hexdigest()[:32]


def generate_apa_xml(organisation: dict, payout: dict, records: list[dict], *, version: int = 1,
                     operation: str = "R") -> bytes:
    """Generate one APA transaction file from frozen, tenant-scoped payout rows."""
    if not records:
        raise ValueError("A payout export requires at least one frozen payment record")
    records = sorted(records, key=lambda row: (row["recipient_personal_id"],
                                                int(row["tsd_payment_type"]),
                                                row.get("payment_record_id", "")))
    date = payout["payout_date"]
    root = ET.Element(_tag(XBRLI, "xbrl"), {
        _tag(XSI, "schemaLocation"): f"{GL_PLT} https://www.xbrl.org/taxonomy/int/gl/2015-03-25/plt/case-c-b-m-u-t/gl-plt-all-2015-03-25.xsd"
    })
    ET.SubElement(root, _tag(XBRLL, "schemaRef"), {
        _tag(XLINK, "href"): "../plt/case-c-b-m-e/gl-plt-2015-03-25.xsd",
        _tag(XLINK, "arcrole"): "http://www.w3.org/1999/xlink/properties/linkbase",
        _tag(XLINK, "type"): "simple",
    })
    context = ET.SubElement(root, _tag(XBRLI, "context"), {"id": "now"})
    entity = ET.SubElement(context, _tag(XBRLI, "entity"))
    _element(entity, XBRLI, "identifier", organisation["registration_no"].strip(),
             scheme="http://www.ariregister.rik.ee")
    period = ET.SubElement(context, _tag(XBRLI, "period"))
    _element(period, XBRLI, "instant", date)
    for unit_id, measure in (("eur", "iso4217:EUR"), ("NotUsed", "pure")):
        unit = ET.SubElement(root, _tag(XBRLI, "unit"), {"id": unit_id})
        _element(unit, XBRLI, "measure", measure)

    entries = ET.SubElement(root, _tag(GL_COR, "accountingEntries"))
    info = ET.SubElement(entries, _tag(GL_COR, "documentInfo"))
    _element(info, GL_COR, "entriesType", "other", contextRef="now")
    _element(info, GL_COR, "uniqueID", transaction_id(organisation["id"], payout["id"], version), contextRef="now")
    _element(info, GL_COR, "language", "iso639:et", contextRef="now")
    _element(info, GL_COR, "creationDate", date, contextRef="now")
    _element(info, GL_COR, "entriesComment", "APA TSD palgamaksete andmed", contextRef="now")
    _element(info, GL_COR, "periodCoveredStart", date, contextRef="now")
    _element(info, GL_COR, "periodCoveredEnd", date, contextRef="now")
    _element(info, GL_BUS, "sourceApplication", "FastAccounts", contextRef="now")
    _element(info, GL_MUC, "defaultCurrency", "iso4217:eur", contextRef="now")
    entity_info = ET.SubElement(entries, _tag(GL_COR, "entityInformation"))
    identifiers = ET.SubElement(entity_info, _tag(GL_BUS, "organizationIdentifiers"))
    _element(identifiers, GL_BUS, "organizationIdentifier", organisation["registration_no"].strip(), contextRef="now")
    _element(identifiers, GL_BUS, "organizationDescription", "ARIREGISTRIKOOD", contextRef="now")
    header = ET.SubElement(entries, _tag(GL_COR, "entryHeader"))
    _element(header, GL_COR, "entryNumber", "EE0201001", contextRef="now")
    for index, record in enumerate(records, start=1):
        detail = ET.SubElement(header, _tag(GL_COR, "entryDetail"))
        line_id = f"{payout['id']}-{index}" if operation == "M" or version == 1 else f"{payout['id']}-v{version}-{index}"
        _element(detail, GL_COR, "lineNumber", line_id, contextRef="now")
        _element(detail, GL_COR, "lineNumberCounter", index, contextRef="now", unitRef="NotUsed")
        account = ET.SubElement(detail, _tag(GL_COR, "account"))
        for code, codelist in ((str(record["tsd_payment_type"]), "VALJAMLIIK2023ap"), (operation, "TOIMINGUTYYP2023ap")):
            sub = ET.SubElement(account, _tag(GL_COR, "accountSub"))
            _element(sub, GL_COR, "accountSubID", code, contextRef="now")
            _element(sub, GL_COR, "accountSubType", codelist, contextRef="now")
        _element(detail, GL_COR, "amount", amount(record["gross_amount"]), contextRef="now", decimals="2", unitRef="eur")
        reference = ET.SubElement(detail, _tag(GL_COR, "identifierReference"))
        _element(reference, GL_COR, "identifierCode", record["recipient_personal_id"], contextRef="now")
        _element(reference, GL_COR, "identifierDescription", "ISIKUKOOD", contextRef="now")
        _element(detail, GL_COR, "documentDate", date, contextRef="now")
        measurable = ET.SubElement(detail, _tag(GL_BUS, "measurable"))
        _element(measurable, GL_BUS, "measurableID", "TSD01", contextRef="now")
        _element(measurable, GL_BUS, "measurableIDSchema", "SYNDMUS2017ap", contextRef="now")
        for label, value in (("MVT_610", record["tax_free_minimum"]), ("TSD_SMVM", record["social_tax_base"])):
            if Decimal(str(value)):
                node = ET.SubElement(detail, _tag(GL_BUS, "measurable"))
                _element(node, GL_BUS, "measurableDescription", label, contextRef="now")
                _element(node, GL_BUS, "measurableQuantity", amount(value), contextRef="now", decimals="2", unitRef="eur")
        fields = [*TAX_CODES]
        for field in fields:
            value = Decimal(str(record[field]))
            if value:
                taxes = ET.SubElement(detail, _tag(GL_COR, "taxes"))
                _element(taxes, GL_COR, "taxAmount", amount(value), contextRef="now", decimals="2", unitRef="eur")
                _element(taxes, GL_COR, "taxCode", TAX_CODES[field], contextRef="now")
    payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    # ElementTree omits registered prefixes that are used only in schemaLocation.
    declaration = (b' xmlns:gl-usk="' + GL_USK.encode() + b'" xmlns:gl-ext="' + GL_EXT.encode()
                   + b'" xmlns:gl-plt="' + GL_PLT.encode() + b'" xmlns:iso639="' + ISO639.encode()
                   + b'" xmlns:iso4217="' + ISO4217.encode() + b'"')
    return payload.replace(b"<xbrli:xbrl ", b"<xbrli:xbrl" + declaration + b" ", 1)
