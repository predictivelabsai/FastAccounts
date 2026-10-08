from __future__ import annotations

import os

from fastapi.testclient import TestClient

from api_app import api
from database import reset_database_cache


def test_api_auth_openapi_and_full_invoice_flow(tmp_path,monkeypatch):
    monkeypatch.setenv("FASTACCOUNTS_DB",str(tmp_path/"api.sqlite"))
    monkeypatch.setenv("FASTACCOUNTS_ALLOW_TEST_AUTH","true")
    reset_database_cache()
    from database import get_database
    get_database().migrate()
    client=TestClient(api)
    assert client.get("/organisations").status_code==401
    headers={"X-Test-User":"api@example.test"}
    response=client.post("/organisations",headers=headers,json={"name":"API Ltd","country_code":"UK","entity_type":"UK_COMPANY"})
    assert response.status_code==201,response.text
    org=response.json()
    accounts=client.get(f"/organisations/{org['id']}/accounts",headers=headers).json()
    taxes=client.get(f"/organisations/{org['id']}/tax-codes",headers=headers).json()
    contact=client.post(f"/organisations/{org['id']}/contacts",headers=headers,json={"name":"API Customer","country_code":"GB","contact_type":"customer"}).json()
    sale=next(x for x in accounts if x["system_role"]=="SALES")
    tax=next(x for x in taxes if x["code"]=="UK20")
    posting_date=get_database().scalar("SELECT starts_on FROM fiscal_periods WHERE organisation_id=? ORDER BY starts_on LIMIT 1",(org["id"],))
    invoice=client.post(f"/organisations/{org['id']}/invoices",headers=headers,json={"contact_id":contact["id"],"issue_date":posting_date,"lines":[{"description":"API work","quantity":"1","unit_price":"100","account_id":sale["id"],"tax_code_id":tax["id"]}]}).json()
    issued=client.post(f"/organisations/{org['id']}/invoices/{invoice['id']}/issue",headers=headers).json()
    assert issued["number"]=="INV-000001"
    assert client.get(f"/organisations/{org['id']}/invoices/{invoice['id']}.pdf",headers=headers).content.startswith(b"%PDF")
    assert client.get("/openapi.json").json()["info"]["title"]=="FastAccounts API"


def test_api_cross_tenant_access_is_forbidden(tmp_path,monkeypatch):
    monkeypatch.setenv("FASTACCOUNTS_DB",str(tmp_path/"tenant-api.sqlite"));reset_database_cache()
    from database import get_database
    get_database().migrate();client=TestClient(api)
    owner={"X-Test-User":"owner@test.invalid"};other={"X-Test-User":"other@test.invalid"}
    org=client.post("/organisations",headers=owner,json={"name":"Private","country_code":"EE","entity_type":"EE_OU"}).json()
    assert client.get(f"/organisations/{org['id']}/accounts",headers=other).status_code==403


def test_tax_code_descriptions_follow_organisation_country(db, uk_org, ee_org, monkeypatch):
    monkeypatch.setenv("FASTACCOUNTS_DB", db.path)
    monkeypatch.setenv("DB_URL", "")
    client = TestClient(api)
    headers = {"X-Test-User": "owner@example.test"}
    expected = {
        uk_org["id"]: {
            "UK20": "Standard rate 20%", "UK5": "Reduced rate 5%",
            "UK0": "Zero rated", "UKEX": "Exempt",
            "UKOS": "Outside scope", "UKRC": "Reverse charge",
        },
        ee_org["id"]: {
            "EE24": "Standardmäär 24%", "EE13": "Vähendatud määr 13%",
            "EE9": "Vähendatud määr 9%", "EE0": "Nullmääraga käive",
            "EEEX": "Maksuvaba käive", "EEOS": "Käibemaksu kohaldamisalast väljas",
            "EERC": "Pöördmaksustamine", "EEICS": "Ühendusesisene käive",
        },
    }
    for oid, descriptions in expected.items():
        response = client.get(f"/organisations/{oid}/tax-codes", headers=headers)
        assert response.status_code == 200
        assert {row["code"]: row["name"] for row in response.json()} == descriptions
