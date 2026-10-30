"""Browser regression for the tenant-scoped integration workspace."""
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("language", ["et", "lt", "lv"])
def test_mobile_catalogue_copy_and_wrapping(monkeypatch, language):
    playwright = pytest.importorskip("playwright.sync_api")
    import integrations
    from connectors.registry import provider_metadata
    from web import i18n
    from web_app import app

    monkeypatch.setenv("FASTACCOUNTS_DEFAULT_LANG", language)
    html = TestClient(app).get("/auth/test").text
    root = Path(__file__).resolve().parents[1]
    catalogue = [{**item.__dict__, **provider_metadata(item.key)} for item in integrations.CATALOGUE]
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        page = browser.new_page(viewport={"width": 375, "height": 844})

        def respond(route):
            path = urlsplit(route.request.url).path
            if path == "/app":
                return route.fulfill(body=html, content_type="text/html")
            if path.startswith("/static/"):
                file = root / path.lstrip("/")
                if file.is_file():
                    return route.fulfill(path=str(file))
            if path == "/api/organisations":
                return route.fulfill(json=[dict(id="org", name="Synthetic books", country_code="EE", base_currency="EUR", role="owner")])
            if path == "/api/integrations":
                return route.fulfill(json=catalogue)
            if path == "/api/csrf":
                return route.fulfill(json={"csrf_token": "synthetic"})
            if path.startswith("/api/"):
                return route.fulfill(json=[], content_type="application/json")
            return route.fulfill(status=404)

        page.route("**/*", respond)
        page.goto("http://workspace.test/app#integrations")
        card = page.locator('.integration-provider[data-provider="smartaccounts"]')
        copy = i18n.integration_copy(language, "smartaccounts")
        playwright.expect(card).to_contain_text(copy["description"])
        playwright.expect(card).to_contain_text(copy["direction"])
        assert card.locator(".integration-provider-head").evaluate("el => getComputedStyle(el).flexDirection") == "column"
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        for pill in page.locator(".status-pill").all():
            assert pill.evaluate("el => getComputedStyle(el).whiteSpace") == "normal"
        browser.close()


@pytest.mark.parametrize("object_type,label", [("employee", "Employees"), ("contact", "Contacts")])
def test_smartaccounts_reviewed_import(monkeypatch, db, ee_org, object_type, label):
    playwright = pytest.importorskip("playwright.sync_api")
    import httpx
    from dataclasses import replace
    from datetime import datetime, timezone
    from api_app import api
    from connectors.providers import SmartAccountsProvider
    from connectors.registry import REGISTRY
    from database import reset_database_cache
    from documents import DocumentService
    from web_app import app

    monkeypatch.setenv("FASTACCOUNTS_DB", db.path)
    monkeypatch.setenv("DB_URL", "")
    monkeypatch.setenv("FASTACCOUNTS_ALLOW_TEST_AUTH", "true")
    monkeypatch.setenv("FASTACCOUNTS_DEFAULT_LANG", "en")
    reset_database_cache()
    state = {"fail": True, "empty": False}
    provider_calls, sync_calls = [], []
    names = ["Mari Testmaa", "Jaan Testmaa"] if object_type == "employee" else ["Synthetic Client One", "Synthetic Client Two"]

    def provider_response(request):
        provider_calls.append(request.url.path)
        if request.url.path.endswith("settings/accounts:get"):
            return httpx.Response(200, json={"accounts": []})
        if state["fail"]:
            raise RuntimeError("Synthetic pull failure")
        if object_type == "employee":
            records = [{
                "id": index, "forename": name.split()[0], "surname": "Testmaa",
                "startDate": "2025-01-01", "vendor": {"email": f"worker{index}@example.test"},
                "contracts": [{"startDate": "2025-01-01", "grossSum": "2400.00", "payoutType": "SALARY"}],
            } for index, name in enumerate(names, 1)]
            key = "workers"
        else:
            records = [{"id": index, "name": name, "regCode": f"SYNTHETIC-{index}",
                        "contacts": [{"type": "EMAIL", "value": f"client{index}@example.test"}],
                        "address": {"country": "EE"}}
                       for index, name in enumerate(names, 1)]
            key = "clients"
        return httpx.Response(200, json={key: [] if state["empty"] else records, "hasMoreEntries": False})

    transport_client = httpx.Client(transport=httpx.MockTransport(provider_response))
    monkeypatch.setitem(REGISTRY, "smartaccounts", replace(
        REGISTRY["smartaccounts"], factory=lambda credentials, config: SmartAccountsProvider(
            "synthetic-public", "synthetic-secret", lang="en", client=transport_client,
            clock=lambda: datetime(2026, 10, 14, 12, tzinfo=timezone.utc),
        ),
    ))
    if object_type == "contact":
        DocumentService(db).create_contact(ee_org["id"], name=names[0], country_code="EE",
                                          registration_no="SYNTHETIC-1", email="client1@example.test")
    html = TestClient(app).get("/auth/test").text
    root = Path(__file__).resolve().parents[1]
    base = f"/organisations/{ee_org['id']}/integrations/smartaccounts"
    try:
        with TestClient(api, headers={"X-Test-User": "owner@example.test"}) as client:
            configured = client.post(base, json={"credentials": {"api_key": "synthetic-public", "secret_key": "synthetic-secret"}, "config": {}})
            assert configured.status_code == 200, configured.text
            with playwright.sync_playwright() as runtime:
                browser = runtime.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))

                def respond(route):
                    path = urlsplit(route.request.url).path
                    if path == "/app":
                        return route.fulfill(body=html, content_type="text/html")
                    if path.startswith("/static/"):
                        file = root / path.lstrip("/")
                        return route.fulfill(path=str(file)) if file.is_file() else route.fulfill(status=404)
                    if path.startswith("/api/"):
                        if path == "/api/csrf":
                            return route.fulfill(json={"csrf_token": "synthetic-csrf"})
                        payload = route.request.post_data_json if route.request.post_data else None
                        if path.endswith("/sync"):
                            sync_calls.append(payload)
                        response = client.request(route.request.method, path.removeprefix("/api"), json=payload)
                        return route.fulfill(status=response.status_code, body=response.content,
                                             content_type=response.headers.get("content-type", "application/json"))
                    return route.fulfill(status=404)

                page.route("**/*", respond)
                page.goto("http://workspace.test/app#integrations")
                card = page.locator('.integration-provider[data-provider="smartaccounts"]')
                import_button = card.get_by_role("button", name="Import data", exact=True)
                playwright.expect(import_button).to_be_disabled()
                playwright.expect(import_button).to_have_attribute("title", "Test the connection before importing.")
                card.get_by_role("button", name="Test connection", exact=True).click()
                page.locator('.dialog [name="api_key"]').fill("synthetic-public")
                page.locator('.dialog [name="secret_key"]').fill("synthetic-secret")
                page.locator('.dialog [data-action="testConnection"]').click()
                playwright.expect(import_button).to_be_enabled()
                page.locator('.dialog [data-close]').click()
                import_button.click()
                dialog = page.locator(".dialog")
                playwright.expect(dialog).to_contain_text("Records are staged for review. Nothing changes until decisions are applied.")
                assert dialog.locator('[name="object_type"] option').all_text_contents() == [
                    "Chart of accounts", "Contacts", "Sales invoices", "Purchase invoices", "Payments", "General ledger entries", "Employees"]
                dialog.locator('[name="object_type"]').select_option(label=label)
                dialog.locator('[type="submit"]').click()
                playwright.expect(dialog.locator(".form-error")).to_have_text("Connector pull failed")
                playwright.expect(dialog.locator('[type="submit"]')).to_be_enabled()
                state["fail"] = False
                dialog.locator('[type="submit"]').click()
                expected_title = "Review employee import" if object_type == "employee" else "Review import: Contacts"
                playwright.expect(page.locator("#app-content h1")).to_have_text(expected_title)
                assert f"#integrations/review/smartaccounts/" in page.url
                playwright.expect(page.locator("#app-content tbody tr")).to_have_count(2)
                for name in names:
                    playwright.expect(page.locator("#app-content")).to_contain_text(name)
                playwright.expect(page.locator(".toast").last).to_contain_text("Records staged: 2")
                section = "Staged employees" if object_type == "employee" else "Staged records"
                column = "Matched employee" if object_type == "employee" else "Matched record"
                playwright.expect(page.locator("#app-content h2")).to_have_text(section)
                playwright.expect(page.get_by_role("columnheader", name=column, exact=True)).to_be_visible()
                if object_type == "contact":
                    matched_row = page.locator("tbody tr").filter(has_text=names[0])
                    playwright.expect(matched_row.locator("td").nth(2)).to_have_text(names[0])
                    playwright.expect(matched_row.locator("td").first).to_contain_text("SYNTHETIC-1 · client1@example.test")
                assert db.scalar("SELECT COUNT(*) FROM employees WHERE organisation_id=?", (ee_org["id"],)) == 0
                page.get_by_role("link", name="Recent runs", exact=True).click()
                playwright.expect(page.locator("#app-content h1")).to_have_text("Import runs")
                playwright.expect(page.get_by_role("columnheader", name="Object type", exact=True)).to_be_visible()
                playwright.expect(page.locator("tbody")).to_contain_text(label)
                state["empty"] = True
                page.get_by_role("link", name="Back to integrations", exact=True).first.click()
                import_button.click()
                dialog.locator('[name="object_type"]').select_option(label=label)
                dialog.locator('[type="submit"]').click()
                empty_copy = "The sync completed without new employee records." if object_type == "employee" else "The sync completed without new records."
                playwright.expect(page.locator("#app-content")).to_contain_text(empty_copy)
                assert sync_calls == [{"object_type": object_type}] * 3
                assert any(path.endswith("workers:get" if object_type == "employee" else "clients:get") for path in provider_calls)
                assert not errors
                browser.close()
    finally:
        transport_client.close()
        reset_database_cache()


def test_workspace_integration_connection_and_review_flow(monkeypatch):
    playwright = pytest.importorskip("playwright.sync_api")
    import integrations
    from connectors.registry import provider_metadata
    from web_app import app

    monkeypatch.setenv("FASTACCOUNTS_ALLOW_TEST_AUTH", "true")
    monkeypatch.setenv("FASTACCOUNTS_DEFAULT_LANG", "en")
    html = TestClient(app).get("/auth/test").text
    root = Path(__file__).resolve().parents[1]
    catalogue = [
        {**item.__dict__, **provider_metadata(item.key)}
        for item in integrations.CATALOGUE
    ]
    connections = []
    records = [
        {
            "id": "staged-1",
            "external_id": "employee-1",
            "status": "Pending",
            "matched_local_employee_name": "Local Mari",
            "review_note": None,
            "external_payload": {
                "name": "Mari Maasik",
                "email": "mari@example.test",
                "gross_salary": "2100.00",
            },
        },
        {
            "id": "staged-2",
            "external_id": "employee-2",
            "status": "Failed",
            "matched_local_employee_name": None,
            "review_note": "Employee name is required",
            "external_payload": {"email": "missing-name@example.test"},
        },
    ]
    summary = {
        "id": "run-1",
        "provider": "fasthr",
        "object_type": "employee",
        "status": "Review Required",
        "read_count": 2,
        "staged_counts": {
            "Pending": 1,
            "Applied": 0,
            "Rejected": 0,
            "Failed": 1,
        },
        "started_at": "2026-10-09T10:00:00Z",
    }
    file_summary = {
        **summary,
        "id": "file-run-1",
        "provider": "file_import",
        "read_count": 1,
        "staged_counts": {
            "Pending": 1,
            "Applied": 0,
            "Rejected": 0,
            "Failed": 0,
        },
    }
    file_records = [{
        "id": "file-staged-1",
        "external_id": "file-employee-1",
        "status": "Pending",
        "matched_local_employee_name": None,
        "review_note": None,
        "external_payload": {
            "name": "CSV Mari",
            "email": "csv-mari@example.test",
            "gross_salary": "2200.00",
        },
    }]
    calls = []

    with playwright.sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch()
        except playwright.Error as exc:
            if "Executable doesn't exist" in str(exc):
                pytest.skip("Install Playwright Chromium to run browser regressions")
            raise
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page_errors = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))

        def respond(route):
            path = urlsplit(route.request.url).path
            method = route.request.method
            payload = json.loads(route.request.post_data or "{}")
            if path.startswith("/api/"):
                calls.append((path, method, payload))
                if path == "/api/csrf":
                    return route.fulfill(json={"csrf_token": "synthetic-csrf"})
                if path == "/api/organisations":
                    return route.fulfill(
                        json=[
                            {
                                "id": "org",
                                "name": "Demo OÜ",
                                "country_code": "EE",
                                "base_currency": "EUR",
                            }
                        ]
                    )
                if path == "/api/integrations":
                    return route.fulfill(json=catalogue)
                if path == "/api/email-status":
                    return route.fulfill(
                        json={"connected": False, "provider": "postmark", "from_email": ""}
                    )
                if path == "/api/organisations/org/integrations" and method == "GET":
                    return route.fulfill(
                        body=json.dumps(connections), content_type="application/json"
                    )
                if path.endswith("/integrations/fasthr/test"):
                    failed = payload.get("credentials", {}).get("token") == "bad-token"
                    if connections:
                        connections[0]["status"] = "Error" if failed else "Connected"
                    return route.fulfill(
                        json={
                            "provider": "fasthr",
                            "operation": "check",
                            "ok": not failed,
                            "live": True,
                            "message": (
                                "FastHR API authentication failed (HTTP 401)"
                                if failed
                                else "FastHR connection succeeded"
                            ),
                        }
                    )
                if path.endswith("/integrations/fasthr") and method == "POST":
                    connection = {
                        "id": "connection-1",
                        "provider": "fasthr",
                        "status": "Configured",
                        "external_tenant_id": payload.get("external_tenant_id"),
                        "config": {},
                        "registry_status": "Adapter ready",
                    }
                    connections[:] = [connection]
                    return route.fulfill(json=connection)
                if path.endswith("/integrations/fasthr/sync") and method == "POST":
                    return route.fulfill(json=summary)
                if path.endswith("/integrations/file_import/import") and method == "POST":
                    return route.fulfill(json=file_summary)
                if path.endswith("/integrations/file_import/sync/file-run-1"):
                    return route.fulfill(
                        json={"summary": file_summary, "records": file_records}
                    )
                if path.endswith("/integrations/file_import/syncs"):
                    return route.fulfill(json=[file_summary])
                if path.endswith("/integrations/fasthr/sync/run-1/apply"):
                    records[0]["status"] = "Applied"
                    records[1]["status"] = "Rejected"
                    summary["status"] = "Completed"
                    summary["staged_counts"] = {
                        "Pending": 0,
                        "Applied": 1,
                        "Rejected": 1,
                        "Failed": 0,
                    }
                    return route.fulfill(
                        json={
                            "sync_run_id": "run-1",
                            "applied": 1,
                            "updated": 0,
                            "unchanged": 0,
                            "rejected": 1,
                            "failed": 0,
                            "outcomes": [
                                {"staged_id": "staged-1", "outcome": "applied"},
                                {"staged_id": "staged-2", "outcome": "rejected"},
                            ],
                        }
                    )
                if path.endswith("/integrations/fasthr/sync/run-1"):
                    return route.fulfill(json={"summary": summary, "records": records})
                if path.endswith("/integrations/fasthr/sync/run-empty"):
                    empty_summary = {**summary, "id": "run-empty", "read_count": 0}
                    empty_summary["staged_counts"] = {
                        "Pending": 0,
                        "Applied": 0,
                        "Rejected": 0,
                        "Failed": 0,
                    }
                    return route.fulfill(
                        json={"summary": empty_summary, "records": []}
                    )
                if path.endswith("/integrations/fasthr/syncs"):
                    return route.fulfill(json=[summary])
                return route.fulfill(status=404, json={"detail": "Unexpected API route"})
            if path == "/app":
                return route.fulfill(body=html, content_type="text/html")
            if path in ("/static/app.js", "/static/app.css"):
                return route.fulfill(path=str(root / path.lstrip("/")))
            return route.fulfill(status=404)

        page.route("**/*", respond)
        page.goto("http://workspace.test/app#integrations")
        page.wait_for_timeout(500)
        assert page.locator(".integration-provider").count() == 8, (
            page_errors,
            page.locator("#app-content").inner_text(),
            calls,
        )
        playwright.expect(page.locator(".planned-integrations")).not_to_have_attribute(
            "open", ""
        )
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(300)
        playwright.expect(page.locator(".integration-provider").first).to_be_visible()
        playwright.expect(
            page.locator('[data-action="integrationRuns"]').first
        ).to_be_visible()
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        ), page.evaluate("""() => [...document.querySelectorAll('#app-content *')]
            .filter(el => el.getBoundingClientRect().right > innerWidth)
            .map(el => ({tag: el.tagName, cls: el.className, text: el.textContent.slice(0, 80),
                right: el.getBoundingClientRect().right}))""")
        page.set_viewport_size({"width": 1440, "height": 1000})
        file_import = page.locator('.integration-provider[data-provider="file_import"]')
        playwright.expect(file_import).to_contain_text("No connection needed")
        playwright.expect(
            file_import.locator('[data-action="configureIntegration"]')
        ).to_have_count(0)
        file_import.locator('[data-action="importEmployeeFile"]').click()
        page.locator('.dialog input[name="employee_file"]').set_input_files({
            "name": "employees.csv",
            "mimeType": "text/csv",
            "buffer": b"Name,Email,Salary\nCSV Mari,csv-mari@example.test,2200\n",
        })
        page.locator('.dialog [type="submit"]').click()
        playwright.expect(page.locator("#app-content h1")).to_have_text(
            "Review employee import"
        )
        playwright.expect(page.locator("#app-content")).to_contain_text("CSV Mari")
        file_call = next(
            payload
            for path, method, payload in calls
            if path.endswith("/integrations/file_import/import") and method == "POST"
        )
        assert file_call == {
            "object_type": "employee",
            "csv_content": "Name,Email,Salary\nCSV Mari,csv-mari@example.test,2200\n",
        }
        page.evaluate("location.hash = 'integrations'")
        playwright.expect(page.locator("#app-content h1")).to_have_text("Integrations")
        fasthr = page.locator('.integration-provider[data-provider="fasthr"]')
        playwright.expect(fasthr).to_contain_text("Not configured")

        fasthr.locator('[data-action="configureIntegration"]').click()
        secret = page.locator('.dialog input[name="token"]')
        playwright.expect(secret).to_have_attribute("type", "password")
        playwright.expect(secret).to_have_value("")
        secret.fill("synthetic-secret")
        page.locator('.dialog [data-action="testConnection"]').click()
        playwright.expect(page.locator(".connection-test-result")).to_contain_text(
            "Live connection"
        )
        page.locator('.dialog [type="submit"]').click()
        playwright.expect(page.locator(".dialog")).to_have_count(0)
        playwright.expect(fasthr).to_contain_text("Configured")
        assert "synthetic-secret" not in page.locator("body").inner_text()

        fasthr.locator('[data-action="testIntegration"]').click()
        playwright.expect(secret).to_have_value("")
        secret.fill("bad-token")
        page.locator('.dialog [data-action="testConnection"]').click()
        playwright.expect(page.locator(".connection-test-result")).to_contain_text(
            "HTTP 401"
        )
        playwright.expect(fasthr).to_contain_text("Error")
        playwright.expect(
            fasthr.locator('[data-action="runEmployeeImport"]')
        ).to_be_disabled()
        secret.fill("synthetic-secret")
        page.locator('.dialog [data-action="testConnection"]').click()
        playwright.expect(fasthr).to_contain_text("Connected")
        page.locator(".dialog [data-close]").click()
        import_button = fasthr.locator('[data-action="runEmployeeImport"]')
        playwright.expect(import_button).to_be_enabled()
        import_button.click()

        playwright.expect(page.locator("#app-content h1")).to_have_text(
            "Review employee import"
        )
        playwright.expect(page.locator("#app-content tbody tr")).to_have_count(2)
        page.locator('[data-id="staged-1"][data-decision="apply"]').check()
        page.locator('[data-id="staged-2"][data-decision="reject"]').check()
        page.locator('[data-action="applyImportDecisions"]').click()
        playwright.expect(page.locator(".outcome-summary")).to_contain_text(
            "Import outcomes"
        )
        playwright.expect(page.locator("#app-content .notice")).to_contain_text(
            "No records are awaiting a decision."
        )
        apply_call = next(
            payload
            for path, method, payload in calls
            if path.endswith("/sync/run-1/apply") and method == "POST"
        )
        assert apply_call == {
            "decisions": {"staged-1": "apply", "staged-2": "reject"}
        }

        page.locator('a[href="#integrations/runs/fasthr"]').click()
        playwright.expect(page.locator("#app-content h1")).to_have_text(
            "Employee import runs"
        )
        playwright.expect(page.locator("#app-content tbody tr")).to_have_count(1)

        page.evaluate("location.hash = 'integrations/review/fasthr/run-empty'")
        playwright.expect(page.locator("#app-content")).to_contain_text(
            "No records were staged"
        )
        playwright.expect(
            page.locator('[data-action="applyImportDecisions"]')
        ).to_be_disabled()

        page.evaluate("location.hash = 'integrations/review/unknown/run-1'")
        playwright.expect(page.locator("#app-content h1")).to_have_text(
            "Integration not found"
        )
        browser.close()
