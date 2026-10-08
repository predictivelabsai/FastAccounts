"""Browser regression for the tenant-scoped integration workspace."""
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient


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
        assert page.locator(".integration-provider").count() == 4, (
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
            page.locator('[data-action="integrationRuns"]')
        ).to_be_visible()
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        page.set_viewport_size({"width": 1440, "height": 1000})
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
