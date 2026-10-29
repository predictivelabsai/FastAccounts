from datetime import date

from bureau_overview import PayrollBureauOverviewService
from organisations import OrganisationService
from fastapi.testclient import TestClient
from api_app import api
from database import reset_database_cache


def test_bureau_overview_only_includes_the_signed_in_users_organisations(db, ee_org):
    service = OrganisationService(db)
    second = service.create(name='Second bureau client', country_code='EE', entity_type='EE_OU',
                            owner_email='other@example.test')
    third = service.create(name='Unrelated bureau client', country_code='EE', entity_type='EE_OU',
                           owner_email='other@example.test')
    with db.transaction() as tx:
        tx.execute('INSERT INTO memberships(id,organisation_id,email,role,created_at) VALUES (?,?,?,?,?)',
                   ('member-second', second['id'], 'owner@example.test', 'accountant', '2026-01-01'))
    rows = PayrollBureauOverviewService(db).for_user('owner@example.test', today=date(2026, 10, 29))
    assert {row['id'] for row in rows} == {ee_org['id'], second['id']}
    assert next(row for row in rows if row['id'] == second['id'])['role'] == 'accountant'
    assert all(row['period'] == '2026-10' for row in rows)
    assert all(row['palk_due_date'] == row['tsd_due_date'] == '2026-11-10' for row in rows)


def test_dimension_register_api_is_readable_to_members_and_write_restricted(db, ee_org, monkeypatch):
    monkeypatch.setenv('FASTACCOUNTS_DB', db.path)
    monkeypatch.setenv('DB_URL', '')
    reset_database_cache()
    with db.transaction() as tx:
        tx.execute('INSERT INTO memberships(id,organisation_id,email,role,created_at) VALUES (?,?,?,?,?)',
                   ('bureau-viewer', ee_org['id'], 'viewer@example.test', 'viewer', '2026-01-01'))
    path = f"/organisations/{ee_org['id']}/payroll/dimensions"
    with TestClient(api) as client:
        owner = {'X-Test-User': 'owner@example.test'}
        viewer = {'X-Test-User': 'viewer@example.test'}
        saved = client.post(path, headers=owner, json={'kind': 'department', 'code': 'OPS', 'name': 'Operations'})
        assert saved.status_code == 201
        assert client.get(path, headers=viewer).json()[0]['id'] == saved.json()['id']
        assert client.post(path, headers=viewer, json={'kind': 'department', 'code': 'FIN', 'name': 'Finance'}).status_code == 403
