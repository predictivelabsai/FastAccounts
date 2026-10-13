"""Fiscal period close and reopen: role matrix, posting freeze and audit."""
from decimal import Decimal
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from ledger import LedgerService, PostingLine
from test_bulk_sending import ACTOR, sending


def url(d):
    return f"/organisations/{d['oid']}/periods"


def test_list_close_reopen_and_posting_freeze(sending):
    d = sending
    periods = d["client"].get(url(d)).json()
    assert periods and all(set(row) == {"id", "code", "starts_on", "ends_on", "status",
                                        "locked_at", "locked_by", "lock_reason"}
                           for row in periods)
    period = periods[0]
    assert period["status"] == "Open"
    response = d["client"].put(url(d) + f"/{period['id']}/close", json={"reason": "Month end complete"})
    assert response.status_code == 200, response.text
    locked = [row for row in response.json() if row["id"] == period["id"]][0]
    assert locked["status"] == "Locked" and locked["locked_by"] == ACTOR
    assert locked["lock_reason"] == "Month end complete" and locked["locked_at"]
    assert d["db"].scalar("SELECT action FROM audit_events WHERE action='period.locked' "
                          "AND object_id=?", (period["id"],))
    accounts = {row["system_role"]: row["id"] for row in
                d["db"].rows("SELECT * FROM accounts WHERE organisation_id=?", (d["oid"],))}
    base_currency = d["db"].scalar("SELECT base_currency FROM organisations WHERE id=?", (d["oid"],))

    def posting(voucher_code):
        LedgerService(d["db"]).post(
            organisation_id=d["oid"], voucher_type="journal", voucher_id=period["id"],
            voucher_code=voucher_code, posting_date=period["starts_on"],
            lines=[PostingLine(accounts["BANK"], debit=Decimal("1.00")),
                   PostingLine(accounts["CAPITAL"], credit=Decimal("1.00"))],
            actor=ACTOR, currency=base_currency)

    with pytest.raises(Exception) as refused:
        posting("Synthetic into closed")
    assert "locked" in str(refused.value)
    double = d["client"].put(url(d) + f"/{period['id']}/close", json={"reason": "again"})
    assert double.status_code == 422 and "already locked" in double.text
    reopen = d["client"].put(url(d) + f"/{period['id']}/reopen", json={"reason": "Late invoice arrived"})
    assert reopen.status_code == 200, reopen.text
    reopened = [row for row in reopen.json() if row["id"] == period["id"]][0]
    assert reopened["status"] == "Open" and reopened["locked_at"] is None
    assert reopened["locked_by"] is None and reopened["lock_reason"] is None
    assert d["db"].scalar("SELECT action FROM audit_events WHERE action='period.reopened' "
                          "AND object_id=?", (period["id"],))
    posting("Synthetic after reopen")


@pytest.mark.parametrize("role", ["administrator", "accountant", "approver", "viewer"])
def test_reopen_close_roles(sending, role):
    d = sending
    headers = {"X-Test-User": role + "@example.test"}
    periods = d["client"].get(url(d), headers=headers).json()
    period = periods[0]
    expected = 200 if role == "administrator" else 403
    close = d["client"].put(url(d) + f"/{period['id']}/close",
                            json={"reason": "synthetic"}, headers=headers)
    assert close.status_code == expected, close.text
    if expected == 403:
        assert d["client"].put(url(d) + f"/{period['id']}/reopen", json={"reason": "x"},
                               headers=headers).status_code == 403
        return
    assert all(row["status"] == "Locked" for row in close.json() if row["id"] == period["id"])
    reopening = d["client"].put(url(d) + f"/{period['id']}/reopen",
                                json={"reason": "retraction"}, headers=headers)
    assert reopening.status_code == 200
    assert all(row["status"] == "Open" for row in reopening.json() if row["id"] == period["id"])


@pytest.mark.parametrize("role", ["accountant", "approver", "viewer", "outsider"])
def test_read_roles(sending, role):
    d = sending
    headers = {"X-Test-User": role + "@example.test"}
    assert d["client"].get(url(d), headers=headers).status_code == (403 if role == "outsider" else 200)


def test_reason_required_and_tenant_isolation(sending):
    d = sending
    periods = d["client"].get(url(d)).json()
    period = periods[0]
    assert d["client"].put(url(d) + f"/{period['id']}/close", json={"reason": ""}).status_code == 422
    assert d["client"].put(url(d) + f"/{period['id']}/close", json={"reason": "x" * 501}).status_code == 422
    assert d["client"].put(url(d) + f"/{period['id']}/reopen", json={}).status_code == 422
    foreign = d["client"].get(f"/organisations/{d['other']['id']}/periods")
    if foreign.status_code == 200:
        assert all(row["id"] not in {p["id"] for p in periods} for row in foreign.json())
        assert d["client"].put(url(d) + f"/{foreign.json()[0]['id']}/close",
                               json={"reason": "x"}).status_code == 404
    else:
        assert foreign.status_code == 403
    assert d["client"].put(url(d) + "/missing-period/close", json={"reason": "x"}).status_code == 404


@pytest.mark.parametrize("language", ["en", "et", "lt", "lv"])
def test_nav_and_locale_keys(language):
    from web import i18n

    catalog = i18n.catalog(language)
    en_catalog = i18n.catalog("en")
    assert list(catalog)[-1] == "periods"
    assert set(catalog["periods"]["workspace"]) == set(en_catalog["periods"]["workspace"]), language
    if language == "en":
        assert catalog["nav"]["periods"] == "Fiscal periods"


def test_workspace_periods_view_offline(sending, monkeypatch):
    playwright = pytest.importorskip("playwright.sync_api")
    from pathlib import Path

    from web_app import app

    ROOT = Path(__file__).resolve().parents[1]
    with TestClient(app) as client:
        html = client.get("/auth/test").text
    periods = [{"id": "p1", "code": "2026-01", "starts_on": "2026-01-01", "ends_on": "2026-01-31",
                "status": "Open", "locked_at": None, "locked_by": None, "lock_reason": None}]
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
                                                        country_code="EE", base_currency="EUR", role="viewer")])
            if path.endswith("/periods"):
                return request_route.fulfill(json=periods, content_type="application/json")
            if path.startswith("/api/"):
                return request_route.fulfill(json=[], content_type="application/json")
            if path == "/app":
                return request_route.fulfill(body=html, content_type="text/html")
            if path in ("/static/app.js", "/static/app.css"):
                return request_route.fulfill(path=str(ROOT / path.lstrip("/")))
            return request_route.fulfill(status=404)

        page.route("**/*", route)
        page.goto("http://workspace.test/app#periods")
        playwright.expect(page.locator("h1")).to_have_text("Fiscal periods")
        playwright.expect(page.locator("#app-content table")).to_contain_text("2026-01")
        assert not errors
        browser.close()