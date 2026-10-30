import pytest
from fastapi.testclient import TestClient

from organisations import OrganisationService
from payroll import PayrollService
from payroll_tax_settings import EmployeeTaxSettingsService

ACTOR = 'owner@example.test'


@pytest.fixture
def tax_api(db, ee_org, monkeypatch):
    monkeypatch.setenv('FASTACCOUNTS_DB', db.path)
    monkeypatch.setenv('DB_URL', '')
    from api_app import api
    payroll = PayrollService(db)
    person = payroll.save_employee(ee_org['id'], actor=ACTOR, name='Synthetic API person', gross_salary='2000')
    base = f"/organisations/{ee_org['id']}/employees/{person['id']}/tax-settings"
    with TestClient(api, headers={'X-Test-User': ACTOR}) as client:
        yield client, base, payroll, person


def test_history_crud_roles_and_tenant_boundary(tax_api, db, ee_org, uk_org):
    client, base, payroll, person = tax_api
    assert client.get(base).status_code == 200
    for index, role in enumerate(('owner', 'administrator', 'accountant', 'approver', 'viewer'), 1):
        if role != 'owner':
            OrganisationService(db).add_member(ee_org['id'], ACTOR, f'{role}@example.test', role)
        headers = {'X-Test-User': ACTOR if role == 'owner' else f'{role}@example.test'}
        assert client.get(base, headers=headers).status_code == 200
        body = dict(kind='pension', start_date=f'2026-11-{index:02}', rate=4)
        created = client.post(base, headers=headers, json=body)
        assert created.status_code == (201 if index <= 3 else 403), created.text
        target = base + '/' + (created.json()['id'] if created.status_code == 201 else client.get(base).json()[0]['id'])
        edited = client.put(target, headers=headers, json=body | {'rate': 6})
        assert edited.status_code == (200 if index <= 3 else 403), edited.text
        assert client.delete(target, headers=headers).status_code == (204 if index <= 3 else 403)
    foreign_base = base.replace(ee_org['id'], uk_org['id'])
    assert client.get(foreign_base).status_code == 404
    assert client.post(foreign_base, json=body).status_code == 404
    existing = client.get(base).json()[0]
    assert client.delete(foreign_base + '/' + existing['id']).status_code == 404
    other = payroll.save_employee(ee_org['id'], actor=ACTOR, name='Other person', gross_salary='1000')
    other_base = base.replace(person['id'], other['id'])
    assert client.put(other_base + '/' + existing['id'], json=body).status_code == 404
    assert client.delete(other_base + '/' + existing['id']).status_code == 404
    with TestClient(client.app) as anonymous:
        assert anonymous.get(base).status_code == 401
    assert client.get(base, headers={'X-Test-User': 'intruder@example.test'}).status_code == 403


def test_frozen_history_conflicts_and_translated_year(tax_api, ee_org):
    from web import i18n
    client, base, payroll, person = tax_api
    run = payroll.create_run(ee_org['id'], period='2026-10', actor=ACTOR)
    payroll.approve(ee_org['id'], run['id'], actor=ACTOR)
    row = next(r for r in client.get(base).json() if r['kind'] == 'pension')
    assert row['frozen']
    headers = {'Accept-Language': 'et'}
    response = client.delete(base + '/' + row['id'], headers=headers)
    assert response.status_code == 409
    assert response.json()['detail'] == i18n.catalog('et')['workspace']['Tax settings used in an approved run cannot be changed or deleted']
    assert client.put(base + '/' + row['id'], json=dict(kind='pension', start_date=row['start_date'], rate=6)).status_code == 409
    response = client.post(f"/organisations/{ee_org['id']}/pay-runs", json={'period': '2027-01'}, headers=headers)
    assert response.status_code == 422
    assert response.json()['detail'] == i18n.catalog('et')['workspace']['Payroll rules are not configured for this year']
    # Re-saving unchanged legacy pension fields must not mutate a frozen election.
    assert client.patch(base.rsplit('/tax-settings', 1)[0], json={'name': 'Renamed', 'funded_pension_percent': '2.00'}).status_code == 200


def test_history_writes_require_real_csrf(tax_api):
    from api_app import api, current_user, User
    from web_app import app
    _, base, _, _ = tax_api
    api.dependency_overrides[current_user] = lambda: User(email=ACTOR)
    try:
        with TestClient(app) as client:
            body = dict(kind='tax_free', start_date='2026-11-01', mode='limited', amount='300')
            assert client.post('/api' + base, json=body).status_code == 403
            token = client.get('/api/csrf').json()['csrf_token']
            headers = {'X-CSRF-Token': token}
            created = client.post('/api' + base, json=body, headers=headers)
            assert created.status_code == 201, created.text
            target = '/api' + base + '/' + created.json()['id']
            assert client.put(target, json=body).status_code == 403
            assert client.delete(target).status_code == 403
            assert client.put(target, json=body | {'amount': '200'}, headers=headers).status_code == 200
            assert client.delete(target, headers=headers).status_code == 204
    finally:
        api.dependency_overrides.pop(current_user, None)
