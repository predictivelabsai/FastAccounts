"""Offline coverage for generalized reviewed connector imports."""
from __future__ import annotations

from dataclasses import replace

import pytest
from cryptography.fernet import Fernet

from connectors.base import ConnectorResult
from connectors.registry import REGISTRY
from import_service import ImportService
from integration_service import CredentialVault, IntegrationService


class ObjectConnector:
    key = "xero"
    PULL_OBJECT_TYPES = (
        "contact", "purchase_invoice", "sales_invoice", "payment", "account", "gl_entry"
    )

    def __init__(self, records):
        self.records = tuple(records)

    def pull(self, object_type, *, cursor=None):
        return ConnectorResult(
            self.key, f"pull:{object_type}", True, False, "Synthetic offline pull",
            self.records, cursor,
        )


@pytest.fixture
def object_import(db, uk_org, monkeypatch):
    integration = IntegrationService(db, CredentialVault(Fernet.generate_key().decode()))
    integration.configure(
        uk_org["id"], "xero", credentials={"access_token": "synthetic", "tenant_id": "tenant"},
        config={}, actor="owner@example.test",
    )

    def service(records):
        connector = ObjectConnector(records)
        monkeypatch.setitem(
            REGISTRY, "xero", replace(REGISTRY["xero"], factory=lambda credentials, config: connector)
        )
        return ImportService(db, integration=integration)

    return service


def _sync_apply(service, organisation_id, object_type, records):
    service = service(records)
    sync = service.run_sync(
        organisation_id, "xero", object_type, actor="owner@example.test"
    )
    staged = service.get_staged(organisation_id, sync_run_id=sync["id"])["records"]
    result = service.apply_staged(
        organisation_id, "xero", sync["id"], {row["id"]: "apply" for row in staged},
        actor="owner@example.test",
    )
    return service, sync, staged, result


def test_contact_staging_matches_and_applies(db, uk_org, object_import):
    service, _sync, staged, result = _sync_apply(
        object_import, uk_org["id"], "contacts",
        [{"external_id": "contact-1", "name": "Synthetic Supplier", "registry_code": "REG-1",
          "email": "supplier@example.test", "country": "UK", "is_supplier": True}],
    )
    assert result["applied"] == 1
    contact = db.one(
        "SELECT * FROM contacts WHERE organisation_id=? AND name='Synthetic Supplier'",
        (uk_org["id"],),
    )
    assert contact["contact_type"] == "supplier"
    assert staged[0]["matched_local_id"] is None
    assert db.one(
        "SELECT local_id FROM external_mappings WHERE organisation_id=? AND provider='xero' "
        "AND object_type='contact' AND external_id='contact-1'", (uk_org["id"],)
    )["local_id"] == contact["id"]

    again = service.run_sync(uk_org["id"], "xero", "contact", actor="owner@example.test")
    record = service.get_staged(uk_org["id"], sync_run_id=again["id"])["records"][0]
    assert record["matched_local_id"] == contact["id"]
    assert record["match"]["strategy"] == "external_mapping"


def test_purchase_and_sales_invoices_apply_as_drafts(db, uk_org, object_import):
    expense = db.one(
        "SELECT id FROM accounts WHERE organisation_id=? AND account_type='Expense' ORDER BY code LIMIT 1",
        (uk_org["id"],),
    )["id"]
    income = db.one(
        "SELECT id FROM accounts WHERE organisation_id=? AND account_type='Income' ORDER BY code LIMIT 1",
        (uk_org["id"],),
    )["id"]
    _service, _sync, _staged, purchase = _sync_apply(
        object_import, uk_org["id"], "purchase_invoices", [{
            "external_id": "bill-1", "external_number": "SUP-100", "date": "2026-10-01",
            "due_date": "2026-10-31", "currency": "GBP", "total": "120.00",
            "supplier": {"name": "Paper Supplier", "registry_code": "SUP-REG", "country": "UK"},
            "lines": [{"description": "Paper", "quantity": "2", "unit_price": "60", "account_id": expense}],
        }]
    )
    assert purchase["applied"] == 1
    bill = db.one("SELECT * FROM bills WHERE organisation_id=?", (uk_org["id"],))
    assert bill["status"] == "Draft" and bill["supplier_number"] == "SUP-100"

    _service, _sync, _staged, sales = _sync_apply(
        object_import, uk_org["id"], "sales_invoices", [{
            "external_id": "invoice-1", "external_number": "EXT-INV-1", "date": "2026-10-02",
            "currency": "GBP", "buyer": {"name": "Synthetic Buyer", "country": "UK"},
            "lines": [{"description": "Consulting", "quantity": "1", "unit_price": "250", "account_id": income}],
        }]
    )
    assert sales["applied"] == 1
    invoice = db.one("SELECT * FROM invoices WHERE organisation_id=?", (uk_org["id"],))
    assert invoice["status"] == "Draft" and invoice["number"] is None


def test_purchase_total_mismatch_and_unmapped_payment_are_refused(db, uk_org, object_import):
    expense = db.one(
        "SELECT id FROM accounts WHERE organisation_id=? AND account_type='Expense' ORDER BY code LIMIT 1",
        (uk_org["id"],),
    )["id"]
    _service, _sync, _staged, mismatch = _sync_apply(
        object_import, uk_org["id"], "purchase_invoice", [{
            "external_id": "bill-bad", "external_number": "BAD-1", "date": "2026-10-01",
            "total": "999", "supplier_name": "Mismatch Supplier",
            "lines": [{"description": "Mismatch", "unit_price": "10", "account_id": expense}],
        }]
    )
    assert mismatch["failed"] == 1
    assert db.scalar("SELECT COUNT(*) FROM bills WHERE organisation_id=?", (uk_org["id"],)) == 0
    assert db.scalar("SELECT COUNT(*) FROM contacts WHERE organisation_id=?", (uk_org["id"],)) == 0

    _service, _sync, _staged, payment = _sync_apply(
        object_import, uk_org["id"], "payments", [{
            "external_id": "pay-1", "invoice_external_id": "missing-invoice",
            "amount": "10", "date": "2026-10-02", "bank_account_id": "missing-bank",
        }]
    )
    assert payment["failed"] == 1
    assert payment["outcomes"][0]["reason"] == "no local document linked for this payment"
    assert db.scalar("SELECT COUNT(*) FROM sync_conflicts WHERE sync_run_id=?", (payment["sync_run_id"],)) == 1


def test_account_suggestion_and_gl_import_are_idempotent(db, uk_org, object_import):
    account = db.one(
        "SELECT code FROM accounts WHERE organisation_id=? AND account_type='Expense' ORDER BY code LIMIT 1",
        (uk_org["id"],),
    )
    _service, _sync, _staged, suggestion = _sync_apply(
        object_import, uk_org["id"], "accounts", [{
            "external_id": "account-1", "external_account_code": "EXT-600",
            "external_account_name": "External expenses", "local_account_code": account["code"],
        }]
    )
    assert suggestion["applied"] == 1
    mapping = db.one(
        "SELECT * FROM account_mappings WHERE organisation_id=? AND provider='xero'",
        (uk_org["id"],),
    )
    assert mapping["status"] == "Suggested" and mapping["is_default"] == 0

    local_gl_before = db.scalar(
        "SELECT COUNT(*) FROM gl_entries WHERE organisation_id=?", (uk_org["id"],)
    )
    service, sync, staged, first = _sync_apply(
        object_import, uk_org["id"], "gl_entries", [{
            "external_id": "gl-1", "external_batch_ref": "batch-1", "date": "2026-10-03",
            "external_account_code": "EXT-600", "description": "Read-only external row",
            "debit": "42.50", "credit": "0", "dimensions": {"department": "Synthetic"},
        }]
    )
    assert first["applied"] == 1
    assert db.one(
        "SELECT local_account_code FROM external_gl_entries WHERE organisation_id=? AND external_id='gl-1'",
        (uk_org["id"],),
    )["local_account_code"] == account["code"]
    second = service.apply_staged(
        uk_org["id"], "xero", sync["id"], {staged[0]["id"]: "apply"},
        actor="owner@example.test",
    )
    assert second["applied"] == 1
    assert db.scalar(
        "SELECT COUNT(*) FROM external_gl_entries WHERE organisation_id=? AND external_id='gl-1'",
        (uk_org["id"],),
    ) == 1
    assert db.scalar(
        "SELECT COUNT(*) FROM gl_entries WHERE organisation_id=?", (uk_org["id"],)
    ) == local_gl_before
