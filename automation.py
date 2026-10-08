"""Recurring invoice issuance and payment reminder services."""
from __future__ import annotations

import calendar
import logging
import os
import sqlite3
import threading
from contextlib import nullcontext
from datetime import date, timedelta

import httpx
from psycopg import IntegrityError as PostgresIntegrityError

from core_utils import audit, db_number, decimal, money, new_id, utc_now
from database import Database, get_database
from documents import DocumentService

REMINDER_STAGES = ((0, -3), (1, 7), (2, 14))
MAX_CATCHUPS_PER_PASS = 24
AUTOMATION_ACTOR = "automation"
HTTP_CLIENT_FACTORY = lambda: httpx.Client(timeout=20)
_INTEGRITY_ERRORS = (sqlite3.IntegrityError, PostgresIntegrityError)
_log = logging.getLogger(__name__)
_reminder_lock = threading.RLock()


def email_configured() -> bool:
    return bool(os.getenv("POSTMARK_API_TOKEN", "").strip() and os.getenv("FROM_EMAIL", "").strip())


def email_status() -> dict:
    connected = email_configured()
    address = os.getenv("FROM_EMAIL", "").strip() if connected else ""
    local, separator, domain = address.partition("@")
    masked = local[:1] + "•••@" + domain if local and separator and domain else ""
    return {"connected": connected, "provider": "postmark", "from_email": masked}


def _date(value=None) -> date:
    return date.today() if value is None else value if isinstance(value, date) else date.fromisoformat(value)


def add_interval(run_date: date, schedule: dict) -> date:
    kind = schedule["interval_kind"]
    if kind == "weekly":
        return run_date + timedelta(days=7)
    if kind == "custom_days":
        days = schedule.get("interval_days")
        if not isinstance(days, int) or not 1 <= days <= 365:
            raise ValueError("Custom intervals require 1-365 days")
        return run_date + timedelta(days=days)
    if kind not in {"monthly", "quarterly"}:
        raise ValueError("Invalid interval kind")
    month_index = run_date.year * 12 + run_date.month - 1 + (1 if kind == "monthly" else 3)
    year, month = divmod(month_index, 12)
    month += 1
    return date(year, month, min(run_date.day, calendar.monthrange(year, month)[1]))


def start_automation_worker(poll_seconds=None) -> threading.Thread | None:
    if os.getenv("FASTACCOUNTS_AUTOMATION_WORKER") != "true":
        return None
    seconds = float(poll_seconds if poll_seconds is not None else os.getenv("FASTACCOUNTS_AUTOMATION_POLL_SECONDS", "60"))
    if seconds <= 0:
        raise ValueError("Automation poll interval must be positive")
    stop = threading.Event()

    def work():
        while not stop.is_set():
            try:
                AutomationService().worker_tick()
            except Exception:
                _log.exception("Automation tick failed")
            stop.wait(seconds)

    thread = threading.Thread(target=work, name="automation", daemon=True)
    thread.stop_event = stop
    thread.start()
    return thread


class AutomationService:
    def __init__(self, db: Database | None = None):
        self.db = db or get_database()
        self.documents = DocumentService(self.db)

    @staticmethod
    def _validate(schedule):
        add_interval(_date(schedule["next_run_date"]), schedule)
        days = schedule.get("interval_days")
        if days is not None and (not isinstance(days, int) or not 1 <= days <= 365):
            raise ValueError("Interval days must be between 1 and 365")
        if schedule.get("end_date") and _date(schedule["end_date"]) < _date(schedule["next_run_date"]):
            raise ValueError("End date must be on or after next run date")
        if schedule["active"] not in (0, 1) or schedule["auto_email"] not in (0, 1):
            raise ValueError("Active and auto_email must be boolean")

    def create_schedule(self, organisation_id: str, *, template_invoice_id: str,
                        interval_kind: str, next_run_date, actor: str, name: str = "",
                        interval_days: int | None = None, end_date=None,
                        auto_email=False, active=True) -> dict:
        values = dict(interval_kind=interval_kind, next_run_date=_date(next_run_date).isoformat(),
                      interval_days=interval_days, end_date=_date(end_date).isoformat() if end_date else None,
                      auto_email=auto_email, active=active)
        self._validate(values)
        schedule_id, now = new_id(), utc_now()
        with self.db.transaction() as tx:
            template = tx.one("SELECT * FROM invoices WHERE id=? AND organisation_id=? AND document_type='invoice'",
                              (template_invoice_id, organisation_id))
            if not template:
                raise KeyError("Template invoice not found")
            lines = tx.rows("SELECT * FROM invoice_lines WHERE invoice_id=? ORDER BY line_number", (template_invoice_id,))
            self.documents._document_lines(tx, organisation_id, lines, template["line_amount_type"])
            tx.execute(
                "INSERT INTO invoice_schedules(id,organisation_id,template_invoice_id,contact_id,name,interval_kind,interval_days,next_run_date,end_date,auto_email,active,amount_type,currency,reference,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (schedule_id, organisation_id, template_invoice_id, template["contact_id"], name,
                 interval_kind, interval_days, values["next_run_date"], values["end_date"], int(auto_email), int(active),
                 template["line_amount_type"], template["currency"], template["reference"], actor, now, now),
            )
            for line in lines:
                tx.execute("INSERT INTO invoice_schedule_lines(id,schedule_id,line_number,description,quantity,unit_price,account_id,tax_code_id) VALUES (?,?,?,?,?,?,?,?)",
                           (new_id(), schedule_id, line["line_number"], line["description"], db_number(decimal(line["quantity"])),
                            db_number(decimal(line["unit_price"])), line["account_id"], line["tax_code_id"]))
            audit(tx, organisation_id, actor, "schedule.created", "invoice_schedule", schedule_id)
        return self.schedule(schedule_id, organisation_id)

    def list_schedules(self, organisation_id: str) -> list[dict]:
        return self.db.rows(
            "SELECT s.*,c.name contact_name,r.run_date last_run_date,i.number last_invoice_number "
            "FROM invoice_schedules s JOIN contacts c ON c.id=s.contact_id AND c.organisation_id=s.organisation_id "
            "LEFT JOIN schedule_runs r ON r.id=(SELECT latest.id FROM schedule_runs latest "
            "WHERE latest.schedule_id=s.id AND latest.organisation_id=s.organisation_id "
            "ORDER BY latest.run_date DESC,latest.created_at DESC,latest.id DESC LIMIT 1) "
            "LEFT JOIN invoices i ON i.id=r.invoice_id AND i.organisation_id=s.organisation_id "
            "WHERE s.organisation_id=? ORDER BY s.next_run_date,s.id", (organisation_id,))

    def schedule(self, schedule_id: str, organisation_id: str) -> dict:
        row = self.db.one("SELECT * FROM invoice_schedules WHERE id=? AND organisation_id=?", (schedule_id, organisation_id))
        if not row:
            raise KeyError("Schedule not found")
        row["lines"] = self.db.rows("SELECT * FROM invoice_schedule_lines WHERE schedule_id=? ORDER BY line_number", (schedule_id,))
        row["runs"] = self.db.rows(
            "SELECT r.*,i.number invoice_number FROM schedule_runs r "
            "LEFT JOIN invoices i ON i.id=r.invoice_id AND i.organisation_id=r.organisation_id "
            "WHERE r.schedule_id=? AND r.organisation_id=? "
            "ORDER BY r.run_date DESC,r.created_at DESC,r.id DESC", (schedule_id, organisation_id))
        return row

    def update_schedule(self, schedule_id: str, organisation_id: str, *, actor: str, **changes) -> dict:
        allowed = {"name", "interval_kind", "interval_days", "next_run_date", "end_date", "auto_email", "active"}
        if changes.keys() - allowed:
            raise ValueError("Unsupported schedule fields")
        for key in ("next_run_date", "end_date"):
            if key in changes and changes[key] is not None:
                changes[key] = _date(changes[key]).isoformat()
        with self.db.transaction() as tx:
            row = tx.one("SELECT * FROM invoice_schedules WHERE id=? AND organisation_id=?", (schedule_id, organisation_id))
            if not row:
                raise KeyError("Schedule not found")
            self._validate(row | changes)
            for key in ("active", "auto_email"):
                if key in changes:
                    changes[key] = int(changes[key])
            fields = changes | {"updated_at": utc_now()}
            tx.execute("UPDATE invoice_schedules SET " + ",".join(f"{key}=?" for key in fields) + " WHERE id=? AND organisation_id=?",
                       (*fields.values(), schedule_id, organisation_id))
            audit(tx, organisation_id, actor, "schedule.updated", "invoice_schedule", schedule_id, changes)
        return self.schedule(schedule_id, organisation_id)

    def _insert_invoice(self, tx, schedule, run_date, actor):
        org_id = schedule["organisation_id"]
        contact = tx.one("SELECT * FROM contacts WHERE id=? AND organisation_id=?", (schedule["contact_id"], org_id))
        if not contact or contact["contact_type"] not in {"customer", "both"}:
            raise ValueError("A customer in this organisation is required")
        items = tx.rows("SELECT * FROM invoice_schedule_lines WHERE schedule_id=? ORDER BY line_number", (schedule["id"],))
        lines, subtotal, tax_total, total = self.documents._document_lines(tx, org_id, items, schedule["amount_type"])
        invoice_id, now = new_id(), utc_now()
        currency = schedule["currency"] or tx.scalar("SELECT base_currency FROM organisations WHERE id=?", (org_id,))
        tx.execute("INSERT INTO invoices(id,organisation_id,contact_id,document_type,issue_date,tax_point_date,due_date,currency,line_amount_type,reference,subtotal,tax_total,total,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (invoice_id, org_id, contact["id"], "invoice", run_date.isoformat(), run_date.isoformat(),
                    (run_date + timedelta(days=contact["payment_terms_days"])).isoformat(), currency, schedule["amount_type"],
                    schedule["reference"], db_number(subtotal), db_number(tax_total), db_number(total), actor, now, now))
        for line in lines:
            tx.execute("INSERT INTO invoice_lines(id,invoice_id,line_number,description,quantity,unit_price,account_id,tax_code_id,tax_rate,net_amount,tax_amount,gross_amount) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (line["id"], invoice_id, line["line_number"], line["description"], db_number(line["quantity"]),
                        db_number(line["unit_price"]), line["account_id"], line["tax_code_id"], db_number(line["tax_rate"]),
                        db_number(line["net_amount"]), db_number(line["tax_amount"]), db_number(line["gross_amount"])))
        audit(tx, org_id, actor, "invoice.created", "invoice", invoice_id, {"document_type": "invoice", "total": str(total)})
        return invoice_id

    def _claim_and_issue(self, schedule: dict, *, actor=AUTOMATION_ACTOR, run_date=None) -> dict:
        period = schedule["next_run_date"]
        day = _date(run_date or period)
        result = {"schedule_id": schedule["id"], "period_start": period, "run_date": day.isoformat()}
        run_id, now = new_id(), utc_now()
        try:
            with self.db.transaction() as tx:
                claimed = tx.execute("UPDATE invoice_schedules SET next_run_date=?,updated_at=? WHERE id=? AND organisation_id=? AND active=1 AND next_run_date=?",
                                     (add_interval(_date(period), schedule).isoformat(), now, schedule["id"], schedule["organisation_id"], period))
                if claimed.rowcount != 1:
                    return result | {"status": "Skipped"}
                tx.execute("INSERT INTO schedule_runs(id,organisation_id,schedule_id,period_start,run_date,status,created_at) VALUES (?,?,?,?,?,'Claimed',?)",
                           (run_id, schedule["organisation_id"], schedule["id"], period, day.isoformat(), now))
                invoice_id = self._insert_invoice(tx, schedule, day, actor)
                invoice = self.documents._issue_invoice_tx(tx, invoice_id, actor)
                tx.execute("UPDATE schedule_runs SET status='Issued',invoice_id=?,completed_at=? WHERE id=?", (invoice_id, utc_now(), run_id))
                audit(tx, schedule["organisation_id"], actor, "schedule.run", "invoice_schedule", schedule["id"], {"run_id": run_id, "invoice_id": invoice_id})
        except _INTEGRITY_ERRORS:
            if self.db.one("SELECT id FROM schedule_runs WHERE schedule_id=? AND period_start=?", (schedule["id"], period)):
                return result | {"status": "Skipped"}
            raise
        result |= {"id": run_id, "status": "Issued", "invoice_id": invoice_id, "invoice": invoice}
        if schedule["auto_email"] and email_configured():
            try:
                result["delivery"] = self.documents.send_invoice_email(invoice_id, actor=actor)
            except Exception as exc:
                result["email_error"] = str(exc)
        return result

    def _run_period(self, schedule, actor, run_date=None):
        try:
            return self._claim_and_issue(schedule, actor=actor, run_date=run_date)
        except Exception as exc:
            result = {"schedule_id": schedule["id"], "period_start": schedule["next_run_date"],
                      "run_date": _date(run_date or schedule["next_run_date"]).isoformat(), "status": "Failed", "error_message": str(exc)[:500]}
            try:
                with self.db.transaction() as tx:
                    tx.execute("INSERT INTO schedule_runs(id,organisation_id,schedule_id,period_start,run_date,status,error_message,created_at,completed_at) VALUES (?,?,?,?,?,'Failed',?,?,?)",
                               (new_id(), schedule["organisation_id"], schedule["id"], result["period_start"], result["run_date"], result["error_message"], utc_now(), utc_now()))
                    audit(tx, schedule["organisation_id"], actor, "schedule.failed", "invoice_schedule", schedule["id"], result)
            except _INTEGRITY_ERRORS:
                result["status"] = "Skipped"
            return result

    def run_now(self, schedule_id: str, organisation_id: str, *, actor: str, today=None) -> dict:
        schedule = self.schedule(schedule_id, organisation_id)
        if not schedule["active"] or (schedule["end_date"] and (_date(schedule["next_run_date"]) > _date(schedule["end_date"]) or _date(today) > _date(schedule["end_date"]))):
            return {"schedule_id": schedule_id, "status": "Skipped"}
        return self._run_period(schedule, actor, _date(today))

    def _organisations(self, organisation_ids):
        return list(organisation_ids) if organisation_ids is not None else [row["id"] for row in self.db.rows("SELECT id FROM organisations ORDER BY id")]

    def run_due(self, *, today=None, organisation_ids=None, actor=AUTOMATION_ACTOR) -> list[dict]:
        day, results = _date(today), []
        for org_id in self._organisations(organisation_ids):
            for schedule in self.list_schedules(org_id):
                try:
                    for _ in range(MAX_CATCHUPS_PER_PASS):
                        if not schedule["active"] or _date(schedule["next_run_date"]) > day or (schedule["end_date"] and schedule["next_run_date"] > schedule["end_date"]):
                            break
                        result = self._run_period(schedule, actor)
                        results.append(result)
                        if result["status"] != "Issued":
                            break
                        schedule = self.schedule(schedule["id"], org_id)
                except Exception as exc:
                    results.append({"schedule_id": schedule["id"], "status": "Failed", "error_message": str(exc)[:500]})
        return results

    def reminders_due(self, organisation_id: str, *, today=None) -> list[dict]:
        day, results = _date(today), []
        invoices = self.db.rows("SELECT i.*,c.name contact_name,c.email contact_email FROM invoices i JOIN contacts c ON c.id=i.contact_id AND c.organisation_id=i.organisation_id WHERE i.organisation_id=? AND i.document_type='invoice' AND i.status IN ('Issued','Part Paid') AND i.paid_total<i.total AND i.reminders_disabled=0 ORDER BY i.due_date,i.id", (organisation_id,))
        for invoice in invoices:
            sent = {row["ladder_stage"] for row in self.db.rows("SELECT ladder_stage FROM invoice_reminder_events WHERE invoice_id=? AND organisation_id=? AND status='Sent'", (invoice["id"], organisation_id))}
            for stage, offset in REMINDER_STAGES:
                target = _date(invoice["due_date"]) + timedelta(days=offset)
                if target <= day:
                    results.append({"invoice_id": invoice["id"], "number": invoice["number"], "contact_name": invoice["contact_name"],
                                    "contact_email": invoice["contact_email"], "due_date": invoice["due_date"], "stage": stage,
                                    "target_date": target.isoformat(), "days_delta": (day - _date(invoice["due_date"])).days,
                                    "sent": stage in sent, "reminders_disabled": invoice["reminders_disabled"]})
        return results

    def set_reminders_opt_out(self, invoice_id: str, organisation_id: str, *, reminders_disabled: bool, actor: str) -> dict:
        with self.db.transaction() as tx:
            updated = tx.execute("UPDATE invoices SET reminders_disabled=? WHERE id=? AND organisation_id=?",
                                 (int(reminders_disabled), invoice_id, organisation_id))
            if updated.rowcount != 1:
                raise KeyError("Invoice not found")
            audit(tx, organisation_id, actor, "reminder.opt_out" if reminders_disabled else "reminder.opt_in",
                  "invoice", invoice_id)
        return {"invoice_id": invoice_id, "reminders_disabled": reminders_disabled}

    def send_reminder(self, invoice_id: str, organisation_id: str, *, stage: int, actor: str, client=None) -> dict:
        if not email_configured() and client is None:
            raise ValueError("Email delivery is not connected. Set POSTMARK_API_TOKEN and FROM_EMAIL to send reminders.")
        if stage not in {0, 1, 2}:
            raise ValueError("Invalid reminder stage")
        with _reminder_lock:
            invoice = self.documents.invoice(invoice_id, organisation_id)
            if invoice["document_type"] != "invoice" or invoice["status"] not in {"Issued", "Part Paid"} or decimal(invoice["paid_total"]) >= decimal(invoice["total"]) or invoice["reminders_disabled"]:
                raise ValueError("Invoice is not eligible for reminders")
            previous = self.db.one("SELECT * FROM invoice_reminder_events WHERE invoice_id=? AND ladder_stage=?", (invoice_id, stage))
            if previous:
                raise ValueError("Reminder stage already sent or attempted")
            before = {r["id"] for r in self.db.rows("SELECT id FROM invoice_deliveries WHERE invoice_id=?", (invoice_id,))}
            delivery, error = None, None
            try:
                with nullcontext(client) if client is not None else HTTP_CLIENT_FACTORY() as http:
                    delivery = self.documents.send_invoice_email(invoice_id, actor=actor, client=http,
                        subject=f"Payment reminder: invoice {invoice['number']}",
                        text_body=f"Payment reminder for invoice {invoice['number']}: {invoice['currency']} {money(decimal(invoice['total']) - decimal(invoice['paid_total'])):.2f} outstanding, due {invoice['due_date']}. Please arrange payment.")
            except Exception as exc:
                error = str(exc)[:500]
                deliveries = self.db.rows("SELECT * FROM invoice_deliveries WHERE invoice_id=? AND organisation_id=? ORDER BY created_at DESC", (invoice_id, organisation_id))
                delivery = next((row for row in deliveries if row["id"] not in before and row["status"] == "Failed"), None)
            status = delivery["status"] if delivery else "Failed"
            event_id = new_id()
            try:
                with self.db.transaction() as tx:
                    values = (status, delivery["id"] if delivery else None, delivery["error_message"] if delivery else error, utc_now())
                    tx.execute("INSERT INTO invoice_reminder_events(id,organisation_id,invoice_id,ladder_stage,due_date,status,delivery_id,error_message,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                               (event_id, organisation_id, invoice_id, stage, invoice["due_date"], *values))
                    audit(tx, organisation_id, actor, "reminder.sent" if status == "Sent" else "reminder.failed", "invoice_reminder_event", event_id, {"invoice_id": invoice_id, "stage": stage})
            except _INTEGRITY_ERRORS as exc:
                raise ValueError("Reminder stage already sent") from exc
            return (self.db.one("SELECT * FROM invoice_reminder_events WHERE id=?", (event_id,)) or {}) | {"delivery": delivery}

    def process_reminders(self, *, today=None, organisation_ids=None, actor=AUTOMATION_ACTOR, client=None) -> list[dict]:
        results = []
        for org_id in self._organisations(organisation_ids):
            for candidate in self.reminders_due(org_id, today=today):
                if candidate["sent"]:
                    continue
                try:
                    results.append(self.send_reminder(candidate["invoice_id"], org_id, stage=candidate["stage"], actor=actor, client=client))
                except Exception as exc:
                    results.append(candidate | {"status": "Failed", "error_message": str(exc)[:500]})
        return results

    def worker_tick(self, *, today=None) -> dict:
        result = {"runs": [], "reminders": [], "errors": []}
        for org_id in self._organisations(None):
            for key, method in (("runs", self.run_due), ("reminders", self.process_reminders)):
                try:
                    result[key].extend(method(today=today, organisation_ids=[org_id]))
                except Exception as exc:
                    result["errors"].append({"organisation_id": org_id, "operation": key, "error_message": str(exc)[:500]})
        return result
