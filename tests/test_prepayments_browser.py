"""Prepayment dialogs, errors and refreshes with all browser requests intercepted."""
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

playwright = pytest.importorskip("playwright.sync_api")


@pytest.mark.parametrize("language", ["en", "et", "lt", "lv"])
@pytest.mark.parametrize("side", ["customer", "supplier"])
def test_prepayment_create_allocate_refund_dialogs(monkeypatch, language, side):
    from web import i18n
    from web_app import app
    monkeypatch.setenv("FASTACCOUNTS_ALLOW_TEST_AUTH", "true")
    monkeypatch.setenv("FASTACCOUNTS_DEFAULT_LANG", language)
    html = TestClient(app).get("/auth/test").text
    words = i18n.catalog(language)["workspace"]
    root = Path(__file__).resolve().parents[1]
    requests, prepayments, errors = [], [], []
    customer = side == "customer"
    document_type = "invoice" if customer else "bill"
    document = dict(id="document", document_type=document_type, contact_id="contact", contact_name="Synthetic Õun OÜ",
        number="INV-SYN", supplier_number="SUP-SYN", total="100", paid_total="0", currency="EUR",
        issue_date="2026-10-01", bill_date="2026-10-01", due_date="2026-10-01", status="Issued" if customer else "Approved")
    with playwright.sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch()
        except playwright.Error as exc:
            if "Executable doesn't exist" in str(exc):
                pytest.skip("Install Playwright Chromium to run browser regressions")
            raise
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.on("pageerror", lambda error: errors.append(str(error)))

        def respond(route):
            url = urlsplit(route.request.url)
            path, method = url.path, route.request.method
            if path == "/api/organisations":
                return route.fulfill(json=[dict(id="org", name="Synthetic company", country_code="EE", base_currency="EUR", role="owner")])
            if path == "/api/csrf":
                return route.fulfill(json={"csrf_token": "synthetic-token"})
            if path.endswith("/contacts"):
                return route.fulfill(json=[dict(id="contact", name="Synthetic Õun OÜ", contact_type="both")])
            if path.endswith("/bank-accounts"):
                return route.fulfill(json=[dict(id="bank", name="Synthetic bank", currency="EUR")])
            if path.endswith("/prepayments/outstanding"):
                return route.fulfill(json={"contact_id": "contact", "items": prepayments,
                                          "totals": {side: "80"}})
            if path.endswith("/prepayments"):
                if method == "GET":
                    assert parse_qs(url.query)["side"] == [side]
                    return route.fulfill(json=prepayments, content_type="application/json")
                payload = json.loads(route.request.post_data)
                requests.append(("create", payload, route.request.headers))
                prepayments.append(dict(id="prepayment", contact_name="Synthetic Õun OÜ", unallocated_balance="200", **payload))
                return route.fulfill(status=201, json=prepayments[0])
            if path.endswith("/allocate"):
                payload = json.loads(route.request.post_data)
                requests.append(("allocate", payload, route.request.headers))
                if len([r for r in requests if r[0] == "allocate"]) == 1:
                    return route.fulfill(status=422, json={"detail": "Allocation exceeds the open document balance"})
                document.update(paid_total="40", status="Part Paid")
                prepayments[0]["unallocated_balance"] = "160"
                return route.fulfill(json={"id": "allocation"})
            if path.endswith("/refund"):
                payload = json.loads(route.request.post_data)
                requests.append(("refund", payload, route.request.headers))
                prepayments[0]["unallocated_balance"] = "80"
                return route.fulfill(json={"id": "refund"})
            if path.endswith("/invoices") or path.endswith("/bills"):
                return route.fulfill(json=[document])
            if path.startswith("/api/"):
                return route.fulfill(json=[], content_type="application/json")
            if path == "/app":
                return route.fulfill(body=html, content_type="text/html")
            if path in ("/static/app.js", "/static/app.css"):
                return route.fulfill(path=str(root / path.lstrip("/")))
            return route.fulfill(status=404)

        page.route("**/*", respond)
        page.goto("http://workspace.test/app#" + ("invoices" if customer else "bills"))
        try:
            playwright.expect(page.locator("#app-content")).not_to_have_attribute("aria-busy", "true", timeout=5000)
        except AssertionError:
            raise AssertionError(f"Workspace did not load: {errors}; {page.locator('body').inner_text()}")
        playwright.expect(page.get_by_role("button", name=words["Record customer prepayment" if customer else "Record supplier prepayment"], exact=True)).to_be_visible()
        page.get_by_role("button", name=words["Record customer prepayment" if customer else "Record supplier prepayment"], exact=True).click()
        dialog = page.get_by_role("dialog")
        dialog.locator("[name=document_date]").fill("2026-10-01")
        dialog.locator("[name=amount]").fill("200")
        dialog.locator("[name=reference]").fill("Synthetic reference")
        assert dialog.evaluate("el => el.scrollWidth <= el.clientWidth")
        dialog.get_by_role("button", name=words["Record prepayment"], exact=True).click()
        playwright.expect(page.get_by_role("dialog")).to_have_count(0)
        page.get_by_role("button", name=words["Allocate prepayment"], exact=True).click()
        dialog = page.get_by_role("dialog")
        playwright.expect(dialog.locator("[name=document_id] option")).to_have_count(1)
        dialog.locator("[name=allocation_date]").fill("2026-10-02")
        dialog.locator("[name=amount]").fill("150")
        submit = dialog.get_by_role("button", name=words["Allocate prepayment"], exact=True)
        submit.click()
        playwright.expect(dialog.locator(".form-error")).to_have_text(words["Allocation exceeds the open document balance"])
        dialog.locator("[name=amount]").fill("40")
        submit.click()
        playwright.expect(page.get_by_role("dialog")).to_have_count(0)
        playwright.expect(page.get_by_text(words["Part Paid"], exact=True)).to_be_visible()
        page.get_by_role("button", name=words["Refund prepayment"], exact=True).click()
        dialog = page.get_by_role("dialog")
        playwright.expect(dialog.locator("[name=amount]")).to_have_value("160")
        dialog.locator("[name=refund_date]").fill("2026-10-02")
        dialog.locator("[name=amount]").fill("80")
        dialog.get_by_role("button", name=words["Refund prepayment"], exact=True).click()
        playwright.expect(page.get_by_role("dialog")).to_have_count(0)
        assert [r[0] for r in requests] == ["create", "allocate", "allocate", "refund"]
        assert requests[0][1]["side"] == side
        assert requests[1][1]["document_type"] == document_type
        assert requests[1][1]["idempotency_key"] == requests[2][1]["idempotency_key"]
        assert len({requests[i][1]["idempotency_key"] for i in [0, 1, 3]}) == 3
        assert all(r[2]["x-csrf-token"] == "synthetic-token" for r in requests)
        page.evaluate("location.hash = 'contacts'")
        page.get_by_role("button", name=words["Outstanding prepayments"], exact=True).click()
        dialog = page.get_by_role("dialog")
        playwright.expect(dialog.get_by_role("button", name=words["Allocate prepayment"], exact=True)).to_be_visible()
        playwright.expect(dialog.get_by_text("Synthetic Õun OÜ", exact=True).first).to_be_visible()
        assert dialog.evaluate("el => el.scrollWidth <= el.clientWidth")
        dialog.get_by_role("button", name=words["Close"], exact=True).click()
        assert not errors
        browser.close()
