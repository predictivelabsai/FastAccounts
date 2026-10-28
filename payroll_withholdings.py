"""Tenant-scoped payroll withholding registers and Decimal rule helpers."""
from datetime import date
from decimal import Decimal
import re

from core_utils import audit, db_number, money, new_id, utc_now
from payment_orders import PaymentOrderService

COMPONENT_TYPES = {'alimony', 'bailiff', 'union_fee', 'agreed_deduction', 'third_pillar'}
METHODS = {'fixed_sum', 'percent_of_gross', 'sum_x_qty', 'third_pillar_net'}
THIRD_PILLAR_ANNUAL_RATE = Decimal('0.15')
THIRD_PILLAR_ANNUAL_CAP = Decimal('6000.00')


def normalise_iban(value):
    result = re.sub(r'\s+', '', value or '').upper()
    if not PaymentOrderService._valid_iban(result):
        raise ValueError('Enter a valid IBAN')
    return result


def calculate_withholding(agreement, *, gross, net, withheld_to_date=0,
                          available_net=None, garnishable=None):
    """Calculate one monthly withholding, returning an exact cent Decimal."""
    gross, net = money(gross), money(net)
    amount = Decimal('0.00')
    method = agreement['method']
    if method == 'fixed_sum':
        amount = money(agreement.get('monthly_amount') or 0)
    elif method == 'percent_of_gross':
        amount = money(gross * Decimal(str(agreement.get('percentage') or 0)) / 100)
    elif method == 'sum_x_qty':
        amount = money(Decimal(str(agreement.get('rate') or 0)) * Decimal(str(agreement.get('quantity') or 0)))
    elif method == 'third_pillar_net':
        amount = money(agreement.get('monthly_amount') or 0)
    else:
        raise ValueError('Unknown withholding method')
    if agreement.get('component_type') == 'third_pillar':
        amount = min(amount, money(gross * THIRD_PILLAR_ANNUAL_RATE))
    cap = agreement.get('total_cap')
    if cap is not None:
        amount = min(amount, max(Decimal('0.00'), money(Decimal(str(cap)) - money(withheld_to_date))))
    if garnishable is not None:
        amount = min(amount, money(garnishable))
    amount = min(amount, max(Decimal('0.00'), money(available_net if available_net is not None else net)))
    return max(Decimal('0.00'), amount)


class PayrollWithholdingService:
    def __init__(self, db):
        self.db = db

    def recipients(self, organisation_id):
        return self.db.rows('SELECT * FROM payroll_withholding_recipients WHERE organisation_id=? ORDER BY name,id', (organisation_id,))

    def save_recipient(self, organisation_id, *, actor, recipient_id=None, name,
                       registry_code, iban, reference_number=None, default_description=''):
        name, registry_code = name.strip(), registry_code.strip()
        if not name or not registry_code:
            raise ValueError('Recipient name and registry or personal code are required')
        iban = normalise_iban(iban)
        with self.db.transaction() as tx:
            if not tx.one('SELECT id FROM organisations WHERE id=?', (organisation_id,)):
                raise KeyError('Organisation not found')
            now = utc_now()
            if recipient_id:
                result = tx.execute('UPDATE payroll_withholding_recipients SET name=?,registry_code=?,iban=?,reference_number=?,default_description=?,updated_at=? WHERE organisation_id=? AND id=?',
                    (name, registry_code, iban, reference_number, default_description, now, organisation_id, recipient_id))
                if result.rowcount != 1:
                    raise KeyError('Withholding recipient not found')
            else:
                recipient_id = new_id()
                tx.execute('INSERT INTO payroll_withholding_recipients(id,organisation_id,name,registry_code,iban,reference_number,default_description,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)',
                    (recipient_id, organisation_id, name, registry_code, iban, reference_number, default_description, now, now))
            audit(tx, organisation_id, actor, 'payroll.withholding_recipient.saved', 'payroll_withholding_recipient', recipient_id)
            return tx.one('SELECT * FROM payroll_withholding_recipients WHERE organisation_id=? AND id=?', (organisation_id, recipient_id))

    def delete_recipient(self, organisation_id, recipient_id, *, actor):
        with self.db.transaction() as tx:
            result = tx.execute('UPDATE payroll_withholding_recipients SET active=0,updated_at=? WHERE organisation_id=? AND id=?',
                                (utc_now(), organisation_id, recipient_id))
            if result.rowcount != 1:
                raise KeyError('Withholding recipient not found')
            audit(tx, organisation_id, actor, 'payroll.withholding_recipient.archived', 'payroll_withholding_recipient', recipient_id)

    def agreements(self, organisation_id, *, employee_id=None):
        query = ('SELECT a.*,e.name employee_name,r.name recipient_name FROM payroll_withholding_agreements a '
                 'JOIN employees e ON e.organisation_id=a.organisation_id AND e.id=a.employee_id '
                 'JOIN payroll_withholding_recipients r ON r.organisation_id=a.organisation_id AND r.id=a.recipient_id '
                 'WHERE a.organisation_id=?')
        params = [organisation_id]
        if employee_id:
            query += ' AND a.employee_id=?'
            params.append(employee_id)
        return self.db.rows(query + ' ORDER BY e.name,a.start_date,a.id', params)

    def save_agreement(self, organisation_id, *, actor, agreement_id=None, **data):
        required = ('employee_id', 'recipient_id', 'component_type', 'method', 'start_date')
        if any(not data.get(key) for key in required) or data['component_type'] not in COMPONENT_TYPES or data['method'] not in METHODS:
            raise ValueError('Choose a valid employee, recipient, withholding type, method and start date')
        if data.get('end_date') and data['end_date'] < data['start_date']:
            raise ValueError('End date must be on or after start date')
        if data['method'] == 'fixed_sum' and (data.get('monthly_amount') is None or Decimal(str(data['monthly_amount'])) <= 0):
            raise ValueError('Fixed sum needs a positive monthly amount')
        if data['method'] == 'percent_of_gross' and not (Decimal('0') < Decimal(str(data.get('percentage') or 0)) <= Decimal('100')):
            raise ValueError('Percentage must be greater than 0 and at most 100')
        with self.db.transaction() as tx:
            if not tx.one('SELECT id FROM employees WHERE organisation_id=? AND id=?', (organisation_id, data['employee_id'])):
                raise KeyError('Employee not found')
            if not tx.one('SELECT id FROM payroll_withholding_recipients WHERE organisation_id=? AND id=? AND active=1', (organisation_id, data['recipient_id'])):
                raise KeyError('Withholding recipient not found')
            now = utc_now()
            fields = ('employee_id','recipient_id','component_type','method','start_date','end_date','monthly_amount','percentage','quantity','rate','total_cap','payment_description')
            values = [data.get(key, '') if key == 'payment_description' else data.get(key) for key in fields]
            if agreement_id:
                update = ','.join(key + '=?' for key in fields)
                result = tx.execute('UPDATE payroll_withholding_agreements SET '+update+',updated_at=? WHERE organisation_id=? AND id=?', (*values,now,organisation_id,agreement_id))
                if result.rowcount != 1:
                    raise KeyError('Withholding agreement not found')
            else:
                agreement_id = new_id()
                tx.execute('INSERT INTO payroll_withholding_agreements(id,organisation_id,'+','.join(fields)+',created_at,updated_at) VALUES ('+','.join('?' for _ in range(len(fields)+4))+')',
                    (agreement_id,organisation_id,*values,now,now))
            audit(tx, organisation_id, actor, 'payroll.withholding_agreement.saved', 'payroll_withholding_agreement', agreement_id)
            return tx.one('SELECT * FROM payroll_withholding_agreements WHERE organisation_id=? AND id=?', (organisation_id,agreement_id))

    def delete_agreement(self, organisation_id, agreement_id, *, actor):
        with self.db.transaction() as tx:
            result = tx.execute('UPDATE payroll_withholding_agreements SET active=0,updated_at=? WHERE organisation_id=? AND id=?',
                                (utc_now(),organisation_id,agreement_id))
            if result.rowcount != 1:
                raise KeyError('Withholding agreement not found')
            audit(tx, organisation_id, actor, 'payroll.withholding_agreement.archived', 'payroll_withholding_agreement', agreement_id)

    def report(self, organisation_id, *, start, end):
        return self.db.rows('SELECT e.name employee_name,r.name recipient_name,l.component_type,SUM(l.amount) amount '
            'FROM payroll_withholding_run_lines l JOIN pay_runs p ON p.organisation_id=l.organisation_id AND p.id=l.pay_run_id '
            'JOIN employees e ON e.organisation_id=l.organisation_id AND e.id=l.employee_id '
            'JOIN payroll_withholding_recipients r ON r.organisation_id=l.organisation_id AND r.id=l.recipient_id '
            'WHERE l.organisation_id=? AND p.period>=? AND p.period<=? GROUP BY e.name,r.name,l.component_type ORDER BY e.name,r.name,l.component_type',
            (organisation_id,start,end))
