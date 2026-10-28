from decimal import Decimal

from ledger import LedgerService
from organisations import OrganisationService
from payroll import PayrollService

ACTOR = 'owner@example.test'


def _approved(service, org):
    employee = service.save_employee(org['id'], actor=ACTOR, name='Correction employee',
                                    gross_salary='2000')
    run = service.create_run(org['id'], period='2026-10', actor=ACTOR)
    return employee, service.approve(org['id'], run['id'], actor=ACTOR)


def _delta_batch(db, org, correction):
    return db.rows('SELECT g.* FROM gl_entries g WHERE g.organisation_id=? AND g.posting_batch_id=?',
                   (org['id'], correction['posted_batch_id']))


def test_correction_increase_and_decrease_post_only_delta(db, ee_org):
    service = PayrollService(db)
    employee, original = _approved(service, ee_org)
    frozen = original['items'][0]['gross']
    correction = service.create_correction(ee_org['id'], original['id'], actor=ACTOR)
    service.update_item(ee_org['id'], correction['id'], correction['items'][0]['id'],
                        actor=ACTOR, gross_salary='2500')
    approved = service.approve(ee_org['id'], correction['id'], actor=ACTOR)
    lines = _delta_batch(db, ee_org, approved)
    assert sum((Decimal(line['debit']) for line in lines), Decimal(0)) == sum(
        (Decimal(line['credit']) for line in lines), Decimal(0))
    assert Decimal(approved['total_gross']) == Decimal('2500.00')
    corrected = next(run for run in service.runs(ee_org['id']) if run['id'] == approved['id'])
    assert corrected['items'][0]['gross'] != frozen
    assert db.scalar('SELECT gross FROM pay_run_items WHERE organisation_id=? AND pay_run_id=?',
                     (ee_org['id'], original['id'])) == Decimal('2000')
    second = service.create_correction(ee_org['id'], original['id'], actor=ACTOR)
    service.update_item(ee_org['id'], second['id'], second['items'][0]['id'],
                        actor=ACTOR, gross_salary='1800')
    approved_second = service.approve(ee_org['id'], second['id'], actor=ACTOR)
    assert approved_second['status'] == 'Approved'
    assert len(_delta_batch(db, ee_org, approved_second)) > 0


def test_correction_can_fully_reverse_original(db, ee_org):
    service = PayrollService(db)
    _, original = _approved(service, ee_org)
    correction = service.create_correction(ee_org['id'], original['id'], actor=ACTOR)
    service.update_item(ee_org['id'], correction['id'], correction['items'][0]['id'],
                        actor=ACTOR, gross_salary='0')
    approved = service.approve(ee_org['id'], correction['id'], actor=ACTOR)
    assert Decimal(approved['items'][0]['gross']) == 0
    lines = _delta_batch(db, ee_org, approved)
    assert sum((Decimal(line['debit']) for line in lines), Decimal(0)) == sum(
        (Decimal(line['credit']) for line in lines), Decimal(0))


def test_supplementary_starts_empty_and_shares_monthly_exemption(db, ee_org):
    service = PayrollService(db)
    employee = service.save_employee(ee_org['id'], actor=ACTOR, name='Supplementary employee',
                                    gross_salary='2000', apply_tax_free_minimum=True)
    regular = service.create_run(ee_org['id'], period='2026-10', actor=ACTOR)
    regular = service.approve(ee_org['id'], regular['id'], actor=ACTOR)
    supplementary = service.create_supplementary(ee_org['id'], regular['id'], [employee['id']], actor=ACTOR)
    item = supplementary['items'][0]
    assert Decimal(item['gross']) == 0
    component_type = service.save_component_type(
        ee_org['id'], actor=ACTOR, name='Supplementary bonus', direction='income',
        income_tax=True, social_tax=True, ui_employee=True, ui_employer=True,
        funded_pension=True)
    updated = service.update_item(ee_org['id'], supplementary['id'], item['id'], actor=ACTOR,
                                  components=[{'type_id': component_type['id'], 'amount': '100'}])
    assert Decimal(updated['items'][0]['gross']) == Decimal('100.00')
    assert Decimal(updated['items'][0]['tax_free_minimum']) == 0


def test_correction_draft_is_unique_and_tenant_scoped(db, ee_org):
    service = PayrollService(db)
    _, original = _approved(service, ee_org)
    draft = service.create_correction(ee_org['id'], original['id'], actor=ACTOR)
    try:
        service.create_correction(ee_org['id'], original['id'], actor=ACTOR)
        assert False, 'second draft correction should fail'
    except ValueError:
        pass
    other = OrganisationService(db).create(name='Other payroll tenant', country_code='EE',
        entity_type='EE_OU', owner_email='other@example.test')
    try:
        service.create_correction(other['id'], original['id'], actor='other@example.test')
        assert False, 'cross-tenant correction should fail'
    except KeyError:
        pass


def test_creation_routes_are_role_tenant_and_csrf_protected(db, ee_org, monkeypatch):
    from fastapi.testclient import TestClient
    from api_app import api, require_csrf

    monkeypatch.setenv('FASTACCOUNTS_DB', db.path)
    monkeypatch.setenv('DB_URL', '')
    service = PayrollService(db)
    employee = service.save_employee(ee_org['id'], actor=ACTOR, name='Routed payroll employee',
                                    gross_salary='2000')
    regular = service.approve(ee_org['id'],
        service.create_run(ee_org['id'], period='2026-10', actor=ACTOR)['id'], actor=ACTOR)
    client = TestClient(api)
    root = f"/organisations/{ee_org['id']}/pay-runs/{regular['id']}"
    assert client.post(root + '/corrections').status_code == 401
    owner = {'X-Test-User': ACTOR}
    created = client.post(root + '/corrections', headers=owner)
    assert created.status_code == 201, created.text
    assert client.post(root + '/supplementary', headers=owner,
                       json={'employee_ids': [employee['id']]}).status_code == 201
    assert client.post(root + '/corrections', headers={'X-Test-User': 'intruder@example.test'}).status_code == 403
    for path in (f"/organisations/{{organisation_id}}/pay-runs/{{run_id}}/corrections",
                 f"/organisations/{{organisation_id}}/pay-runs/{{run_id}}/supplementary"):
        route = next(route for route in api.routes if getattr(route, 'path', None) == path)
        assert any(dependency.call is require_csrf for dependency in route.dependant.dependencies)
