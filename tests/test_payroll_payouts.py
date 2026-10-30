from decimal import Decimal

import pytest

from payroll import PayrollService
from payroll_payouts import PayoutConflict, PayoutService
from payroll_payday import PaydaySettingsService
from payment_orders import PaymentOrderService, PAIN_NS
from xml.etree import ElementTree as ET

ACTOR = 'owner@example.test'
IBAN = 'EE382200221020145685'


def approved_run(db, ee_org, legacy_payroll):
    run = legacy_payroll(db, ee_org['id'], name='Payout employee', gross='2000')
    PayrollService(db).approve(ee_org['id'], run['id'], actor=ACTOR)
    with db.transaction() as tx:
        tx.execute('UPDATE employees SET iban=?,bank_account_owner=? WHERE organisation_id=? AND id=?',
                   (IBAN, 'Payout employee', ee_org['id'], 'legacy-employee'))
    return PayrollService(db).runs(ee_org['id'])[0]


def bank_account(db, org_id):
    account = db.one("SELECT id FROM accounts WHERE organisation_id=? AND account_type='Asset' AND active=1 ORDER BY code LIMIT 1", (org_id,))
    assert account
    with db.transaction() as tx:
        tx.execute("INSERT INTO bank_accounts(id,organisation_id,ledger_account_id,name,currency,iban_masked,iban,bic) VALUES ('payroll-bank',?,?,?,'EUR','********5685',?,'HABAEE2X')",
                   (org_id, account['id'], 'Salary bank', 'EE382200221020145685'))
    return 'payroll-bank'


def test_partial_payout_caps_unpaid_net_and_cancellation_releases_amount(db, ee_org, legacy_payroll):
    run = approved_run(db, ee_org, legacy_payroll)
    service = PayoutService(db)
    net = Decimal(str(run['items'][0]['net']))
    first = service.create(ee_org['id'], run['id'], actor=ACTOR, amounts={'legacy-employee': str(net / 2)})
    assert Decimal(str(first['lines'][0]['amount'])) == net / 2
    summary = service.summary(ee_org['id'], run_id=run['id'])[0]
    assert Decimal(summary['paid']) == 0 and Decimal(summary['pending']) == net / 2 and Decimal(summary['unpaid']) == net / 2
    with pytest.raises(PayoutConflict, match='exceeds'):
        service.create(ee_org['id'], run['id'], actor=ACTOR, amounts={'legacy-employee': str(net)})
    service.cancel(ee_org['id'], first['id'], actor=ACTOR)
    replacement = service.create(ee_org['id'], run['id'], actor=ACTOR)
    assert Decimal(str(replacement['lines'][0]['amount'])) == net
    assert service.list(ee_org['id'], run_id=run['id'])


def test_paid_payout_posts_balanced_bank_transfer_and_reversal_on_cancel(db, ee_org, legacy_payroll):
    run = approved_run(db, ee_org, legacy_payroll)
    bank_id = bank_account(db, ee_org['id'])
    service = PayoutService(db)
    batch = service.create(ee_org['id'], run['id'], actor=ACTOR, bank_account_id=bank_id)
    assert batch['lines'][0]['iban'] == IBAN
    paid = service.mark_paid(ee_org['id'], batch['id'], bank_id, actor=ACTOR)
    summary = service.summary(ee_org['id'], run_id=run['id'])[0]
    assert Decimal(summary['paid']) == Decimal(run['items'][0]['net'])
    rows = db.rows('SELECT debit,credit FROM gl_entries WHERE organisation_id=? AND posting_batch_id=?',
                   (ee_org['id'], paid['posted_batch_id']))
    assert sum((Decimal(str(row['debit'])) for row in rows), Decimal(0)) == sum((Decimal(str(row['credit'])) for row in rows), Decimal(0))
    cancelled = service.cancel(ee_org['id'], batch['id'], actor=ACTOR)
    assert cancelled['status'] == 'Cancelled' and cancelled['reversal_batch_id']
    assert db.one('SELECT status FROM posting_batches WHERE id=?', (paid['posted_batch_id'],))['status'] == 'Reversed'


def test_salary_payout_cannot_move_an_approved_run_to_another_payment_month(db, ee_org, legacy_payroll):
    PaydaySettingsService(db).save(ee_org['id'], start_date='2026-01-01', rule_start_date='2026-01-01',
                                   rule='next_month_day', day=10, actor=ACTOR)
    run = approved_run(db, ee_org, legacy_payroll)
    with pytest.raises(PayoutConflict, match='correction'):
        PayoutService(db).create(ee_org['id'], run['id'], actor=ACTOR, payout_date='2026-10-30')
    valid = PayoutService(db).create(ee_org['id'], run['id'], actor=ACTOR, payout_date='2026-11-10')
    assert valid['payout_date'] == '2026-11-10'


def test_payout_routes_enforce_tenant_role_and_csrf(db, ee_org, legacy_payroll, monkeypatch):
    from fastapi.testclient import TestClient
    from api_app import api, current_user, User
    from web_app import app
    monkeypatch.setenv('FASTACCOUNTS_DB', db.path)
    monkeypatch.setenv('DB_URL', '')
    run = approved_run(db, ee_org, legacy_payroll)
    base = f"/organisations/{ee_org['id']}"
    api.dependency_overrides[current_user] = lambda: User(email=ACTOR)
    client = TestClient(app)
    try:
        token = client.get('/api/csrf').json()['csrf_token']
        body = {'payout_type': 'salary'}
        assert client.post(f"/api{base}/pay-runs/{run['id']}/payouts", json=body).status_code == 403
        created = client.post(f"/api{base}/pay-runs/{run['id']}/payouts", json=body,
                              headers={'X-CSRF-Token': token})
        assert created.status_code == 201, created.text
        summary = client.get(f"/api{base}/payroll/payouts/summary?run_id={run['id']}")
        assert summary.status_code == 200 and summary.json()[0]['pending'] == run['total_net']
        assert 'iban' not in summary.json()[0]['employees'][0]
        other = __import__('organisations').OrganisationService(db).create(
            name='Other payout tenant', country_code='EE', entity_type='EE_OU', owner_email='other@example.test')
        assert client.get(f"/api/organisations/{other['id']}/payroll/payouts/{created.json()['id']}").status_code == 403
    finally:
        api.dependency_overrides.clear()


def test_salary_payout_pain001_contains_frozen_payments_and_control_totals(db, ee_org, legacy_payroll):
    run = approved_run(db, ee_org, legacy_payroll)
    bank_id = bank_account(db, ee_org['id'])
    batch = PayoutService(db).create(ee_org['id'], run['id'], actor=ACTOR, bank_account_id=bank_id)
    content = PaymentOrderService(db).payroll_payout_xml(ee_org['id'], batch['id'])
    root = ET.fromstring(content)
    ns = {'p': PAIN_NS}
    assert root.tag == f'{{{PAIN_NS}}}Document'
    assert root.findtext('.//p:GrpHdr/p:NbOfTxs', namespaces=ns) == '1'
    assert root.findtext('.//p:GrpHdr/p:CtrlSum', namespaces=ns) == run['items'][0]['net']
    assert root.findtext('.//p:DbtrAgt/p:FinInstnId/p:BIC', namespaces=ns) == 'HABAEE2X'
    assert root.findtext('.//p:DbtrAcct/p:Id/p:IBAN', namespaces=ns) == 'EE382200221020145685'
    assert root.findtext('.//p:CdtTrfTxInf/p:PmtId/p:EndToEndId', namespaces=ns) == batch['lines'][0]['id'].replace('-', '')
    assert root.findtext('.//p:CdtTrfTxInf/p:RmtInf/p:Ustrd', namespaces=ns) == 'oktoober 2026 töötasu'


@pytest.mark.parametrize('iban', [None, 'EE00'])
def test_pain001_refuses_missing_or_invalid_employee_ibans(db, ee_org, legacy_payroll, iban):
    run = approved_run(db, ee_org, legacy_payroll)
    bank_id = bank_account(db, ee_org['id'])
    batch = PayoutService(db).create(ee_org['id'], run['id'], actor=ACTOR, bank_account_id=bank_id)
    with db.transaction() as tx:
        tx.execute('UPDATE payroll_payout_lines SET iban=? WHERE organisation_id=? AND payout_batch_id=?',
                   (iban, ee_org['id'], batch['id']))
    with pytest.raises(ValueError, match='Payout employee'):
        PaymentOrderService(db).payroll_payout_xml(ee_org['id'], batch['id'])
