from decimal import Decimal

import pytest

from payroll import PayrollService
from payroll_payouts import PayoutConflict, PayoutService

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
        tx.execute("INSERT INTO bank_accounts(id,organisation_id,ledger_account_id,name,currency,iban_masked) VALUES ('payroll-bank',?,?,?,'EUR','********5685')",
                   (org_id, account['id'], 'Salary bank'))
    return 'payroll-bank'


def test_partial_payout_caps_unpaid_net_and_cancellation_releases_amount(db, ee_org, legacy_payroll):
    run = approved_run(db, ee_org, legacy_payroll)
    service = PayoutService(db)
    net = Decimal(str(run['items'][0]['net']))
    first = service.create(ee_org['id'], run['id'], actor=ACTOR, amounts={'legacy-employee': str(net / 2)})
    assert Decimal(str(first['lines'][0]['amount'])) == net / 2
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
    rows = db.rows('SELECT debit,credit FROM gl_entries WHERE organisation_id=? AND posting_batch_id=?',
                   (ee_org['id'], paid['posted_batch_id']))
    assert sum((Decimal(str(row['debit'])) for row in rows), Decimal(0)) == sum((Decimal(str(row['credit'])) for row in rows), Decimal(0))
    cancelled = service.cancel(ee_org['id'], batch['id'], actor=ACTOR)
    assert cancelled['status'] == 'Cancelled' and cancelled['reversal_batch_id']
    assert db.one('SELECT status FROM posting_batches WHERE id=?', (paid['posted_batch_id'],))['status'] == 'Reversed'
