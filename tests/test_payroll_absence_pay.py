from datetime import date
from decimal import Decimal

import pytest

from payroll_absence_pay import (
    employer_sick_benefit, unused_leave_compensation, vacation_pay,
    vacation_payout_date,
)


def test_vacation_payout_and_salary_share_payment_month_exemption_and_reverse(db, ee_org):
    from payroll import PayrollService
    from payroll_absences import PayrollAbsenceService
    from payroll_absence_payouts import AbsencePayoutService
    from payroll_payday import PaydaySettingsService
    from payroll_tax_repository import monthly_exemption_used

    actor = 'owner@example.test'
    payroll = PayrollService(db)
    employee = payroll.save_employee(ee_org['id'], actor=actor, name='November employee',
                                    personal_id='49001010018', gross_salary='2000',
                                    apply_tax_free_minimum=True)
    PaydaySettingsService(db).save(ee_org['id'], start_date='2026-01-01', rule_start_date='2026-01-01',
                                   rule='next_month_day', day=10, actor=actor)
    run = payroll.create_run(ee_org['id'], period='2026-10', actor=actor)
    payroll.approve(ee_org['id'], run['id'], actor=actor)
    absences = PayrollAbsenceService(db)
    absence = absences.save(ee_org['id'], employee['id'], actor=actor, absence_type='annual_leave',
                            start_date='2026-11-23', end_date='2026-11-27')
    snapshot = absences.set_pay_method(ee_org['id'], absence['id'], 'fixed_sum', actor=actor, fixed_amount='275')
    payouts = AbsencePayoutService(db)
    batch = payouts.create(ee_org['id'], [snapshot['id']], actor=actor)
    assert batch['payout_date'] == '2026-11-20'
    assert batch['lines'][0]['calculation']['tax_free_minimum'] == '0.00'
    with db.transaction() as tx:
        assert monthly_exemption_used(tx, ee_org['id'], employee['id'], '2026-11') == Decimal('700.00')
    approved = payouts.approve(ee_org['id'], batch['id'], actor=actor)
    gl = db.rows('SELECT debit,credit FROM gl_entries WHERE organisation_id=? AND posting_batch_id=?',
                 (ee_org['id'], approved['posted_batch_id']))
    assert sum((Decimal(str(row['debit'])) for row in gl), Decimal(0)) == sum(
        (Decimal(str(row['credit'])) for row in gl), Decimal(0))
    assert sum((Decimal(str(row['debit'])) for row in gl), Decimal(0)) == Decimal('275.00') + Decimal(
        approved['lines'][0]['calculation']['social_tax']) + Decimal(approved['lines'][0]['calculation']['ui_employer']) + Decimal(
        approved['lines'][0]['calculation']['withholding_total'])
    bank_asset = db.one("SELECT id FROM accounts WHERE organisation_id=? AND account_type='Asset' AND active=1 ORDER BY code LIMIT 1", (ee_org['id'],))
    with db.transaction() as tx:
        tx.execute("INSERT INTO bank_accounts(id,organisation_id,ledger_account_id,name,currency) VALUES ('absence-bank',?,?,?,'EUR')",
                   (ee_org['id'], bank_asset['id'], 'Absence pay bank'))
    paid = payouts.paid(ee_org['id'], batch['id'], 'absence-bank', actor=actor)
    assert paid['status'] == 'Paid'
    from tsd import TSDExportService
    workpaper = TSDExportService(db).prepare(ee_org['id'], run['id'], actor=actor)
    absence_records = [row for row in workpaper['records'] if row['pay_run_id'] == batch['id']]
    assert len(absence_records) == 1 and absence_records[0]['payment_date'] == '2026-11-20'
    assert Decimal(workpaper['totals']['gross_amount']) == Decimal('2275.00')
    tsd = TSDExportService(db)
    tsd.review(ee_org['id'], workpaper['id'], actor=actor)
    assert batch['id'].encode() in tsd.export_csv(ee_org['id'], workpaper['id'], actor=actor)
    assert batch['id'].encode() in tsd.export_xbrl_gl(ee_org['id'], workpaper['id'], actor=actor)
    cancelled = payouts.cancel(ee_org['id'], batch['id'], actor=actor)
    assert cancelled['status'] == 'Cancelled'
    assert db.one('SELECT status FROM payroll_absence_pay WHERE organisation_id=? AND id=?',
                  (ee_org['id'], snapshot['id']))['status'] == 'pending'
    assert cancelled['reversal_batch_id']
    assert db.one('SELECT status FROM posting_batches WHERE organisation_id=? AND id=?',
                  (ee_org['id'], approved['posted_batch_id']))['status'] == 'Reversed'
    assert db.one('SELECT status FROM posting_batches WHERE organisation_id=? AND id=?',
                  (ee_org['id'], paid['paid_batch_id']))['status'] == 'Reversed'


def test_absence_payout_routes_enforce_roles_tenant_and_csrf(db, ee_org, monkeypatch):
    from fastapi.testclient import TestClient
    from api_app import api, current_user, User
    from web_app import app
    from payroll_absences import PayrollAbsenceService

    monkeypatch.setenv('FASTACCOUNTS_DB', db.path)
    monkeypatch.setenv('DB_URL', '')

    actor = 'owner@example.test'
    from payroll import PayrollService
    employee = PayrollService(db).save_employee(ee_org['id'], actor=actor, name='Route employee',
                                                personal_id='49001010018', gross_salary='2000')
    service = PayrollAbsenceService(db)
    absence = service.save(ee_org['id'], employee['id'], actor=actor, absence_type='annual_leave',
                          start_date='2026-11-23', end_date='2026-11-27')
    pay = service.set_pay_method(ee_org['id'], absence['id'], 'fixed_sum', actor=actor, fixed_amount='275')
    with db.transaction() as tx:
        tx.execute("INSERT INTO memberships(id,organisation_id,email,role,created_at) VALUES ('absence-viewer',?,'viewer@example.test','viewer','2026-10-01')",
                   (ee_org['id'],))
    current_email = {'value': 'viewer@example.test'}
    api.dependency_overrides[current_user] = lambda: User(email=current_email['value'])
    client = TestClient(app)
    base = f"/api/organisations/{ee_org['id']}/payroll/absence-payouts"
    try:
        assert client.get(f"/api/organisations/{ee_org['id']}/payroll/absence-pay/pending").status_code == 200
        body = {'absence_pay_ids': [pay['id']]}
        assert client.post(base, json=body).status_code == 403
        current_email['value'] = actor
        assert client.post(base, json=body).status_code == 403
        token = client.get('/api/csrf').json()['csrf_token']
        created = client.post(base, json=body, headers={'X-CSRF-Token': token})
        assert created.status_code == 201, created.text
        other = __import__('organisations').OrganisationService(db).create(name='Other absence payout tenant', country_code='EE',
                                               entity_type='EE_OU', owner_email='other@example.test')
        assert client.get(f"/api/organisations/{other['id']}/payroll/absence-payouts/{created.json()['id']}").status_code == 403
    finally:
        api.dependency_overrides.clear()


def test_adding_to_existing_draft_batch_shares_one_exemption(db, ee_org):
    from payroll import PayrollService
    from payroll_absences import PayrollAbsenceService
    from payroll_absence_payouts import AbsencePayoutService

    actor = 'owner@example.test'
    employee = PayrollService(db).save_employee(ee_org['id'], actor=actor, name='Draft batch employee',
                                                personal_id='49001010018', gross_salary='2000',
                                                apply_tax_free_minimum=True)
    absences = PayrollAbsenceService(db)
    ids = []
    for start, end in (('2026-11-23','2026-11-24'), ('2026-11-26','2026-11-27')):
        absence = absences.save(ee_org['id'], employee['id'], actor=actor, absence_type='annual_leave',
                                start_date=start, end_date=end)
        ids.append(absences.set_pay_method(ee_org['id'], absence['id'], 'fixed_sum',
                                           actor=actor, fixed_amount='500')['id'])
    payouts = AbsencePayoutService(db)
    batch = payouts.create(ee_org['id'], [ids[0]], actor=actor)
    batch = payouts.add(ee_org['id'], batch['id'], [ids[1]], actor=actor)
    used = sum((Decimal(line['calculation']['tax_free_minimum']) for line in batch['lines']), Decimal(0))
    assert used == Decimal('700.00')


def test_vacation_pay_methods_return_auditable_breakdown():
    args = dict(average_daily_pay='100', leave_days=5, monthly_salary='2200',
                leave_working_days=5, norm_working_days=22)
    assert vacation_pay('average', **args)['amount'] == '500.00'
    assert vacation_pay('unchanged_salary', **args)['amount'] == '500.00'
    assert vacation_pay('best_of', **args)['method'] == 'best_of'
    assert vacation_pay('fixed_sum', **args, fixed_sum='275')['amount'] == '275.00'
    assert vacation_pay('best_of', **{**args, 'average_daily_pay': '120'})['amount'] == '600.00'


def test_fixed_sum_requires_explicit_amount():
    with pytest.raises(ValueError):
        vacation_pay('fixed_sum', average_daily_pay=0, leave_days=1)


def test_employer_sick_pay_covers_days_two_to_five_at_seventy_percent():
    result = employer_sick_benefit(Decimal('100'), date(2026, 10, 1),
                                   date(2026, 10, 1), date(2026, 10, 6))
    assert result['qualifying_days'] == 4
    assert result['amount'] == '280.00'
    assert result['health_fund_day_start'] == 6


def test_termination_compensation_and_vacation_payout_date():
    assert unused_leave_compensation(Decimal('3.5'), Decimal('40')) == Decimal('140.00')
    assert vacation_payout_date(date(2026, 10, 5)) == date(2026, 10, 2)


def test_sick_benefit_is_split_across_monthly_draft_runs_and_frozen_on_approval(db, ee_org):
    from payroll import PayrollConflict, PayrollService
    from payroll_absences import PayrollAbsenceService
    actor = 'owner@example.test'
    payroll = PayrollService(db)
    employee = payroll.save_employee(ee_org['id'], actor=actor, name='Cross-month sickness',
                                     gross_salary='2200', apply_tax_free_minimum=False)
    absence = PayrollAbsenceService(db).save(ee_org['id'], employee['id'], actor=actor,
        absence_type='sick_leave', start_date='2026-10-30', end_date='2026-11-04')
    october_run = payroll.create_run(ee_org['id'], period='2026-10', actor=actor)
    october = october_run['items'][0]
    october_component = next(c for c in october['components'] if c['preset_key'] == 'employer_sick_pay')
    assert october_component['amount'] == october_component['breakdown']['amount']
    assert october_component['breakdown']['qualifying_days'] == 1
    assert october_component['income_tax'] is True
    assert october_component['social_tax'] is False
    november = payroll.create_run(ee_org['id'], period='2026-11', actor=actor)['items'][0]
    november_component = next(c for c in november['components'] if c['preset_key'] == 'employer_sick_pay')
    assert november_component['breakdown']['qualifying_days'] == 3
    assert Decimal(october_component['amount']) + Decimal(november_component['amount']) > 0
    payroll.approve(ee_org['id'], october_run['id'], actor=actor)
    with pytest.raises(PayrollConflict, match='draft'):
        payroll.update_item(ee_org['id'], october_run['id'], october['id'], actor=actor,
                            gross_salary='2500')
    frozen = payroll.runs(ee_org['id'])
    assert next(r for r in frozen if r['period'] == '2026-10')['items'][0]['components'][0]['breakdown']


def test_termination_component_uses_opening_entitlement_and_taken_leave(db, ee_org):
    from payroll import PayrollService
    from payroll_absences import PayrollAbsenceService
    actor = 'owner@example.test'
    payroll = PayrollService(db)
    employee = payroll.save_employee(ee_org['id'], actor=actor, name='Terminating employee',
                                     gross_salary='2200', apply_tax_free_minimum=False)
    with db.transaction() as tx:
        tx.execute('UPDATE employees SET employment_end_date=? WHERE organisation_id=? AND id=?',
                   ('2026-10-15', ee_org['id'], employee['id']))
        tx.execute('INSERT INTO payroll_leave_entitlements(id,organisation_id,employee_id,effective_from,days_per_year,created_at) VALUES (?,?,?,?,?,?)',
                   ('entitlement-unit5', ee_org['id'], employee['id'], '2026-01-01', '28', '2026-01-01'))
        tx.execute('INSERT INTO payroll_leave_openings(organisation_id,employee_id,cutover_date,unused_days,source,reviewed_at,reviewed_by) VALUES (?,?,?,?,?,?,?)',
                   (ee_org['id'], employee['id'], '2025-12-31', '5', 'manual', '2026-01-01', actor))
    PayrollAbsenceService(db).save(ee_org['id'], employee['id'], actor=actor,
        absence_type='annual_leave', start_date='2026-03-02', end_date='2026-03-04')
    item = payroll.create_run(ee_org['id'], period='2026-10', actor=actor)['items'][0]
    comp = next(c for c in item['components'] if c['preset_key'] == 'unused_leave')
    assert comp['breakdown']['entitlement_days'] == '28'
    assert comp['breakdown']['opening_unused_days'] == '5'
    assert comp['breakdown']['taken_annual_leave_days'] == '3'
    assert comp['breakdown']['remaining_leave_days'] == '30'
    assert Decimal(comp['amount']) == Decimal(comp['breakdown']['average_daily_pay']) * 30
    assert comp['social_tax'] is True and comp['ui_employee'] is True
    edited = payroll.update_item(ee_org['id'], item['pay_run_id'], item['id'], actor=actor,
        components=[{'type_id': comp['type_id'], 'name': comp['name'], 'amount': '999.00',
            'direction': comp['direction'], **{key: comp[key] for key in
                ('income_tax', 'social_tax', 'ui_employee', 'ui_employer', 'funded_pension', 'social_minimum')}}])
    overridden = next(c for c in edited['items'][0]['components'] if c['preset_key'] == 'unused_leave')
    assert overridden['amount'] == '999.00'
    assert overridden['breakdown']['accountant_override'] == '999.00'
