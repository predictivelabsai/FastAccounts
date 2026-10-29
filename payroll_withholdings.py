"""Tenant-scoped payroll withholding registers and Decimal rule helpers."""
from datetime import date
from decimal import Decimal
import re

from core_utils import audit, db_number, decimal, money, new_id, utc_now
from payment_orders import PaymentOrderService
from payroll_rules import garnishable_amount, rules_for

COMPONENT_TYPES = {'alimony', 'bailiff', 'union_fee', 'agreed_deduction', 'third_pillar'}
METHODS = {'fixed_sum', 'percent_of_gross', 'sum_x_qty', 'third_pillar_net'}


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
        rows = self.db.rows('SELECT e.name employee_name,r.name recipient_name,l.component_type,SUM(l.amount) amount '
            'FROM payroll_withholding_run_lines l JOIN pay_runs p ON p.organisation_id=l.organisation_id AND p.id=l.pay_run_id '
            'JOIN employees e ON e.organisation_id=l.organisation_id AND e.id=l.employee_id '
            'JOIN payroll_withholding_recipients r ON r.organisation_id=l.organisation_id AND r.id=l.recipient_id '
            'WHERE l.organisation_id=? AND p.period>=? AND p.period<=? GROUP BY e.name,r.name,l.component_type ORDER BY e.name,r.name,l.component_type',
            (organisation_id,start,end))
        for row in rows:
            row['amount'] = db_number(money(decimal(row['amount'])))
        total = sum((money(decimal(row['amount'])) for row in rows), Decimal('0.00'))
        return {'rows': rows, 'total': db_number(total), 'start': start, 'end': end}

    def payout_report(self, organisation_id, *, start, end):
        rows = self.db.rows('SELECT p.period,b.payout_date,b.status,b.id payout_id,r.name recipient_name,'
            'l.description,l.amount FROM payroll_withholding_payout_lines l '
            'JOIN payroll_withholding_payout_batches w ON w.organisation_id=l.organisation_id AND w.id=l.withholding_payout_id '
            'JOIN payroll_payout_batches b ON b.organisation_id=w.organisation_id AND b.id=w.payout_batch_id '
            'JOIN pay_runs p ON p.organisation_id=w.organisation_id AND p.id=w.pay_run_id '
            'JOIN payroll_withholding_recipients r ON r.organisation_id=l.organisation_id AND r.id=l.recipient_id '
            'WHERE l.organisation_id=? AND p.period>=? AND p.period<=? AND b.status!=\'Cancelled\' '
            'ORDER BY p.period,b.payout_date,r.name,b.id', (organisation_id,start,end))
        for row in rows:
            row['amount'] = db_number(money(decimal(row['amount'])))
        total = sum((money(decimal(row['amount'])) for row in rows), Decimal('0.00'))
        return {'rows': rows, 'total': db_number(total), 'start': start, 'end': end}

    def report_xlsx(self, organisation_id, *, start, end, payouts=False):
        from excel_export import payroll_withholding_workbook
        report = self.payout_report(organisation_id, start=start, end=end) if payouts else self.report(
            organisation_id, start=start, end=end)
        with self.db.transaction() as tx:
            organisation = tx.one('SELECT * FROM organisations WHERE id=?', (organisation_id,))
        return payroll_withholding_workbook(organisation, report, payouts=payouts)

    @staticmethod
    def generate_for_item(tx, organisation_id, run, item, *, gross, net, minimum_wage):
        """Freeze active agreement deductions for a draft item and return total."""
        if not tx.table_exists('payroll_withholding_agreements'):
            return Decimal('0.00')
        period_start = run['period'] + '-01'
        period_end = run['period'] + '-31'
        agreements = tx.rows('SELECT a.*,r.name recipient_name FROM payroll_withholding_agreements a '
            'JOIN payroll_withholding_recipients r ON r.organisation_id=a.organisation_id AND r.id=a.recipient_id '
            'WHERE a.organisation_id=? AND a.employee_id=? AND a.active=1 AND a.start_date<=? '
            'AND (a.end_date IS NULL OR a.end_date>=?) AND r.active=1 '
            "ORDER BY CASE WHEN a.component_type='alimony' THEN 0 ELSE 1 END,a.id",
            (organisation_id, item['employee_id'], period_end, period_start))
        rules = rules_for(date.fromisoformat(run.get('settlement_date') or period_end))
        manual_lines = tx.rows('SELECT agreement_id,component_type,amount FROM payroll_withholding_run_lines '
            'WHERE organisation_id=? AND pay_run_id=? AND pay_run_item_id=? AND generated=0',
            (organisation_id, run['id'], item['id']))
        manual_total = sum((money(line['amount']) for line in manual_lines), Decimal('0.00'))
        ordinary_limit = garnishable_amount(net, minimum_wage, rules=rules)
        child_limit = garnishable_amount(net, minimum_wage, child_maintenance=True, rules=rules)
        has_child_claim = any(row['component_type'] == 'alimony' for row in agreements)
        manual_garnishable = sum((money(line['amount']) for line in manual_lines
            if line['component_type'] in ('alimony', 'bailiff')), Decimal('0.00'))
        garnishable_left = max(Decimal('0.00'), money((child_limit if has_child_claim else ordinary_limit)
                                                       - manual_garnishable))
        remaining_net = max(Decimal('0.00'), money(net - manual_total))
        ordinary_left = max(Decimal('0.00'), money(ordinary_limit - manual_garnishable))
        child_left = max(Decimal('0.00'), money(child_limit - manual_garnishable))
        total = manual_total
        manual_agreement_ids = {line['agreement_id'] for line in manual_lines}
        for agreement in agreements:
            if agreement['id'] in manual_agreement_ids:
                continue
            child = agreement['component_type'] == 'alimony'
            available = min(child_left if child else ordinary_left, garnishable_left)
            desired = calculate_withholding(agreement, gross=gross, net=net,
                withheld_to_date=agreement['withheld_to_date'], available_net=remaining_net,
                garnishable=available if agreement['component_type'] in ('alimony', 'bailiff') else None)
            reduced = desired < calculate_withholding(agreement, gross=gross, net=net,
                withheld_to_date=agreement['withheld_to_date'], available_net=net)
            if desired or reduced:
                description = agreement['payment_description'] or agreement['recipient_name']
                if agreement['component_type'] == 'third_pillar':
                    description += ' | tax-free treatment (TSD type 25 / exemption 640) pending accountant confirmation'
                tx.execute('INSERT INTO payroll_withholding_run_lines '
                    '(id,organisation_id,pay_run_id,pay_run_item_id,agreement_id,recipient_id,employee_id,component_type,amount,generated,description) '
                    'VALUES (?,?,?,?,?,?,?,?,?,1,?)', (new_id(), organisation_id, run['id'], item['id'],
                     agreement['id'], agreement['recipient_id'], item['employee_id'], agreement['component_type'],
                     db_number(desired), description + (' | reduced to legal/net limit' if reduced else '')))
            remaining_net = money(remaining_net - desired)
            total = money(total + desired)
            if agreement['component_type'] == 'alimony':
                child_left = money(child_left - desired)
            elif agreement['component_type'] == 'bailiff':
                ordinary_left = money(ordinary_left - desired)
            if agreement['component_type'] in ('alimony', 'bailiff'):
                garnishable_left = money(garnishable_left - desired)
        return total
