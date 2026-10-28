"""Contact and user groups: CRUD, membership, filtering and migration."""
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from test_bulk_sending import ACTOR, sending

ROOT = Path(__file__).resolve().parents[1]


def url(d, kind, suffix=""):
    return f"/organisations/{d['oid']}/{kind}-groups{suffix}"


def create_group(client, d, kind, name, **kwargs):
    response = client.post(url(d, kind), json={"name": name}, **kwargs)
    assert response.status_code == 201, response.text
    return response.json()


def customer(d, name):
    return d["docs"].create_contact(d["oid"], name=name, country_code="UK",
                                    contact_type="customer")


def test_migration_count_rerun_and_ci(sending):
    d = sending
    assert d["db"].scalar("SELECT COUNT(*) FROM schema_migrations") == 41
    assert d["db"].rows("SELECT * FROM contact_groups") == []
    assert d["db"].rows("SELECT * FROM user_groups") == []
    for _ in range(2):
        with d["db"].transaction() as tx:
            tx.execute("DELETE FROM schema_migrations WHERE version='0031_master_data_groups'")
        assert d["db"].migrate() == ["0031_master_data_groups"]
    assert "'0030_master_data_maintenance', '0031_master_data_groups', '0032_copilot_access', '0033_copilot_settings', '0034_payroll_demo_fixes', '0035_payroll_income_line', '0036_payroll_component_catalogue', '0037_employee_tax_settings', '0038_payroll_payday_rules', '0039_payroll_payouts', '0040_payroll_settlement_dates', '0041_payroll_sepa_details', '0042_payroll_component_metadata', '0043_payroll_absences']" in (ROOT / ".github/workflows/ci.yml").read_text()


def test_group_crud_membership_and_filter(sending):
    d = sending
    wholesale = create_group(d["client"], d, "contact", "Wholesale")
    retail = create_group(d["client"], d, "contact", "Retail")
    duplicate = d["client"].post(url(d, "contact"), json={"name": "Wholesale"})
    assert duplicate.status_code == 422 and "already exists" in duplicate.text
    first = customer(d, "Grouped customer")
    second = customer(d, "Other customer")
    added = d["client"].post(url(d, "contact", f"/{wholesale['id']}/members"),
                             json={"member": first["id"]})
    assert added.status_code == 201, added.text
    assert added.json()["members"] == [first["id"]]
    again = d["client"].post(url(d, "contact", f"/{wholesale['id']}/members"),
                             json={"member": first["id"]})
    assert again.status_code == 422 and "already" in again.text
    listing = d["client"].get(url(d, "contact")).json()
    assert [row["name"] for row in listing] == ["Retail", "Wholesale"]
    assert listing[1]["members"] == 1
    grouped = [row["name"] for row in d["client"].get(
        f"/organisations/{d['oid']}/contacts?group_id={wholesale['id']}").json()]
    assert grouped == ["Grouped customer"]
    removed = d["client"].delete(url(d, "contact", f"/{wholesale['id']}/members/{first['id']}"))
    assert removed.status_code == 200
    grouped = [row["name"] for row in d["client"].get(
        f"/organisations/{d['oid']}/contacts?group_id={wholesale['id']}").json()]
    assert grouped == []
    deleted = d["client"].delete(url(d, "contact", f"/{retail['id']}"))
    assert deleted.status_code == 200
    actions = [row["action"] for row in d["db"].rows(
        "SELECT action FROM audit_events WHERE action LIKE 'group.%' ORDER BY created_at")]
    assert actions == ["group.contact_created", "group.contact_created", "group.contact_member_added",
                       "group.contact_member_removed", "group.contact_deleted"]


def test_user_groups_membership_and_audit(sending):
    d = sending
    team = create_group(d["client"], d, "user", "Accounting team")
    for email in ("viewer@example.test", "accountant@example.test"):
        assert d["client"].post(url(d, "user", f"/{team['id']}/members"),
                                json={"member": email}).status_code == 201
    members = d["client"].get(url(d, "user", f"/{team['id']}/members")).json()
    assert sorted(members["members"]) == sorted(["viewer@example.test", "accountant@example.test"])
    unknown = d["client"].post(url(d, "user", f"/{team['id']}/members"),
                               json={"member": "stranger@example.test"})
    assert unknown.status_code == 201  # user groups may stage addresses not in memberships yet
    removed = d["client"].delete(url(d, "user", f"/{team['id']}/members/stranger@example.test"))
    assert removed.status_code == 200


def test_tenant_isolation_and_unknown_refs(sending):
    d = sending
    group = create_group(d["client"], d, "contact", "Isolated")
    foreign = d["client"].get(f"/organisations/{d['other']['id']}/contact-groups")
    if foreign.status_code == 200:
        assert foreign.json() == []
    assert d["client"].post(url(d, "contact", f"/{group['id']}/members"),
                            json={"member": "00000000-0000-0000-0000-000000000000"}).status_code == 404
    assert d["client"].get(url(d, "contact", f"/{group['id']}/members")).status_code == 200
    assert d["client"].delete(url(d, "contact", "/missing/members/x")).status_code == 404


@pytest.mark.parametrize("role,expected_list,expected_write", [
    ("owner", 200, 201), ("administrator", 200, 201),
    ("accountant", 200, 403), ("approver", 200, 403), ("viewer", 200, 403),
])
def test_roles(sending, role, expected_list, expected_write):
    d = sending
    if role == "owner":
        headers = {"X-Test-User": ACTOR}
    else:
        headers = {"X-Test-User": role + "@example.test"}
    if role == "outsider":
        return
    listing = d["client"].get(url(d, "contact"), headers=headers)
    assert listing.status_code == expected_list
    created = d["client"].post(url(d, "contact"), json={"name": f"Role {role}"}, headers=headers)
    assert created.status_code == expected_write
    assert d["client"].delete(url(d, "contact", f"/{created.json().get('id', 'x')}"),
                              headers=headers).status_code == (200 if expected_write == 201 else 403)


@pytest.mark.parametrize("language", ["en", "et", "lt", "lv"])
def test_workspace_group_keys(language):
    from web import i18n

    en = i18n.catalog("en")
    catalog = i18n.catalog(language)
    assert en["nav"]["groups"] == "Groups"
    for key in ("Groups", "Contact groups", "User groups", "Create group",
                "Members of {name}", "No members yet."):
        assert key in catalog["workspace"], (language, key)


def test_workspace_groups_view_offline(sending):
    playwright = pytest.importorskip("playwright.sync_api")
    from web_app import app

    with TestClient(app) as client:
        html = client.get("/auth/test").text
    groups = [{"id": "g1", "name": "Wholesale", "members": 2, "created_at": "2026-01-01T00:00:00+00:00"}]
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
            if path.endswith("/contact-groups") or path.endswith("/user-groups"):
                return request_route.fulfill(json=groups if "contact" in path else [],
                                             content_type="application/json")
            if path.endswith("/contacts"):
                return request_route.fulfill(json=[], content_type="application/json")
            if path.endswith("/members"):
                return request_route.fulfill(json=dict(group=dict(id="g1", name="Wholesale"),
                                                       members=["m1"]), content_type="application/json")
            if path.startswith("/api/"):
                return request_route.fulfill(json=[], content_type="application/json")
            if path == "/app":
                return request_route.fulfill(body=html, content_type="text/html")
            if path in ("/static/app.js", "/static/app.css"):
                return request_route.fulfill(path=str(ROOT / path.lstrip("/")))
            return request_route.fulfill(status=404)

        page.route("**/*", route)
        page.goto("http://workspace.test/app#groups")
        playwright.expect(page.locator("h1")).to_have_text("Groups")
        playwright.expect(page.locator("#app-content table").first).to_contain_text("Wholesale")
        page.locator('[data-action=manageMembers]').first.click()
        playwright.expect(page.locator(".dialog")).to_contain_text("m1")
        assert not errors
        browser.close()