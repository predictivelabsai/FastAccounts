"""Accountant-reviewed Estonian TSD manual-upload exports.

The data-based TSD direction is represented as one payment transaction per
confirmed pay-run item. This module does not submit files or make network calls.
The detailed EMTA taxonomy/classification profile was not included in the
authoritative project plan, so the explicit mapping below is intentionally small
and is documented in docs/tsd-export.md as not live-verified against e-MTA.
"""
from __future__ import annotations

import calendar
import csv
import io
import json
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile
from datetime import date, timedelta
from decimal import Decimal
from xml.etree import ElementTree as ET

from core_utils import audit, db_number, decimal, money, new_id, utc_now
from database import Database, get_database
from payroll_calendar import is_working_day
from payroll_payday import payday_for_period
from payroll_rules import settlement_date
from payroll_tsd_breakdown import calculate_tsd_breakdown, _allocate
from tsd_apa_xml import generate_apa_xml


XBRLI_NS = "http://www.xbrl.org/2003/instance"
XBRL_GL_CORE_NS = "http://www.xbrl.org/int/gl/cor/2006-10-25"
TSD_NS = "urn:fastaccounts:ee:tsd:2026:review-only"

# The payroll plan specifies the data-based Annex 1-2 direction, but not the
# official EMTA payment codes. These semantic classifications are therefore
# FastAccounts mapping labels, not claimed EMTA codes.
TSD_PAYMENT_CLASSIFICATION = {
    "monthly": "EMPLOYMENT_SALARY",
    "hourly": "EMPLOYMENT_SALARY",
    "board_fee": "BOARD_MEMBER_FEE",
    "income_line": "CONTRACTOR_FEE",
}
TSD_ANNEX_MAPPING = {
    "EE_RESIDENT_PAYMENT": "1",
    "NON_RESIDENT_PAYMENT": "2",
}

TSD_PAYMENT_FIELDS = (
    "declaration",
    "annex",
    "payment_record_id",
    "pay_run_id",
    "payment_date",
    "payment_month",
    "filing_deadline",
    "payer_registration_no",
    "recipient_personal_id",
    "recipient_name",
    "payment_classification",
    "tsd_payment_type",
    "pay_basis",
    "currency",
    "gross_amount",
    "tax_free_minimum",
    "income_tax_base",
    "income_tax",
    "employee_unemployment_insurance",
    "employer_unemployment_insurance",
    "funded_pension",
    "social_tax_base",
    "social_tax",
    "net_amount",
    "employer_cost",
)

TSD_AMOUNT_FIELDS = (
    "gross_amount",
    "tax_free_minimum",
    "income_tax_base",
    "income_tax",
    "employee_unemployment_insurance",
    "employer_unemployment_insurance",
    "funded_pension",
    "social_tax_base",
    "social_tax",
    "net_amount",
    "employer_cost",
)

CSV_TRANSITION_END = date(2027, 12, 31)
LEGACY_A1_FIELDS = ("1000", "1010", "1020", "1030", "1040", "1050", "1060", "1070", "1080", "1090", "1100", "1110", "1120", "1130", "1140", "1150", "1160", "1170")


def _tag(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}"


def _text(parent: ET.Element, namespace: str, name: str, value) -> ET.Element:
    element = ET.SubElement(parent, _tag(namespace, name))
    element.text = str(value)
    return element


def _month_end(period: str) -> date:
    year, month = map(int, period.split("-"))
    return date(year, month, calendar.monthrange(year, month)[1])


def _filing_deadline(payment_date: date) -> date:
    if payment_date.month == 12:
        due = date(payment_date.year + 1, 1, 10)
    else:
        due = date(payment_date.year, payment_date.month + 1, 10)
    while not is_working_day(due):
        due += timedelta(days=1)
    return due


class TSDExportService:
    """Prepare, review and download TSD files without direct submission."""

    def __init__(self, db: Database | None = None):
        self.db = db or get_database()

    @staticmethod
    def _organisation(tx, organisation_id: str, *, require_registration: bool = False) -> dict:
        organisation = tx.one(
            "SELECT * FROM organisations WHERE id=?", (organisation_id,)
        )
        if not organisation:
            raise KeyError("Organisation not found")
        if organisation["country_code"] != "EE" or organisation["base_currency"] != "EUR":
            raise ValueError("TSD preparation is available only for Estonian organisations with EUR books")
        if require_registration and not (organisation.get("registration_no") or "").strip():
            raise ValueError("TSD preparation requires the organisation registration number")
        return organisation

    @staticmethod
    def _run(tx, organisation_id: str, run_id: str) -> dict:
        run = tx.one(
            "SELECT * FROM pay_runs WHERE organisation_id=? AND id=?",
            (organisation_id, run_id),
        )
        if not run:
            raise KeyError("Pay run not found")
        if run["status"] != "Approved":
            raise ValueError("Only an approved pay run can be prepared for TSD export")
        if 'settlement_date' in run:
            payout = tx.one("SELECT payout_date FROM payroll_payout_batches WHERE organisation_id=? AND pay_run_id=? "
                            "AND payout_type='salary' AND status!='Cancelled' ORDER BY payout_date,id LIMIT 1",
                            (organisation_id, run_id))
            payday_date = payday_for_period(tx, organisation_id, run['period'])
            run['payment_date'] = settlement_date(run['period'],
                salary_payout_date=payout['payout_date'] if payout else None,
                payday_rule_date=run['settlement_date'] or payday_date).isoformat()
        else:
            run['payment_date'] = _month_end(run['period']).isoformat()
        run["items"] = tx.rows(
            "SELECT * FROM pay_run_items WHERE organisation_id=? AND pay_run_id=? "
            "ORDER BY employee_name,id",
            (organisation_id, run_id),
        )
        if not run["items"]:
            raise ValueError("TSD preparation requires at least one payment record")
        missing = [item["employee_name"] for item in run["items"]
                   if not (item.get("employee_personal_id") or "").strip()]
        if missing:
            raise ValueError(
                "TSD preparation requires a frozen personal ID for every payment record: "
                + ", ".join(missing)
            )
        return run

    @staticmethod
    def _record(organisation: dict, run: dict, item: dict, line: dict | None = None) -> dict:
        payment_date = date.fromisoformat(run['payment_date'])
        pension = money(line["ii_pillar"] if line else item["funded_pension"])
        employee_ui = money(line["ui_employee"] if line else item["ui_employee"])
        exemption = money(line["exemption_610"] if line else item["tax_free_minimum"])
        gross = money(line["amount"] if line else item["gross"])
        excluded_income = sum((money(line['amount']) for line in item.get('components', [])
                               if line['direction'] == 'income' and not line['income_tax']), Decimal(0))
        income_tax_base = money(decimal(line["taxable_amount"]) + exemption if line else
            max(Decimal("0"), gross - excluded_income - pension - employee_ui - exemption))
        net = money(line["net_amount"] if line and "net_amount" in line else item["net"])
        employer_cost = money(line["employer_cost"] if line and "employer_cost" in line
                              else gross + money(line["social_tax"]) + money(line["ui_employer"]) if line else item["employer_cost"])
        payment_type = int(line["payment_type"]) if line else int(item.get("tsd_payment_type") or
            {"monthly": 10, "hourly": 10, "board_fee": 21, "income_line": 17}[item["pay_basis"]])
        classification = {10: "EMPLOYMENT_SALARY", 17: "CONTRACTOR_FEE", 21: "BOARD_MEMBER_FEE",
                          24: "EMPLOYER_SICK_BENEFIT", 33: "TERMINATION_COMPENSATION"}.get(payment_type, "OTHER_PAYMENT")
        values = {
            "declaration": "TSD",
            # Current payroll scope contains resident calculations only. Annex 2
            # stays in the declared mapping/scope and is not fabricated.
            "annex": TSD_ANNEX_MAPPING["EE_RESIDENT_PAYMENT"],
            "payment_record_id": line.get("id", f"{item['id']}:{payment_type}") if line else item["id"],
            "pay_run_id": run["id"],
            "payment_date": payment_date.isoformat(),
            "payment_month": payment_date.strftime("%Y-%m"),
            "filing_deadline": _filing_deadline(payment_date).isoformat(),
            "payer_registration_no": organisation["registration_no"].strip(),
            "recipient_personal_id": item["employee_personal_id"].strip(),
            "recipient_name": item["employee_name"],
            "payment_classification": classification,
            "tsd_payment_type": payment_type,
            "pay_basis": item["pay_basis"],
            "currency": "EUR",
            "gross_amount": gross,
            "tax_free_minimum": exemption,
            "income_tax_base": income_tax_base,
            "income_tax": money(line["income_tax"] if line else item["income_tax"]),
            "employee_unemployment_insurance": employee_ui,
            "employer_unemployment_insurance": money(line["ui_employer"] if line else item["ui_employer"]),
            "funded_pension": pension,
            "social_tax_base": money(line["social_tax_base"] if line else item["social_tax_base"]),
            "social_tax": money(line["social_tax"] if line else item["social_tax"]),
            "net_amount": net,
            "employer_cost": employer_cost,
        }
        if set(values) != set(TSD_PAYMENT_FIELDS):
            raise AssertionError("TSD payment field mapping is incomplete")
        return values

    def _workpaper(self, tx, organisation_id: str, run_id: str) -> dict:
        organisation = self._organisation(tx, organisation_id, require_registration=True)
        run = self._run(tx, organisation_id, run_id)
        for item in run['items']:
            item['components'] = tx.rows('SELECT * FROM pay_item_components WHERE organisation_id=? AND item_id=? ORDER BY position', (organisation_id, item['id']))
        records, warnings = [], []
        for item in run["items"]:
            components = tx.rows('SELECT * FROM pay_item_components WHERE organisation_id=? AND item_id=? ORDER BY position',
                                 (organisation_id, item['id']))
            frozen_lines = tx.rows("SELECT * FROM pay_item_tsd_lines WHERE organisation_id=? AND source_kind='pay_run_item' AND source_id=? ORDER BY payment_type",
                                   (organisation_id, item['id']))
            if not frozen_lines:
                context = tx.one('SELECT * FROM pay_item_context WHERE organisation_id=? AND item_id=?',
                                 (organisation_id, item['id']))
                if context is not None and all('tsd_payment_type' in component for component in components):
                    try:
                        frozen_lines = calculate_tsd_breakdown(item=item, components=components, context=context)
                        for line in frozen_lines:
                            line['id'] = f"{item['id']}:run:{line['payment_type']}"
                    except (KeyError, TypeError, ValueError):
                        frozen_lines = []
                if not frozen_lines:
                    warnings.append('Legacy run: per-type split unavailable')
                    records.append(self._record(organisation, run, item))
                    continue
            nets = _allocate(item['net'], {line['payment_type']: line['amount'] for line in frozen_lines})
            for line in frozen_lines:
                line['net_amount'] = nets[line['payment_type']]
                records.append(self._record(organisation, run, item, line))
        payment_month = run['payment_date'][:7]
        pay_run_record_count = len(records)
        absence_rows = tx.rows("SELECT p.*,b.payout_date FROM payroll_absence_pay p "
                               "JOIN payroll_absence_payout_batches b ON b.organisation_id=p.organisation_id AND b.id=p.absence_payout_batch_id "
                               "WHERE p.organisation_id=? AND p.status IN ('in_payout','paid') AND b.status IN ('Approved','Paid') AND substr(b.payout_date,1,7)=? "
                               "ORDER BY p.employee_id,p.id", (organisation_id, payment_month))
        for absence in absence_rows:
            calc = json.loads(absence['calculation_json'])
            if not (calc.get('employee_personal_id') or '').strip():
                raise ValueError('TSD preparation requires a frozen personal ID for every absence payment record')
            payment_date = date.fromisoformat(absence['payout_date'])
            absence_lines = tx.rows("SELECT * FROM pay_item_tsd_lines WHERE organisation_id=? AND source_kind='absence_pay' AND source_id=? AND payout_batch_id=? ORDER BY payment_type",
                                    (organisation_id, absence['id'], absence['absence_payout_batch_id']))
            if not absence_lines:
                absence_lines = calculate_tsd_breakdown(item=calc | {'tsd_payment_type': 10, 'pay_basis': 'monthly'},
                                                        components=[], context=calc)
                for line in absence_lines:
                    line['id'] = f"{absence['id']}:{absence['absence_payout_batch_id']}:{line['payment_type']}"
            absence_nets = _allocate(calc['net'], {line['payment_type']: line['amount'] for line in absence_lines})
            for line in absence_lines:
                line['net_amount'] = absence_nets[line['payment_type']]
                records.append({
                'declaration':'TSD','annex':TSD_ANNEX_MAPPING['EE_RESIDENT_PAYMENT'],
                'payment_record_id':line.get('id', f"{absence['id']}:{absence['absence_payout_batch_id']}:{line['payment_type']}"),'pay_run_id':absence['absence_payout_batch_id'],
                'payment_date':payment_date.isoformat(),'payment_month':payment_date.strftime('%Y-%m'),
                'filing_deadline':_filing_deadline(payment_date).isoformat(),
                'payer_registration_no':organisation['registration_no'].strip(),
                'recipient_personal_id':(calc.get('employee_personal_id') or '').strip(),
                'recipient_name':calc['employee_name'],'payment_classification':{10:'EMPLOYMENT_SALARY',17:'CONTRACTOR_FEE',21:'BOARD_MEMBER_FEE',24:'EMPLOYER_SICK_BENEFIT'}.get(line['payment_type'],'OTHER_PAYMENT'),
                'tsd_payment_type':line['payment_type'],
                'pay_basis':'monthly','currency':'EUR','gross_amount':money(line['amount']),
                'tax_free_minimum':line['exemption_610'],'income_tax_base':money(decimal(line['taxable_amount'])+decimal(line['exemption_610'])),
                'income_tax':money(line['income_tax']),
                'employee_unemployment_insurance':money(line['ui_employee']),
                'employer_unemployment_insurance':money(line['ui_employer']),
                'funded_pension':money(line['ii_pillar']),'social_tax_base':money(line['social_tax_base']),
                'social_tax':money(line['social_tax']),'net_amount':money(line['net_amount']),
                'employer_cost':money(line['amount']+line['social_tax']+line['ui_employer']),
            })
        totals = {
            field: money(sum((decimal(record[field]) for record in records), Decimal("0")))
            for field in TSD_AMOUNT_FIELDS
        }
        absence_gross = sum((money(record['gross_amount']) for record in records[pay_run_record_count:]), Decimal(0))
        absence_net = sum((money(record['net_amount']) for record in records[pay_run_record_count:]), Decimal(0))
        absence_cost = sum((money(record['employer_cost']) for record in records[pay_run_record_count:]), Decimal(0))
        if totals["gross_amount"] != money(run["total_gross"]) + absence_gross:
            raise ValueError("TSD gross total does not reconcile to the approved pay run")
        if totals["net_amount"] != money(run["total_net"]) + absence_net:
            raise ValueError("TSD net total does not reconcile to the approved pay run")
        if totals["employer_cost"] != money(run["total_employer_cost"]) + absence_cost:
            raise ValueError("TSD employer-cost total does not reconcile to the approved pay run")
        return {
            "organisation_id": organisation_id,
            "pay_run_id": run_id,
            "period": run["period"],
            "payment_date": records[0]["payment_date"],
            "filing_deadline": records[0]["filing_deadline"],
            "records": records,
            "totals": totals,
            "summary_totals": {
                "total_ui": totals["employee_unemployment_insurance"] + totals["employer_unemployment_insurance"],
                "total_payable": sum((totals[field] for field in ("income_tax", "social_tax", "employee_unemployment_insurance", "employer_unemployment_insurance", "funded_pension")), Decimal("0")),
            },
            "warnings": [
                "NOT live-verified against e-MTA; accountant review and manual upload are required",
                "Current payroll calculations are resident-only, so payment records map to TSD Annex 1",
                *warnings,
            ],
        }

    @staticmethod
    def _serialize(workpaper: dict) -> dict:
        result = dict(workpaper)
        result["records"] = [
            {key: db_number(value) if key in TSD_AMOUNT_FIELDS else value
             for key, value in record.items()}
            for record in workpaper["records"]
        ]
        result["totals"] = {
            key: db_number(value) for key, value in workpaper["totals"].items()
        }
        result["summary_totals"] = {
            key: db_number(value) for key, value in workpaper["summary_totals"].items()
        }
        return result

    def prepare(self, organisation_id: str, run_id: str, *, actor: str) -> dict:
        with self.db.transaction() as tx:
            workpaper = self._workpaper(tx, organisation_id, run_id)
            preparation = tx.one(
                "SELECT * FROM sync_runs WHERE organisation_id=? AND provider='emta' "
                "AND direction='export' AND object_type='tsd' AND cursor_before=? "
                "ORDER BY created_at DESC,id DESC LIMIT 1",
                (organisation_id, run_id),
            )
            if not preparation:
                preparation_id, now = new_id(), utc_now()
                tx.execute(
                    "INSERT INTO sync_runs(id,organisation_id,provider,direction,object_type,status,"
                    "cursor_before,read_count,started_at,created_at) "
                    "VALUES (?,?,?,'export','tsd','Review Required',?,?,?,?)",
                    (preparation_id, organisation_id, "emta", run_id,
                     len(workpaper["records"]), now, now),
                )
                preparation = tx.one(
                    "SELECT * FROM sync_runs WHERE organisation_id=? AND id=?",
                    (organisation_id, preparation_id),
                )
                audit(tx, organisation_id, actor, "payroll.tsd.prepared", "sync_run",
                      preparation_id, {"pay_run_id": run_id})
        result = self._serialize(workpaper)
        result.update({"id": preparation["id"], "status": preparation["status"]})
        return result

    def preparations(self, organisation_id: str) -> list[dict]:
        with self.db.transaction() as tx:
            self._organisation(tx, organisation_id)
            rows = tx.rows(
                "SELECT id,cursor_before pay_run_id,status,read_count,write_count,created_at,completed_at "
                "FROM sync_runs WHERE organisation_id=? AND provider='emta' AND direction='export' "
                "AND object_type='tsd' ORDER BY created_at DESC,id DESC",
                (organisation_id,),
            )
        return rows

    def get(self, organisation_id: str, preparation_id: str) -> dict:
        with self.db.transaction() as tx:
            self._organisation(tx, organisation_id)
            preparation = tx.one(
                "SELECT * FROM sync_runs WHERE organisation_id=? AND id=? AND provider='emta' "
                "AND direction='export' AND object_type='tsd'",
                (organisation_id, preparation_id),
            )
            if not preparation:
                raise KeyError("TSD preparation not found")
            workpaper = self._workpaper(tx, organisation_id, preparation["cursor_before"])
        result = self._serialize(workpaper)
        result.update({"id": preparation["id"], "status": preparation["status"]})
        return result

    def review(self, organisation_id: str, preparation_id: str, *, actor: str) -> dict:
        with self.db.transaction() as tx:
            self._organisation(tx, organisation_id)
            preparation = tx.one(
                "SELECT * FROM sync_runs WHERE organisation_id=? AND id=? AND provider='emta' "
                "AND direction='export' AND object_type='tsd'",
                (organisation_id, preparation_id),
            )
            if not preparation:
                raise KeyError("TSD preparation not found")
            self._workpaper(tx, organisation_id, preparation["cursor_before"])
            result = tx.execute(
                "UPDATE sync_runs SET status='Completed',completed_at=? "
                "WHERE organisation_id=? AND id=? AND status='Review Required'",
                (utc_now(), organisation_id, preparation_id),
            )
            if result.rowcount != 1:
                raise ValueError("Only a TSD preparation requiring review can be marked reviewed")
            audit(tx, organisation_id, actor, "payroll.tsd.reviewed", "sync_run",
                  preparation_id, {"pay_run_id": preparation["cursor_before"]})
            return tx.one(
                "SELECT * FROM sync_runs WHERE organisation_id=? AND id=?",
                (organisation_id, preparation_id),
            ) or {}

    def _reviewed_workpaper(self, organisation_id: str, preparation_id: str) -> tuple[dict, dict]:
        with self.db.transaction() as tx:
            self._organisation(tx, organisation_id)
            preparation = tx.one(
                "SELECT * FROM sync_runs WHERE organisation_id=? AND id=? AND provider='emta' "
                "AND direction='export' AND object_type='tsd'",
                (organisation_id, preparation_id),
            )
            if not preparation:
                raise KeyError("TSD preparation not found")
            if preparation["status"] != "Completed":
                raise ValueError("An accountant must review the TSD preparation before export")
            workpaper = self._workpaper(tx, organisation_id, preparation["cursor_before"])
        return preparation, workpaper

    def _record_export(self, preparation: dict, workpaper: dict, *, actor: str, format_name: str) -> None:
        with self.db.transaction() as tx:
            tx.execute(
                "UPDATE sync_runs SET write_count=? WHERE organisation_id=? AND id=?",
                (len(workpaper["records"]), preparation["organisation_id"], preparation["id"]),
            )
            audit(tx, preparation["organisation_id"], actor, "payroll.tsd.exported", "sync_run",
                  preparation["id"], {"pay_run_id": workpaper["pay_run_id"], "format": format_name})

    def export_xbrl_gl(self, organisation_id: str, preparation_id: str, *, actor: str) -> bytes:
        preparation, workpaper = self._reviewed_workpaper(organisation_id, preparation_id)
        ET.register_namespace("xbrli", XBRLI_NS)
        ET.register_namespace("gl-cor", XBRL_GL_CORE_NS)
        ET.register_namespace("tsd", TSD_NS)
        root = ET.Element(_tag(XBRLI_NS, "xbrl"))
        entries = ET.SubElement(root, _tag(XBRL_GL_CORE_NS, "accountingEntries"))
        document = ET.SubElement(entries, _tag(XBRL_GL_CORE_NS, "documentInfo"))
        _text(document, XBRL_GL_CORE_NS, "entriesType", "journal")
        _text(document, XBRL_GL_CORE_NS, "uniqueID", preparation_id)
        _text(document, XBRL_GL_CORE_NS, "language", "et")
        _text(document, XBRL_GL_CORE_NS, "creationDate", preparation["created_at"][:10])
        _text(document, XBRL_GL_CORE_NS, "periodCoveredStart", workpaper["payment_date"])
        _text(document, XBRL_GL_CORE_NS, "periodCoveredEnd", workpaper["payment_date"])
        _text(document, XBRL_GL_CORE_NS, "sourceApplication", "FastAccounts")
        _text(document, TSD_NS, "declaration", "TSD")
        _text(document, TSD_NS, "annexScope", "1-2")
        _text(document, TSD_NS, "filingDeadline", workpaper["filing_deadline"])
        _text(document, TSD_NS, "validationStatus", "NOT_LIVE_VERIFIED_AGAINST_EMTA")
        for number, record in enumerate(workpaper["records"], start=1):
            header = ET.SubElement(entries, _tag(XBRL_GL_CORE_NS, "entryHeader"))
            _text(header, XBRL_GL_CORE_NS, "enteredDate", record["payment_date"])
            _text(header, XBRL_GL_CORE_NS, "sourceJournalID", f"TSD-A{record['annex']}")
            _text(header, XBRL_GL_CORE_NS, "entryNumber", record["payment_record_id"])
            detail = ET.SubElement(header, _tag(XBRL_GL_CORE_NS, "entryDetail"))
            _text(detail, XBRL_GL_CORE_NS, "lineNumber", number)
            _text(detail, XBRL_GL_CORE_NS, "documentType", "TSD")
            _text(detail, XBRL_GL_CORE_NS, "documentNumber", record["pay_run_id"])
            _text(detail, XBRL_GL_CORE_NS, "documentDate", record["payment_date"])
            _text(detail, XBRL_GL_CORE_NS, "detailComment", record["payment_classification"])
            _text(detail, XBRL_GL_CORE_NS, "amount", db_number(record["gross_amount"]))
            _text(detail, XBRL_GL_CORE_NS, "debitCreditCode", "D")
            for field in TSD_PAYMENT_FIELDS:
                value = record[field]
                if field in TSD_AMOUNT_FIELDS:
                    value = db_number(value)
                _text(detail, TSD_NS, field, value)
        payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        self._record_export(preparation, workpaper, actor=actor, format_name="xbrl-gl-xml")
        return payload

    def _apa_payouts(self, organisation_id: str, preparation_id: str) -> list[tuple[dict, bytes, list[dict]]]:
        preparation, workpaper = self._reviewed_workpaper(organisation_id, preparation_id)
        run_id = preparation["cursor_before"]
        with self.db.transaction() as tx:
            organisation = self._organisation(tx, organisation_id, require_registration=True)
            batches = tx.rows("SELECT * FROM payroll_payout_batches WHERE organisation_id=? AND pay_run_id=? "
                              "AND status='Paid' ORDER BY payout_date,id", (organisation_id, run_id))
            result = []
            for payout in batches:
                lines = tx.rows("SELECT l.amount,i.employee_personal_id FROM payroll_payout_lines l "
                                "JOIN pay_run_items i ON i.organisation_id=l.organisation_id AND i.pay_run_id=? "
                                "AND i.employee_id=l.employee_id WHERE l.organisation_id=? AND l.payout_batch_id=?",
                                (run_id, organisation_id, payout["id"]))
                records = []
                for line in lines:
                    person = [row for row in workpaper["records"]
                              if row["recipient_personal_id"] == line["employee_personal_id"]]
                    if not person:
                        continue
                    paid_net = money(line["amount"])
                    full_net = sum((money(row["net_amount"]) for row in person), Decimal("0"))
                    if full_net <= 0:
                        continue
                    ratio = paid_net / full_net
                    for row in person:
                        scaled = dict(row)
                        scaled["payment_date"] = payout["payout_date"]
                        scaled["payment_month"] = payout["payout_date"][:7]
                        for field in TSD_AMOUNT_FIELDS:
                            scaled[field] = money(money(row[field]) * ratio)
                        records.append(scaled)
                if records:
                    result.append((payout, generate_apa_xml(organisation, payout, records), records))
            absence_batches = tx.rows("SELECT * FROM payroll_absence_payout_batches WHERE organisation_id=? "
                                      "AND status='Paid' AND substr(payout_date,1,7)=substr((SELECT settlement_date FROM pay_runs "
                                      "WHERE organisation_id=? AND id=?),1,7) ORDER BY payout_date,id",
                                      (organisation_id, organisation_id, run_id))
            for payout in absence_batches:
                records = [dict(row) for row in workpaper["records"] if row["pay_run_id"] == payout["id"]]
                if records:
                    result.append((payout, generate_apa_xml(organisation, payout, records), records))
        if not result:
            raise ValueError("No paid payout transactions are available for APA export")
        return result

    def _audit_apa_exports(self, organisation_id: str, exports: list[tuple[dict, bytes]], *, actor: str) -> None:
        with self.db.transaction() as tx:
            for payout, _ in exports:
                audit(tx, organisation_id, actor, "payroll.tsd.exported", "payout", payout["id"],
                      {"payout_id": payout["id"], "format": "apa-xbrl-gl-xml"})

    def export_apa_payout(self, organisation_id: str, preparation_id: str, payout_id: str, *, actor: str) -> bytes:
        exports = self._apa_payouts(organisation_id, preparation_id)
        from tsd_apa_history import APAHistoryService
        history = APAHistoryService(self.db)
        for payout, payload, records in exports:
            if payout["id"] == payout_id:
                self._audit_apa_exports(organisation_id, [(payout, payload)], actor=actor)
                return history.export_version(organisation_id, payout, records, actor=actor)[1]
        raise KeyError("Paid payout not found in this reviewed TSD preparation")

    def export_apa_month_zip(self, organisation_id: str, payment_month: str, *, actor: str) -> bytes:
        if len(payment_month) != 7 or payment_month[4] != "-":
            raise ValueError("Payment month must use YYYY-MM")
        with self.db.transaction() as tx:
            self._organisation(tx, organisation_id, require_registration=True)
            preparations = tx.rows("SELECT id,cursor_before FROM sync_runs WHERE organisation_id=? AND provider='emta' "
                                   "AND direction='export' AND object_type='tsd' AND status='Completed' "
                                   "ORDER BY created_at,id", (organisation_id,))
            paid_salary_runs = {row["pay_run_id"] for row in tx.rows(
                "SELECT DISTINCT pay_run_id FROM payroll_payout_batches WHERE organisation_id=? AND status='Paid' "
                "AND substr(payout_date,1,7)=?", (organisation_id, payment_month))}
            candidate_runs = set(paid_salary_runs)
            if tx.one("SELECT id FROM payroll_absence_payout_batches WHERE organisation_id=? AND status='Paid' "
                      "AND substr(payout_date,1,7)=? LIMIT 1", (organisation_id, payment_month)):
                candidate_runs.update(row["id"] for row in tx.rows(
                    "SELECT id FROM pay_runs WHERE organisation_id=? AND status='Approved' AND substr(settlement_date,1,7)=?",
                    (organisation_id, payment_month)))
            reviewed_runs = {row["cursor_before"] for row in preparations}
            if not paid_salary_runs.issubset(reviewed_runs):
                raise ValueError("Every paid salary payout in the month requires a reviewed TSD preparation")
            runs = [row for row in preparations if row["cursor_before"] in candidate_runs]
            if not runs:
                raise ValueError("No reviewed TSD preparation exists for paid payouts in this month")
        exports_by_id = {}
        for prep in runs:
            for payout, payload, records in self._apa_payouts(organisation_id, prep["id"]):
                if payout["payout_date"][:7] == payment_month:
                    exports_by_id[payout["id"]] = (payout, payload, records)
        if not exports_by_id:
            raise ValueError("No paid payout transactions are available for APA export in this month")
        output = BytesIO()
        with ZipFile(output, "w", ZIP_DEFLATED) as archive:
            from tsd_apa_history import APAHistoryService
            history = APAHistoryService(self.db)
            for payout, payload, records in sorted(exports_by_id.values(), key=lambda pair: (pair[0]["payout_date"], pair[0]["id"])):
                _, payload = history.export_version(organisation_id, payout, records, actor=actor)
                archive.writestr(f"tsd-{payout['payout_date']}-{payout['id']}.xml", payload)
        self._audit_apa_exports(organisation_id, [(payout, payload) for payout, payload, _ in exports_by_id.values()], actor=actor)
        return output.getvalue()

    def export_csv(self, organisation_id: str, preparation_id: str, *, actor: str) -> bytes:
        preparation, workpaper = self._reviewed_workpaper(organisation_id, preparation_id)
        if date.fromisoformat(workpaper["payment_date"]) > CSV_TRANSITION_END:
            raise ValueError("The transitional TSD CSV export is available only through 2027")
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=TSD_PAYMENT_FIELDS, lineterminator="\r\n")
        writer.writeheader()
        for record in workpaper["records"]:
            writer.writerow({
                key: db_number(value) if key in TSD_AMOUNT_FIELDS else value
                for key, value in record.items()
            })
        self._record_export(preparation, workpaper, actor=actor, format_name="csv")
        return output.getvalue().encode("utf-8-sig")

    @staticmethod
    def _legacy_a1_row(record: dict) -> dict:
        payment_type = int(record["tsd_payment_type"])
        social_types = {10, 11, 13, 14, 15, 17, 18, 19, 21, 22, 25, 26, 28, 29, 30, 33, 34, 41, 42, 43}
        ui_types = {10, 11, 14, 17, 18, 19, 25, 26, 52}
        tax_exempt_types = {11, 14, 18, 19, 22, 26, 30, 34}
        code_1060 = record["gross_amount"] if payment_type in social_types else Decimal("0")
        code_1120 = record["gross_amount"] if payment_type in ui_types else Decimal("0")
        return {
            "1000": record["recipient_personal_id"], "1010": record["recipient_name"],
            "1020": payment_type, "1030": record["gross_amount"], "1040": "", "1050": "",
            "1060": code_1060, "1070": Decimal("0"), "1080": Decimal("0"),
            "1090": max(Decimal("0"), record["social_tax_base"] - code_1060),
            "1100": record["social_tax"], "1110": record["funded_pension"],
            "1120": code_1120, "1130": record["employee_unemployment_insurance"],
            "1140": record["employer_unemployment_insurance"],
            "1150": 610 if record["tax_free_minimum"] else "",
            "1160": record["tax_free_minimum"],
            "1170": Decimal("0") if payment_type in tax_exempt_types else record["income_tax"],
        }

    def export_legacy_annex1_csv(self, organisation_id: str, preparation_id: str, *, actor: str) -> bytes:
        preparation, workpaper = self._reviewed_workpaper(organisation_id, preparation_id)
        if date.fromisoformat(workpaper["payment_date"]) > CSV_TRANSITION_END:
            raise ValueError("Legacy Annex 1 CSV upload is available only through December 2027")
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=LEGACY_A1_FIELDS, delimiter=";", lineterminator="\r\n")
        writer.writeheader()
        for record in workpaper["records"]:
            writer.writerow({key: format(value, ".2f") if isinstance(value, Decimal) else value
                             for key, value in self._legacy_a1_row(record).items()})
        self._record_export(preparation, workpaper, actor=actor, format_name="legacy-annex1-csv")
        return output.getvalue().encode("utf-8")

    def workpaper_xlsx(self, organisation_id: str, preparation_id: str) -> bytes:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill

        _, workpaper = self._reviewed_workpaper(organisation_id, preparation_id)
        book = Workbook()
        detail = book.active
        detail.title = "Payments"
        headers = ["Recipient", "Personal code", "Payment type", "Payment month", "Gross", "Income tax withheld", "Social tax", "Employee UI", "Employer UI", "II pillar", "Total payable"]
        detail.append(headers)
        for record in workpaper["records"]:
            detail.append([record["recipient_name"], record["recipient_personal_id"], record["tsd_payment_type"], record["payment_month"], record["gross_amount"], record["income_tax"], record["social_tax"], record["employee_unemployment_insurance"], record["employer_unemployment_insurance"], record["funded_pension"], sum((decimal(record[k]) for k in ("income_tax", "social_tax", "employee_unemployment_insurance", "employer_unemployment_insurance", "funded_pension")), Decimal("0"))])
        for sheet_name, key in (("By payment type", "tsd_payment_type"), ("By recipient", "recipient_personal_id")):
            sheet = book.create_sheet(sheet_name)
            sheet.append([key, *headers[4:]])
            groups = {}
            for record in workpaper["records"]:
                group_key = record[key]
                bucket = groups.setdefault(group_key, [Decimal("0")] * 7)
                for index, field in enumerate(("gross_amount", "income_tax", "social_tax", "employee_unemployment_insurance", "employer_unemployment_insurance", "funded_pension")):
                    bucket[index] += record[field]
                bucket[6] += sum((record[k] for k in ("income_tax", "social_tax", "employee_unemployment_insurance", "employer_unemployment_insurance", "funded_pension")), Decimal("0"))
            for group_key, values in groups.items():
                sheet.append([group_key, *values])
        summary = book.create_sheet("Summary", 0)
        summary.append(["TSD workpaper", workpaper["records"][0]["payment_month"]])
        summary.append(["Record count", len(workpaper["records"])])
        for label, field in (("Income tax withheld", "income_tax"), ("Social tax", "social_tax"),
                             ("Employee UI", "employee_unemployment_insurance"),
                             ("Employer UI", "employer_unemployment_insurance"),
                             ("II pillar", "funded_pension")):
            summary.append([label, workpaper["totals"][field]])
        payable = sum((workpaper["totals"][field] for field in ("income_tax", "social_tax", "employee_unemployment_insurance", "employer_unemployment_insurance", "funded_pension")), Decimal("0"))
        summary.append(["Total payable", payable])
        summary.append(["Validation messages", ""])
        for warning in workpaper["warnings"]:
            summary.append([warning])
        for sheet in book.worksheets:
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for cell in sheet[1]:
                cell.font = Font(name="Arial", bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="17365D")
            for column in sheet.columns:
                sheet.column_dimensions[column[0].column_letter].width = min(32, max(12, max(len(str(cell.value or "")) for cell in column) + 2))
        output = BytesIO()
        book.save(output)
        return output.getvalue()
