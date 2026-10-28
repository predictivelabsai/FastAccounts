"""Tenant-scoped APA export history, cancellation and feedback processing."""
from __future__ import annotations

from hashlib import sha256
from copy import deepcopy
from uuid import uuid4
from xml.etree import ElementTree as ET

from core_utils import audit, utc_now

STATUS_MAP = {"OK": "Accepted", "ERROR": "Rejected", "PARTLYERROR": "PartiallyRejected"}


class APAHistoryService:
    def __init__(self, db):
        self.db = db

    def exports(self, organisation_id: str) -> list[dict]:
        return self.db.rows("SELECT e.id,e.organisation_id,e.payout_id,e.transaction_id,e.version,e.file_sha256,e.created_at,e.created_by,e.status,"
                            "COALESCE((SELECT payout_date FROM payroll_payout_batches p WHERE p.organisation_id=e.organisation_id AND p.id=e.payout_id),"
                            "(SELECT payout_date FROM payroll_absence_payout_batches p WHERE p.organisation_id=e.organisation_id AND p.id=e.payout_id)) AS payout_date "
                            "FROM tsd_apa_exports e WHERE e.organisation_id=? ORDER BY e.created_at DESC,e.id DESC",
                            (organisation_id,))

    def record_export(self, organisation_id: str, payout_id: str, transaction_id: str,
                      version: int, payload: bytes, *, actor: str) -> dict:
        digest = sha256(payload).hexdigest()
        with self.db.transaction() as tx:
            existing = tx.one("SELECT * FROM tsd_apa_exports WHERE organisation_id=? AND payout_id=? AND version=?",
                              (organisation_id, payout_id, version))
            if existing:
                if existing["file_sha256"] != digest:
                    raise ValueError("An APA export version is immutable")
                return existing
            row_id = str(uuid4())
            created = utc_now()
            tx.execute("INSERT INTO tsd_apa_exports(id,organisation_id,payout_id,transaction_id,version,file_sha256,file_xml,created_at,created_by,status) "
                       "VALUES (?,?,?,?,?,?,?,?,?,'Exported')",
                       (row_id, organisation_id, payout_id, transaction_id, version, digest, payload, created, actor))
            audit(tx, organisation_id, actor, "payroll.tsd.apa_exported", "tsd_apa_export", row_id,
                  {"payout_id": payout_id, "transaction_id": transaction_id, "version": version, "sha256": digest})
            return tx.one("SELECT * FROM tsd_apa_exports WHERE organisation_id=? AND id=?", (organisation_id, row_id))

    def export_version(self, organisation_id: str, payout: dict, records: list[dict], *, actor: str) -> tuple[dict, bytes]:
        from tsd_apa_xml import generate_apa_xml, transaction_id
        rows = self.db.rows("SELECT * FROM tsd_apa_exports WHERE organisation_id=? AND payout_id=? ORDER BY version DESC LIMIT 1",
                            (organisation_id, payout["id"]))
        latest = rows[0] if rows else None
        version = int(latest["version"]) if latest else 1
        payload = generate_apa_xml({"id":organisation_id, **self.db.one("SELECT registration_no FROM organisations WHERE id=?", (organisation_id,))},
                                   payout, records, version=version)
        if latest and sha256(payload).hexdigest() == latest["file_sha256"]:
            if latest["status"] == "Cancelled":
                raise ValueError("A cancelled APA transaction cannot be exported again without a correction")
            return latest, bytes(latest["file_xml"])
        if latest:
            version += 1
            payload = generate_apa_xml({"id":organisation_id, **self.db.one("SELECT registration_no FROM organisations WHERE id=?", (organisation_id,))},
                                       payout, records, version=version)
        row = self.record_export(organisation_id, payout["id"], transaction_id(organisation_id, payout["id"], version),
                                 version, payload, actor=actor)
        return row, payload

    def cancellation(self, organisation_id: str, export_id: str, *, actor: str) -> bytes:
        with self.db.transaction() as tx:
            row = tx.one("SELECT * FROM tsd_apa_exports WHERE organisation_id=? AND id=?", (organisation_id, export_id))
            if not row:
                raise KeyError("APA export not found")
            if row["status"] == "Cancelled":
                raise ValueError("APA export is already cancelled")
            original = ET.fromstring(row["file_xml"])
            ns = {"x":"http://www.xbrl.org/2003/instance", "cor":"http://www.xbrl.org/int/gl/cor/2015-03-25"}
            payload = self._cancellation_xml(original, row["transaction_id"], ns)
            tx.execute("UPDATE tsd_apa_exports SET status='Cancelled' WHERE organisation_id=? AND id=?", (organisation_id, export_id))
            audit(tx, organisation_id, actor, "payroll.tsd.apa_cancelled", "tsd_apa_export", export_id,
                  {"transaction_id": row["transaction_id"], "sha256": sha256(payload).hexdigest()})
            return payload

    @staticmethod
    def _cancellation_xml(original, transaction_id, ns) -> bytes:
        from tsd_apa_xml import GL_COR, GL_USK, GL_EXT, GL_PLT, GL_BUS, GL_MUC, ISO639, ISO4217, XBRLI, XBRLL, XLINK, XSI
        tag = lambda uri, name: f"{{{uri}}}{name}"
        root = ET.Element(tag(XBRLI, "xbrl"), {tag(XSI, "schemaLocation"): f"{GL_PLT} https://www.xbrl.org/taxonomy/int/gl/2015-03-25/plt/case-c-b-m-u-t/gl-plt-all-2015-03-25.xsd"})
        # Preserve the official example namespace set and document context.
        for prefix, uri in (("xbrli",XBRLI),("xlink",XLINK),("xbrll",XBRLL),("xsi",XSI),("gl-usk",GL_USK),("gl-cor",GL_COR),("gl-ext",GL_EXT),("iso639",ISO639),("iso4217",ISO4217),("gl-plt",GL_PLT),("gl-bus",GL_BUS),("gl-muc",GL_MUC)):
            ET.register_namespace(prefix, uri)
        ref = original.find(tag(XBRLL, "schemaRef"))
        if ref is not None:
            root.append(ref)
        original_context = original.find(tag(XBRLI, "context"))
        if original_context is not None:
            root.append(original_context)
        for unit in original.findall(tag(XBRLI, "unit")):
            root.append(unit)
        source = original.find(f".//{tag(GL_COR,'documentInfo')}")
        entries = ET.SubElement(root, tag(GL_COR, "accountingEntries"))
        info = ET.SubElement(entries, tag(GL_COR, "documentInfo"))
        if source is not None:
            for child in source:
                info.append(deepcopy(child))
        uid = info.find(tag(GL_COR, "uniqueID"))
        if uid is not None:
            uid.text = transaction_id
        header = ET.SubElement(entries, tag(GL_COR, "entryHeader"))
        entity_info = original.find(tag(GL_COR, "entityInformation"))
        if entity_info is not None:
            entries.insert(1, deepcopy(entity_info))
        entry_number = original.find(f".//{tag(GL_COR,'entryNumber')}")
        if entry_number is not None:
            header.append(entry_number)
        for index, detail in enumerate(original.findall(f".//{tag(GL_COR,'entryDetail')}"), 1):
            cancellation = ET.SubElement(header, tag(GL_COR, "entryDetail"))
            line = detail.find(tag(GL_COR, "lineNumber"))
            counter = detail.find(tag(GL_COR, "lineNumberCounter"))
            if line is not None:
                cancellation.append(deepcopy(line))
            if counter is not None:
                counter.text = str(index)
                cancellation.append(deepcopy(counter))
            account = ET.SubElement(cancellation, tag(GL_COR, "account"))
            sub = ET.SubElement(account, tag(GL_COR, "accountSub"))
            ET.SubElement(sub, tag(GL_COR, "accountSubID"), {"contextRef":"now"}).text = "T"
            ET.SubElement(sub, tag(GL_COR, "accountSubType"), {"contextRef":"now"}).text = "TOIMINGUTYYP2023ap"
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def import_feedback(self, organisation_id: str, transaction_id: str, payload: bytes, *, actor: str) -> dict:
        try:
            root = ET.fromstring(payload)
        except ET.ParseError as exc:
            raise ValueError("Invalid EMTA feedback XML") from exc
        if root.tag != "processing":
            raise ValueError("Unexpected EMTA feedback root element")
        result = root.attrib.get("result", "ERROR").upper()
        status = STATUS_MAP.get(result, "Rejected")
        with self.db.transaction() as tx:
            export = tx.one("SELECT id,status FROM tsd_apa_exports WHERE organisation_id=? AND transaction_id=?",
                            (organisation_id, transaction_id))
            feedback_id = str(uuid4())
            tx.execute("INSERT INTO tsd_apa_feedback(id,organisation_id,export_id,transaction_id,file_result,imported_at,imported_by) VALUES (?,?,?,?,?,?,?)",
                       (feedback_id, organisation_id, export["id"] if export else None, transaction_id, result, utc_now(), actor))
            messages = []
            for validation in root.findall(".//validation"):
                code = (validation.findtext("errorCode") or "UNKNOWN").strip()
                category = (validation.findtext("errorLevel") or "UNKNOWN").strip()
                descriptions = validation.findall("errorDescription")
                message_text = "\n".join((node.text or "").strip() for node in descriptions if (node.text or "").strip())
                refs = validation.findall(".//lineReference") or [None]
                for ref in refs:
                    line_id = ref.findtext("lineInternalId") if ref is not None else None
                    counter = ref.findtext("lineNumberCounter") if ref is not None else None
                    tx.execute("INSERT INTO tsd_apa_feedback_messages(id,organisation_id,feedback_id,rule_code,category,message_text,line_internal_id,line_number_counter) VALUES (?,?,?,?,?,?,?,?)",
                               (str(uuid4()), organisation_id, feedback_id, code, category, message_text, line_id, counter))
                    messages.append({"rule_code":code,"category":category,"message_text":message_text,"line_internal_id":line_id,"line_number_counter":counter})
            for entry_detail in root.findall(".//entryDetail"):
                refs = entry_detail.findall("./lineReferences/lineReference") or [None]
                for data in entry_detail.findall("./data"):
                    code = (data.findtext("code") or "").strip()
                    category = (data.findtext("description") or "").strip()
                    if not code.startswith("KR_") and category.upper() not in {"ERROR", "WARNING"}:
                        continue
                    message_text = "\n".join((node.text or "").strip() for node in data.findall("info") if (node.text or "").strip())
                    for ref in refs:
                        line_id = ref.findtext("lineInternalId") if ref is not None else None
                        counter = ref.findtext("lineNumberCounter") if ref is not None else None
                        tx.execute("INSERT INTO tsd_apa_feedback_messages(id,organisation_id,feedback_id,rule_code,category,message_text,line_internal_id,line_number_counter) VALUES (?,?,?,?,?,?,?,?)",
                                   (str(uuid4()), organisation_id, feedback_id, code, category, message_text, line_id, counter))
                        messages.append({"rule_code":code,"category":category,"message_text":message_text,"line_internal_id":line_id,"line_number_counter":counter})
            if export:
                tx.execute("UPDATE tsd_apa_exports SET status=? WHERE organisation_id=? AND id=?", (status, organisation_id, export["id"]))
            audit(tx, organisation_id, actor, "payroll.tsd.apa_feedback_imported", "tsd_apa_feedback", feedback_id,
                  {"transaction_id": transaction_id, "result": result, "matched": bool(export)})
            return {"id": feedback_id, "transaction_id": transaction_id, "status": status if export else "Unmatched",
                    "matched": bool(export), "file_result": result, "messages": messages}

    def feedback_results(self, organisation_id: str, export_id: str) -> list[dict]:
        rows = self.db.rows("SELECT f.id,f.transaction_id,f.file_result,f.imported_at,m.rule_code,m.category,m.message_text,m.line_internal_id,m.line_number_counter "
                            "FROM tsd_apa_feedback f LEFT JOIN tsd_apa_feedback_messages m ON m.organisation_id=f.organisation_id AND m.feedback_id=f.id "
                            "WHERE f.organisation_id=? AND f.export_id=? ORDER BY f.imported_at,f.id,m.id", (organisation_id, export_id))
        return rows
