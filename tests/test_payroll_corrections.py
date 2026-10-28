from decimal import Decimal
import pytest

from ledger import LedgerService
from organisations import OrganisationService
from payroll import PayrollService

ACTOR = 'owner@example.test'


def _approved(service, org):
    employee = service.save_employee(org['id'], actor=ACTOR, name='Correction employee',
                                    gross_salary='2000', personal_id='49001010018')
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


def test_positive_correction_delta_is_paid_as_separate_salary_payout(db, ee_org):
    from payroll_payouts import PayoutConflict, PayoutService

    service = PayrollService(db)
    _, original = _approved(service, ee_org)
    correction = service.create_correction(ee_org['id'], original['id'], actor=ACTOR)
    corrected = service.update_item(ee_org['id'], correction['id'], correction['items'][0]['id'],
                                    actor=ACTOR, gross_salary='2500')
    approved = service.approve(ee_org['id'], correction['id'], actor=ACTOR)
    delta = Decimal(str(approved['items'][0]['net'])) - Decimal(str(original['items'][0]['net']))
    half_delta = (delta / 2).quantize(Decimal('0.01'))
    payout = PayoutService(db).create(ee_org['id'], approved['id'], actor=ACTOR, payout_date='2026-11-20',
                                      amounts={approved['items'][0]['employee_id']: str(half_delta)})
    assert payout['pay_run_id'] == approved['id']
    assert payout['payout_date'] == '2026-11-20'
    assert Decimal(str(payout['lines'][0]['amount'])) == half_delta
    assert delta > 0
    with pytest.raises(PayoutConflict, match='exceeds'):
        PayoutService(db).create(ee_org['id'], approved['id'], actor=ACTOR,
                                 amounts={approved['items'][0]['employee_id']: str(delta)})


def test_later_month_positive_correction_uses_payment_month_allowance(db, ee_org):
    from payroll_payouts import PayoutService

    service = PayrollService(db)
    employee = service.save_employee(ee_org['id'], actor=ACTOR, name='Tax-free correction employee',
        gross_salary='2000', personal_id='49001010026', apply_tax_free_minimum=True)
    original = service.approve(ee_org['id'], service.create_run(ee_org['id'], period='2026-10', actor=ACTOR)['id'], actor=ACTOR)
    correction = service.create_correction(ee_org['id'], original['id'], actor=ACTOR)
    service.update_item(ee_org['id'], correction['id'], correction['items'][0]['id'],
                        actor=ACTOR, gross_salary='2500')
    approved = service.approve(ee_org['id'], correction['id'], actor=ACTOR)
    payout = PayoutService(db).create(ee_org['id'], approved['id'], actor=ACTOR,
        payout_date='2026-11-20')
    assert Decimal(str(payout['lines'][0]['amount'])) == Decimal('482.00')
    tsd_line = db.one('SELECT * FROM payroll_payout_tsd_lines WHERE organisation_id=? AND payout_batch_id=?',
                      (ee_org['id'], payout['id']))
    assert Decimal(tsd_line['exemption_610']) == Decimal('482.00')
    assert Decimal(tsd_line['income_tax']) == Decimal('0.00')
    assert Decimal(str(approved['items'][0]['payout_net_delta'])) != Decimal('482.00')
    adjustment = db.one("SELECT id FROM posting_batches WHERE organisation_id=? AND voucher_type='payroll_correction_tax_adjustment' AND voucher_id=?",
                        (ee_org['id'], payout['id']))
    assert adjustment
    lines = db.rows('SELECT debit,credit FROM gl_entries WHERE organisation_id=? AND posting_batch_id=?',
                    (ee_org['id'], adjustment['id']))
    assert sum((Decimal(line['debit']) for line in lines), Decimal(0)) == sum(
        (Decimal(line['credit']) for line in lines), Decimal(0))


def test_later_month_negative_correction_amends_original_month(db, ee_org):
    from payroll_payouts import PayoutService
    from tsd import TSDExportService

    service = PayrollService(db)
    service.save_employee(ee_org['id'], actor=ACTOR, name='Negative tax-free correction employee',
        gross_salary='2000', personal_id='49001010034', apply_tax_free_minimum=True)
    original = service.approve(ee_org['id'], service.create_run(ee_org['id'], period='2026-10', actor=ACTOR)['id'], actor=ACTOR)
    correction = service.create_correction(ee_org['id'], original['id'], actor=ACTOR)
    service.update_item(ee_org['id'], correction['id'], correction['items'][0]['id'],
                        actor=ACTOR, gross_salary='1800')
    approved = service.approve(ee_org['id'], correction['id'], actor=ACTOR)
    with pytest.raises(ValueError, match='No unpaid net remains'):
        PayoutService(db).create(ee_org['id'], approved['id'], actor=ACTOR, payout_date='2026-11-20')
    with db.transaction() as tx:
        workpaper = TSDExportService(db)._workpaper(tx, ee_org['id'], original['id'])
    assert workpaper['totals']['gross_amount'] == Decimal('1800.00')


def test_negative_correction_creates_receivable_and_next_payout_offsets_it(db, ee_org):
    from payroll_payouts import PayoutService

    service = PayrollService(db)
    employee, original = _approved(service, ee_org)
    correction = service.create_correction(ee_org['id'], original['id'], actor=ACTOR)
    service.update_item(ee_org['id'], correction['id'], correction['items'][0]['id'],
                        actor=ACTOR, gross_salary='1800')
    approved = service.approve(ee_org['id'], correction['id'], actor=ACTOR)
    receivable = PayoutService(db).open_receivables(ee_org['id'])
    assert len(receivable) == 1 and receivable[0]['employee_id'] == employee['id']
    assert Decimal(receivable[0]['remaining_amount']) == Decimal(receivable[0]['amount'])
    from tsd import TSDExportService
    with db.transaction() as tx:
        workpaper = TSDExportService(db)._workpaper(tx, ee_org['id'], original['id'])
    assert workpaper['totals']['gross_amount'] == Decimal('1800.00')
    gl = db.rows('SELECT a.system_role,g.debit,g.credit FROM gl_entries g JOIN accounts a '
                 'ON a.organisation_id=g.organisation_id AND a.id=g.account_id WHERE g.organisation_id=? '
                 'AND g.posting_batch_id=(SELECT id FROM posting_batches WHERE organisation_id=? AND voucher_id=?)',
                 (ee_org['id'], ee_org['id'], receivable[0]['id']))
    assert [(row['system_role'], Decimal(row['debit']), Decimal(row['credit'])) for row in gl] == [
        ('PAYROLL_EMPLOYEE_RECEIVABLE', Decimal(receivable[0]['amount']), Decimal(0)),
        ('PAYROLL_SALARY_PAYABLE', Decimal(0), Decimal(receivable[0]['amount']))]

    next_run = service.approve(ee_org['id'], service.create_run(ee_org['id'], period='2026-11', actor=ACTOR)['id'], actor=ACTOR)
    payout_service = PayoutService(db)
    payout = payout_service.create(ee_org['id'], next_run['id'], actor=ACTOR)
    proposed = payout['offsets']
    assert proposed and proposed[0]['status'] == 'Proposed'
    before = Decimal(str(payout['lines'][0]['amount']))
    paid_amount = Decimal(str(proposed[0]['amount']))
    confirmed = payout_service.confirm_offsets(ee_org['id'], payout['id'], actor=ACTOR)
    assert Decimal(str(confirmed['lines'][0]['amount'])) == max(Decimal(0), before - paid_amount)
    assert payout_service.open_receivables(ee_org['id']) == []
    assert all(Decimal(line['amount']) >= 0 for line in confirmed['lines'])
    bank_ledger = db.one("SELECT id FROM accounts WHERE organisation_id=? AND account_type='Asset' AND active=1 ORDER BY code LIMIT 1",
                         (ee_org['id'],))
    with db.transaction() as tx:
        tx.execute("UPDATE employees SET iban='EE382200221020145685',bank_account_owner=? WHERE organisation_id=? AND id=?",
                   (employee['name'], ee_org['id'], employee['id']))
        tx.execute("INSERT INTO bank_accounts(id,organisation_id,ledger_account_id,name,currency,iban_masked,iban,bic) "
                   "VALUES ('correction-bank',?,?,?,'EUR','********5685','EE382200221020145685','HABAEE2X')",
                   (ee_org['id'], bank_ledger['id'], 'Correction bank'))
    paid = payout_service.mark_paid(ee_org['id'], payout['id'], 'correction-bank', actor=ACTOR)
    if paid['posted_batch_id']:
        bank_lines = db.rows("SELECT g.debit,g.credit FROM gl_entries g JOIN bank_accounts b "
                             "ON b.organisation_id=g.organisation_id AND b.ledger_account_id=g.account_id "
                             "WHERE g.organisation_id=? AND g.posting_batch_id=?",
                             (ee_org['id'], paid['posted_batch_id']))
        assert all(Decimal(line['debit']) >= 0 and Decimal(line['credit']) >= 0 for line in bank_lines)
    assert approved['status'] == 'Approved'


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
    approved = service.approve(ee_org['id'], supplementary['id'], actor=ACTOR)
    from payroll_payouts import PayoutService
    payout = PayoutService(db).create(ee_org['id'], approved['id'], actor=ACTOR)
    assert payout['pay_run_id'] == supplementary['id']
    assert Decimal(str(payout['lines'][0]['amount'])) == Decimal(str(approved['items'][0]['net']))


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
    receivables_url = f"/organisations/{ee_org['id']}/payroll/receivables"
    assert client.get(receivables_url).status_code == 401
    assert client.get(receivables_url, headers=owner).status_code == 200
    assert client.get(receivables_url, headers={'X-Test-User': 'intruder@example.test'}).status_code == 403
    for path in (f"/organisations/{{organisation_id}}/pay-runs/{{run_id}}/corrections",
                 f"/organisations/{{organisation_id}}/pay-runs/{{run_id}}/supplementary",
                 "/organisations/{organisation_id}/payroll/payouts/{payout_id}/confirm-offsets"):
        route = next(route for route in api.routes if getattr(route, 'path', None) == path)
        assert any(dependency.call is require_csrf for dependency in route.dependant.dependencies)
