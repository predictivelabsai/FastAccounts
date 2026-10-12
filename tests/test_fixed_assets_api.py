"""Authenticated, synthetic fixed asset API workflows and locale coverage."""
from calendar import monthrange
from decimal import Decimal
import json
from pathlib import Path

from fastapi.testclient import TestClient

from api_app import api, current_user, require_csrf
from database import reset_database_cache
from documents import DocumentService


def test_fixed_asset_api_workflow_and_tenant_scope(db, uk_org, ee_org, monkeypatch):
    monkeypatch.setenv("FASTACCOUNTS_DB", db.path)
    monkeypatch.setenv("DB_URL", "")
    reset_database_cache()
    client = TestClient(api, headers={"X-Test-User": "owner@example.test"})
    base = f"/organisations/{uk_org['id']}"
    other = f"/organisations/{ee_org['id']}"
    bank = DocumentService(db).create_bank_account(uk_org['id'], name="Synthetic asset bank", currency="GBP")
    day = db.scalar("SELECT starts_on FROM fiscal_periods WHERE organisation_id=? ORDER BY starts_on LIMIT 1", (uk_org['id'],))
    year, month = map(int, day[:7].split("-"))
    end = f"{year}-{month:02d}-{monthrange(year, month)[1]:02d}"
    groups = client.get(base + "/asset-groups?locale=et").json()
    assert len(groups) == 3
    response = client.post(base + "/asset-groups", json={"name": "Synthetic group", "annual_percentage": "20", "frequency": "monthly"})
    assert response.status_code == 201, response.text
    group = response.json()
    payload = dict(group_id=group['id'], name="Synthetic desk", acquisition_date=day,
                   acquisition_cost="1200", bank_account_id=bank['id'], idempotency_key="asset-api-acquisition")
    response = client.post(base + "/fixed-assets", json=payload)
    assert response.status_code == 201, response.text
    asset = response.json()
    assert asset['acquisition_cost'] == '1200.00'
    assert asset['disposal_depreciation_amount'] == '0.00'
    assert client.post(base + "/fixed-assets", json=payload).json()['id'] == asset['id']
    assert client.post(other + "/fixed-assets", json={**payload, "idempotency_key": "other"}).status_code == 404
    run_payload = dict(period_date=end, kind="monthly")
    response = client.post(base + "/fixed-assets/runs", json=run_payload)
    assert response.status_code == 200, response.text
    run = response.json()
    assert client.post(base + "/fixed-assets/runs", json=run_payload).json() == run
    register = client.get(base + "/fixed-assets").json()
    assert Decimal(register['assets'][0]['accumulated_depreciation']) == Decimal("20")
    assert client.get(base + "/fixed-assets/schedule").json()[0]['asset_id'] == asset['id']
    assert client.get(base + "/fixed-assets/runs").json()[0]['id'] == run['id']
    disposal = dict(disposal_date=end, disposal_amount="900", bank_account_id=bank['id'])
    assert client.post(other + f"/fixed-assets/{asset['id']}/dispose", json=disposal).status_code == 404
    response = client.post(base + f"/fixed-assets/{asset['id']}/dispose", json=disposal)
    assert response.status_code == 200, response.text
    assert response.json()['disposal_amount'] == '900.00'
    assert client.get(base + "/fixed-assets").json()['assets'][0]['carrying_value'] == "0.00"
    with db.transaction() as tx:
        tx.execute("UPDATE memberships SET role='viewer' WHERE organisation_id=?", (uk_org['id'],))
    for endpoint in ("/asset-groups", "/fixed-assets", "/fixed-assets/schedule", "/fixed-assets/runs"):
        assert client.get(base + endpoint).status_code == 200
        assert client.get(base + endpoint, headers={"X-Test-User": "outsider@example.invalid"}).status_code == 403
    for endpoint, data in (("/asset-groups", {"name": "Restricted", "annual_percentage": "20"}),
                           ("/fixed-assets", payload), ("/fixed-assets/runs", run_payload),
                           (f"/fixed-assets/{asset['id']}/dispose", disposal)):
        assert client.post(base + endpoint, json=data).status_code == 403
    reset_database_cache()


def test_fixed_asset_api_dependencies_and_all_locales():
    routes = [r for r in api.routes if "/fixed-assets" in r.path or "/asset-groups" in r.path]
    assert len(routes) == 8
    for route in routes:
        expected = current_user if route.methods == {"GET"} else require_csrf
        assert expected in [d.call for d in route.dependant.dependencies]
    for lang in ("en", "et", "lt", "lv"):
        catalogue = json.loads((Path(__file__).resolve().parents[1] / "web" / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
        assert catalogue['nav']['fixed_assets']
        for key in ("Fixed assets", "Asset group", "Run depreciation", "Dispose asset", "Depreciation runs"):
            assert catalogue['workspace'][key]
