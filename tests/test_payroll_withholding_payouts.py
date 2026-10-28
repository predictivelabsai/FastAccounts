from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest

from payment_orders import PAIN_NS, PaymentOrderService
from payroll import PayrollService
from payroll_payouts import PayoutConflict, PayoutService
from payroll_withholdings import PayrollWithholdingService


ACTOR = 'owner@example.test'
IBAN = 'EE382200221020145685'


def bank_account(db, org_id):
    account = db.one("SELECT id FROM accounts WHERE organisation_id=? AND account_type='Asset' AND active=1 ORDER BY code LIMIT 1", (org_id,))
    with db.transaction() as tx:
        tx.execute("INSERT INTO bank_accounts(id,organisation_id,ledger_account_id,name,currency,iban_masked,iban,bic) VALUES ('withholding-bank',?,?,?,'EUR','********5685',?,'HABAEE2X')",
                   (org_id, account['id'], 'Payroll bank', IBAN))
    return 'withholding-bank'


def approved_run(db, ee_org):
    payroll = PayrollService(db)
    service = PayrollWithholdingService(db)
    recipient = service.save_recipient(ee_org['id'], actor=ACTOR, name='Court office',
        registry_code='court-001', iban=IBAN, reference_number='REF-77', default_description='Order payment')
    for name, amount in [('First employee', '25'), ('Second employee', '35')]:
        employee = payroll.save_employee(ee_org['id'], actor=ACTOR, name=name, gross_salary='2000')
        service.save_agreement(ee_org['id'], actor=ACTOR, employee_id=employee['id'], recipient_id=recipient['id'],
            component_type='bailiff', method='fixed_sum', start_date='2026-01-01', monthly_amount=amount,
            payment_description='Enforcement order')
    run = payroll.create_run(ee_org['id'], period='2026-10', actor=ACTOR)
    payroll.approve(ee_org['id'], run['id'], actor=ACTOR)
    return run, recipient


def test_withholding_payout_aggregates_recipient_and_applies_partial_cap(db, ee_org):
    run, recipient = approved_run(db, ee_org)
    service = PayoutService(db)
    batch = service.create(ee_org['id'], run['id'], actor=ACTOR, payout_type='withholding')
    assert len(batch['withholding_lines']) == 1
    line = batch['withholding_lines'][0]
    assert line['recipient_id'] == recipient['id']
    assert Decimal(str(line['amount'])) == Decimal('60.00')
    assert line['iban'] == IBAN
    assert line['description'] == 'First employee: Enforcement order; Second employee: Enforcement order'
    with pytest.raises(PayoutConflict, match='exceeds'):
        service.create(ee_org['id'], run['id'], actor=ACTOR, payout_type='withholding', amounts={recipient['id']: '60.01'})
    service.cancel(ee_org['id'], batch['id'], actor=ACTOR)
    partial = service.create(ee_org['id'], run['id'], actor=ACTOR, payout_type='withholding', amounts={recipient['id']: '20'})
    rest = service.create(ee_org['id'], run['id'], actor=ACTOR, payout_type='withholding')
    assert Decimal(str(partial['withholding_lines'][0]['amount'])) == Decimal('20.00')
    assert Decimal(str(rest['withholding_lines'][0]['amount'])) == Decimal('40.00')


def test_withholding_payout_posts_liability_and_reverses_on_cancel(db, ee_org):
    run, _ = approved_run(db, ee_org)
    bank_id = bank_account(db, ee_org['id'])
    service = PayoutService(db)
    batch = service.create(ee_org['id'], run['id'], actor=ACTOR, payout_type='withholding', bank_account_id=bank_id)
    paid = service.mark_paid(ee_org['id'], batch['id'], bank_id, actor=ACTOR)
    rows = db.rows('SELECT a.system_role,g.debit,g.credit FROM gl_entries g JOIN accounts a ON a.organisation_id=g.organisation_id AND a.id=g.account_id WHERE g.organisation_id=? AND g.posting_batch_id=?',
                   (ee_org['id'], paid['posted_batch_id']))
    assert sum((Decimal(str(row['debit'])) for row in rows), Decimal(0)) == Decimal('60.00')
    assert sum((Decimal(str(row['credit'])) for row in rows), Decimal(0)) == Decimal('60.00')
    assert any(row['system_role'] == 'PAYROLL_BAILIFF' and Decimal(str(row['debit'])) == Decimal('60.00') for row in rows)
    cancelled = service.cancel(ee_org['id'], batch['id'], actor=ACTOR)
    assert cancelled['reversal_batch_id']


def test_withholding_pain001_uses_recipient_iban_and_references(db, ee_org):
    run, _ = approved_run(db, ee_org)
    bank_id = bank_account(db, ee_org['id'])
    batch = PayoutService(db).create(ee_org['id'], run['id'], actor=ACTOR,
        payout_type='withholding', bank_account_id=bank_id)
    root = ET.fromstring(PaymentOrderService(db).payroll_payout_xml(ee_org['id'], batch['id']))
    ns = {'p': PAIN_NS}
    assert root.findtext('.//p:GrpHdr/p:NbOfTxs', namespaces=ns) == '1'
    assert root.findtext('.//p:GrpHdr/p:CtrlSum', namespaces=ns) == '60.00'
    assert root.findtext('.//p:CdtTrfTxInf/p:Cdtr/p:Nm', namespaces=ns) == 'Court office'
    assert root.findtext('.//p:CdtTrfTxInf/p:CdtrAcct/p:Id/p:IBAN', namespaces=ns) == IBAN
    assert root.findtext('.//p:CdtTrfTxInf/p:RmtInf/p:Ustrd', namespaces=ns) == 'First employee: Enforcement order; Second employee: Enforcement order'
