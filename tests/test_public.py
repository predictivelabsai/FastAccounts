"""Public shell, integration catalogue, auth guard, and health checks."""
from __future__ import annotations

from starlette.testclient import TestClient

import integrations
from web.public import integrations_page, landing_page, login_page
from web_app import app


client = TestClient(app)


def test_landing_has_primary_product_and_sign_in_routes():
    rendered = str(landing_page())
    assert "Bookkeeping that stays clear" in rendered
    assert 'href="/integrations"' in rendered
    assert 'href="/login"' in rendered
    assert "UK and Estonian VAT" in rendered


def test_integration_catalogue_lists_platforms_agents_and_bank_plan():
    rendered = str(integrations_page())
    for name in (
        "QuickBooks Online",
        "Xero",
        "Merit Aktiva",
        "HMRC Making Tax Digital",
        "Estonian Tax and Customs Board",
        "Open banking",
    ):
        assert name in rendered
    for item in integrations.CATALOGUE:
        assert item.status not in rendered
    assert "No provider below is connected by default" in rendered
    assert "Configured per object" in rendered


def test_integration_status_remains_available_to_internal_workspace():
    response = client.get("/api/integrations", headers={"X-Test-User": "viewer@test.invalid"})
    assert response.status_code == 200
    assert [item["status"] for item in response.json()] == [
        item.status for item in integrations.CATALOGUE
    ]


def test_provider_logos_have_accessible_alt_text_and_local_assets_resolve():
    rendered = str(integrations_page())
    for item in integrations.CATALOGUE:
        assert f'alt="{item.logo_alt}"' in rendered
        if item.logo.startswith("/static/"):
            response = client.get(item.logo)
            assert response.status_code == 200
            assert "image/svg+xml" in response.headers["content-type"]


def test_login_explains_disabled_google_configuration(monkeypatch):
    for key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
        monkeypatch.delenv(key, raising=False)
    rendered = str(login_page())
    assert "Google sign-in is not configured" in rendered
    response = client.get("/auth/google", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?error=")


def test_google_callback_rejects_missing_or_invalid_state_without_network():
    response = client.get(
        "/auth/google/callback?code=unused&state=invalid",
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "state+was+invalid" in response.headers["location"]


def test_workspace_requires_authentication():
    response = client.get("/app", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?next=")


def test_health_reports_every_connector_as_non_live():
    with TestClient(app) as live_client:
        response = live_client.get("/healthz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["product"] == "FastAccounts"
    assert payload["integrations"] == len(integrations.CATALOGUE)
    assert payload["live_integrations"] == 0
    assert payload["database"]["status"] == "ok"
    assert payload["database"]["migrations"] == 4
