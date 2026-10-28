"""Tenant-scoped persistence for employee tax elections."""
import json


def employee(tx, organisation_id, employee_id, *, lock=True):
    # Shared serialisation point with payroll creation and employee writes.
    if lock:
        tx.execute('UPDATE employees SET active=active WHERE organisation_id=? AND id=?',
                   (organisation_id, employee_id))
    row = tx.one('SELECT * FROM employees WHERE organisation_id=? AND id=?', (organisation_id, employee_id))
    if not row:
        raise KeyError('Employee not found')
    return row


def histories(tx, organisation_id, employee_id):
    return tx.rows('SELECT * FROM employee_tax_settings WHERE organisation_id=? AND employee_id=? '
                   'ORDER BY kind,start_date,id', (organisation_id, employee_id))


def frozen(tx, organisation_id, setting_id):
    return bool(tx.one("SELECT c.item_id FROM pay_item_context c JOIN pay_run_items i "
                       "ON i.organisation_id=c.organisation_id AND i.id=c.item_id "
                       "JOIN pay_runs r ON r.organisation_id=i.organisation_id AND r.id=i.pay_run_id "
                       "WHERE c.organisation_id=? AND r.status='Approved' AND "
                       "(c.tax_free_setting_id=? OR c.pension_setting_id=? OR c.unemployment_setting_id=?)",
                       (organisation_id, setting_id, setting_id, setting_id)))


def save(tx, row):
    fields = ('id', 'organisation_id', 'employee_id', 'kind', 'start_date', 'mode', 'amount', 'rate', 'applies')
    tx.execute('INSERT INTO employee_tax_settings(' + ','.join(fields) + ') VALUES (' +
               ','.join('?' for _ in fields) + ') ON CONFLICT(organisation_id,id) DO UPDATE SET '
               'start_date=excluded.start_date,mode=excluded.mode,amount=excluded.amount,'
               'rate=excluded.rate,applies=excluded.applies', tuple(row.get(f) for f in fields))


def delete(tx, organisation_id, setting_id):
    tx.execute('DELETE FROM employee_tax_settings WHERE organisation_id=? AND id=?',
               (organisation_id, setting_id))


def monthly_exemption_used(tx, organisation_id, employee_id, payment_month):
    """Sum exemption frozen in approved items paid in the same calendar month."""
    from datetime import date
    from core_utils import decimal
    from payroll_rules import settlement_date
    year, month = map(int, payment_month.split('-'))
    start = date(year, month, 1)
    next_month = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    rows = tx.rows("SELECT i.tax_free_minimum,r.period,COALESCE((SELECT b.payout_date FROM payroll_payout_batches b "
                   "WHERE b.organisation_id=r.organisation_id AND b.pay_run_id=r.id AND b.payout_type='salary' "
                   "AND b.status!='Cancelled' ORDER BY b.payout_date,b.id LIMIT 1),r.settlement_date) payment_date FROM pay_run_items i "
                   "JOIN pay_runs r ON r.organisation_id=i.organisation_id AND r.id=i.pay_run_id "
                   "WHERE i.organisation_id=? AND i.employee_id=? AND r.status='Approved'",
                   (organisation_id, employee_id))
    used = decimal('0')
    for row in rows:
        paid_on = date.fromisoformat(row['payment_date']) if row['payment_date'] else settlement_date(row['period'])
        if start <= paid_on < next_month:
            used += decimal(row['tax_free_minimum'])
    absence_rows = tx.rows("SELECT p.calculation_json FROM payroll_absence_pay p "
                            "JOIN payroll_absence_payout_batches b ON b.organisation_id=p.organisation_id AND b.id=p.absence_payout_batch_id "
                            "WHERE p.organisation_id=? AND p.employee_id=? AND p.status IN ('in_payout','paid') AND b.status IN ('Approved','Paid') "
                            "AND substr(b.payout_date,1,7)=?", (organisation_id, employee_id, payment_month))
    for row in absence_rows:
        used += decimal(json.loads(row['calculation_json']).get('tax_free_minimum', '0'))
    return used
