import pytest
from fastapi.testclient import TestClient

from payroll_absences import AbsenceConflict, PayrollAbsenceService

ACTOR = 'owner@example.test'


def test_absence_counts_include_calendar_days_but_annual_leave_excludes_public_holidays(db, ee_org, legacy_payroll):
    legacy_payroll(db, ee_org['id'], name='Absence employee', gross='2000')
    service = PayrollAbsenceService(db)
    annual = service.save(ee_org['id'], 'legacy-employee', actor=ACTOR, absence_type='annual_leave',
                         start_date='2026-12-24', end_date='2026-12-27')
    sick = service.save(ee_org['id'], 'legacy-employee', actor=ACTOR, absence_type='sick_leave',
                        start_date='2026-12-28', end_date='2026-12-29')
    assert (annual['calendar_days'], annual['leave_days'], annual['working_days']) == (4, 1, 0)
    assert (sick['calendar_days'], sick['leave_days'], sick['working_days']) == (2, 2, 2)
    assert [row['id'] for row in service.list(ee_org['id'], month='2026-12', kind='annual_leave')] == [annual['id']]


def test_absence_pay_is_persisted_and_only_pending_records_recalculate(db, ee_org, legacy_payroll):
    legacy_payroll(db, ee_org['id'], name='Absence pay employee', gross='2000')
    service = PayrollAbsenceService(db)
    absence = service.save(ee_org['id'], 'legacy-employee', actor=ACTOR, absence_type='annual_leave',
                           start_date='2026-10-19', end_date='2026-10-21')
    saved = service.set_pay_method(ee_org['id'], absence['id'], 'best_of', actor=ACTOR)
    assert saved['method'] == 'best_of' and saved['status'] == 'pending'
    assert saved['gross'] == '272.73'
    assert saved['breakdown']['method'] == 'best_of'
    fixed = service.set_pay_method(ee_org['id'], absence['id'], 'fixed_sum', actor=ACTOR, fixed_amount='275')
    assert fixed['gross'] == '275.00' and fixed['fixed_amount'] == '275.00'
    assert service.list(ee_org['id'])[0]['absence_pay']['breakdown']['amount'] == '275.00'
    with db.transaction() as tx:
        tx.execute("UPDATE payroll_absence_pay SET status='in_payout' WHERE organisation_id=? AND absence_id=?",
                   (ee_org['id'], absence['id']))
    with pytest.raises(AbsenceConflict, match='frozen'):
        service.set_pay_method(ee_org['id'], absence['id'], 'average', actor=ACTOR)


def test_absence_overlap_is_refused_and_updates_remain_tenant_scoped(db, ee_org, legacy_payroll):
    legacy_payroll(db, ee_org['id'], name='Overlap employee', gross='2000')
    service = PayrollAbsenceService(db)
    first = service.save(ee_org['id'], 'legacy-employee', actor=ACTOR, absence_type='sick_leave',
                         start_date='2026-10-12', end_date='2026-10-14')
    with pytest.raises(AbsenceConflict, match='overlap'):
        service.save(ee_org['id'], 'legacy-employee', actor=ACTOR, absence_type='annual_leave',
                     start_date='2026-10-14', end_date='2026-10-20')
    other = __import__('organisations').OrganisationService(db).create(
        name='Other absence tenant', country_code='EE', entity_type='EE_OU', owner_email='other@example.test')
    with pytest.raises(KeyError, match='not found'):
        service.save(other['id'], 'legacy-employee', actor='other@example.test', absence_type='annual_leave',
                     start_date='2026-10-12', end_date='2026-10-14')
    assert service.list(ee_org['id'])[0]['id'] == first['id']


def test_collective_leave_creates_one_absence_per_employee(db, ee_org, legacy_payroll):
    legacy_payroll(db, ee_org['id'], name='Collective employee', gross='2000')
    from payroll import PayrollService
    service = PayrollAbsenceService(db)
    employee = PayrollService(db).save_employee(ee_org['id'], actor=ACTOR, name='Second employee',
                                               gross_salary='1500', apply_tax_free_minimum=False)
    rows = service.collective_annual_leave(ee_org['id'], ['legacy-employee', employee['id']], actor=ACTOR,
                                          start_date='2026-08-17', end_date='2026-08-21')
    assert len(rows) == 2 and {row['employee_id'] for row in rows} == {'legacy-employee', employee['id']}
    assert all(row['absence_type'] == 'annual_leave' and row['leave_days'] == 4 for row in rows)


def test_absence_api_requires_csrf_and_scopes_employee_to_organisation(db, ee_org, monkeypatch, legacy_payroll):
    from api_app import api, current_user, User
    from web_app import app
    monkeypatch.setenv('FASTACCOUNTS_DB', db.path)
    monkeypatch.setenv('DB_URL', '')
    legacy_payroll(db, ee_org['id'], name='API absence employee', gross='2000')
    api.dependency_overrides[current_user] = lambda: User(email=ACTOR)
    client = TestClient(app)
    root = f"/api/organisations/{ee_org['id']}/payroll"
    try:
        body = {'employee_id':'legacy-employee','absence_type':'annual_leave',
                'start_date':'2026-10-19','end_date':'2026-10-21'}
        assert client.post(root + '/absences', json=body).status_code == 403
        token = client.get('/api/csrf').json()['csrf_token']
        headers = {'X-CSRF-Token': token}
        created = client.post(root + '/absences', json=body, headers=headers)
        assert created.status_code == 201, created.text
        assert created.json()['leave_days'] == 3
        assert client.post(root + '/absences', json=body, headers=headers).status_code == 409
        foreign = {**body, 'employee_id':'missing-from-this-tenant', 'start_date':'2026-11-02', 'end_date':'2026-11-03'}
        assert client.post(root + '/absences', json=foreign, headers=headers).status_code == 404
    finally:
        api.dependency_overrides.clear()


def test_absence_type_salary_setting_is_audited(db, ee_org):
    service = PayrollAbsenceService(db)
    settings = {row['absence_type']: row['paid_salary'] for row in service.types(ee_org['id'])}
    assert settings['permitted_absence'] is False
    updated = service.set_type_paid(ee_org['id'], 'permitted_absence', True, actor=ACTOR)
    assert updated['paid_salary'] is True
    assert db.scalar("SELECT COUNT(*) FROM audit_events WHERE organisation_id=? AND action='payroll.absence_type.updated'", (ee_org['id'],)) == 1


def test_monthly_salary_is_prorated_by_frozen_absence_workdays(db, ee_org):
    from decimal import Decimal
    from payroll import PayrollService
    service = PayrollService(db)
    employee = service.save_employee(ee_org['id'], actor=ACTOR, name='Prorated employee',
                                     gross_salary='2200', apply_tax_free_minimum=False)
    absence = PayrollAbsenceService(db).save(ee_org['id'], employee['id'], actor=ACTOR,
                                             absence_type='sick_leave', start_date='2026-10-05',
                                             end_date='2026-10-05')
    item = service.create_run(ee_org['id'], period='2026-10', actor=ACTOR)['items'][0]
    assert item['worked_days'] == 21 and item['norm_days'] == 22
    assert item['absence_working_days'] == absence['working_days'] == 1
    assert item['gross_salary'] == item['gross'] == '2100.00'
    assert Decimal(item['minimum_wage']) == Decimal('903.00')
    assert db.scalar('SELECT COUNT(*) FROM payroll_absence_run_items WHERE organisation_id=? AND absence_id=?',
                     (ee_org['id'], absence['id'])) == 1


def test_hourly_pay_is_not_reduced_for_absences_and_approved_freeze_protects_record(db, ee_org):
    from payroll import PayrollConflict, PayrollService
    service = PayrollService(db)
    employee = service.save_employee(ee_org['id'], actor=ACTOR, name='Hourly absence employee',
                                     pay_basis='hourly', hourly_rate='8.00', apply_tax_free_minimum=False)
    absence_service = PayrollAbsenceService(db)
    absence = absence_service.save(ee_org['id'], employee['id'], actor=ACTOR, absence_type='sick_leave',
                                   start_date='2026-10-05', end_date='2026-10-05')
    run = service.create_run(ee_org['id'], period='2026-10', actor=ACTOR, hours={employee['id']: '176'})
    item = run['items'][0]
    assert item['gross'] == '1408.00' and item['hours'] == '176.00'
    assert item['worked_days'] is None and item['norm_days'] is None
    service.approve(ee_org['id'], run['id'], actor=ACTOR)
    with pytest.raises(AbsenceConflict, match='approved'):
        absence_service.delete(ee_org['id'], absence['id'], actor=ACTOR)
    with pytest.raises(PayrollConflict):
        service.delete_run(ee_org['id'], run['id'], actor=ACTOR)


def test_part_time_monthly_minimum_and_absence_proration_use_fte(db, ee_org):
    from decimal import Decimal
    from payroll import PayrollService
    service = PayrollService(db)
    employee = service.save_employee(ee_org['id'], actor=ACTOR, name='Part-time absence employee',
                                     gross_salary='1500', fte='0.5', apply_tax_free_minimum=False)
    PayrollAbsenceService(db).save(ee_org['id'], employee['id'], actor=ACTOR, absence_type='annual_leave',
                                   start_date='2026-10-05', end_date='2026-10-05')
    item = service.create_run(ee_org['id'], period='2026-10', actor=ACTOR)['items'][0]
    assert item['gross'] == '1431.82' and item['minimum_wage'] == '451.50'
    assert item['fte'] == '0.5' and Decimal(item['worked_days']) == Decimal('21')


def test_paid_permitted_absence_does_not_reduce_monthly_salary(db, ee_org):
    from payroll import PayrollService
    service = PayrollService(db)
    employee = service.save_employee(ee_org['id'], actor=ACTOR, name='Paid permitted absence',
                                     gross_salary='2200', apply_tax_free_minimum=False)
    absences = PayrollAbsenceService(db)
    absences.save(ee_org['id'], employee['id'], actor=ACTOR, absence_type='permitted_absence',
                  start_date='2026-10-05', end_date='2026-10-05')
    absences.set_type_paid(ee_org['id'], 'permitted_absence', True, actor=ACTOR)
    item = service.create_run(ee_org['id'], period='2026-10', actor=ACTOR)['items'][0]
    assert item['gross'] == '2200.00' and item['worked_days'] == item['norm_days'] == 22
    assert item['absence_working_days'] == 0

