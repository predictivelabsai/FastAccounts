from __future__ import annotations

from decimal import Decimal

import pytest

from ledger import LedgerService, PostingLine


def _accounts(db, org_id):
    return {row["system_role"]: row["id"] for row in db.rows("SELECT * FROM accounts WHERE organisation_id=?", (org_id,))}


def _posting_date(db, org_id):
    return db.scalar("SELECT starts_on FROM fiscal_periods WHERE organisation_id=? ORDER BY starts_on LIMIT 1", (org_id,))


def test_balanced_posting_and_idempotency(db, uk_org):
    accounts, date = _accounts(db, uk_org["id"]), _posting_date(db, uk_org["id"])
    service = LedgerService(db)
    args = dict(organisation_id=uk_org["id"], voucher_type="opening", voucher_id="opening-1",
                voucher_code="OPEN-1", posting_date=date, actor="owner@example.test", currency="GBP",
                lines=[PostingLine(accounts["BANK"], debit=Decimal("100.00")),
                       PostingLine(accounts["CAPITAL"], credit=Decimal("100.00"))])
    first = service.post(**args)
    second = service.post(**args)
    assert first["id"] == second["id"]
    assert db.scalar("SELECT COUNT(*) FROM gl_entries") == 2


def test_unbalanced_and_cross_tenant_postings_fail(db, uk_org, ee_org):
    uk, ee = _accounts(db, uk_org["id"]), _accounts(db, ee_org["id"])
    date = _posting_date(db, uk_org["id"])
    with pytest.raises(ValueError, match="Unbalanced"):
        LedgerService(db).post(organisation_id=uk_org["id"], voucher_type="x", voucher_id="1", voucher_code="x",
            posting_date=date, actor="a", currency="GBP", lines=[PostingLine(uk["BANK"], debit=Decimal("2")), PostingLine(uk["CAPITAL"], credit=Decimal("1"))])
    with pytest.raises(ValueError, match="another organisation"):
        LedgerService(db).post(organisation_id=uk_org["id"], voucher_type="x", voucher_id="2", voucher_code="x",
            posting_date=date, actor="a", currency="GBP", lines=[PostingLine(uk["BANK"], debit=Decimal("1")), PostingLine(ee["CAPITAL"], credit=Decimal("1"))])


def test_posted_entries_are_immutable_and_reversed_with_new_entries(db, uk_org):
    accounts, date = _accounts(db, uk_org["id"]), _posting_date(db, uk_org["id"])
    service = LedgerService(db)
    batch = service.post(organisation_id=uk_org["id"], voucher_type="journal", voucher_id="j1", voucher_code="J1",
        posting_date=date, actor="a", currency="GBP", lines=[PostingLine(accounts["BANK"], debit=Decimal("25")), PostingLine(accounts["CAPITAL"], credit=Decimal("25"))])
    entry = db.one("SELECT * FROM gl_entries WHERE posting_batch_id=? LIMIT 1", (batch["id"],))
    with pytest.raises(Exception, match="immutable"):
        with db.transaction() as tx:
            tx.execute("UPDATE gl_entries SET debit=99 WHERE id=?", (entry["id"],))
    reversal = service.reverse(batch["id"], reversal_date=date, actor="a", reason="Fixture correction")
    assert reversal["reverses_batch_id"] == batch["id"]
    assert db.one("SELECT status FROM posting_batches WHERE id=?", (batch["id"],))["status"] == "Reversed"
    trial = service.trial_balance(uk_org["id"], start="0001-01-01", end="9999-12-31")
    assert sum((row["debit"] for row in trial), Decimal("0")) == sum((row["credit"] for row in trial), Decimal("0"))


def test_locked_period_rejects_posting(db, uk_org):
    period = db.one("SELECT * FROM fiscal_periods WHERE organisation_id=? ORDER BY starts_on LIMIT 1", (uk_org["id"],))
    accounts = _accounts(db, uk_org["id"])
    service = LedgerService(db)
    service.lock_period(period["id"], actor="accountant@example.test", reason="Month end complete")
    with pytest.raises(ValueError, match="locked"):
        service.post(organisation_id=uk_org["id"], voucher_type="x", voucher_id="locked", voucher_code="X",
            posting_date=period["starts_on"], actor="a", currency="GBP",
            lines=[PostingLine(accounts["BANK"], debit=Decimal("1")), PostingLine(accounts["CAPITAL"], credit=Decimal("1"))])


def test_financial_reports(db, uk_org):
    accounts, date = _accounts(db, uk_org["id"]), _posting_date(db, uk_org["id"])
    service = LedgerService(db)
    service.post(organisation_id=uk_org["id"], voucher_type="sale", voucher_id="s1", voucher_code="S1",
        posting_date=date, actor="a", currency="GBP", lines=[PostingLine(accounts["AR"], debit=Decimal("120")),
        PostingLine(accounts["SALES"], credit=Decimal("100")), PostingLine(accounts["OUTPUT_VAT"], credit=Decimal("20"))])
    profit = service.profit_and_loss(uk_org["id"], start=date, end=date)
    balance = service.balance_sheet(uk_org["id"], as_at=date)
    assert profit["income"] == Decimal("100.00") and profit["profit"] == Decimal("100.00")
    assert balance["assets"] == Decimal("120.00") and balance["liabilities"] == Decimal("20.00")
