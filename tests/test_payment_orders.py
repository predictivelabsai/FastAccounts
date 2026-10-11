"""Synthetic payment instructions and evidence, without bank network calls."""
import os
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from core_utils import new_id
from database import reset_database_cache
from documents import DocumentService
from payment_orders import PAIN_NS, PaymentOrderService


ACTOR = "owner@example.test"
SUPPLIER_IBAN = "EE382200221020145685"
BANK_IBAN = "GB82WEST12345698765432"
NS = {"p": PAIN_NS}


def bill(db, org, *, number=None, amount="1000", iban=SUPPLIER_IBAN,
         status="Approved", paid="0", due="2026-10-15", currency=None):
    docs = DocumentService(db)
    contact = docs.create_contact(org["id"], name="Synthetic supplier & Co", country_code="EE", iban=iban)
    account = db.scalar("SELECT id FROM accounts WHERE organisation_id=? AND system_role='EXPENSE'", (org["id"],))
    result = docs.create_bill(org["id"], contact_id=contact["id"], supplier_number=number or new_id(),
        bill_date="2026-10-01", due_date=due, actor=ACTOR, currency=currency,
        reference="Synthetic reference & invoice",
        lines=[dict(description="Synthetic service", quantity=1, unit_price=amount, account_id=account)])
    if status in {"Approved", "Part Paid", "Paid"}:
        docs.approve_bill(result["id"], actor=ACTOR)
    with db.transaction() as tx:
        tx.execute("UPDATE bills SET status=?,paid_total=? WHERE id=?", (status, paid, result["id"]))
    return docs.bill(result["id"])


def bank(db, org, *, iban=BANK_IBAN, currency=None):
    return DocumentService(db).create_bank_account(org["id"], name=new_id(),
        currency=currency or org["base_currency"], iban=iban)


def test_candidates_exclusions_cutoff_and_tenancy(db, uk_org, ee_org):
    ready = bill(db, uk_org)
    partial = bill(db, uk_org, status="Part Paid", paid="100")
    draft = bill(db, uk_org, status="Draft")
    paid = bill(db, uk_org, status="Paid", paid="1000")
    zero = bill(db, uk_org, paid="1000")
    missing = bill(db, uk_org, iban="")
    late = bill(db, uk_org, due="2026-11-01")
    foreign = bill(db, ee_org)
    service = PaymentOrderService(db)
    preview = service.candidates(uk_org["id"], due_before="2026-10-15")
    assert {row["id"] for row in preview["candidates"]} == {ready["id"], partial["id"]}
    assert preview["totals"] == {"GBP": "1900.00"}
    reasons = {row["id"]: row["reason"] for row in preview["excluded"]}
    assert reasons == {draft["id"]: "Draft", paid["id"]: "Paid", zero["id"]: "No outstanding balance",
                       missing["id"]: "No supplier IBAN"}
    all_rows = service.candidates(uk_org["id"])
    assert late["id"] in {row["id"] for row in all_rows["candidates"]}
    assert foreign["id"] not in {row["id"] for row in all_rows["candidates"] + all_rows["excluded"]}


def test_create_freezes_values_without_posting(db, uk_org):
    source = bill(db, uk_org, status="Part Paid", paid="100")
    paying = bank(db, uk_org)
    service = PaymentOrderService(db)
    before = db.rows("SELECT * FROM bills")
    ledger = db.rows("SELECT * FROM gl_entries")
    order = service.create(uk_org["id"], paying["id"], execution_date="2026-10-20", actor=ACTOR)
    assert order["bill_count"] == 1 and order["total"] == "900.00"
    assert order["lines"][0]["bill_id"] == source["id"]
    assert order["lines"][0]["amount"] == "900.00"
    original_xml = service.xml(uk_org["id"], order["id"])
    assert db.rows("SELECT * FROM bills") == before
    assert db.rows("SELECT * FROM gl_entries") == ledger
    assert db.scalar("SELECT COUNT(*) FROM payments") == 0
    assert db.scalar("SELECT COUNT(*) FROM audit_events WHERE action='payment_order.created'") == 1
    with db.transaction() as tx:
        tx.execute("UPDATE bills SET paid_total=1000,status='Paid',reference='Changed' WHERE id=?", (source["id"],))
        tx.execute("UPDATE contacts SET name='Changed',iban='Changed' WHERE id=?", (source["contact_id"],))
        tx.execute("UPDATE bank_accounts SET iban='Changed' WHERE id=?", (paying["id"],))
    assert service.xml(uk_org["id"], order["id"]) == original_xml
    assert service.list(uk_org["id"])[0] == order


def test_create_revalidates_selection_and_currency_atomically(db, uk_org, ee_org):
    ready = bill(db, uk_org)
    foreign_currency = bill(db, uk_org, currency="EUR")
    excluded = bill(db, uk_org, iban="")
    foreign = bill(db, ee_org)
    paying = bank(db, uk_org)
    service = PaymentOrderService(db)
    for ids, error in [([], ValueError), ([excluded["id"]], ValueError),
                       ([ready["id"], foreign_currency["id"]], ValueError),
                       ([ready["id"], foreign["id"]], KeyError), (["missing"], KeyError)]:
        with pytest.raises(error):
            service.create(uk_org["id"], paying["id"], execution_date="2026-10-20", bill_ids=ids, actor=ACTOR)
    with pytest.raises(ValueError):
        service.create(uk_org["id"], paying["id"], execution_date="bad-date", actor=ACTOR)
    with pytest.raises(ValueError):
        service.create(uk_org["id"], bank(db, uk_org, iban="")["id"], execution_date="2026-10-20", actor=ACTOR)
    with pytest.raises(KeyError):
        service.create(uk_org["id"], bank(db, ee_org)["id"], execution_date="2026-10-20", actor=ACTOR)
    with db.transaction() as tx:
        tx.execute("UPDATE bills SET paid_total=1000,status='Paid' WHERE id=?", (ready["id"],))
    with pytest.raises(ValueError):
        service.create(uk_org["id"], paying["id"], execution_date="2026-10-20", bill_ids=[ready["id"]], actor=ACTOR)
    assert db.scalar("SELECT COUNT(*) FROM payment_orders") == 0
    assert db.scalar("SELECT COUNT(*) FROM payment_order_lines") == 0


@pytest.mark.parametrize("operation", ["payment_order", "attachment"])
def test_failed_audit_rolls_back_new_records(db, uk_org, monkeypatch, tmp_path, operation):
    import documents
    import payment_orders
    source = bill(db, uk_org)
    paying = bank(db, uk_org)
    before = db.rows("SELECT * FROM bills"), db.rows("SELECT * FROM gl_entries")
    monkeypatch.setenv("FASTACCOUNTS_DATA_DIR", str(tmp_path))

    def fail_audit(*args, **kwargs):
        raise RuntimeError("Synthetic audit failure")

    monkeypatch.setattr(documents if operation == "attachment" else payment_orders, "audit", fail_audit)
    with pytest.raises(RuntimeError, match="Synthetic audit failure"):
        if operation == "payment_order":
            PaymentOrderService(db).create(uk_org["id"], paying["id"], execution_date="2026-10-20", actor=ACTOR)
        else:
            DocumentService(db).attach_evidence(uk_org["id"], owner_type="bill", owner_id=source["id"],
                filename="proof.txt", content_type="text/plain", content=b"synthetic evidence", actor=ACTOR)
    assert db.scalar("SELECT COUNT(*) FROM payment_orders") == 0
    assert db.scalar("SELECT COUNT(*) FROM payment_order_lines") == 0
    assert db.scalar("SELECT COUNT(*) FROM attachments") == 0
    assert not list(tmp_path.rglob("proof.txt"))
    assert not list(tmp_path.rglob("*-proof.txt"))
    assert before == (db.rows("SELECT * FROM bills"), db.rows("SELECT * FROM gl_entries"))


def test_xml_namespace_amounts_and_stored_currency_groups(db, uk_org):
    first = bill(db, uk_org, amount=Decimal("1000"))
    second = bill(db, uk_org, amount="12.30")
    with db.transaction() as tx:
        tx.execute("UPDATE bills SET reference=NULL WHERE id=?", (second["id"],))
    service = PaymentOrderService(db)
    order = service.create(uk_org["id"], bank(db, uk_org)["id"], execution_date="2026-10-20", actor=ACTOR)
    # Creation deliberately enforces the bank currency. Exercise the generic
    # stored-line grouping independently of that account-selection policy.
    with db.transaction() as tx:
        tx.execute("UPDATE payment_order_lines SET currency='EUR' WHERE bill_id=?", (second["id"],))
    xml = service.xml(uk_org["id"], order["id"])
    root = ET.fromstring(xml)
    assert root.tag == f"{{{PAIN_NS}}}Document"
    assert root.findtext(".//p:GrpHdr/p:MsgId", namespaces=NS) == order["id"]
    assert Decimal(root.findtext(".//p:GrpHdr/p:CtrlSum", namespaces=NS)) == Decimal(order["total"])
    assert root.findtext(".//p:GrpHdr/p:NbOfTxs", namespaces=NS) == "2"
    groups = root.findall(".//p:PmtInf", NS)
    assert len(groups) == 2
    assert {g.find(".//p:InstdAmt", NS).get("Ccy") for g in groups} == {"GBP", "EUR"}
    assert {n.text for n in root.findall(".//p:InstdAmt", NS)} == {"1000.00", "12.30"}
    assert b"1E+3" not in xml
    assert {n.text for n in root.findall(".//p:IBAN", NS)} == {SUPPLIER_IBAN, BANK_IBAN}
    assert {n.text for n in root.findall(".//p:EndToEndId", NS)} == {first["id"].replace("-", ""), second["id"].replace("-", "")}
    assert all(len(n.text) <= 35 for name in ("MsgId", "PmtInfId", "EndToEndId")
               for n in root.findall(f".//p:{name}", NS))
    assert all(g.findtext("p:ReqdExctnDt", namespaces=NS) == "2026-10-20" for g in groups)
    assert {n.text for n in root.findall(".//p:Ustrd", NS)} == {"Synthetic reference & invoice", second["supplier_number"]}


@pytest.fixture
def client(db, monkeypatch, tmp_path):
    monkeypatch.setenv("FASTACCOUNTS_DB", db.path)
    monkeypatch.setenv("DB_URL", "")
    monkeypatch.setenv("FASTACCOUNTS_DATA_DIR", str(tmp_path / "evidence"))
    reset_database_cache()
    from api_app import api
    with TestClient(api, headers={"X-Test-User": ACTOR}) as client:
        yield client
    reset_database_cache()


def test_payment_order_routes(client, db, uk_org, ee_org):
    source = bill(db, uk_org)
    paying = bank(db, uk_org)
    base = f"/organisations/{uk_org['id']}/payment-orders"
    before = db.rows("SELECT * FROM bills"), db.rows("SELECT * FROM gl_entries")
    assert client.get(base + "/candidates?due_before=2026-10-15").status_code == 200
    result = client.post(base, json={"bank_account_id": paying["id"], "execution_date": "2026-10-20", "bill_ids": [source["id"]]})
    assert result.status_code == 201, result.text
    order = result.json()
    assert client.get(base).json() == [order]
    download = client.get(base + f"/{order['id']}.xml")
    assert download.status_code == 200 and download.headers["content-type"].startswith("application/xml")
    assert "attachment;" in download.headers["content-disposition"]
    assert client.get(base + "/missing.xml").json() == {"detail": "Payment order not found"}
    assert client.get(base + "/missing.xml").status_code == 404
    assert client.get(f"/organisations/{ee_org['id']}/payment-orders/{order['id']}.xml").status_code == 404
    assert before == (db.rows("SELECT * FROM bills"), db.rows("SELECT * FROM gl_entries"))


def test_attachments_round_trip_validation_and_tenancy(client, db, uk_org, ee_org, monkeypatch):
    source = bill(db, uk_org)
    base = f"/organisations/{uk_org['id']}/attachments"
    upload = base + f"/bill/{source['id']}"
    content = b"synthetic evidence"
    result = client.post(upload, files={"file": ("../proof.pdf", content, "application/pdf")})
    assert result.status_code == 201, result.text
    attachment = result.json()
    assert attachment["filename"] == "proof.pdf"
    assert "storage_path" not in attachment
    listing = client.get(base, params={"owner_type": "bill", "owner_id": source["id"]})
    assert listing.status_code == 200 and listing.json()[0]["id"] == attachment["id"]
    assert "storage_path" not in listing.json()[0]
    download = client.get(base + f"/{attachment['id']}/download")
    assert download.status_code == 200 and download.content == content
    assert download.headers["x-content-type-options"] == "nosniff"
    assert client.post(upload, files={"file": ("again.pdf", content)}).status_code == 422
    monkeypatch.setenv("MAX_ATTACHMENT_BYTES", "3")
    assert client.post(upload, files={"file": ("big.pdf", b"1234")}).status_code == 422
    assert client.post(upload, files={"file": ("empty.pdf", b"")}).status_code == 422
    monkeypatch.setenv("MAX_ATTACHMENT_BYTES", "10485760")
    assert client.post(base + f"/contact/{source['contact_id']}", files={"file": ("bad.pdf", b"new")}).status_code == 422
    other = bill(db, ee_org)
    assert client.post(base + f"/bill/{other['id']}", files={"file": ("bad.pdf", b"new")}).status_code == 404
    assert client.get(base, params={"owner_type": "bill", "owner_id": other["id"]}).status_code == 404
    assert client.get(f"/organisations/{ee_org['id']}/attachments/{attachment['id']}/download").status_code == 404
    assert client.get(base + "/missing/download").status_code == 404
    assert len(list(Path(os.environ['FASTACCOUNTS_DATA_DIR']).rglob('*.pdf'))) == 1
    stored = db.one("SELECT * FROM attachments WHERE id=?", (attachment["id"],))
    Path(stored["storage_path"]).write_bytes(b"tampered")
    assert client.get(base + f"/{attachment['id']}/download").status_code == 422
    Path(stored["storage_path"]).unlink()
    assert client.get(base + f"/{attachment['id']}/download").status_code == 404


def test_contact_and_bank_iban_routes(client, uk_org):
    base = f"/organisations/{uk_org['id']}"
    contact = client.post(base + "/contacts", json={"name": "Synthetic supplier", "country_code": "EE", "iban": "ee38 2200 2210 2014 5685"})
    assert contact.status_code == 201 and contact.json()["iban"] == SUPPLIER_IBAN
    paying = client.post(base + "/bank-accounts", json={"name": "Synthetic paying account", "currency": "GBP", "iban": BANK_IBAN})
    assert paying.status_code == 201 and paying.json()["iban"] == BANK_IBAN
    assert paying.json()["iban_masked"].endswith("5432")


def test_payment_and_attachment_role_and_csrf_gates(client, db, uk_org):
    from api_app import api, current_user, User
    from starlette.middleware.sessions import SessionMiddleware
    source = bill(db, uk_org)
    paying = bank(db, uk_org)
    base = f"/organisations/{uk_org['id']}"
    with db.transaction() as tx:
        tx.execute("INSERT INTO memberships(id,organisation_id,email,role,created_at) VALUES (?,?,?,'viewer','2026-10-01')",
                   (new_id(), uk_org["id"], "viewer@example.test"))
    payload = {"bank_account_id": paying["id"], "execution_date": "2026-10-20"}
    headers = {"X-Test-User": "viewer@example.test"}
    assert client.get(base + "/payment-orders/candidates", headers=headers).status_code == 200
    assert client.post(base + "/payment-orders", headers=headers, json=payload).status_code == 403
    assert client.post(base + f"/attachments/bill/{source['id']}", headers=headers,
                       files={"file": ("proof.txt", b"proof")}).status_code == 403
    assert client.get(base + "/payment-orders", headers={"X-Test-User": "outsider@example.test"}).status_code == 403
    api.dependency_overrides[current_user] = lambda: User(email=ACTOR)
    try:
        with TestClient(SessionMiddleware(api, secret_key="synthetic-csrf-test")) as session_client:
            assert session_client.post(base + "/payment-orders", json=payload).status_code == 403
            assert session_client.post(base + f"/attachments/bill/{source['id']}",
                files={"file": ("proof.txt", b"proof")}).status_code == 403
    finally:
        api.dependency_overrides.pop(current_user, None)


def test_invoice_and_manual_journal_attachments(client, db, uk_org):
    docs = DocumentService(db)
    contact = docs.create_contact(uk_org["id"], name="Synthetic customer", country_code="GB")
    sales = db.scalar("SELECT id FROM accounts WHERE organisation_id=? AND system_role='SALES'", (uk_org["id"],))
    expense = db.scalar("SELECT id FROM accounts WHERE organisation_id=? AND system_role='EXPENSE'", (uk_org["id"],))
    invoice = docs.create_invoice(uk_org["id"], contact_id=contact["id"], issue_date="2026-10-01", actor=ACTOR,
        lines=[dict(description="Synthetic sale", quantity=1, unit_price=20, account_id=sales)])
    base = f"/organisations/{uk_org['id']}"
    journal = client.post(base + "/journals", json={"voucher_code": "SYNTHETIC", "posting_date": "2026-10-01",
        "currency": "GBP", "idempotency_key": "synthetic-journal",
        "lines": [{"account_id": expense, "debit": "20"}, {"account_id": sales, "credit": "20"}]})
    assert journal.status_code == 201, journal.text
    for owner_type, owner_id in [("invoice", invoice["id"]), ("journal", journal.json()["id"])]:
        result = client.post(base + f"/attachments/{owner_type}/{owner_id}", files={"file": ("proof.txt", b"same evidence")})
        assert result.status_code == 201, result.text
        assert client.get(base + f"/attachments/{result.json()['id']}/download").content == b"same evidence"


def test_workspace_payment_order_and_attachments_browser(client, db, uk_org, monkeypatch, tmp_path):
    from urllib.parse import urlsplit
    from playwright.sync_api import sync_playwright, expect
    from web_app import app

    monkeypatch.setenv("FASTACCOUNTS_DEFAULT_LANG", "en")
    source = bill(db, uk_org, number="SYNTHETIC-1000")
    bill(db, uk_org, number="SYNTHETIC-NO-IBAN", iban="")
    bank(db, uk_org)
    html = TestClient(app).get("/auth/test").text
    root = Path(__file__).resolve().parents[1]
    errors = []
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 1000})
        page.on("pageerror", lambda error: errors.append(str(error)))

        def respond(route):
            url = urlsplit(route.request.url)
            if url.path == "/api/csrf":
                return route.fulfill(json={"csrf_token": "synthetic-browser-csrf"})
            if url.path.startswith("/api/"):
                headers = {k: v for k, v in route.request.headers.items() if k in {"content-type", "x-csrf-token"}}
                response = client.request(route.request.method, url.path[4:] + ("?" + url.query if url.query else ""),
                    content=route.request.post_data_buffer, headers=headers)
                return route.fulfill(status=response.status_code, headers=dict(response.headers), body=response.content)
            if url.path == "/app":
                return route.fulfill(body=html, content_type="text/html")
            if url.path in {"/static/app.js", "/static/app.css"}:
                return route.fulfill(path=str(root / url.path.lstrip("/")))
            return route.fulfill(status=404)

        page.route("**/*", respond)
        page.goto("http://workspace.test/app#bills")
        page.get_by_role("button", name="Create payment order", exact=True).click()
        preview = page.locator("[data-payment-preview]")
        expect(preview).to_contain_text("SYNTHETIC-1000")
        expect(preview).to_contain_text("No supplier IBAN")
        page.set_viewport_size({"width": 390, "height": 844})
        expect(page.get_by_role("dialog")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        assert page.locator(".dialog-card").evaluate("el => el.scrollWidth <= el.clientWidth")
        page.screenshot(path=str(tmp_path / "payment-order-preview.png"), full_page=True)
        page.get_by_role("dialog").get_by_role("button", name="Create payment order", exact=True).click()
        expect(page.get_by_role("dialog")).to_have_count(0)
        expect(page.get_by_role("link", name="Download XML")).to_be_visible()
        page.locator("#app-content tbody tr").filter(has_text="SYNTHETIC-1000").get_by_role("button", name="Attachments").click()
        expect(page.get_by_role("dialog")).to_contain_text("No attachments yet.")
        page.get_by_label("File", exact=True).set_input_files({"name": "synthetic-proof.txt", "mimeType": "text/plain", "buffer": b"synthetic browser evidence"})
        page.get_by_role("button", name="Upload attachment").click()
        expect(page.get_by_role("dialog")).to_contain_text("synthetic-proof.txt")
        expect(page.get_by_role("dialog").get_by_role("link", name="Download", exact=True)).to_be_visible()
        page.get_by_role("dialog").get_by_role("button", name="Close", exact=True).click()
        page.evaluate("location.hash = 'invoices'")
        page.locator('.page-title [data-action="newInvoice"]').click()
        page.get_by_label("Description", exact=True).fill("Synthetic browser sale")
        page.get_by_label("Unit price", exact=True).fill("25")
        page.get_by_role("button", name="Create draft", exact=True).click()
        expect(page.get_by_role("dialog")).to_contain_text("No attachments yet.")
        page.get_by_label("File", exact=True).set_input_files({"name": "invoice-proof.txt", "mimeType": "text/plain", "buffer": b"synthetic invoice evidence"})
        page.get_by_role("button", name="Upload attachment").click()
        expect(page.get_by_role("dialog")).to_contain_text("invoice-proof.txt")
        assert db.scalar("SELECT COUNT(*) FROM payment_orders") == 1
        assert db.scalar("SELECT status FROM bills WHERE id=?", (source["id"],)) == "Approved"
        assert not errors
        browser.close()
