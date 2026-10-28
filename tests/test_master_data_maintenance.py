"""Master-data maintenance: analysis findings, lifecycle actions, migration."""
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

import copilot
from test_bulk_sending import ACTOR, sending

ROOT = Path(__file__).resolve().parents[1]


def url(d, suffix=""):
    return f"/organisations/{d['oid']}/master-data{suffix}"


def fixture(sending):
    return sending


def contact(d, name, *, contact_type="customer", **fields):
    row = d["docs"].create_contact(d["oid"], name=name, country_code="UK",
                                   contact_type=contact_type, **fields)
    row["active"] = d["db"].scalar("SELECT active FROM contacts WHERE id=?", (row["id"],))
    return row


def item(d, code_name, name):
    return d["docs"].create_item(d["oid"], code=code_name, name=name)


def test_migration_count_rerun_and_ci(sending):
    d = sending
    assert d["db"].scalar("SELECT COUNT(*) FROM schema_migrations") == 41
    for _ in range(2):
        with d["db"].transaction() as tx:
            tx.execute("DELETE FROM schema_migrations WHERE version='0030_master_data_maintenance'")
        assert d["db"].migrate() == ["0030_master_data_maintenance"]
    assert d["db"].rows("SELECT name FROM pragma_table_info('contacts') WHERE name='active'")
    assert "'0029_copilot', '0030_master_data_maintenance', '0031_master_data_groups', '0032_copilot_access', '0033_copilot_settings', '0034_payroll_demo_fixes', '0035_payroll_income_line', '0036_payroll_component_catalogue', '0037_employee_tax_settings', '0038_payroll_payday_rules', '0039_payroll_payouts', '0040_payroll_settlement_dates', '0041_payroll_sepa_details']" in (ROOT / ".github/workflows/ci.yml").read_text()


def test_analysis_finds_all_four_categories(sending):
    d = sending
    orphan = contact(d, "Orphan Ltd")
    duplicate_one = contact(d, "Alpha  GmbH", vat_no="GB123456789")
    duplicate_two = contact(d, "Alpha GmbH", vat_no="GB123456789")
    used = contact(d, "Used supplier", contact_type="both")  # no identifiers, has bill + invoice
    account = d["db"].scalar("SELECT id FROM accounts WHERE organisation_id=? AND system_role='SALES'", (d["oid"],))
    invoice = d["docs"].create_invoice(
        d["oid"], contact_id=used["id"], issue_date="2026-01-10", actor=ACTOR,
        lines=[dict(account_id=account, unit_price="10.00")])
    d["docs"].create_bill(d["oid"], contact_id=used["id"], supplier_number="RB-1",
                          bill_date="2026-01-10", due_date="2026-01-20", actor=ACTOR,
                          lines=[dict(account_id=account, unit_price="5.00")])
    other_supplier = contact(d, "Second supplier", contact_type="supplier")
    d["docs"].create_bill(d["oid"], contact_id=other_supplier["id"], supplier_number="RB-1",
                          bill_date="2026-01-11", due_date="2026-01-21", actor=ACTOR,
                          lines=[dict(account_id=account, unit_price="5.00")])
    report = d["client"].get(url(d, "/maintenance")).json()
    names = {row["name"] for row in report["unused_contacts"]}
    assert "Orphan Ltd" in names and "Used supplier" not in names
    duplicates = {row["name"] for row in report["duplicate_contacts"]}
    assert duplicates == {"Alpha  GmbH", "Alpha GmbH"}
    missing = {row["name"] for row in report["contacts_missing_identifiers"]}
    assert "Used supplier" in missing and "Orphan Ltd" not in missing
    reused = {row["supplier_number"]: row["suppliers"] for row in report["reused_supplier_numbers"]}
    assert reused.get("RB-1") == 2


def test_contact_lifecycle_deactivate_reactivate_delete(sending):
    d = sending
    orphan = contact(d, "Lifecycle orphan")
    used = contact(d, "Lifecycle used")
    account = d["db"].scalar("SELECT id FROM accounts WHERE organisation_id=? AND system_role='SALES'", (d["oid"],))
    d["docs"].create_invoice(d["oid"], contact_id=used["id"], issue_date="2026-01-10", actor=ACTOR,
                             lines=[dict(account_id=account, unit_price="10.00")])
    visible = [row["name"] for row in d["client"].get(f"/organisations/{d['oid']}/contacts").json()]
    assert "Lifecycle orphan" in visible and "Lifecycle used" in visible
    assert d["client"].post(url(d, f"/contacts/{orphan['id']}/deactivate"), json={}).status_code == 200
    assert d["db"].scalar("SELECT active FROM contacts WHERE id=?", (orphan["id"],)) == 0
    visible = [row["name"] for row in d["client"].get(f"/organisations/{d['oid']}/contacts").json()]
    assert "Lifecycle orphan" not in visible
    hidden = [row["name"] for row in
              d["client"].get(f"/organisations/{d['oid']}/contacts?include_inactive=true").json()]
    assert "Lifecycle orphan" in hidden
    assert d["client"].post(url(d, f"/contacts/{orphan['id']}/reactivate"), json={}).status_code == 200
    assert d["db"].scalar("SELECT active FROM contacts WHERE id=?", (orphan["id"],)) == 1
    denied = d["client"].post(url(d, f"/contacts/{used['id']}/delete"), json={})
    assert denied.status_code == 422 and "without documents" in denied.text
    assert d["client"].post(url(d, f"/contacts/{orphan['id']}/delete"), json={}).status_code == 200
    assert d["db"].rows("SELECT id FROM contacts WHERE id=?", (orphan["id"],)) == []
    actions = [row["action"] for row in d["db"].rows(
        "SELECT action FROM audit_events WHERE action LIKE 'contact.%' ORDER BY created_at")]
    assert actions == ["contact.deactivated", "contact.reactivated", "contact.deleted"]


def test_item_actions_and_roles(sending):
    d = sending
    catalogue = item(d, "MAINT-1", "Maintenance widget")
    for role in ("accountant", "approver", "viewer"):
        assert d["client"].get(url(d, "/maintenance"), headers={"X-Test-User": role + "@example.test"}).status_code == 200
        assert d["client"].post(url(d, f"/items/{catalogue['id']}/deactivate"),
                                headers={"X-Test-User": role + "@example.test"}).status_code == 403
    assert d["client"].get(url(d, "/maintenance"), headers={"X-Test-User": "outsider@example.test"}).status_code == 403
    assert d["client"].post(url(d, f"/items/{catalogue['id']}/deactivate"), json={}).status_code == 200
    assert d["db"].scalar("SELECT active FROM items WHERE id=?", (catalogue["id"],)) == 0
    assert d["client"].post(url(d, f"/items/{catalogue['id']}/delete"), json={}).status_code == 200
    assert d["db"].rows("SELECT id FROM items WHERE id=?", (catalogue["id"],)) == []
    assert d["db"].scalar("SELECT action FROM audit_events WHERE action='item.deactivated'")
    assert d["db"].scalar("SELECT action FROM audit_events WHERE action='item.deleted'")
    assert d["client"].post(url(d, f"/items/missing/deactivate"), json={}).status_code == 404


@pytest.mark.parametrize("language", ["en", "et", "lt", "lv"])
def test_workspace_maintenance_keys(language):
    from web import i18n

    en = i18n.catalog("en")
    catalog = i18n.catalog(language)
    assert en["nav"]["maintenance"] == "Data maintenance"
    for key in ("Data maintenance", "Unused contacts", "Duplicate contacts",
                "Reused supplier numbers", "Delete contact"):
        assert key in catalog["workspace"], (language, key)


def test_workspace_maintenance_view_offline(sending):
    playwright = pytest.importorskip("playwright.sync_api")
    from web_app import app

    with TestClient(app) as client:
        html = client.get("/auth/test").text
    payload = {"unused_contacts": [{'id': 'c1', 'name': 'Orphan Ltd', 'contact_type': 'customer',
                                    'vat_no': None, 'registration_no': None, 'active': 1,
                                    'created_at': '2026-01-01T00:00:00+00:00'}],
               "duplicate_contacts": [], "contacts_missing_identifiers": [],
               "reused_supplier_numbers": [{"supplier_number": "RB-1", "suppliers": 2}]}
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
            if path.endswith("/master-data/maintenance"):
                return request_route.fulfill(json=payload, content_type="application/json")
            if path.startswith("/api/"):
                return request_route.fulfill(json=[], content_type="application/json")
            if path == "/app":
                return request_route.fulfill(body=html, content_type="text/html")
            if path in ("/static/app.js", "/static/app.css"):
                return request_route.fulfill(path=str(ROOT / path.lstrip("/")))
            return request_route.fulfill(status=404)

        page.route("**/*", route)
        page.goto("http://workspace.test/app#maintenance")
        playwright.expect(page.locator("h1")).to_have_text("Data maintenance")
        playwright.expect(page.locator("#app-content table").first).to_contain_text("Orphan Ltd")
        playwright.expect(page.locator("#app-content table").last).to_contain_text("RB-1")
        delete_button = page.locator('[data-action=deleteContact]')
        playwright.expect(delete_button.first).to_be_visible()
        assert not errors
        browser.close()