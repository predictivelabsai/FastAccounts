from __future__ import annotations

import json
import shutil
import socket
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest

import automation
from automation import AutomationService, add_interval
from core_utils import new_id, utc_now
from database import Database
from documents import DocumentService
from ledger import LedgerService
from organisations import OrganisationService


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Live network is forbidden")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.delenv("POSTMARK_API_TOKEN", raising=False)
    monkeypatch.delenv("FROM_EMAIL", raising=False)


def template(db, org, *, day=None, due=None, issued=False):
    docs = DocumentService(db)
    contact = docs.create_contact(org["id"], name="Synthetic customer", country_code="GB",
                                  email="customer@example.invalid", payment_terms_days=14)
    account = db.scalar("SELECT id FROM accounts WHERE organisation_id=? AND system_role='SALES'", (org["id"],))
    tax = db.scalar("SELECT id FROM tax_codes WHERE organisation_id=? AND code='UK20'", (org["id"],))
    day = day or db.scalar("SELECT starts_on FROM fiscal_periods WHERE organisation_id=? ORDER BY starts_on LIMIT 1", (org["id"],))
    invoice = docs.create_invoice(org["id"], contact_id=contact["id"], issue_date=day, due_date=due,
                                  actor="test", reference="Retainer", lines=[dict(description="Service", quantity="1.2500",
                                  unit_price="100.10", account_id=account, tax_code_id=tax)])
    return docs.issue_invoice(invoice["id"], actor="test") if issued else invoice


def schedule(db, org, **kwargs):
    invoice = template(db, org)
    return AutomationService(db).create_schedule(org["id"], template_invoice_id=invoice["id"], actor="test",
        interval_kind=kwargs.pop("interval_kind", "monthly"), next_run_date=kwargs.pop("next_run_date", invoice["issue_date"]), **kwargs)


def test_monthly_issue_balance_sequence_snapshot_restart(db, uk_org):
    service = AutomationService(db)
    s = schedule(db, uk_org)
    day = s["next_run_date"]
    with db.transaction() as tx:
        tx.execute("UPDATE invoice_lines SET unit_price=999 WHERE invoice_id=?", (s["template_invoice_id"],))
    original = DocumentService(db).issue_invoice(s["template_invoice_id"], actor="test")
    results = service.run_due(today=day)
    assert len(results) == 1 and results[0]["status"] == "Issued"
    invoice = results[0]["invoice"]
    assert int(invoice["number"][-6:]) == int(original["number"][-6:]) + 1
    assert Decimal(str(invoice["lines"][0]["unit_price"])) == Decimal("100.1")
    assert invoice["reference"] == "Retainer"
    assert invoice["due_date"] == (date.fromisoformat(day) + timedelta(days=14)).isoformat()
    entries = LedgerService(db).general_ledger(uk_org["id"], start=day, end=day)
    assert sum(Decimal(str(e["debit"])) for e in entries) == sum(Decimal(str(e["credit"])) for e in entries)
    assert service.schedule(s["id"], uk_org["id"])["next_run_date"] == add_interval(date.fromisoformat(day), s).isoformat()
    assert AutomationService(db).run_due(today=day) == []
    assert db.scalar("SELECT COUNT(*) FROM schedule_runs WHERE status='Issued'") == 1


def test_catch_up_three_months(db, uk_org):
    s = schedule(db, uk_org)
    start = date.fromisoformat(s["next_run_date"])
    second = add_interval(start, s)
    third = add_interval(second, s)
    results = AutomationService(db).run_due(today=add_interval(third, s) - timedelta(days=1))
    assert [r["invoice"]["issue_date"] for r in results] == [d.isoformat() for d in (start, second, third)]
    assert [r["invoice"]["number"][-6:] for r in results] == ["000001", "000002", "000003"]


@pytest.mark.parametrize("kind,days,start,expected", [
    ("weekly", None, "2026-01-31", "2026-02-07"),
    ("custom_days", 10, "2026-01-31", "2026-02-10"),
    ("monthly", None, "2026-01-31", "2026-02-28"),
    ("monthly", None, "2024-01-31", "2024-02-29"),
    ("quarterly", None, "2026-01-31", "2026-04-30"),
    ("quarterly", None, "2026-11-30", "2027-02-28"),
])
def test_intervals(kind, days, start, expected):
    assert add_interval(date.fromisoformat(start), {"interval_kind": kind, "interval_days": days}).isoformat() == expected


def test_end_pause_and_catchup_limit(db, uk_org):
    service = AutomationService(db)
    s = schedule(db, uk_org)
    day = date.fromisoformat(s["next_run_date"])
    service.update_schedule(s["id"], uk_org["id"], actor="test", end_date=day, active=False)
    assert service.run_due(today=day) == []
    service.update_schedule(s["id"], uk_org["id"], actor="test", active=True)
    assert len(service.run_due(today=day + timedelta(days=90))) == 1
    assert service.run_due(today=day + timedelta(days=90)) == []
    daily = schedule(db, uk_org, interval_kind="custom_days", interval_days=1)
    assert len(service.run_due(today=day + timedelta(days=30))) == 24
    assert len(service.run_due(today=day + timedelta(days=30))) == 7
    assert service.run_due(today=day + timedelta(days=30)) == []


def test_preclaimed_period_rolls_back_cas(db, uk_org):
    s = schedule(db, uk_org)
    with db.transaction() as tx:
        tx.execute("INSERT INTO schedule_runs(id,organisation_id,schedule_id,period_start,run_date,created_at) VALUES (?,?,?,?,?,?)",
                   (new_id(), uk_org["id"], s["id"], s["next_run_date"], s["next_run_date"], utc_now()))
    service = AutomationService(db)
    assert service.run_due(today=s["next_run_date"])[0]["status"] == "Skipped"
    assert service.schedule(s["id"], uk_org["id"])["next_run_date"] == s["next_run_date"]
    assert db.scalar("SELECT COUNT(*) FROM invoices WHERE status='Issued'") == 0


def test_failed_schedule_does_not_block_and_rolls_back(db, uk_org, ee_org):
    broken = schedule(db, uk_org)
    good = schedule(db, uk_org)
    foreign = db.scalar("SELECT id FROM accounts WHERE organisation_id=? AND system_role='SALES'", (ee_org["id"],))
    with db.transaction() as tx:
        tx.execute("UPDATE invoice_schedule_lines SET account_id=? WHERE schedule_id=?", (foreign, broken["id"]))
    results = AutomationService(db).run_due(today=good["next_run_date"])
    assert {r["status"] for r in results} == {"Failed", "Issued"}
    assert db.scalar("SELECT COUNT(*) FROM invoices") == 3
    assert db.scalar("SELECT COUNT(*) FROM posting_batches") == 1
    failed = db.one("SELECT * FROM schedule_runs WHERE schedule_id=?", (broken["id"],))
    assert failed["status"] == "Failed" and "organisation" in failed["error_message"]
    assert AutomationService(db).schedule(broken["id"], uk_org["id"])["next_run_date"] == broken["next_run_date"]


def test_reminder_ladder_and_toggle(db, uk_org):
    day = date.fromisoformat(db.scalar("SELECT starts_on FROM fiscal_periods WHERE organisation_id=? ORDER BY starts_on LIMIT 1", (uk_org["id"],))) + timedelta(days=30)
    invoices = [template(db, uk_org, due=(day + timedelta(days=offset)).isoformat(), issued=True) for offset in (3, -7, -14)]
    service = AutomationService(db)
    candidates = service.reminders_due(uk_org["id"], today=day)
    assert [[r["stage"] for r in candidates if r["invoice_id"] == inv["id"]] for inv in invoices] == [[0], [0, 1], [0, 1, 2]]
    assert all(not r["sent"] for r in candidates)
    with db.transaction() as tx:
        tx.execute("UPDATE invoices SET reminders_disabled=1 WHERE id=?", (invoices[0]["id"],))
    assert len(service.reminders_due(uk_org["id"], today=day)) == 5
    with db.transaction() as tx:
        tx.execute("UPDATE invoices SET reminders_disabled=0 WHERE id=?", (invoices[0]["id"],))
    assert len(service.reminders_due(uk_org["id"], today=day)) == 6


def email_client(monkeypatch, status=200, requests=None):
    monkeypatch.setenv("POSTMARK_API_TOKEN", "synthetic-token")
    monkeypatch.setenv("FROM_EMAIL", "sender@example.invalid")
    def respond(request):
        if requests is not None:
            requests.append(json.loads(request.content))
        return httpx.Response(status, json={"MessageID": "synthetic-message"})
    return httpx.Client(transport=httpx.MockTransport(respond))


def test_reminder_sent_delivery_and_idempotency(db, uk_org, monkeypatch):
    invoice = template(db, uk_org, issued=True)
    service = AutomationService(db)
    requests = []
    day = date.fromisoformat(invoice["due_date"]) - timedelta(days=3)
    with email_client(monkeypatch, requests=requests) as client:
        result = service.send_reminder(invoice["id"], uk_org["id"], stage=0, actor="test", client=client)
        assert result["status"] == result["delivery"]["status"] == "Sent"
        assert result["delivery_id"] == result["delivery"]["id"]
        assert service.process_reminders(today=day, client=client) == []
        with pytest.raises(ValueError, match="already sent"):
            service.send_reminder(invoice["id"], uk_org["id"], stage=0, actor="test", client=client)
    assert len(requests) == 1 and "Payment reminder" in requests[0]["Subject"]
    assert invoice["due_date"] in requests[0]["TextBody"]
    assert db.scalar("SELECT COUNT(*) FROM invoice_reminder_events") == 1


def test_failed_reminder_records_delivery_once(db, uk_org, monkeypatch):
    invoice = template(db, uk_org, issued=True)
    service = AutomationService(db)
    day = date.fromisoformat(invoice["due_date"]) - timedelta(days=3)
    with email_client(monkeypatch, status=500) as client:
        results = service.process_reminders(today=day, client=client)
    assert len(results) == 1 and results[0]["status"] == "Failed"
    assert results[0]["delivery"]["status"] == "Failed"
    assert results[0]["error_message"] == results[0]["delivery"]["error_message"]
    with email_client(monkeypatch) as client:
        results = service.process_reminders(today=day, client=client)
    assert results[0]["status"] == "Failed"
    assert "already sent or attempted" in results[0]["error_message"]
    assert db.scalar("SELECT COUNT(*) FROM invoice_reminder_events") == 1
    assert db.scalar("SELECT COUNT(*) FROM invoice_deliveries") == 1


def test_unconfigured_reminder_no_writes(db, uk_org, monkeypatch):
    invoice = template(db, uk_org, issued=True)
    monkeypatch.setenv("POSTMARK_API_TOKEN", "  ")
    monkeypatch.setenv("FROM_EMAIL", "sender@example.invalid")
    before = db.scalar("SELECT COUNT(*) FROM audit_events")
    with pytest.raises(ValueError) as error:
        AutomationService(db).send_reminder(invoice["id"], uk_org["id"], stage=0, actor="test")
    assert str(error.value) == "Email delivery is not connected. Set POSTMARK_API_TOKEN and FROM_EMAIL to send reminders."
    assert db.scalar("SELECT COUNT(*) FROM invoice_reminder_events") == 0
    assert db.scalar("SELECT COUNT(*) FROM invoice_deliveries") == 0
    assert db.scalar("SELECT COUNT(*) FROM audit_events") == before


def test_tenant_scoping(db, uk_org, ee_org, monkeypatch):
    service = AutomationService(db)
    s = schedule(db, uk_org)
    assert service.list_schedules(ee_org["id"]) == []
    assert service.reminders_due(ee_org["id"], today="2099-01-01") == []
    assert service.run_due(today=s["next_run_date"], organisation_ids=[ee_org["id"]]) == []
    assert service.run_due(today=s["next_run_date"], organisation_ids=[]) == []
    with pytest.raises(KeyError):
        service.schedule(s["id"], ee_org["id"])
    with pytest.raises(KeyError):
        service.update_schedule(s["id"], ee_org["id"], actor="test", active=False)
    with pytest.raises(KeyError):
        service.create_schedule(ee_org["id"], template_invoice_id=s["template_invoice_id"], interval_kind="monthly", next_run_date=s["next_run_date"], actor="test")
    with email_client(monkeypatch) as client, pytest.raises(KeyError):
        service.send_reminder(s["template_invoice_id"], ee_org["id"], stage=0, actor="test", client=client)


@pytest.mark.parametrize("changes", [dict(interval_kind="yearly"), dict(interval_kind="custom_days"),
    dict(interval_days=366), dict(end_date="1900-01-01"), dict(active=2)])
def test_schedule_validation(db, uk_org, changes):
    with pytest.raises(ValueError):
        schedule(db, uk_org, **changes)
    assert db.scalar("SELECT COUNT(*) FROM invoice_schedules") == 0


def test_issue_transaction_result_and_rollback(db, uk_org):
    invoice = template(db, uk_org)
    docs = DocumentService(db)
    with pytest.raises(RuntimeError, match="rollback"):
        with db.transaction() as tx:
            transactional = docs._issue_invoice_tx(tx, invoice["id"], "test")
            assert transactional["status"] == "Issued"
            raise RuntimeError("rollback")
    assert docs.invoice(invoice["id"])["status"] == "Draft"
    assert db.scalar("SELECT COUNT(*) FROM posting_batches") == 0
    public = docs.issue_invoice(invoice["id"], actor="test")
    for key in ("posting_batch_id", "issued_at", "updated_at"):
        transactional.pop(key)
        public.pop(key)
    assert transactional == public
    with db.transaction() as tx:
        assert docs.issue_invoice(invoice["id"], actor="test", tx=tx) == docs._issue_invoice_tx(tx, invoice["id"], "test")


def test_automation_tables_exist(db):
    tables = {row["name"] for row in db.rows("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"invoice_schedules", "invoice_schedule_lines", "schedule_runs", "invoice_reminder_events"} <= tables


def test_populated_upgrade_preserves_posted_data(tmp_path, monkeypatch):
    import database
    original = database.MIGRATIONS
    previous = tmp_path / "previous" / "sqlite"
    previous.mkdir(parents=True)
    for path in (original / "sqlite").glob("*.sql"):
        if path.stem < "0007":
            shutil.copyfile(path, previous / path.name)
    monkeypatch.setattr(database, "MIGRATIONS", previous.parent)
    db = Database(path=str(tmp_path / "upgrade.sqlite"))
    assert len(db.migrate()) == 6
    org = OrganisationService(db).create(name="Synthetic upgrade", country_code="UK", entity_type="UK_COMPANY", owner_email="test@example.invalid")
    invoice = template(db, org, issued=True)
    ledger = db.rows("SELECT * FROM gl_entries ORDER BY id")
    audits = db.rows("SELECT * FROM audit_events ORDER BY id")
    monkeypatch.setattr(database, "MIGRATIONS", original)
    assert db.migrate() == ["0007_automation", "0008_import_staging", "0009_local_accounts"]
    assert db.migrate() == []
    current = DocumentService(db).invoice(invoice["id"])
    assert current.pop("reminders_disabled") == 0
    assert current == invoice
    assert db.rows("SELECT * FROM gl_entries ORDER BY id") == ledger
    assert db.rows("SELECT * FROM audit_events ORDER BY id") == audits


def test_worker_opt_in_and_tick_isolation(db, uk_org, ee_org, monkeypatch):
    monkeypatch.delenv("FASTACCOUNTS_AUTOMATION_WORKER", raising=False)
    assert automation.start_automation_worker() is None
    service = AutomationService(db)
    calls = []
    def runs(**kwargs):
        calls.append(kwargs["organisation_ids"][0])
        if kwargs["organisation_ids"] == [uk_org["id"]]:
            raise RuntimeError("Synthetic failure")
        return []
    monkeypatch.setattr(service, "run_due", runs)
    result = service.worker_tick(today="2026-01-01")
    assert set(calls) == {uk_org["id"], ee_org["id"]}
    assert len(result["errors"]) == 1


def test_concurrent_schedule_claim_posts_once(db, uk_org):
    from concurrent.futures import ThreadPoolExecutor
    s = schedule(db, uk_org)
    def issue():
        return AutomationService(db)._claim_and_issue(s)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: issue(), range(2)))
    assert sorted(r["status"] for r in results) == ["Issued", "Skipped"]
    assert db.scalar("SELECT COUNT(*) FROM schedule_runs") == 1
    assert db.scalar("SELECT COUNT(*) FROM posting_batches") == 1


def test_schedule_failure_after_posting_rolls_back_everything(db, uk_org, monkeypatch):
    service = AutomationService(db)
    s = schedule(db, uk_org)
    original = service.documents._issue_invoice_tx
    def fail_after_posting(tx, invoice_id, actor):
        original(tx, invoice_id, actor)
        raise RuntimeError("Synthetic failure after posting")
    monkeypatch.setattr(service.documents, "_issue_invoice_tx", fail_after_posting)
    assert service.run_due(today=s["next_run_date"])[0]["status"] == "Failed"
    assert db.scalar("SELECT COUNT(*) FROM invoices") == 1
    assert db.scalar("SELECT COUNT(*) FROM posting_batches") == 0
    assert db.scalar("SELECT COUNT(*) FROM gl_entries") == 0
    assert db.scalar("SELECT COUNT(*) FROM audit_events WHERE action='invoice.issued'") == 0
    assert DocumentService(db).issue_invoice(s["template_invoice_id"], actor="test")["number"].endswith("000001")


def test_run_now_advances_one_period_and_is_tenant_scoped(db, uk_org, ee_org):
    service = AutomationService(db)
    s = schedule(db, uk_org)
    day = date.fromisoformat(s["next_run_date"])
    with pytest.raises(KeyError):
        service.run_now(s["id"], ee_org["id"], actor="test", today=day)
    result = service.run_now(s["id"], uk_org["id"], actor="test", today=day)
    assert result["invoice"]["issue_date"] == day.isoformat()
    assert result["period_start"] == day.isoformat()
    assert service.schedule(s["id"], uk_org["id"])["next_run_date"] == add_interval(day, s).isoformat()
    assert service.run_due(today=day) == []


def test_run_now_future_period_skipped_without_writes(db, uk_org):
    service = AutomationService(db)
    s = schedule(db, uk_org)
    day = date.fromisoformat(s["next_run_date"]) - timedelta(days=1)
    before = db.scalar("SELECT COUNT(*) FROM audit_events")
    assert s["active"]
    assert service.run_now(s["id"], uk_org["id"], actor="test", today=day) == {"schedule_id": s["id"], "status": "Skipped"}
    assert db.scalar("SELECT COUNT(*) FROM invoices") == 1
    assert DocumentService(db).invoice(s["template_invoice_id"])["status"] == "Draft"
    assert db.scalar("SELECT COUNT(*) FROM schedule_runs") == 0
    assert db.scalar("SELECT COUNT(*) FROM posting_batches") == 0
    assert db.scalar("SELECT COUNT(*) FROM audit_events") == before
    assert service.schedule(s["id"], uk_org["id"]) == s


def test_reminder_failure_does_not_block_next_invoice(db, uk_org, monkeypatch):
    bad = template(db, uk_org, issued=True)
    good = template(db, uk_org, issued=True)
    with db.transaction() as tx:
        tx.execute("UPDATE contacts SET email=NULL WHERE id=?", (bad["contact_id"],))
    day = date.fromisoformat(good["due_date"]) - timedelta(days=3)
    with email_client(monkeypatch) as client:
        results = AutomationService(db).process_reminders(today=day, client=client)
    assert {r["status"] for r in results} == {"Failed", "Sent"}
    assert db.scalar("SELECT COUNT(*) FROM invoice_reminder_events") == 2


def test_enabled_worker_stop_and_exception_recovery(monkeypatch):
    monkeypatch.setenv("FASTACCOUNTS_AUTOMATION_WORKER", "true")
    calls = []
    class Stop:
        def __init__(self):
            self.stopped = False
        def is_set(self):
            return self.stopped
        def set(self):
            self.stopped = True
        def wait(self, seconds):
            assert seconds == 17
            if len(calls) == 2:
                self.set()
    class Thread:
        def __init__(self, *, target, name, daemon):
            self.target, self.name, self.daemon = target, name, daemon
        def start(self):
            self.target()
    def tick(self):
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError("Synthetic tick failure")
        return {}
    monkeypatch.setattr(automation.threading, "Event", Stop)
    monkeypatch.setattr(automation.threading, "Thread", Thread)
    monkeypatch.setattr(AutomationService, "worker_tick", tick)
    thread = automation.start_automation_worker(poll_seconds=17)
    assert thread.daemon and thread.stop_event.is_set() and len(calls) == 2
