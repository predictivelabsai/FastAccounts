"""Synthetic fixed asset accounting, calendar and tenant regressions."""
import calendar
from datetime import date
from decimal import Decimal

import pytest

from core_utils import money, new_id
from documents import DocumentService
from fixed_assets import FixedAssetService
from ledger import LedgerService

ACTOR = "owner@example.test"


def periods(db, organisation_id):
    """Use explicit calendar years so leap-year tests do not depend on today."""
    with db.transaction() as tx:
        for year in range(2024, 2031):
            for month in range(1, 13):
                start = date(year, month, 1).isoformat()
                if not tx.one("SELECT id FROM fiscal_periods WHERE organisation_id=? AND starts_on=?", (organisation_id, start)):
                    tx.execute("INSERT INTO fiscal_periods(id,organisation_id,code,starts_on,ends_on) VALUES (?,?,?,?,?)",
                               (new_id(), organisation_id, f"{year}-{month:02}", start,
                                date(year, month, calendar.monthrange(year, month)[1]).isoformat()))


def setup(db, org, *, percentage="20", frequency="monthly", cost="1200", acquired="2024-01-15"):
    periods(db, org["id"])
    bank = DocumentService(db).create_bank_account(org["id"], name="Synthetic asset bank", currency=org["base_currency"])
    service = FixedAssetService(db)
    group = service.create_group(org["id"], name="Synthetic equipment", annual_percentage=percentage,
                                 frequency=frequency, actor=ACTOR)
    asset = service.create(org["id"], group_id=group["id"], name="Synthetic desk", acquisition_date=acquired,
                           acquisition_cost=cost, bank_account_id=bank["id"], idempotency_key="asset-1", actor=ACTOR)
    return service, group, asset, bank


def entries(db, batch_id):
    return db.rows("SELECT g.*,a.system_role FROM gl_entries g JOIN accounts a ON a.id=g.account_id "
                   "WHERE g.posting_batch_id=? ORDER BY line_number", (batch_id,))


def balanced(db, batch_id, amount=None):
    rows = entries(db, batch_id)
    debit = sum((money(row["debit"]) for row in rows), Decimal("0"))
    credit = sum((money(row["credit"]) for row in rows), Decimal("0"))
    assert debit == credit and debit > 0
    if amount is not None:
        assert debit == Decimal(amount)
    assert db.scalar("SELECT status FROM posting_batches WHERE id=?", (batch_id,)) == "Posted"
    return rows


def accumulated(db, asset_id):
    return sum((money(row["amount"]) for row in db.rows("SELECT amount FROM depreciation_run_assets WHERE asset_id=?", (asset_id,))), Decimal("0"))


@pytest.mark.parametrize("fixture", ["uk_org", "ee_org"])
def test_acquisition_and_run_are_balanced_idempotent_and_asset_tagged(request, db, fixture):
    org = request.getfixturevalue(fixture)
    service, group, asset, bank = setup(db, org)
    again = service.create(org["id"], group_id=group["id"], name="Synthetic desk", acquisition_date="2024-01-15",
                           acquisition_cost="1200", bank_account_id=bank["id"], idempotency_key="asset-1", actor=ACTOR)
    assert again["id"] == asset["id"]
    acquisition = balanced(db, asset["posting_batch_id"], "1200")
    assert {row["account_id"] for row in acquisition} == {group["asset_account_id"], bank["ledger_account_id"]}
    assert next(row for row in acquisition if row["system_role"] == "FIXED_ASSETS")["memo"] == asset["name"]
    run = service.run(org["id"], period_date="2024-01-31", actor=ACTOR)
    assert service.run(org["id"], period_date="2024-01-31", actor=ACTOR)["id"] == run["id"]
    charge = balanced(db, run["posting_batch_id"], "20")
    assert {row["system_role"] for row in charge} == {"DEPRECIATION_EXPENSE", "ACCUMULATED_DEPRECIATION"}
    assert all(row["source_line_id"] == asset["id"] and row["source_line_type"] for row in charge)
    assert accumulated(db, asset["id"]) == 20
    assert db.scalar("SELECT COUNT(*) FROM depreciation_run_assets WHERE asset_id=?", (asset["id"],)) == 1
    report = service.register(org["id"])
    assert len(report["assets"]) == 1 and report["groups"] and report["totals"]
    assert report["assets"][0]["acquisition_cost"] == Decimal("1200")
    assert report["assets"][0]["accumulated_depreciation"] == Decimal("20")
    assert report["assets"][0]["carrying_value"] == Decimal("1180")
    assert len(service.runs(org["id"])) == 1


def test_one_run_posts_one_batch_for_multiple_assets(db, uk_org):
    service, group, first, bank = setup(db, uk_org)
    second = service.create(uk_org["id"], group_id=group["id"], name="Synthetic chair", acquisition_date="2024-01-31",
                            acquisition_cost="600", bank_account_id=bank["id"], idempotency_key="asset-2", actor=ACTOR)
    run = service.run(uk_org["id"], period_date="2024-01-31", actor=ACTOR)
    rows = balanced(db, run["posting_batch_id"], "30")
    assert {row["source_line_id"] for row in rows} == {first["id"], second["id"]}
    assert db.scalar("SELECT COUNT(DISTINCT posting_batch_id) FROM depreciation_run_assets WHERE run_id=?", (run["id"],)) == 1


def test_rounding_final_period_top_up_caps_at_cost(db, uk_org):
    service, _, asset, _ = setup(db, uk_org, percentage="33.33", cost="100")
    amounts = []
    for index in range(40):
        year, month = divmod(2024 * 12 + index, 12)
        month += 1
        service.run(uk_org["id"], period_date=date(year, month, calendar.monthrange(year, month)[1]).isoformat(), actor=ACTOR)
        amount = accumulated(db, asset["id"])
        assert amount <= 100
        amounts.append(amount)
    assert amounts[35] == Decimal("99.99")
    assert amounts[36:] == [Decimal("100.00")] * 4


def test_zero_cent_charge_advances_until_the_first_payable_cent(db, uk_org):
    service, _, asset, _ = setup(db, uk_org, percentage="10", cost="0.01")
    service.run_due(uk_org["id"], today="2024-01-31")
    assert accumulated(db, asset["id"]) == 0
    assert len(service.runs(uk_org["id"])) == 1
    assert service.schedule(uk_org["id"])[0]["next_due_date"] == "2024-02-29"
    service.run_due(uk_org["id"], today="2029-12-31")
    assert accumulated(db, asset["id"]) == Decimal("0.01")


@pytest.mark.parametrize("frequency,acquired,before,due,next_due,charge", [
    ("monthly", "2024-01-31", "2024-01-30", "2024-01-31", "2024-02-29", "20"),
    ("quarterly", "2024-02-29", "2024-03-30", "2024-03-31", "2024-06-30", "60"),
    ("yearly", "2024-02-29", "2024-12-30", "2024-12-31", "2025-12-31", "240"),
])
def test_due_calendar_boundaries_and_leap_year(db, uk_org, frequency, acquired, before, due, next_due, charge):
    service, _, asset, _ = setup(db, uk_org, frequency=frequency, acquired=acquired)
    assert service.run_due(uk_org["id"], today=before) == []
    first = service.run_due(uk_org["id"], today=due)
    assert len(first) == 1
    assert accumulated(db, asset["id"]) == Decimal(charge)
    assert service.run_due(uk_org["id"], today=due) == []
    service.run_due(uk_org["id"], today=next_due)
    assert accumulated(db, asset["id"]) == Decimal(charge) * 2


@pytest.mark.parametrize("proceeds", ["0", "100", "1160", "1300"])
def test_disposal_after_partial_depreciation_is_exactly_balanced(db, uk_org, proceeds):
    service, _, asset, bank = setup(db, uk_org)
    service.run(uk_org["id"], period_date="2024-01-31", actor=ACTOR)
    disposed = service.dispose(uk_org["id"], asset["id"], disposal_date="2024-02-15", disposal_amount=proceeds,
                                bank_account_id=bank["id"], actor=ACTOR)
    batch_id = disposed["disposal_posting_batch_id"]
    rows = balanced(db, batch_id)
    # February's full charge is included in this same disposal batch.
    assert sum(money(row["debit"]) for row in rows if row["system_role"] == "ACCUMULATED_DEPRECIATION") == 40
    assert sum(money(row["credit"]) for row in rows if row["system_role"] == "FIXED_ASSETS") == 1200
    assert sum(money(row["debit"]) for row in rows if row["account_id"] == bank["ledger_account_id"]) == Decimal(proceeds)
    assert sum(money(row["debit"]) for row in rows if row["system_role"] == "DEPRECIATION_EXPENSE") >= 20
    assert service.register(uk_org["id"])["assets"][0]["carrying_value"] == 0
    assert service.dispose(uk_org["id"], asset["id"], disposal_date="2024-02-15", disposal_amount=proceeds,
                           bank_account_id=bank["id"], actor=ACTOR)["disposal_posting_batch_id"] == batch_id
    original = [dict(row) for row in entries(db, asset["posting_batch_id"])]
    service.run_due(uk_org["id"], today="2024-12-31")
    assert entries(db, asset["posting_batch_id"]) == original
    assert db.scalar("SELECT COUNT(*) FROM gl_entries WHERE posting_batch_id=?", (batch_id,)) == len(rows)
    assert accumulated(db, asset["id"]) + money(disposed["disposal_depreciation_amount"]) == 40


def test_tenant_isolation_for_groups_assets_bank_and_accounts(db, uk_org, ee_org):
    service, uk_group, uk_asset, uk_bank = setup(db, uk_org)
    _, ee_group, _, ee_bank = setup(db, ee_org)
    for org, group, bank in [(uk_org, ee_group, uk_bank), (uk_org, uk_group, ee_bank)]:
        with pytest.raises((ValueError, KeyError)):
            service.create(org["id"], group_id=group["id"], name="Invalid", acquisition_date="2024-01-15",
                           acquisition_cost="100", bank_account_id=bank["id"], idempotency_key=new_id(), actor=ACTOR)
    foreign_account = db.scalar("SELECT id FROM accounts WHERE organisation_id=? AND system_role='FIXED_ASSETS'", (ee_org["id"],))
    with pytest.raises((ValueError, KeyError)):
        service.create_group(uk_org["id"], name="Invalid", annual_percentage="20", asset_account_id=foreign_account, actor=ACTOR)
    with pytest.raises((ValueError, KeyError)):
        service.dispose(ee_org["id"], uk_asset["id"], disposal_date="2024-02-15", disposal_amount="0", bank_account_id=ee_bank["id"], actor=ACTOR)
    assert {row["organisation_id"] for row in service.register(uk_org["id"])["assets"]} == {uk_org["id"]}
    assert service.runs(ee_org["id"]) == []


def test_locked_run_rolls_back_and_can_be_retried(db, uk_org):
    service, _, asset, _ = setup(db, uk_org)
    period = db.one("SELECT id FROM fiscal_periods WHERE organisation_id=? AND starts_on='2024-01-01'", (uk_org["id"],))
    LedgerService(db).lock_period(period["id"], actor=ACTOR, reason="Synthetic close")
    with pytest.raises(ValueError, match="locked"):
        service.run(uk_org["id"], period_date="2024-01-31", actor=ACTOR)
    assert service.runs(uk_org["id"]) == []
    assert accumulated(db, asset["id"]) == 0
    with db.transaction() as tx:
        tx.execute("UPDATE fiscal_periods SET status='Open' WHERE id=?", (period["id"],))
    run = service.run(uk_org["id"], period_date="2024-01-31", actor=ACTOR)
    balanced(db, run["posting_batch_id"], "20")


def test_default_groups_are_seeded_once_per_tenant(db, uk_org, ee_org):
    service = FixedAssetService(db)
    assert db.scalar("SELECT COUNT(*) FROM asset_groups") == 0
    groups = service.groups(ee_org["id"], locale="et")
    assert len(groups) == 3
    assert sorted(money(row["annual_percentage"]) for row in groups) == [Decimal("10"), Decimal("20"), Decimal("25")]
    assert service.groups(ee_org["id"], locale="et") == groups
    assert len(service.groups(uk_org["id"])) == 3
    assert db.scalar("SELECT COUNT(*) FROM asset_groups") == 6


def test_run_cannot_skip_earlier_due_period_and_worker_catches_up(db, uk_org):
    service, _, asset, _ = setup(db, uk_org)
    with pytest.raises(ValueError):
        service.run(uk_org["id"], period_date="2024-03-31", actor=ACTOR)
    assert accumulated(db, asset["id"]) == 0
    result = service.run_due(uk_org["id"], today="2024-03-31")
    assert len(result) == 3
    assert accumulated(db, asset["id"]) == 60
    assert service.run_due(uk_org["id"], today="2024-03-31") == []


def test_disposal_rejects_backdating_and_acquisition_into_processed_period(db, uk_org):
    service, group, asset, bank = setup(db, uk_org)
    service.run_due(uk_org["id"], today="2024-03-31")
    with pytest.raises(ValueError):
        service.dispose(uk_org["id"], asset["id"], disposal_date="2024-02-15", disposal_amount="0",
                        bank_account_id=bank["id"], actor=ACTOR)
    with pytest.raises(ValueError):
        service.create(uk_org["id"], group_id=group["id"], name="Backdated acquisition", acquisition_date="2024-01-15",
                       acquisition_cost="100", bank_account_id=bank["id"], idempotency_key="backdated", actor=ACTOR)
    assert db.scalar("SELECT COUNT(*) FROM fixed_assets WHERE organisation_id=?", (uk_org["id"],)) == 1


def test_disposal_catches_up_missing_periods_in_single_batch(db, uk_org):
    service, _, asset, bank = setup(db, uk_org)
    before = db.scalar("SELECT COUNT(*) FROM posting_batches")
    disposed = service.dispose(uk_org["id"], asset["id"], disposal_date="2024-03-15", disposal_amount="100",
                                bank_account_id=bank["id"], actor=ACTOR)
    assert db.scalar("SELECT COUNT(*) FROM posting_batches") == before + 1
    rows = balanced(db, disposed["disposal_posting_batch_id"])
    assert sum(money(row["debit"]) for row in rows if row["system_role"] == "ACCUMULATED_DEPRECIATION") == 60
    assert sum(money(row["debit"]) for row in rows if row["system_role"] == "DEPRECIATION_EXPENSE") >= 60
    assert money(disposed["disposal_depreciation_amount"]) == 60


@pytest.mark.parametrize("percentage,frequency", [("0", "monthly"), ("-1", "monthly"), ("101", "monthly"), ("NaN", "monthly"), ("Infinity", "monthly"), ("20", "weekly")])
def test_invalid_group_policy_is_rejected(db, uk_org, percentage, frequency):
    with pytest.raises(ValueError):
        FixedAssetService(db).create_group(uk_org["id"], name="Invalid policy", annual_percentage=percentage,
                                           frequency=frequency, actor=ACTOR)


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-1", "0"])
def test_invalid_acquisition_amounts_do_not_post(db, uk_org, amount):
    service, group, _, bank = setup(db, uk_org)
    before = db.scalar("SELECT COUNT(*) FROM posting_batches")
    with pytest.raises(ValueError):
        service.create(uk_org["id"], group_id=group["id"], name="Invalid amount", acquisition_date="2024-01-15",
                       acquisition_cost=amount, bank_account_id=bank["id"], idempotency_key="invalid", actor=ACTOR)
    assert db.scalar("SELECT COUNT(*) FROM posting_batches") == before


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-1"])
def test_invalid_disposal_amounts_do_not_post(db, uk_org, amount):
    service, _, asset, bank = setup(db, uk_org)
    before = db.scalar("SELECT COUNT(*) FROM posting_batches")
    with pytest.raises(ValueError):
        service.dispose(uk_org["id"], asset["id"], disposal_date="2024-02-15", disposal_amount=amount,
                        bank_account_id=bank["id"], actor=ACTOR)
    assert db.scalar("SELECT COUNT(*) FROM posting_batches") == before


def test_disposal_zero_proceeds_replay_requires_original_bank(db, uk_org):
    service, _, asset, bank = setup(db, uk_org)
    other_bank = DocumentService(db).create_bank_account(uk_org["id"], name="Another synthetic bank", currency="GBP")
    service.dispose(uk_org["id"], asset["id"], disposal_date="2024-02-15", disposal_amount="0", bank_account_id=bank["id"], actor=ACTOR)
    before = db.scalar("SELECT COUNT(*) FROM posting_batches")
    with pytest.raises(ValueError):
        service.dispose(uk_org["id"], asset["id"], disposal_date="2024-02-15", disposal_amount="0", bank_account_id=other_bank["id"], actor=ACTOR)
    assert db.scalar("SELECT COUNT(*) FROM posting_batches") == before


@pytest.mark.parametrize("period", ["2024-01-15", "2024-02-28", "2024-02-30", "not-a-date"])
def test_noncanonical_or_invalid_run_dates_rejected(db, uk_org, period):
    service, _, _, _ = setup(db, uk_org)
    with pytest.raises(ValueError):
        service.run(uk_org["id"], period_date=period, actor=ACTOR)
    assert service.runs(uk_org["id"]) == []


def test_custom_group_account_mappings_and_acquisition_policy_snapshot(db, uk_org):
    periods(db, uk_org["id"])
    account_ids = [new_id() for _ in range(3)]
    with db.transaction() as tx:
        for account_id, code, kind, balance in zip(account_ids, ("9870", "9871", "9872"), ("Asset", "Asset", "Expense"), ("Debit", "Credit", "Debit")):
            tx.execute("INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance) VALUES (?,?,?,'Synthetic mapped account',?,?)",
                       (account_id, uk_org["id"], code, kind, balance))
    service = FixedAssetService(db)
    group = service.create_group(uk_org["id"], name="Synthetic mapped group", annual_percentage="20", actor=ACTOR,
                                 asset_account_id=account_ids[0], accumulated_depreciation_account_id=account_ids[1], expense_account_id=account_ids[2])
    bank = DocumentService(db).create_bank_account(uk_org["id"], name="Synthetic mapped bank", currency="GBP")
    asset = service.create(uk_org["id"], group_id=group["id"], name="Synthetic mapped desk", acquisition_date="2024-01-15",
                           acquisition_cost="1200", bank_account_id=bank["id"], idempotency_key="mapped", actor=ACTOR)
    assert {row["account_id"] for row in entries(db, asset["posting_batch_id"])} == {account_ids[0], bank["ledger_account_id"]}
    with db.transaction() as tx:
        tx.execute("UPDATE asset_groups SET annual_percentage=100,frequency='yearly' WHERE id=?", (group["id"],))
    run = service.run(uk_org["id"], period_date="2024-01-31", actor=ACTOR)
    rows = balanced(db, run["posting_batch_id"], "20")
    assert {row["account_id"] for row in rows} == {account_ids[1], account_ids[2]}


def test_worker_isolates_depreciation_failure_and_keeps_other_jobs(db, uk_org, ee_org, monkeypatch):
    import automation

    calls = []

    class FakeAssets:
        def __init__(self, database):
            assert database is db

        def run_due(self, organisation_id, *, today=None, actor="automation"):
            calls.append((organisation_id, today))
            if organisation_id == uk_org["id"]:
                raise ValueError("Synthetic depreciation failure")
            return [{"organisation_id": organisation_id, "status": "Posted"}]

    monkeypatch.setattr(automation, "FixedAssetService", FakeAssets)
    monkeypatch.setattr(automation.AutomationService, "run_due", lambda *args, **kwargs: [])
    monkeypatch.setattr(automation.AutomationService, "process_reminders", lambda *args, **kwargs: [])
    monkeypatch.setattr(automation.OpenBankingService, "pull_due", lambda *args, **kwargs: [])
    result = automation.AutomationService(db).worker_tick(today="2024-02-29")
    assert {org for org, _ in calls} == {uk_org["id"], ee_org["id"]}
    assert len(result["depreciation"]) == 1
    assert result["depreciation"][0]["organisation_id"] == ee_org["id"]
    assert any(error["organisation_id"] == uk_org["id"] and error["operation"] == "depreciation" for error in result["errors"])


def test_api_register_mutations_permissions_and_mounted_routes(db, uk_org, ee_org, monkeypatch):
    from fastapi.testclient import TestClient
    from api_app import api, current_user, User
    from database import reset_database_cache
    from web_app import app

    monkeypatch.setenv("FASTACCOUNTS_DB", db.path)
    monkeypatch.setenv("DB_URL", "")
    reset_database_cache()
    periods(db, uk_org["id"])
    bank = DocumentService(db).create_bank_account(uk_org["id"], name="Synthetic API asset bank", currency="GBP")
    base = f"/organisations/{uk_org['id']}"
    try:
        with TestClient(api, headers={"X-Test-User": ACTOR}) as client:
            defaults = client.get(base + "/asset-groups?locale=et")
            assert defaults.status_code == 200 and len(defaults.json()) == 3
            created_group = client.post(base + "/asset-groups", json=dict(name="Synthetic API equipment", annual_percentage="20"))
            assert created_group.status_code == 201
            payload = dict(group_id=created_group.json()["id"], name="Synthetic API desk", acquisition_date="2024-01-15",
                           acquisition_cost="1200", bank_account_id=bank["id"], idempotency_key="api-asset")
            acquisition = client.post(base + "/fixed-assets", json=payload)
            assert acquisition.status_code == 201
            asset_id = acquisition.json()["id"]
            assert client.post(base + "/fixed-assets", json=payload).json()["id"] == asset_id
            assert client.get(base + "/fixed-assets/schedule").json()[0]["next_due_date"] == "2024-01-31"
            run = client.post(base + "/fixed-assets/runs", json=dict(period_date="2024-01-31"))
            assert run.status_code == 200
            assert client.get(base + "/fixed-assets").json()["assets"][0]["carrying_value"] == "1180.00"
            assert len(client.get(base + "/fixed-assets/runs").json()) == 1
            disposal = dict(disposal_date="2024-02-15", disposal_amount="100", bank_account_id=bank["id"])
            assert client.post(base + f"/fixed-assets/{asset_id}/dispose", json=disposal).status_code == 200
            assert client.post(f"/organisations/{ee_org['id']}/fixed-assets/{asset_id}/dispose", json=disposal).status_code == 404
            assert client.post(base + "/asset-groups", json=dict(name="Invalid", annual_percentage="NaN")).status_code == 422
        with db.transaction() as tx:
            tx.execute("INSERT INTO memberships(id,organisation_id,email,role,created_at) VALUES (?,?,?,'viewer',?)",
                       (new_id(), uk_org["id"], "viewer@example.test", "2024-01-01"))
        for email, read_status in [("viewer@example.test", 200), ("outsider@example.test", 403)]:
            with TestClient(api, headers={"X-Test-User": email}) as client:
                assert client.get(base + "/fixed-assets").status_code == read_status
                assert client.post(base + "/fixed-assets", json=payload).status_code == 403
                assert client.post(base + "/fixed-assets/runs", json=dict(period_date="2024-03-31")).status_code == 403
                assert client.post(base + f"/fixed-assets/{asset_id}/dispose", json=disposal).status_code == 403
        with TestClient(app, headers={"X-Test-User": ACTOR}) as client:
            assert client.get("/api" + base + "/fixed-assets").status_code == 200
        api.dependency_overrides[current_user] = lambda: User(email=ACTOR)
        with TestClient(app) as client:
            assert client.post("/api" + base + "/fixed-assets", json=payload).status_code == 403
    finally:
        api.dependency_overrides.clear()
        reset_database_cache()
