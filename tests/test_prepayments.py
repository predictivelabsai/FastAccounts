"""Synthetic prepayment posting, allocation, refund and tenancy regressions."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
import shutil

import pytest
from fastapi.testclient import TestClient

from core_utils import money, new_id
from database import Database, reset_database_cache
from documents import DocumentService
from ledger import LedgerService
from organisations import OrganisationService
from prepayments import PrepaymentService

ACTOR = "owner@example.test"


def setup(db, org, side="customer", *, total="100", document_type=None, posted=True):
    docs = DocumentService(db)
    contact = docs.create_contact(org["id"], name="Synthetic prepayment contact", country_code=org["country_code"])
    bank = docs.create_bank_account(org["id"], name="Synthetic prepayment bank", currency=org["base_currency"])
    accounts = {r["system_role"]: r["id"] for r in db.rows("SELECT * FROM accounts WHERE organisation_id=?", (org["id"],))}
    day = db.scalar("SELECT starts_on FROM fiscal_periods WHERE organisation_id=? ORDER BY starts_on LIMIT 1", (org["id"],))
    lines = [dict(description="Synthetic service", unit_price=total, account_id=accounts["SALES" if side == "customer" else "EXPENSE"])]
    if side == "customer":
        document = docs.create_invoice(org["id"], contact_id=contact["id"], issue_date=day, due_date=day,
            actor=ACTOR, lines=lines, document_type=document_type or "invoice")
        if posted:
            document = docs.issue_invoice(document["id"], actor=ACTOR)
    else:
        document = docs.create_bill(org["id"], contact_id=contact["id"], bill_date=day, due_date=day,
            supplier_number="SYN-1", actor=ACTOR, lines=lines, document_type=document_type or "bill")
        if posted:
            document = docs.approve_bill(document["id"], actor=ACTOR)
    create = dict(side=side, contact_id=contact["id"], bank_account_id=bank["id"], document_date=day,
                  amount="200", idempotency_key="create", actor=ACTOR, reference="PRE-SYN")
    allocate = dict(document_type="invoice" if side == "customer" else "bill", document_id=document["id"],
                    allocation_date=day, amount="40", idempotency_key="allocate", actor=ACTOR)
    return docs, contact, bank, accounts, day, document, create, allocate


def entries(db, batch_id):
    return db.rows("SELECT g.*,a.system_role FROM gl_entries g JOIN accounts a ON a.id=g.account_id "
                   "WHERE g.posting_batch_id=? ORDER BY g.line_number", (batch_id,))


def assert_balanced(db, batch_id, amount):
    rows = entries(db, batch_id)
    assert sum(money(r["debit"]) for r in rows) == sum(money(r["credit"]) for r in rows) == Decimal(amount)
    assert db.scalar("SELECT status FROM posting_batches WHERE id=?", (batch_id,)) == "Posted"
    return rows


@pytest.mark.parametrize("org_fixture", ["uk_org", "ee_org"])
@pytest.mark.parametrize("side", ["customer", "supplier"])
def test_post_allocate_refund_balance_idempotency_and_status(request, db, org_fixture, side):
    org = request.getfixturevalue(org_fixture)
    docs, contact, bank, accounts, day, document, create, allocate = setup(db, org, side)
    service = PrepaymentService(db)
    control = "CUSTOMER_PREPAYMENTS" if side == "customer" else "SUPPLIER_PREPAYMENTS"
    prepayment = service.create(org["id"], **create)
    assert service.create(org["id"], **create) == prepayment
    initial_entries = assert_balanced(db, prepayment["posting_batch_id"], "200")
    assert {r["account_id"] for r in initial_entries} == {bank["ledger_account_id"], accounts[control]}
    assert money(next(r for r in initial_entries if r["account_id"] == bank["ledger_account_id"])["debit" if side == "customer" else "credit"]) == 200
    original_bank = db.scalar("SELECT SUM(debit-credit) FROM gl_entries WHERE account_id=?", (bank["ledger_account_id"],))
    first = service.allocate(org["id"], prepayment["id"], **allocate)
    assert service.allocate(org["id"], prepayment["id"], **allocate) == first
    allocation_entries = assert_balanced(db, first["posting_batch_id"], "40")
    assert {r["system_role"] for r in allocation_entries} == {control, "AR" if side == "customer" else "AP"}
    assert all(r["contact_id"] == contact["id"] for r in allocation_entries)
    assert db.scalar("SELECT SUM(debit-credit) FROM gl_entries WHERE account_id=?", (bank["ledger_account_id"],)) == original_bank
    get_document = docs.invoice if side == "customer" else docs.bill
    assert get_document(document["id"])["status"] == "Part Paid"
    assert money(get_document(document["id"])["paid_total"]) == 40
    second = service.allocate(org["id"], prepayment["id"], **{**allocate, "amount": "60", "idempotency_key": "allocate-2"})
    assert_balanced(db, second["posting_batch_id"], "60")
    assert get_document(document["id"])["status"] == "Paid"
    assert money(get_document(document["id"])["paid_total"]) == 100
    assert service.get(org["id"], prepayment["id"])["unallocated_balance"] == 100
    outstanding = service.outstanding(org["id"], contact["id"])
    assert outstanding["totals"][side] == 100 and len(outstanding["items"]) == 1
    refund_args = dict(refund_date=day, amount="30", idempotency_key="refund", actor=ACTOR, reference="REF-SYN")
    refund = service.refund(org["id"], prepayment["id"], **refund_args)
    assert service.refund(org["id"], prepayment["id"], **refund_args) == refund
    refund_entries = assert_balanced(db, refund["posting_batch_id"], "30")
    assert {r["account_id"] for r in refund_entries} == {bank["ledger_account_id"], accounts[control]}
    assert {r["reverses_entry_id"] for r in refund_entries} == {r["id"] for r in initial_entries}
    assert db.scalar("SELECT reverses_batch_id FROM posting_batches WHERE id=?", (refund["posting_batch_id"],)) == prepayment["posting_batch_id"]
    # A partial refund does not reverse the entire original prepayment.
    assert db.scalar("SELECT status FROM posting_batches WHERE id=?", (prepayment["posting_batch_id"],)) == "Posted"
    service.refund(org["id"], prepayment["id"], **{**refund_args, "amount": "70", "idempotency_key": "refund-2"})
    final = service.get(org["id"], prepayment["id"])
    assert final["unallocated_balance"] == 0 and len(final["allocations"]) == len(final["refunds"]) == 2
    assert service.outstanding(org["id"], contact["id"])["items"] == []
    assert len(service.list(org["id"], side=side, contact_id=contact["id"])) == 1
    assert service.list(org["id"], outstanding_only=True) == []
    assert len(entries(db, prepayment["posting_batch_id"])) == 2
    assert db.scalar("SELECT COUNT(*) FROM posting_batches WHERE voucher_type='prepayment'") == 1
    assert db.scalar("SELECT COUNT(*) FROM posting_batches WHERE voucher_type='prepayment_allocation'") == 2
    assert db.scalar("SELECT COUNT(*) FROM posting_batches WHERE voucher_type='prepayment_refund'") == 2
    with pytest.raises(Exception, match="immutable"):
        with db.transaction() as tx:
            tx.execute("UPDATE gl_entries SET debit=99 WHERE posting_batch_id=?", (prepayment["posting_batch_id"],))


@pytest.mark.parametrize("side", ["customer", "supplier"])
def test_full_unallocated_refund_restores_bank_and_control(db, ee_org, side):
    _, contact, bank, accounts, day, document, create, allocate = setup(db, ee_org, side)
    service = PrepaymentService(db)
    prepayment = service.create(ee_org["id"], **create)
    refund = service.refund(ee_org["id"], prepayment["id"], refund_date=day, amount="200",
                            idempotency_key="refund", actor=ACTOR)
    assert_balanced(db, refund["posting_batch_id"], "200")
    for account_id in [bank["ledger_account_id"], accounts["CUSTOMER_PREPAYMENTS" if side == "customer" else "SUPPLIER_PREPAYMENTS"]]:
        assert money(db.scalar("SELECT SUM(debit-credit) FROM gl_entries WHERE account_id=?", (account_id,))) == 0
    assert service.get(ee_org["id"], prepayment["id"])["unallocated_balance"] == 0


@pytest.mark.parametrize("side", ["customer", "supplier"])
@pytest.mark.parametrize("posted,credit", [(False, False), (True, True)])
def test_draft_and_credit_documents_are_not_allocatable(db, ee_org, side, posted, credit):
    credit_type = ("credit_note" if side == "customer" else "supplier_credit") if credit else None
    *_, create, allocate = setup(db, ee_org, side, posted=posted, document_type=credit_type)
    service = PrepaymentService(db)
    prepayment = service.create(ee_org["id"], **create)
    with pytest.raises(ValueError, match="open document"):
        service.allocate(ee_org["id"], prepayment["id"], **allocate)
    assert service.get(ee_org["id"], prepayment["id"])["unallocated_balance"] == 200
    assert db.scalar("SELECT COUNT(*) FROM prepayment_allocations") == 0


@pytest.mark.parametrize("side", ["customer", "supplier"])
def test_overallocation_closed_documents_dates_and_failed_events_rollback(db, ee_org, side):
    docs, contact, bank, accounts, day, document, create, allocate = setup(db, ee_org, side)
    service, oid = PrepaymentService(db), ee_org["id"]
    prepayment = service.create(oid, **create)
    before = db.rows("SELECT * FROM gl_entries ORDER BY id")
    for args, message in [({"amount": "201"}, "unallocated"), ({"amount": "101"}, "open document balance"),
                          ({"allocation_date": (date.fromisoformat(day)-timedelta(days=1)).isoformat()}, "precede"),
                          ({"document_type": "bill" if side == "customer" else "invoice"}, "does not match")]:
        with pytest.raises(ValueError, match=message):
            service.allocate(oid, prepayment["id"], **{**allocate, **args})
    assert db.rows("SELECT * FROM gl_entries ORDER BY id") == before
    service.allocate(oid, prepayment["id"], **{**allocate, "amount": "100"})
    with pytest.raises(ValueError, match="open document"):
        service.allocate(oid, prepayment["id"], **{**allocate, "idempotency_key": "closed"})
    for amount in ["101", "200"]:
        with pytest.raises(ValueError, match="unallocated"):
            service.refund(oid, prepayment["id"], refund_date=day, amount=amount, idempotency_key="refund", actor=ACTOR)
    assert service.get(oid, prepayment["id"])["unallocated_balance"] == 100


def test_tenant_and_contact_isolation(db, ee_org, uk_org):
    docs, contact, bank, accounts, day, document, create, allocate = setup(db, ee_org)
    _, foreign_contact, foreign_bank, _, _, foreign_doc, _, _ = setup(db, uk_org)
    service, oid = PrepaymentService(db), ee_org["id"]
    for args, error in [({"contact_id": foreign_contact["id"]}, KeyError), ({"bank_account_id": foreign_bank["id"]}, ValueError)]:
        with pytest.raises(error):
            service.create(oid, **{**create, **args})
    prepayment = service.create(oid, **create)
    assert service.list(uk_org["id"]) == []
    for operation in [lambda: service.get(uk_org["id"], prepayment["id"]),
                      lambda: service.allocate(uk_org["id"], prepayment["id"], **allocate),
                      lambda: service.refund(uk_org["id"], prepayment["id"], refund_date=day, amount="1", idempotency_key="f", actor=ACTOR),
                      lambda: service.outstanding(uk_org["id"], contact["id"])]:
        with pytest.raises(KeyError):
            operation()
    for target in [foreign_doc["id"]]:
        with pytest.raises(ValueError, match="same contact"):
            service.allocate(oid, prepayment["id"], **{**allocate, "document_id": target})
    other_contact = docs.create_contact(oid, name="Other synthetic contact", country_code="EE")
    other_doc = docs.create_invoice(oid, contact_id=other_contact["id"], issue_date=day, actor=ACTOR,
                                   lines=[dict(unit_price="100", account_id=accounts["SALES"])])
    docs.issue_invoice(other_doc["id"], actor=ACTOR)
    with pytest.raises(ValueError, match="same contact"):
        service.allocate(oid, prepayment["id"], **{**allocate, "document_id": other_doc["id"]})
    # Composite foreign keys also prevent tenant mixing below the service.
    with pytest.raises(Exception, match="FOREIGN KEY"):
        with db.transaction() as tx:
            tx.execute("UPDATE prepayments SET contact_id=? WHERE id=?", (foreign_contact["id"], prepayment["id"]))


@pytest.mark.parametrize("amount", ["0", "-1", "0.004", "NaN", "Infinity", "invalid"])
def test_invalid_money(db, ee_org, amount):
    *_, create, allocate = setup(db, ee_org)
    with pytest.raises(ValueError, match="positive and finite"):
        PrepaymentService(db).create(ee_org["id"], **{**create, "amount": amount})
    assert db.scalar("SELECT COUNT(*) FROM prepayments") == 0


def test_rounding_currency_contact_type_and_idempotency_conflicts(db, ee_org):
    docs, contact, bank, accounts, day, document, create, allocate = setup(db, ee_org)
    service, oid = PrepaymentService(db), ee_org["id"]
    for currency in ["USD", "GBP"]:
        with pytest.raises(ValueError, match="match the bank"):
            service.create(oid, **create, currency=currency)
    usd = docs.create_bank_account(oid, name="Synthetic USD", currency="USD")
    foreign = service.create(oid, **{**create, "bank_account_id": usd["id"], "idempotency_key": "foreign"})
    assert foreign["currency"] == "USD"
    supplier = docs.create_contact(oid, name="Synthetic supplier only", country_code="EE", contact_type="supplier")
    with pytest.raises(ValueError, match="Contact type"):
        service.create(oid, **{**create, "contact_id": supplier["id"]})
    prepayment = service.create(oid, **{**create, "amount": "200.005"})
    assert prepayment["amount"] == Decimal("200.01")
    with pytest.raises(ValueError, match="different details"):
        service.create(oid, **create)
    first = service.allocate(oid, prepayment["id"], **allocate)
    with pytest.raises(ValueError, match="different details"):
        service.allocate(oid, prepayment["id"], **{**allocate, "amount": "41"})
    refund = dict(refund_date=day, amount="10", idempotency_key="refund", actor=ACTOR)
    service.refund(oid, prepayment["id"], **refund)
    with pytest.raises(ValueError, match="different details"):
        service.refund(oid, prepayment["id"], **{**refund, "reference": "Changed"})
    assert service.get(oid, prepayment["id"])["unallocated_balance"] == Decimal("150.01")
    with pytest.raises(ValueError, match="idempotency key"):
        service.create(oid, **{**create, "idempotency_key": " "})


@pytest.mark.parametrize("event", ["create", "allocate", "refund"])
def test_locked_period_rolls_back_event(db, ee_org, event):
    _, _, _, _, day, document, create, allocate = setup(db, ee_org)
    service, oid = PrepaymentService(db), ee_org["id"]
    if event != "create":
        prepayment = service.create(oid, **create)
    period = db.scalar("SELECT id FROM fiscal_periods WHERE organisation_id=? AND starts_on=?", (oid, day))
    LedgerService(db).lock_period(period, actor=ACTOR, reason="Synthetic lock")
    before = db.rows("SELECT * FROM gl_entries ORDER BY id")
    with pytest.raises(ValueError, match="locked"):
        if event == "create":
            service.create(oid, **create)
        elif event == "allocate":
            service.allocate(oid, prepayment["id"], **allocate)
        else:
            service.refund(oid, prepayment["id"], refund_date=day, amount="40", idempotency_key="refund", actor=ACTOR)
    assert db.rows("SELECT * FROM gl_entries ORDER BY id") == before
    assert db.scalar("SELECT paid_total FROM invoices WHERE id=?", (document["id"],)) == 0
    if event != "create":
        assert service.get(oid, prepayment["id"])["unallocated_balance"] == 200


@pytest.mark.parametrize("event", ["create", "allocate", "refund"])
def test_concurrent_retries_are_idempotent(db, ee_org, event):
    *_, day, document, create, allocate = setup(db, ee_org)
    service, oid = PrepaymentService(db), ee_org["id"]
    prepayment = service.create(oid, **create)
    def perform(_):
        worker = PrepaymentService(db)
        if event == "create":
            return worker.create(oid, **create)
        if event == "allocate":
            return worker.allocate(oid, prepayment["id"], **allocate)
        return worker.refund(oid, prepayment["id"], refund_date=day, amount="40", idempotency_key="refund", actor=ACTOR)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(perform, range(2)))
    assert results[0] == results[1]
    assert service.get(oid, prepayment["id"])["unallocated_balance"] == (200 if event == "create" else 160)


def test_concurrent_distinct_allocations_cannot_exceed_document(db, ee_org):
    *_, create, allocate = setup(db, ee_org)
    service, oid = PrepaymentService(db), ee_org["id"]
    prepayment = service.create(oid, **create)
    def perform(index):
        try:
            PrepaymentService(db).allocate(oid, prepayment["id"], **{**allocate, "amount": "75", "idempotency_key": f"allocate-{index}"})
            return "posted"
        except ValueError as exc:
            return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(perform, range(2)))
    assert results.count("posted") == 1
    assert results.count("Allocation exceeds the open document balance") == 1
    assert service.get(oid, prepayment["id"])["unallocated_balance"] == 125


@pytest.mark.parametrize("event", ["create", "allocate", "refund"])
def test_failure_after_posting_rolls_back_ledger_event_and_balances(db, ee_org, monkeypatch, event):
    *_, day, document, create, allocate = setup(db, ee_org)
    service, oid = PrepaymentService(db), ee_org["id"]
    if event != "create":
        prepayment = service.create(oid, **create)
    tables = ["gl_entries", "posting_batches", "prepayments", "prepayment_allocations", "prepayment_refunds", "invoices", "audit_events"]
    before = {table: db.rows(f"SELECT * FROM {table} ORDER BY id") for table in tables}
    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic persistence failure")
    monkeypatch.setattr(service.repo, "insert" if event == "create" else "set_paid" if event == "allocate" else "set_balance", fail)
    with pytest.raises(RuntimeError, match="Synthetic persistence"):
        if event == "create":
            service.create(oid, **create)
        elif event == "allocate":
            service.allocate(oid, prepayment["id"], **allocate)
        else:
            service.refund(oid, prepayment["id"], refund_date=day, amount="40", idempotency_key="refund", actor=ACTOR)
    assert {table: db.rows(f"SELECT * FROM {table} ORDER BY id") for table in tables} == before


@pytest.mark.parametrize("country", ["UK", "EE"])
@pytest.mark.parametrize("existing_customer_role", [False, True])
def test_upgrade_adds_missing_roles_preserves_chart_and_ledger(tmp_path, monkeypatch, country, existing_customer_role):
    import database
    import organisations
    original = database.MIGRATIONS
    previous = tmp_path / "previous" / "sqlite"
    previous.mkdir(parents=True)
    for path in (original / "sqlite").glob("*.sql"):
        if path.stem < "0017":
            shutil.copyfile(path, previous / path.name)
    monkeypatch.setattr(database, "MIGRATIONS", previous.parent)
    for chart in ["UK_ACCOUNTS", "EE_ACCOUNTS"]:
        monkeypatch.setattr(organisations, chart, tuple(r for r in getattr(organisations, chart) if not r[4].endswith("PREPAYMENTS")))
    db = Database(path=str(tmp_path / "upgrade.sqlite"))
    db.migrate()
    org = OrganisationService(db).create(name="Synthetic upgrade", country_code=country,
        entity_type="UK_COMPANY" if country == "UK" else "EE_OU", owner_email=ACTOR)
    setup(db, org)
    with db.transaction() as tx:
        for code in (["1300", "2200"] if country == "UK" else ["1310", "2110"]):
            tx.execute("INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance) VALUES (?,?,?,'Custom account','Asset','Debit')",
                       (new_id(), org["id"], code))
        if existing_customer_role:
            tx.execute("INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role) "
                       "VALUES (?,?,'2999','Custom customer prepayments','Liability','Credit','CUSTOMER_PREPAYMENTS')",
                       (new_id(), org["id"]))
    before = {table: db.rows(f"SELECT * FROM {table} ORDER BY id") for table in ["organisations", "accounts", "gl_entries", "invoices", "audit_events"]}
    monkeypatch.setattr(database, "MIGRATIONS", original)
    assert db.migrate() == ["0017_prepayments", "0018_fixed_assets", "0019_master_data_import", "0020_quotes", "0021_periodisation", "0022_payment_links", "0023_analytical_objects", "0024_reminder_rules", "0025_fx_realised", "0026_fx_revaluations", "0027_mfa", "0028_document_settings", "0029_copilot", "0030_master_data_maintenance", "0031_master_data_groups", "0032_copilot_access", "0033_copilot_settings", "0034_payroll_demo_fixes", "0035_payroll_income_line", "0036_payroll_component_catalogue", "0037_employee_tax_settings"]
    assert db.migrate() == []
    after_accounts = db.rows("SELECT * FROM accounts ORDER BY id")
    assert all(r in after_accounts for r in before["accounts"])
    for table in ["organisations", "gl_entries", "invoices", "audit_events"]:
        rows = db.rows(f"SELECT * FROM {table} ORDER BY id")
        if table == "organisations":
            assert all(row.pop("copilot_enabled") == 0 for row in rows)
        assert rows == before[table]
    roles = {r["system_role"]: r for r in after_accounts if r["system_role"] and r["system_role"].endswith("PREPAYMENTS")}
    assert roles["SUPPLIER_PREPAYMENTS"]["code"] == ("1301" if country == "UK" else "1311")
    assert roles["CUSTOMER_PREPAYMENTS"]["code"] == ("2999" if existing_customer_role else "2201" if country == "UK" else "2111")
    assert roles["SUPPLIER_PREPAYMENTS"]["account_type"] == "Asset"
    assert roles["CUSTOMER_PREPAYMENTS"]["account_type"] == "Liability"


def test_api_permissions_tenancy_and_web_mount(db, ee_org, uk_org, monkeypatch):
    from api_app import api
    from web_app import app
    docs, contact, bank, accounts, day, document, create, allocate = setup(db, ee_org)
    monkeypatch.setenv("FASTACCOUNTS_DB", db.path)
    monkeypatch.setenv("DB_URL", "")
    reset_database_cache()
    base = f"/organisations/{ee_org['id']}"
    payload = {k: v for k, v in create.items() if k != "actor"}
    allocation = {k: v for k, v in allocate.items() if k != "actor"}
    try:
        with TestClient(api, headers={"X-Test-User": ACTOR}) as client:
            result = client.post(base + "/prepayments", json=payload)
            assert result.status_code == 201
            prepayment = result.json()
            path = base + "/prepayments/" + prepayment["id"]
            assert client.post(base + "/prepayments", json=payload).json()["id"] == prepayment["id"]
            assert client.get(path).json()["amount"] == "200.00"
            assert client.get(base + "/prepayments", params={"side": "supplier"}).json() == []
            assert client.post(path + "/allocate", json=allocation).status_code == 200
            refund = dict(refund_date=day, amount="10", idempotency_key="refund-api")
            assert client.post(path + "/refund", json=refund).status_code == 200
            assert client.get(base + f"/contacts/{contact['id']}/prepayments/outstanding").json()["totals"]["customer"] == "150.00"
            assert client.get(path.replace(ee_org["id"], uk_org["id"])).status_code == 404
            assert client.post(path + "/allocate", json={**allocation, "amount": "41"}).status_code == 422
        with db.transaction() as tx:
            tx.execute("INSERT INTO memberships(id,organisation_id,email,role,created_at) VALUES (?,?,?,'viewer',?)",
                       (new_id(), ee_org["id"], "viewer@example.test", day))
        for email in ["viewer@example.test", "outsider@example.test"]:
            with TestClient(api, headers={"X-Test-User": email}) as client:
                assert client.get(path).status_code == (200 if email.startswith("viewer") else 403)
                for suffix, data in [("", payload), (f"/{prepayment['id']}/allocate", allocation), (f"/{prepayment['id']}/refund", refund)]:
                    assert client.post(base + "/prepayments" + suffix, json=data).status_code == 403
        with TestClient(app, headers={"X-Test-User": ACTOR}) as client:
            assert client.get("/api" + path).json()["unallocated_balance"] == "150.00"
        # With normal session authentication, every mutation requires CSRF.
        from api_app import User, current_user
        api.dependency_overrides[current_user] = lambda: User(email=ACTOR)
        with TestClient(app) as client:
            assert client.post("/api" + base + "/prepayments", json=payload).status_code == 403
    finally:
        api.dependency_overrides.clear()
        reset_database_cache()
