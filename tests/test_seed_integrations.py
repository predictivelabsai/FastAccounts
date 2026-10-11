"""Regression coverage for synthetic integration demo fixtures."""
from integration_service import IntegrationService


def test_demo_seed_creates_encrypted_connections_and_offline_import_runs(db, monkeypatch):
    monkeypatch.setenv("FASTACCOUNTS_DB", db.path)
    monkeypatch.setenv("DB_URL", "")

    from seed import DEMO_CONNECTION_NOTE, seed_demo

    uk, ee = seed_demo()
    service = IntegrationService(db)
    assert {
        (row["provider"], row["status"], row["config"].get("note"))
        for organisation in (uk, ee)
        for row in service.connections(organisation["id"])
    } == {
        ("quickbooks", "Connected", DEMO_CONNECTION_NOTE),
        ("xero", "Connected", DEMO_CONNECTION_NOTE),
        ("merit", "Connected", DEMO_CONNECTION_NOTE),
        ("smartaccounts", "Connected", DEMO_CONNECTION_NOTE),
        ("fasthr", "Connected", DEMO_CONNECTION_NOTE),
    }
    assert {row["provider"] for row in service.connections(uk["id"])} == {
        "quickbooks",
        "xero",
    }
    assert {row["provider"] for row in service.connections(ee["id"])} == {
        "fasthr",
        "merit",
        "smartaccounts",
    }

    secret_fragments = ("demo-synthetic-smartaccounts-public-key", "demo-synthetic-smartaccounts-secret-key", "demo-sandbox-token", "demo-synthetic-xero-token", "demo-synthetic-merit-api-key", "demo-synthetic-fasthr-token")
    stored = db.rows(
        "SELECT provider,encrypted_credentials FROM integration_connections ORDER BY provider"
    )
    assert len(stored) == 5
    assert all(
        fragment not in row["encrypted_credentials"]
        for row in stored
        for fragment in secret_fragments
    )

    runs = db.rows(
        "SELECT * FROM sync_runs WHERE organisation_id=? AND provider='file_import' ORDER BY id",
        (ee["id"],),
    )
    assert sorted(run["status"] for run in runs) == ["Completed", "Review Required"]
    completed = next(run for run in runs if run["status"] == "Completed")
    review = next(run for run in runs if run["status"] == "Review Required")
    assert (completed["read_count"], completed["write_count"]) == (3, 3)
    assert db.scalar(
        "SELECT COUNT(*) FROM import_staged_records WHERE sync_run_id=? AND status='Applied'",
        (completed["id"],),
    ) == 3
    assert (review["read_count"], review["write_count"]) == (2, 0)
    assert db.scalar(
        "SELECT COUNT(*) FROM import_staged_records WHERE sync_run_id=? AND status='Pending'",
        (review["id"],),
    ) == 2

    from push_service import PushService
    import json
    from decimal import Decimal

    pushes = PushService(db).list(ee['id'], 'smartaccounts')
    assert len(pushes) == 1
    push = pushes[0]
    assert (push['direction'], push['object_type'], push['status']) == ('export', 'journals', 'Review Required')
    batch = db.one('SELECT posted_batch_id FROM pay_runs WHERE organisation_id=? AND period=?', (ee['id'], '2026-09'))
    assert push['local_ref'] == batch['posted_batch_id'] and push['reviewed_at'] is None
    payload = json.loads(push['payload_json'])
    assert payload['currency'] == 'EUR' and len(payload['lines']) == 7
    assert sum((Decimal(line['debit']) for line in payload['lines']), Decimal(0)) == sum((Decimal(line['credit']) for line in payload['lines']), Decimal(0))
    assert all(db.one("SELECT id FROM account_mappings WHERE organisation_id=? AND provider='smartaccounts' "
                      "AND local_account_code=? AND status='Confirmed'", (ee['id'], line['account_code'])) for line in payload['lines'])
    # The seeded payload is genuinely reviewable against its source journal.
    expected, _, _ = PushService(db)._payload(ee['id'], 'smartaccounts', 'journals', push['local_ref'])
    from core_utils import canonical_json
    assert canonical_json(expected) == push['payload_json']

    before = {
        "connections": db.rows("SELECT * FROM integration_connections ORDER BY id"),
        "runs": db.rows("SELECT * FROM sync_runs WHERE provider='file_import' ORDER BY id"),
        "staged": db.rows("SELECT * FROM import_staged_records ORDER BY id"),
        "pushes": db.rows("SELECT * FROM sync_runs WHERE direction='export' ORDER BY id"),
        "account_mappings": db.rows("SELECT * FROM account_mappings ORDER BY id"),
    }
    seed_demo()
    assert before == {
        "connections": db.rows("SELECT * FROM integration_connections ORDER BY id"),
        "runs": db.rows("SELECT * FROM sync_runs WHERE provider='file_import' ORDER BY id"),
        "staged": db.rows("SELECT * FROM import_staged_records ORDER BY id"),
        "pushes": db.rows("SELECT * FROM sync_runs WHERE direction='export' ORDER BY id"),
        "account_mappings": db.rows("SELECT * FROM account_mappings ORDER BY id"),
    }
