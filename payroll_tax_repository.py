"""Tenant-scoped persistence for employee tax elections."""


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
    rows = tx.rows("SELECT i.tax_free_minimum,r.period,r.settlement_date FROM pay_run_items i "
                   "JOIN pay_runs r ON r.organisation_id=i.organisation_id AND r.id=i.pay_run_id "
                   "WHERE i.organisation_id=? AND i.employee_id=? AND r.status='Approved'",
                   (organisation_id, employee_id))
    used = decimal('0')
    for row in rows:
        paid_on = date.fromisoformat(row['settlement_date']) if row['settlement_date'] else settlement_date(row['period'])
        if start <= paid_on < next_month:
            used += decimal(row['tax_free_minimum'])
    return used
