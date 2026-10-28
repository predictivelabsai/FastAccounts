from __future__ import annotations

import sqlite3

import pytest

from database import Database
from organisations import AccessDenied, OrganisationService
from payroll_components import ACCOUNTS as PAYROLL_COMPONENT_ACCOUNTS


def test_employee_tax_settings_backfill_and_preservation(tmp_path, legacy_payroll):
    from shutil import copyfile
    from database import MIGRATIONS
    from payroll import PayrollService
    old = tmp_path / 'before-tax-history' / 'sqlite'
    old.mkdir(parents=True)
    for path in (MIGRATIONS / 'sqlite').glob('*.sql'):
        if path.stem < '0037':
            copyfile(path, old / path.name)
    db = Database(path=str(tmp_path / 'tax-backfill.sqlite'))
    db.migrate(migrations=old.parent)
    org = OrganisationService(db).create(name='Synthetic backfill', country_code='EE', entity_type='EE_OU',
                                          owner_email='owner@example.test')
    run = legacy_payroll(db, org['id'], name='Existing employee', gross='2000')
    payroll = PayrollService(db)
    payroll.approve(org['id'], run['id'], actor='owner@example.test')
    with db.transaction() as tx:
        tx.execute("UPDATE employees SET apply_tax_free_minimum=1,funded_pension_percent=6,"
                   "employment_start_date='2025-06-15',personal_id='49001010018' WHERE id='legacy-employee'")
        tx.execute("INSERT INTO employees(id,organisation_id,name,gross_salary,board_member,pay_basis,"
                   "funded_pension_percent,created_at) VALUES ('board',?,'Synthetic board',500,1,'board_fee',0,'2026-01-01')",
                   (org['id'],))
    tables = ('employees', 'pay_run_items', 'pay_item_context', 'pay_runs', 'gl_entries', 'posting_batches')
    before = {table: db.rows(f'SELECT * FROM {table} ORDER BY id' if table != 'pay_item_context'
                             else 'SELECT * FROM pay_item_context ORDER BY item_id') for table in tables}
    assert db.migrate() == ['0037_employee_tax_settings', '0038_payroll_payday_rules', '0039_payroll_payouts', '0040_payroll_settlement_dates', '0041_payroll_sepa_details', '0042_payroll_component_metadata', '0043_payroll_absences', '0044_payroll_absence_day_freeze', '0045_payroll_history']
    for table in tables:
        actual = db.rows(f'SELECT * FROM {table} ORDER BY id' if table != 'pay_item_context'
                         else 'SELECT * FROM pay_item_context ORDER BY item_id')
        assert [{key: row[key] for key in original} for row, original in zip(actual, before[table], strict=True)] == before[table]
    rows = db.rows('SELECT * FROM employee_tax_settings WHERE organisation_id=?', (org['id'],))
    assert len(rows) == 6
    staff = {r['kind']: r for r in rows if r['employee_id'] == 'legacy-employee'}
    board = {r['kind']: r for r in rows if r['employee_id'] == 'board'}
    assert {r['start_date'] for r in staff.values()} == {'2025-06-15'}
    assert staff['tax_free']['mode'] == 'maximum' and staff['pension']['rate'] == 6
    assert staff['unemployment']['applies'] == 1
    assert {r['start_date'] for r in board.values()} == {'2026-01-01'}
    assert board['tax_free']['mode'] == 'none' and board['pension']['rate'] == 0
    assert board['unemployment']['applies'] == 0
    assert payroll.employees(org['id'])[0]['date_of_birth'] == '1990-01-01'
    assert db.migrate() == [] and db.rows('PRAGMA foreign_key_check') == []


def test_component_catalogue_upgrade_preserves_defaults_and_posted_payroll(tmp_path, legacy_payroll):
    from shutil import copyfile
    from database import MIGRATIONS
    from payroll import PayrollService
    from payroll_components import FLAGS, PRESETS, seed_types

    old = tmp_path / 'old' / 'sqlite'
    old.mkdir(parents=True)
    for path in (MIGRATIONS / 'sqlite').glob('*.sql'):
        if path.stem < '0036':
            copyfile(path, old / path.name)
    db = Database(path=str(tmp_path / 'catalogue-upgrade.sqlite'))
    db.migrate(migrations=old.parent)
    actor = 'owner@example.test'
    org = OrganisationService(db).create(name='Synthetic existing EE', country_code='EE', entity_type='EE_OU', owner_email=actor)
    uk = OrganisationService(db).create(name='Synthetic existing UK', country_code='UK', entity_type='UK_COMPANY', owner_email=actor)
    service = PayrollService(db)
    with db.transaction() as tx:
        # Reproduce the five rows present before 0036, independently of current org seeding.
        tx.execute("DELETE FROM pay_component_types WHERE preset_key NOT IN ('bailiff','author','parental','contract','base_adjustment')")
        tx.execute("UPDATE pay_component_types SET name='Bureau author',social_tax=0,ui_employee=0,ui_employer=0,funded_pension=0 WHERE preset_key='author'")
        tx.execute("UPDATE pay_component_types SET social_tax=0,ui_employee=0,ui_employer=0,funded_pension=0,social_minimum=0 WHERE preset_key='parental'")
    custom = service.save_component_type(org['id'], name='Puhkusetasu', actor=actor, income_tax=True)
    run = legacy_payroll(db, org['id'], name='Synthetic employee', gross='2000', actor=actor)
    author = next(t for t in service.component_types(org['id']) if t['preset_key'] == 'author')
    service.update_item(org['id'], run['id'], run['items'][0]['id'], actor=actor,
                        components=[dict(type_id=author['id'], amount='100')])
    service.approve(org['id'], run['id'], actor=actor)
    tables = ('employees', 'pay_runs', 'pay_run_items', 'pay_item_components', 'pay_item_context',
              'pay_run_posting_accounts', 'gl_entries', 'posting_batches', 'audit_events')
    before = {t: db.rows(f'SELECT * FROM {t} ORDER BY 1') for t in tables}
    existing = db.rows('SELECT * FROM pay_component_types ORDER BY id')
    assert db.migrate() == ['0036_payroll_component_catalogue', '0037_employee_tax_settings', '0038_payroll_payday_rules', '0039_payroll_payouts', '0040_payroll_settlement_dates', '0041_payroll_sepa_details', '0042_payroll_component_metadata', '0043_payroll_absences', '0044_payroll_absence_day_freeze', '0045_payroll_history']
    for table in tables:
        actual = db.rows(f'SELECT * FROM {table} ORDER BY 1')
        assert [{key: row[key] for key in original} for row, original in zip(actual, before[table], strict=True)] == before[table]
    after = db.rows('SELECT * FROM pay_component_types ORDER BY id')
    after_by_id = {row['id']: row for row in after}
    assert all(all(after_by_id[row['id']][key] == value for key, value in row.items()) for row in existing)
    assert len(after) == len(PRESETS) + 1
    assert db.scalar('SELECT COUNT(*) FROM pay_component_types WHERE organisation_id=?', (uk['id'],)) == 0
    assert custom['preset_key'] is None
    for key, name, direction, flags, role in PRESETS:
        actual = next(row for row in after if row['preset_key'] == key)
        if key not in {'author', 'bailiff', 'parental', 'contract', 'base_adjustment'}:
            assert (actual['name'], actual['direction'], tuple(actual[f] for f in FLAGS), actual['liability_role']) == (name, direction, flags, role)
    with db.transaction() as tx:
        seed_types(tx, org['id'])
    connection = db.connect()
    try:
        connection.executescript((MIGRATIONS / 'sqlite' / '0036_payroll_component_catalogue.sql').read_text(encoding='utf-8'))
    finally:
        connection.close()
    assert db.rows('SELECT * FROM pay_component_types ORDER BY id') == after
    assert db.migrate() == []
    assert db.rows('PRAGMA foreign_key_check') == []


def test_empty_migration_is_idempotent(tmp_path):
    db = Database(path=str(tmp_path / "empty.sqlite"))
    assert db.migrate() == ["0001_accounting_core", "0002_integrations", "0003_operations", "0004_document_immutability", "0005_payroll", "0006_payroll_part_time_hourly", "0007_automation", "0008_import_staging", "0009_local_accounts", "0010_tsd_export", "0011_account_mappings", "0012_external_gl", "0013_sync_review", "0014_sync_push", "0015_payment_orders", "0016_bank_feed_schedules", "0017_prepayments", "0018_fixed_assets", "0019_master_data_import", "0020_quotes", "0021_periodisation", "0022_payment_links", "0023_analytical_objects", "0024_reminder_rules", "0025_fx_realised", "0026_fx_revaluations", "0027_mfa", "0028_document_settings", "0029_copilot", "0030_master_data_maintenance", "0031_master_data_groups", "0032_copilot_access", "0033_copilot_settings", "0034_payroll_demo_fixes", "0035_payroll_income_line", "0036_payroll_component_catalogue", "0037_employee_tax_settings", "0038_payroll_payday_rules", "0039_payroll_payouts", "0040_payroll_settlement_dates", "0041_payroll_sepa_details", "0042_payroll_component_metadata", "0043_payroll_absences", "0044_payroll_absence_day_freeze", "0045_payroll_history"]
    assert db.migrate() == []
    assert db.scalar("SELECT COUNT(*) FROM schema_migrations") == 45
    assert db.scalar(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
        "AND name IN ('account_mappings','external_gl_entries')"
    ) == 2
    staged_columns = {
        row["name"] for row in db.rows("PRAGMA table_info(import_staged_records)")
    }
    assert {"matched_local_id", "match_json"} <= staged_columns
    sync_columns = {row["name"] for row in db.rows("PRAGMA table_info(sync_runs)")}
    assert {"reviewed_at", "reviewed_by"} <= sync_columns


def test_migration_preserves_existing_data(tmp_path):
    path = str(tmp_path / "upgrade.sqlite")
    db = Database(path=path)
    db.migrate()
    org = OrganisationService(db).create(name="Preserved", country_code="UK",
        entity_type="UK_COMPANY", owner_email="a@example.test")
    assert db.migrate() == []
    assert db.one("SELECT name FROM organisations WHERE id=?", (org["id"],))["name"] == "Preserved"


def test_historical_migration_catalogue_does_not_affect_other_databases(tmp_path):
    import database
    from concurrent.futures import ThreadPoolExecutor

    historical = tmp_path / 'historical'
    (historical / 'sqlite').mkdir(parents=True)
    versions = []
    for source in (database.MIGRATIONS / 'sqlite').glob('000[1-5]*.sql'):
        (historical / 'sqlite' / source.name).write_text(source.read_text(encoding='utf-8'), encoding='utf-8')
        versions.append(source.stem)
    legacy = Database(path=str(tmp_path / 'legacy.sqlite'))
    current = Database(path=str(tmp_path / 'current.sqlite'))
    with ThreadPoolExecutor(max_workers=2) as pool:
        old_setup = pool.submit(legacy.migrate, migrations=historical)
        current_setup = pool.submit(current.migrate)
        assert old_setup.result() == sorted(versions)
        latest = current_setup.result()
    assert latest[-1] == '0045_payroll_history'
    assert legacy.scalar('SELECT COUNT(*) FROM schema_migrations') == 5
    assert current.scalar('SELECT COUNT(*) FROM schema_migrations') == 45
    assert legacy.migrate() == latest[5:]
    assert legacy.migrate() == current.migrate() == []


def test_unsafe_postgres_schema_is_rejected():
    with pytest.raises(ValueError, match="unsafe"):
        Database(url="postgresql://unused", schema='public; DROP SCHEMA public')


def test_postgres_pool_is_singleton_per_url(monkeypatch):
    import database

    created = []

    class FakePool:
        check_connection = staticmethod(lambda connection: None)

        def __init__(self, **kwargs):
            created.append(kwargs)

        def open(self):
            pass

        def close(self):
            pass

    database.close_database_pools()
    monkeypatch.setattr(database, "ConnectionPool", FakePool)
    first = database._postgres_pool("postgresql://example/one")
    second = database._postgres_pool("postgresql://example/one")
    other = database._postgres_pool("postgresql://example/two")

    assert first is second
    assert other is not first
    assert len(created) == 2
    assert created[0]["min_size"] == 0
    assert created[0]["max_size"] == 3
    database.close_database_pools()


def test_organisation_entity_country_and_seed_data(db):
    service = OrganisationService(db)
    with pytest.raises(ValueError, match="does not belong"):
        service.create(name="Wrong", country_code="EE", entity_type="UK_COMPANY", owner_email="a@example.test")
    uk = service.create(name="UK Sole", country_code="UK", entity_type="UK_SOLE_TRADER", owner_email="a@example.test")
    ee = service.create(name="EE FIE", country_code="EE", entity_type="EE_FIE", owner_email="a@example.test")
    assert uk["base_currency"] == "GBP" and ee["base_currency"] == "EUR"
    assert db.scalar("SELECT COUNT(*) FROM accounts WHERE organisation_id=?", (uk["id"],)) == 17
    assert db.scalar("SELECT COUNT(*) FROM tax_codes WHERE organisation_id=?", (ee["id"],)) == 8
    assert db.scalar("SELECT COUNT(*) FROM fiscal_periods WHERE organisation_id=?", (uk["id"],)) == 24
    assert {row["code"]: row["name"] for row in db.rows(
        "SELECT code,name FROM accounts WHERE organisation_id=? AND system_role LIKE 'PAYROLL_%'",
        (ee["id"],),
    )} == {
        **{code: name for code, name, role in PAYROLL_COMPONENT_ACCOUNTS},
        "6110": "Palgakulu",
        "6120": "Sotsiaalmaksu kulu",
        "6130": "Tööandja töötuskindlustusmakse kulu",
        "2210": "Palgavõlg töötajatele",
        "2220": "Kinnipeetud tulumaksu võlg",
        "2230": "Pensioni- ja töötuskindlustusmaksete võlg",
        "2240": "Sotsiaalmaksu ja tööandja töötuskindlustuse võlg",
    }


def test_membership_roles_and_tenant_isolation(db, uk_org, ee_org):
    service = OrganisationService(db)
    service.add_member(uk_org["id"], "owner@example.test", "viewer@example.test", "viewer")
    assert [o["id"] for o in service.for_user("viewer@example.test")] == [uk_org["id"]]
    with pytest.raises(AccessDenied):
        service.require(ee_org["id"], "viewer@example.test", {"viewer"})
    with pytest.raises(AccessDenied):
        service.add_member(uk_org["id"], "viewer@example.test", "x@example.test", "viewer")


def test_database_foreign_keys_are_enforced(db):
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as tx:
            tx.execute("INSERT INTO memberships(id,organisation_id,email,role,created_at) VALUES ('x','missing','x@x.test','viewer','now')")


def test_migration_list_matches_ci_exactly(tmp_path):
    import ast
    import re
    from pathlib import Path
    workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/ci.yml').read_text(encoding='utf-8')
    expected = ast.literal_eval(re.search(r'assert db\.migrate\(\) == (\[[^\n]+\])', workflow).group(1))
    db = Database(path=str(tmp_path / 'ci-migrations.sqlite'))
    assert db.migrate() == expected
    assert db.migrate() == []


def test_bank_feed_migration_preserves_previous_schema_data(tmp_path, monkeypatch):
    import shutil
    import database
    from documents import DocumentService
    from core_utils import canonical_json, utc_now
    directory = tmp_path / 'migrations' / 'sqlite'
    directory.mkdir(parents=True)
    original = database.MIGRATIONS
    for source in (original / 'sqlite').glob('*.sql'):
        if source.stem < '0016':
            shutil.copyfile(source, directory / source.name)
    monkeypatch.setattr(database, 'MIGRATIONS', directory.parent)
    db = Database(path=str(tmp_path / 'bank-upgrade.sqlite'))
    db.migrate()
    org = OrganisationService(db).create(name='Synthetic preserved company', country_code='EE',
        entity_type='EE_OU', owner_email='owner@example.test')
    bank = DocumentService(db).create_bank_account(org['id'], name='Synthetic preserved bank', currency='EUR')
    now = utc_now()
    with db.transaction() as tx:
        tx.execute("INSERT INTO integration_connections(id,organisation_id,provider,status,config_json,created_at,updated_at) VALUES (?,?,?,'Connected',?,?,?)",
                   ('synthetic-connection', org['id'], 'open_banking', canonical_json({'requisition_status': 'LN', 'account_ids': ['synthetic-account'], 'account_mappings': {'synthetic-account': bank['id']}}), now, now))
    tables = ['organisations', 'bank_accounts', 'integration_connections', 'audit_events', 'gl_entries']
    before = {name: db.rows(f'SELECT * FROM {name} ORDER BY id') for name in tables}
    shutil.copyfile(original / 'sqlite' / '0016_bank_feed_schedules.sql', directory / '0016_bank_feed_schedules.sql')
    assert db.migrate() == ['0016_bank_feed_schedules']
    assert {name: db.rows(f'SELECT * FROM {name} ORDER BY id') for name in tables} == before
    assert db.rows('SELECT * FROM bank_feed_schedules') == []


@pytest.mark.parametrize("country", ["UK", "EE"])
@pytest.mark.parametrize("existing_role", [False, True])
def test_fixed_asset_upgrade_preserves_custom_charts_and_postings(tmp_path, monkeypatch, country, existing_role):
    import shutil
    import database
    import organisations
    from core_utils import new_id
    from decimal import Decimal
    from ledger import LedgerService, PostingLine

    original = database.MIGRATIONS
    previous = tmp_path / "previous" / "sqlite"
    previous.mkdir(parents=True)
    for path in (original / "sqlite").glob("*.sql"):
        if path.stem < "0018":
            shutil.copyfile(path, previous / path.name)
    monkeypatch.setattr(database, "MIGRATIONS", previous.parent)
    roles = {"FIXED_ASSETS", "ACCUMULATED_DEPRECIATION", "DEPRECIATION_EXPENSE"}
    for chart in ["UK_ACCOUNTS", "EE_ACCOUNTS"]:
        monkeypatch.setattr(organisations, chart, tuple(row for row in getattr(organisations, chart) if row[4] not in roles))
    db = Database(path=str(tmp_path / "assets-upgrade.sqlite"))
    db.migrate()
    org = OrganisationService(db).create(name="Synthetic assets upgrade", country_code=country,
        entity_type="UK_COMPANY" if country == "UK" else "EE_OU", owner_email="owner@example.test")
    codes = [1500, 1550, 6500] if country == "UK" else [1410, 1419, 6410]
    with db.transaction() as tx:
        for base in codes:
            for offset in range(2):
                tx.execute("INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance) VALUES (?,?,?,'Custom asset chart','Asset','Debit')",
                           (new_id(), org["id"], str(base + offset)))
        if existing_role:
            tx.execute("INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role) VALUES (?,?,'9998','Existing fixed assets','Asset','Debit','FIXED_ASSETS')",
                       (new_id(), org["id"]))
    accounts = {row["system_role"]: row["id"] for row in db.rows("SELECT * FROM accounts WHERE organisation_id=?", (org["id"],))}
    LedgerService(db).post(organisation_id=org["id"], posting_date="2026-01-01", voucher_type="synthetic", voucher_id="upgrade", voucher_code="Synthetic preserved posting", currency=org["base_currency"],
        lines=[PostingLine(accounts["BANK"], debit=Decimal("10")), PostingLine(accounts["CAPITAL"], credit=Decimal("10"))], actor="owner@example.test")
    before = {table: db.rows(f"SELECT * FROM {table} ORDER BY id") for table in ["organisations", "accounts", "gl_entries", "posting_batches", "audit_events"]}
    monkeypatch.setattr(database, "MIGRATIONS", original)
    assert db.migrate() == ["0018_fixed_assets", "0019_master_data_import", "0020_quotes", "0021_periodisation", "0022_payment_links", "0023_analytical_objects", "0024_reminder_rules", "0025_fx_realised", "0026_fx_revaluations", "0027_mfa", "0028_document_settings", "0029_copilot", "0030_master_data_maintenance", "0031_master_data_groups", "0032_copilot_access", "0033_copilot_settings", "0034_payroll_demo_fixes", "0035_payroll_income_line", "0036_payroll_component_catalogue", "0037_employee_tax_settings", "0038_payroll_payday_rules", "0039_payroll_payouts", "0040_payroll_settlement_dates", "0041_payroll_sepa_details", "0042_payroll_component_metadata", "0043_payroll_absences", "0044_payroll_absence_day_freeze", "0045_payroll_history"]
    assert db.migrate() == []
    after_accounts = db.rows("SELECT * FROM accounts ORDER BY id")
    assert all(row in after_accounts for row in before["accounts"])
    for table in ["organisations", "gl_entries", "posting_batches", "audit_events"]:
        rows = db.rows(f"SELECT * FROM {table} ORDER BY id")
        if table == "organisations":
            assert all(row.pop("copilot_enabled") == 0 for row in rows)
            for row in rows:
                row.pop('language', None)
        assert rows == before[table]
    assigned = {row["system_role"]: row for row in after_accounts if row["system_role"] in roles}
    for role, code in zip(["FIXED_ASSETS", "ACCUMULATED_DEPRECIATION", "DEPRECIATION_EXPENSE"], codes):
        assert assigned[role]["code"] == ("9998" if role == "FIXED_ASSETS" and existing_role else str(code + 2))
    assert assigned["ACCUMULATED_DEPRECIATION"]["normal_balance"] == "Credit"
    assert db.rows("SELECT * FROM asset_groups") == []
