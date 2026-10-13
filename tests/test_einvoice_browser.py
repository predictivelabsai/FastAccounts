"""Browser regression for the purchase e-invoice intake dialog, without network calls."""
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

playwright = pytest.importorskip("playwright.sync_api")

from fastapi.testclient import TestClient


@pytest.mark.parametrize("language", ["en", "et"])
def test_einvoice_import_dialog(monkeypatch, language):
    from web import i18n
    from web_app import app

    monkeypatch.setenv("FASTACCOUNTS_ALLOW_TEST_AUTH", "true")
    monkeypatch.setenv("FASTACCOUNTS_DEFAULT_LANG", language)
    html = TestClient(app).get("/auth/test").text
    root = Path(__file__).resolve().parents[1]
    words = i18n.catalog(language)["workspace"]
    bills, uploads = [], []
    attachment = dict(id="source", filename="purchase.xml")
    with playwright.sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch()
        except playwright.Error as exc:
            if "Executable doesn't exist" in str(exc):
                pytest.skip("Install Playwright Chromium to run browser regressions")
            raise
        page = browser.new_page()

        def respond(route):
            path = urlsplit(route.request.url).path
            if path == "/api/csrf":
                return route.fulfill(json={"csrf_token": "synthetic-token"})
            if path == "/api/organisations":
                return route.fulfill(json=[dict(id="ee", name="Synthetic Eesti", country_code="EE", base_currency="EUR")])
            if path.endswith("/e-invoices/import"):
                assert route.request.method == "POST"
                assert route.request.headers["x-csrf-token"] == "synthetic-token"
                assert "multipart/form-data" in route.request.headers["content-type"]
                uploads.append(route.request.post_data_buffer)
                if len(uploads) == 1:
                    return route.fulfill(status=400, json={"detail": "Invoice total mismatch: 1.00"})
                bills.append(dict(id="bill-1", supplier_number="PUR-2026-001", contact_name="Synthetic Supplier OÜ",
                                  bill_date="2026-10-01", status="Draft", currency="EUR", total="153.80"))
                return route.fulfill(json={"bill_id": "bill-1", "supplier": "Synthetic Supplier OÜ", "total": "153.80", "warnings": []})
            if path.endswith("/bills"):
                return route.fulfill(body=json.dumps(bills), content_type="application/json")
            if path.endswith("/attachments"):
                return route.fulfill(json=[attachment])
            if path.startswith("/api/"):
                return route.fulfill(body="[]", content_type="application/json")
            if path == "/app":
                return route.fulfill(body=html, content_type="text/html")
            if path in ("/static/app.js", "/static/app.css"):
                return route.fulfill(path=str(root / path.lstrip("/")))
            return route.fulfill(status=404)

        page.route("**/*", respond)
        page.goto("http://workspace.test/app#bills")
        page.get_by_role("button", name=words["Import e-invoice"], exact=True).click()
        dialog = page.get_by_role("dialog")
        playwright.expect(dialog).to_contain_text(words["Choose an Estonian e-arve XML file. The bill is saved as a draft for review, with the source file attached."])
        submit = dialog.get_by_role("button", name=words["Import draft bill"], exact=True)
        submit.click()
        playwright.expect(dialog.locator("[data-error=file]")).to_have_text(words["This field is required."])
        assert not uploads
        dialog.locator("input[name=file]").set_input_files({"name": "purchase.xml", "mimeType": "application/xml", "buffer": b"<E_Invoice/>"})
        submit.click()
        playwright.expect(dialog.locator(".form-error")).to_have_text("Invoice total mismatch: 1.00")
        playwright.expect(submit).to_be_enabled()
        submit.click()
        playwright.expect(page.get_by_role("dialog")).to_contain_text("PUR-2026-001")
        playwright.expect(page.get_by_role("dialog")).to_contain_text("purchase.xml")
        playwright.expect(page.locator("#app-content tbody tr").first).to_contain_text(words["Draft"])
        assert len(uploads) == 2
        assert b'name="file"' in uploads[-1] and b"<E_Invoice/>" in uploads[-1]
        browser.close()
