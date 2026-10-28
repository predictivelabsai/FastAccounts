from datetime import date
from decimal import Decimal

import pytest

from payroll_rules import remaining_monthly_exemption, settlement_date
from payroll import PayrollService
from payroll_tax_repository import monthly_exemption_used


def test_settlement_date_priority_and_month_end_fallback():
    assert settlement_date('2026-10', '2026-11-05', '2026-11-10') == date(2026, 11, 5)
    assert settlement_date('2026-10', payday_rule_date='2026-11-10') == date(2026, 11, 10)
    assert settlement_date('2026-10') == date(2026, 10, 31)


@pytest.mark.parametrize(('mode', 'amount', 'used', 'expected'), [
    ('maximum', None, Decimal('250'), Decimal('450')),
    ('limited', Decimal('300'), Decimal('250'), Decimal('50')),
    ('limited', Decimal('300'), Decimal('350'), Decimal('0')),
    ('none', None, Decimal('0'), Decimal('0')),
])
def test_payment_month_exemption_remaining(mode, amount, used, expected):
    assert remaining_monthly_exemption(mode, amount, Decimal('700'), used) == expected


def test_invalid_exemption_application_fails():
    with pytest.raises(ValueError):
        remaining_monthly_exemption('limited', None, Decimal('700'), Decimal('0'))


def test_exemption_repository_sums_frozen_items_across_payment_month(db, ee_org, legacy_payroll):
    first = legacy_payroll(db, ee_org['id'], name='Shared month employee', gross='2000')
    PayrollService(db).approve(ee_org['id'], first['id'], actor='owner@example.test')
    with db.transaction() as tx:
        tx.execute("UPDATE pay_runs SET settlement_date='2026-10-12' WHERE organisation_id=? AND id=?", (ee_org['id'], first['id']))
        tx.execute("UPDATE pay_run_items SET tax_free_minimum=250 WHERE organisation_id=? AND pay_run_id=?", (ee_org['id'], first['id']))
        run = tx.one('SELECT * FROM pay_runs WHERE organisation_id=? AND id=?', (ee_org['id'], first['id']))
        tx.execute("INSERT INTO pay_runs(id,organisation_id,period,status,total_gross,total_net,total_employer_cost,created_by,created_at,approved_at,settlement_date) VALUES ('second-run',?,'2026-09','Approved',0,0,0,'owner@example.test','2026-09-30','2026-10-01','2026-10-20')", (ee_org['id'],))
        item = tx.one('SELECT * FROM pay_run_items WHERE organisation_id=? AND pay_run_id=?', (ee_org['id'], first['id']))
        item['id'], item['pay_run_id'], item['employee_name'] = 'second-item', 'second-run', 'Shared month employee'
        fields = list(item)
        tx.execute('INSERT INTO pay_run_items('+','.join(fields)+') VALUES ('+','.join('?' for _ in fields)+')', tuple(item[field] for field in fields))
        tx.execute("UPDATE pay_run_items SET tax_free_minimum=250 WHERE organisation_id=? AND id='second-item'", (ee_org['id'],))
        assert run['status'] == 'Approved'
        used = monthly_exemption_used(tx, ee_org['id'], 'legacy-employee', '2026-10')
    assert used == Decimal('500')
    assert remaining_monthly_exemption('maximum', None, Decimal('700'), used) == Decimal('200')
