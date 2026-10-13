"""Bulk VAT replacement: preview accuracy, rewrite totals, roles and immutability."""
from decimal import Decimal
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from test_bulk_sending import ACTOR, sending


def cents(value):
    return Decimal(str(value)).quantize(Decimal("0.01"))


def url(d, suffix=""):
    return f"/organisations/{d['oid']}/tax/replacement{suffix}"


def code(d, code_name):
    row = d["db"].one("SELECT * FROM tax_codes WHERE organisation_id=? AND code=?",
                      (d["oid"], code_name))
    assert row, code_name
    return row["id"]


def draft_invoice(d, amount_type="exclusive", tax_code=None, unit_price="100"):
    account = d["db"].scalar("SELECT id FROM accounts WHERE organisation_id=? AND system_role='SALES'", (d["oid"],))
    tax_code = tax_code or code(d, "UK20")
    contact = d["docs"].create_contact(d["oid"], name="Replacement customer",
                                       country_code="UK", contact_type="customer")
    return d["docs"].create_invoice(
        d["oid"], contact_id=contact["id"], issue_date="2026-01-10", actor=ACTOR,
        amount_type=amount_type, lines=[dict(account_id=account, unit_price=unit_price, tax_code_id=tax_code)])


def draft_bill(d, tax_code=None, unit_price="100"):
    account = d["db"].scalar("SELECT id FROM accounts WHERE organisation_id=? AND account_type='Expense' ORDER BY code LIMIT 1", (d["oid"],))
    tax_code = tax_code or code(d, "UK20")
    contact = d["docs"].create_contact(d["oid"], name="Replacement supplier",
                                       country_code="UK", contact_type="supplier")
    return d["docs"].create_bill(
        d["oid"], contact_id=contact["id"], supplier_number="RB-1", bill_date="2026-01-10",
        due_date="2026-01-20", actor=ACTOR,
        lines=[dict(account_id=account, unit_price=unit_price, tax_code_id=tax_code)])


def test_apply_rewrites_draft_lines_totals_and_audits(sending):
    d = sending
    invoice, bill = draft_invoice(d), draft_bill(d)
    issued = draft_invoice(d)
    d["docs"].issue_invoice(issued["id"], actor=ACTOR)  # posted keeps the source code
    from_id, to_id = code(d, "UK20"), code(d, "UK5")
    preview = d["client"].post(url(d, "/preview"), json={"from_code_id": from_id, "to_code_id": to_id}).json()
    labels = {(row["kind"], row["id"]) for row in preview["documents"]}
    assert labels == {("invoice", invoice["id"]), ("bill", bill["id"])}
    invoice_row = next(row for row in preview["documents"] if row["id"] == invoice["id"])
    assert cents(invoice_row["old_tax_total"]) == Decimal("20.00")
    assert cents(invoice_row["new_tax_total"]) == Decimal("5.00")
    assert preview["skipped_posted"] == {"invoice": 1, "bill": 0}
    response = d["client"].post(url(d), json={"from_code_id": from_id, "to_code_id": to_id})
    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary["replaced_documents"] == 2 and summary["replaced_lines"] == 2
    invoice_lines = d["db"].rows("SELECT * FROM invoice_lines WHERE invoice_id=?", (invoice["id"],))
    assert invoice_lines[0]["tax_code_id"] == to_id
    assert cents(invoice_lines[0]["tax_amount"]) == Decimal("5.00")
    assert cents(invoice_lines[0]["tax_amount"]) == Decimal("5.00") and cents(invoice_lines[0]["gross_amount"]) == Decimal("105.00")
    assert d["db"].scalar("SELECT tax_total FROM invoices WHERE id=?", (invoice["id"],)) == pytest.approx(5.0)
    bill_lines = d["db"].rows("SELECT * FROM bill_lines WHERE bill_id=?", (bill["id"],))
    assert bill_lines[0]["tax_code_id"] == to_id
    assert cents(bill_lines[0]["recoverable_tax"]) == Decimal("5.00")
    assert d["db"].scalar("SELECT tax_total FROM bills WHERE id=?", (bill["id"],)) == pytest.approx(5.0)
    events = d["db"].rows("SELECT action,object_type,actor FROM audit_events WHERE action='tax.replaced' ORDER BY action")
    assert {row["object_type"] for row in events} == {"invoice", "bill"}
    assert all(row["actor"] == ACTOR for row in events)
    posted = d["db"].rows("SELECT tax_code_id FROM invoice_lines WHERE invoice_id=?", (issued["id"],))
    assert posted[0]["tax_code_id"] == from_id


def test_inclusive_split_gross_is_kept(sending):
    d = sending
    invoice = draft_invoice(d, amount_type="inclusive", unit_price="120")
    assert cents(invoice["subtotal"]) == Decimal("100.00")
    from_id, to_id = code(d, "UK20"), code(d, "UK5")
    response = d["client"].post(url(d), json={"from_code_id": from_id, "to_code_id": to_id})
    assert response.status_code == 200, response.text
    lines = d["db"].rows("SELECT * FROM invoice_lines WHERE invoice_id=?", (invoice["id"],))
    assert cents(lines[0]["net_amount"]) == Decimal("114.29")
    assert cents(lines[0]["tax_amount"]) == Decimal("5.71")
    assert cents(lines[0]["gross_amount"]) == Decimal("120.00")
    header = d["db"].one("SELECT subtotal,tax_total,total FROM invoices WHERE id=?", (invoice["id"],))
    assert cents(header["total"]) == Decimal("120.00")


def test_preview_dry_run_changes_nothing(sending):
    d = sending
    draft_invoice(d)
    from_id, to_id = code(d, "UK20"), code(d, "UK5")
    before = d["db"].rows("SELECT * FROM invoice_lines")
    for _ in range(2):
        d["client"].post(url(d, "/preview"), json={"from_code_id": from_id, "to_code_id": to_id})
    assert d["db"].rows("SELECT * FROM invoice_lines") == before
    assert not d["db"].rows("SELECT id FROM audit_events WHERE action='tax.replaced'")


def test_roles_matrix(sending):
    d = sending
    draft_invoice(d)
    from_id, to_id = code(d, "UK20"), code(d, "UK5")
    def role_headers(role):
        return {"X-Test-User": role + "@example.test"}

    payload = {"from_code_id": from_id, "to_code_id": to_id}
    for role, preview_allowed, apply_allowed in [
        ("administrator", True, True), ("accountant", True, False),
        ("approver", True, False), ("viewer", False, False), ("outsider", False, False),
    ]:
        headers = role_headers(role)  # outsider@example.test has no membership
        preview = d["client"].post(url(d, "/preview"), json=payload, headers=headers)
        assert (preview.status_code == 200) == preview_allowed, (role, preview.text)
        apply = d["client"].post(url(d), json=payload, headers=headers)
        assert (apply.status_code == 200) == apply_allowed, (role, apply.text)


def test_validation_errors_and_tenant_isolation(sending):
    d = sending
    from_id, to_id = code(d, "UK20"), code(d, "UK5")
    same = d["client"].post(url(d), json={"from_code_id": from_id, "to_code_id": from_id})
    assert same.status_code == 422 and "must differ" in same.text
    missing = d["client"].post(url(d, "/preview"), json={"from_code_id": "missing", "to_code_id": to_id})
    assert missing.status_code == 404 and "Source tax code" in missing.text
    inactive = d["client"].post(url(d, "/preview"), json={"from_code_id": to_id, "to_code_id": from_id})
    assert inactive.status_code == 200  # both codes are active: preview is fine
    with d["db"].transaction() as tx:
        tx.execute("UPDATE tax_codes SET active=0 WHERE id=?", (from_id,))
    refused = d["client"].post(url(d, "/preview"), json={"from_code_id": to_id, "to_code_id": from_id})
    assert refused.status_code == 422 and "must be active" in refused.text
    other_id = d["db"].one("SELECT id FROM organisations WHERE id!=?", (d["oid"],))["id"]
    foreign_code = d["db"].one("SELECT id FROM tax_codes WHERE organisation_id=?", (other_id,))
    foreign_attempt = d["client"].post(url(d, "/preview"),
                                       json={"from_code_id": foreign_code["id"], "to_code_id": to_id})
    assert foreign_attempt.status_code == 404


def test_apply_without_candidates(sending):
    d = sending
    from_id, to_id = code(d, "UK20"), code(d, "UK5")
    response = d["client"].post(url(d), json={"from_code_id": from_id, "to_code_id": to_id})
    assert response.status_code == 422 and "No draft documents" in response.text


@pytest.mark.parametrize("language", ["en", "et", "lt", "lv"])
def test_workspace_vat_replacement_keys(language):
    from web import i18n

    en = i18n.catalog("en")
    catalog = i18n.catalog(language)
    for key in ("VAT replacement", "Apply replacement", "Preview", "From tax code"):
        assert key in catalog["workspace"] and key in en["workspace"], (language, key)


def test_workspace_tax_view_offline(sending, monkeypatch):
    playwright = pytest.importorskip("playwright.sync_api")
    from pathlib import Path

    from web_app import app

    ROOT = Path(__file__).resolve().parents[1]
    with TestClient(app) as client:
        html = client.get("/auth/test").text
    codes = [{"id": "a", "code": "UK20", "name": "Standard rate 20%", "rate": 20, "active": 1},
             {"id": "b", "code": "UK5", "name": "Reduced rate 5%", "rate": 5, "active": 1}]
    with playwright.sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch()
        except playwright.Error as error:
            if "Executable doesn't exist" in str(error):
                pytest.skip("Install Playwright Chromium to run browser regressions")
            raise
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def route(request_route):
            path = urlsplit(request_route.request.url).path
            if path == "/api/organisations":
                return request_route.fulfill(json=[dict(id="org", name="Synthetic company",
                                                        country_code="UK", base_currency="GBP", role="owner")])
            if path.endswith("/tax-codes"):
                return request_route.fulfill(json=codes, content_type="application/json")
            if path.endswith("/tax/replacement/preview"):
                return request_route.fulfill(body="""{"source_code": {"id": "a", "code": "UK20",
                    "name": "Standard rate 20%", "rate": "20"}, "target_code": {"id": "b",
                    "code": "UK5", "name": "Reduced rate 5%", "rate": "5"}, "documents": [], "skipped_posted":
                    {"invoice": 1, "bill": 0}}""", content_type="application/json")
            if path.startswith("/api/"):
                return request_route.fulfill(json=[], content_type="application/json")
            if path == "/app":
                return request_route.fulfill(body=html, content_type="text/html")
            if path in ("/static/app.js", "/static/app.css"):
                return request_route.fulfill(path=str(ROOT / path.lstrip("/")))
            return request_route.fulfill(status=404)

        page.route("**/*", route)
        page.goto("http://workspace.test/app#tax")
        replay = page.locator("[data-vat-replacement] [name=from_code_id]")
        playwright.expect(replay).to_be_visible()
        page.select_option("[data-vat-replacement] [name=from_code_id]", "a")
        page.select_option("[data-vat-replacement] [name=to_code_id]", "b")
        page.locator("[data-vat-replacement] button[type=submit]").click()
        playwright.expect(page.locator("#vat-replacement-result")).to_contain_text("Nothing to replace")
        assert not errors
        browser.close()