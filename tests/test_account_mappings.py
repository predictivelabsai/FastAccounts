from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient

from api_app import api
from core_utils import db_number, new_id, utc_now
from database import reset_database_cache
from integration_service import AccountMappingService
from ledger import LedgerService, PostingLine


def test_account_mapping_crud_and_resolve(db, uk_org):
    account = db.one(
        "SELECT code FROM accounts WHERE organisation_id=? AND account_type='Expense' ORDER BY code LIMIT 1",
        (uk_org["id"],),
    )
    service = AccountMappingService(db)
    created = service.create(
        uk_org["id"], "xero", local_account_code=account["code"],
        external_account_code="EXT-1", external_account_name="External one",
        actor="owner@example.test",
    )
    assert service.list(uk_org["id"], "xero")[0]["id"] == created["id"]
    assert service.resolve(uk_org["id"], "xero", account["code"])["id"] == created["id"]
    updated = service.update(
        uk_org["id"], "xero", created["id"], status="Confirmed", is_default=True,
        actor="owner@example.test",
    )
    assert updated["status"] == "Confirmed" and updated["is_default"] == 1
    overwritten = service.create(
        uk_org["id"], "xero", local_account_code=account["code"],
        external_account_code="EXT-1", external_account_name="Renamed",
        status="Confirmed", actor="owner@example.test",
    )
    assert overwritten["id"] == created["id"]
    assert len(service.list(uk_org["id"], "xero")) == 1


def test_reconciliation_endpoint_math(db, uk_org, monkeypatch):
    debit = db.one(
        "SELECT id,code FROM accounts WHERE organisation_id=? AND account_type='Expense' ORDER BY code LIMIT 1",
        (uk_org["id"],),
    )
    credit = db.one(
        "SELECT id FROM accounts WHERE organisation_id=? AND account_type='Liability' ORDER BY code LIMIT 1",
        (uk_org["id"],),
    )
    AccountMappingService(db).create(
        uk_org["id"], "xero", local_account_code=debit["code"],
        external_account_code="EXT-EXP", status="Confirmed", actor="owner@example.test",
    )
    LedgerService(db).post(
        organisation_id=uk_org["id"], voucher_type="manual_journal", voucher_id="reconcile-1",
        voucher_code="REC-1", posting_date="2026-10-05", actor="owner@example.test", currency="GBP",
        lines=[PostingLine(debit["id"], debit=Decimal("100")),
               PostingLine(credit["id"], credit=Decimal("100"))],
    )
    now = utc_now()
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO external_gl_entries(id,organisation_id,provider,external_id,external_batch_ref,"
            "entry_date,external_account_code,local_account_code,debit,credit,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (new_id(), uk_org["id"], "xero", "external-rec-1", "batch", "2026-10-05",
             "EXT-EXP", debit["code"], db_number(Decimal("90")), db_number(Decimal("0")), now),
        )
    rows = AccountMappingService(db).reconcile(
        uk_org["id"], "xero", date_from="2026-10-01", date_to="2026-10-31"
    )
    assert rows[0]["local_total"] == "100.00"
    assert rows[0]["external_total"] == "90.00"
    assert rows[0]["delta"] == "10.00"

    monkeypatch.setenv("FASTACCOUNTS_DB", db.path)
    monkeypatch.setenv("DB_URL", "")
    reset_database_cache()
    with TestClient(api, headers={"X-Test-User": "owner@example.test"}) as client:
        response = client.get(
            f"/organisations/{uk_org['id']}/integrations/xero/gl-reconciliation",
            params={"date_from": "2026-10-01", "date_to": "2026-10-31"},
        )
    reset_database_cache()
    assert response.status_code == 200, response.text
    assert response.json()["rows"][0]["delta"] == "10.00"
