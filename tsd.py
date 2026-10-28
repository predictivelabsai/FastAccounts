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
from datetime import date, timedelta
from decimal import Decimal
from xml.etree import ElementTree as ET

from core_utils import audit, db_number, decimal, money, new_id, utc_now
from database import Database, get_database
from payroll_calendar import is_working_day
from payroll_payday import payday_for_period
from payroll_rules import settlement_date


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
    def _record(organisation: dict, run: dict, item: dict) -> dict:
        payment_date = date.fromisoformat(run['payment_date'])
        pension = money(item["funded_pension"])
        employee_ui = money(item["ui_employee"])
        exemption = money(item["tax_free_minimum"])
        gross = money(item["gross"])
        excluded_income = sum((money(line['amount']) for line in item.get('components', [])
                               if line['direction'] == 'income' and not line['income_tax']), Decimal(0))
        income_tax_base = money(max(Decimal("0"), gross - excluded_income - pension - employee_ui - exemption))
        values = {
            "declaration": "TSD",
            # Current payroll scope contains resident calculations only. Annex 2
            # stays in the declared mapping/scope and is not fabricated.
            "annex": TSD_ANNEX_MAPPING["EE_RESIDENT_PAYMENT"],
            "payment_record_id": item["id"],
            "pay_run_id": run["id"],
            "payment_date": payment_date.isoformat(),
            "payment_month": payment_date.strftime("%Y-%m"),
            "filing_deadline": _filing_deadline(payment_date).isoformat(),
            "payer_registration_no": organisation["registration_no"].strip(),
            "recipient_personal_id": item["employee_personal_id"].strip(),
            "recipient_name": item["employee_name"],
            "payment_classification": TSD_PAYMENT_CLASSIFICATION[item["pay_basis"]],
            "tsd_payment_type": int(item.get("tsd_payment_type") or {"monthly": 10, "hourly": 10, "board_fee": 21, "income_line": 17}[item["pay_basis"]]),
            "pay_basis": item["pay_basis"],
            "currency": "EUR",
            "gross_amount": gross,
            "tax_free_minimum": exemption,
            "income_tax_base": income_tax_base,
            "income_tax": money(item["income_tax"]),
            "employee_unemployment_insurance": employee_ui,
            "employer_unemployment_insurance": money(item["ui_employer"]),
            "funded_pension": pension,
            "social_tax_base": money(item["social_tax_base"]),
            "social_tax": money(item["social_tax"]),
            "net_amount": money(item["net"]),
            "employer_cost": money(item["employer_cost"]),
        }
        if set(values) != set(TSD_PAYMENT_FIELDS):
            raise AssertionError("TSD payment field mapping is incomplete")
        return values

    def _workpaper(self, tx, organisation_id: str, run_id: str) -> dict:
        organisation = self._organisation(tx, organisation_id, require_registration=True)
        run = self._run(tx, organisation_id, run_id)
        for item in run['items']:
            item['components'] = tx.rows('SELECT * FROM pay_item_components WHERE organisation_id=? AND item_id=? ORDER BY position', (organisation_id, item['id']))
        records = [self._record(organisation, run, item) for item in run["items"]]
        payment_month = run['payment_date'][:7]
        absence_rows = tx.rows("SELECT p.*,b.payout_date FROM payroll_absence_pay p "
                               "JOIN payroll_absence_payout_batches b ON b.organisation_id=p.organisation_id AND b.id=p.absence_payout_batch_id "
                               "WHERE p.organisation_id=? AND p.status IN ('in_payout','paid') AND b.status IN ('Approved','Paid') AND substr(b.payout_date,1,7)=? "
                               "ORDER BY p.employee_id,p.id", (organisation_id, payment_month))
        for absence in absence_rows:
            calc = json.loads(absence['calculation_json'])
            if not (calc.get('employee_personal_id') or '').strip():
                raise ValueError('TSD preparation requires a frozen personal ID for every absence payment record')
            payment_date = date.fromisoformat(absence['payout_date'])
            gross = money(calc['gross'])
            pension = money(calc['funded_pension'])
            ui_employee = money(calc['ui_employee'])
            exemption = money(calc['tax_free_minimum'])
            income_base = money(max(Decimal('0'), gross - pension - ui_employee - exemption))
            records.append({
                'declaration':'TSD','annex':TSD_ANNEX_MAPPING['EE_RESIDENT_PAYMENT'],
                'payment_record_id':absence['id'],'pay_run_id':absence['absence_payout_batch_id'],
                'payment_date':payment_date.isoformat(),'payment_month':payment_month,
                'filing_deadline':_filing_deadline(payment_date).isoformat(),
                'payer_registration_no':organisation['registration_no'].strip(),
                'recipient_personal_id':(calc.get('employee_personal_id') or '').strip(),
                'recipient_name':calc['employee_name'],'payment_classification':'EMPLOYMENT_SALARY',
                'tsd_payment_type':10,
                'pay_basis':'monthly','currency':'EUR','gross_amount':gross,
                'tax_free_minimum':exemption,'income_tax_base':income_base,
                'income_tax':money(calc['income_tax']),
                'employee_unemployment_insurance':ui_employee,
                'employer_unemployment_insurance':money(calc['ui_employer']),
                'funded_pension':pension,'social_tax_base':money(calc['social_tax_base']),
                'social_tax':money(calc['social_tax']),'net_amount':money(calc['net']),
                'employer_cost':money(calc['employer_cost']),
            })
        totals = {
            field: money(sum((decimal(record[field]) for record in records), Decimal("0")))
            for field in TSD_AMOUNT_FIELDS
        }
        absence_gross = sum((money(record['gross_amount']) for record in records[len(run['items']):]), Decimal(0))
        absence_net = sum((money(record['net_amount']) for record in records[len(run['items']):]), Decimal(0))
        absence_cost = sum((money(record['employer_cost']) for record in records[len(run['items']):]), Decimal(0))
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
            "warnings": [
                "NOT live-verified against e-MTA; accountant review and manual upload are required",
                "Current payroll calculations are resident-only, so payment records map to TSD Annex 1",
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
