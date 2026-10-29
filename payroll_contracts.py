"""Tenant-scoped employee contract and dated salary agreement history."""
from datetime import date
from decimal import Decimal, InvalidOperation

from core_utils import audit, new_id

CONTRACT_TYPES = frozenset({'employment', 'board_member', 'services', 'other', 'none'})
PAY_TYPES = frozenset({'monthly', 'monthly_day_based', 'hourly', 'contract_sum', 'contract_sum_x_qty'})
PAYDAY_RULES = frozenset({'next_month_day', 'current_month_day', 'next_month_first_working_day'})


def _date(value, label):
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{label} must be YYYY-MM-DD') from exc


def _amount(value, label, *, positive=False):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f'{label} must be a decimal amount') from exc
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise ValueError(f'{label} is outside the allowed range')
    return format(result.quantize(Decimal('0.01')), 'f')


class PayrollContractService:
    def __init__(self, db):
        self.db = db

    def list(self, organisation_id, employee_id):
        with self.db.transaction() as tx:
            if not tx.one('SELECT id FROM employees WHERE organisation_id=? AND id=?', (organisation_id, employee_id)):
                raise ValueError('Employee not found')
            contracts = tx.rows('SELECT * FROM payroll_contracts WHERE organisation_id=? AND employee_id=? ORDER BY start_date,id',
                                (organisation_id, employee_id))
            for contract in contracts:
                contract['agreements'] = tx.rows('SELECT * FROM payroll_salary_agreements WHERE organisation_id=? AND contract_id=? ORDER BY start_date,id',
                                                 (organisation_id, contract['id']))
                contract['positions'] = tx.rows('SELECT * FROM payroll_contract_positions WHERE organisation_id=? AND contract_id=? ORDER BY start_date,id',
                                                (organisation_id, contract['id']))
            return contracts

    def create(self, organisation_id, employee_id, *, contract_type, start_date, actor, end_date=None,
               document_name=None, workplace_address=None, monthly_net_advance='0', payday_rule=None,
               payday_day=None, agreement=None, position=None, department_id=None, position_id=None):
        start_date = _date(start_date, 'Contract start date')
        if end_date:
            end_date = _date(end_date, 'Contract end date')
            if end_date < start_date:
                raise ValueError('Contract end date cannot precede start date')
        if contract_type not in CONTRACT_TYPES:
            raise ValueError('Invalid contract type')
        if payday_rule is not None and payday_rule not in PAYDAY_RULES:
            raise ValueError('Invalid payday rule')
        if payday_rule == 'next_month_first_working_day' and payday_day is not None:
            raise ValueError('Payday rule and day do not match')
        if payday_rule in {'next_month_day', 'current_month_day'} and payday_day is None:
            raise ValueError('Payday rule and day do not match')
        if payday_day is not None and (not isinstance(payday_day, int) or not 1 <= payday_day <= 31):
            raise ValueError('Payday day must be between 1 and 31')
        advance = _amount(monthly_net_advance, 'Monthly net advance')
        agreement_data = self._agreement(agreement, start_date) if agreement else None
        contract_id = new_id()
        with self.db.transaction() as tx:
            if not tx.one('SELECT id FROM employees WHERE organisation_id=? AND id=?', (organisation_id, employee_id)):
                raise ValueError('Employee not found')
            from payroll_dimensions import validate_employee_dimensions
            validate_employee_dimensions(tx, organisation_id, {'department_id': department_id, 'position_id': position_id})
            tx.execute('INSERT INTO payroll_contracts(id,organisation_id,employee_id,contract_type,start_date,end_date,document_name,workplace_address,monthly_net_advance,payday_rule,payday_day,department_id,position_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)',
                       (contract_id, organisation_id, employee_id, contract_type, start_date, end_date,
                        document_name, workplace_address, advance, payday_rule, payday_day, department_id, position_id))
            if agreement_data:
                self._insert_agreement(tx, organisation_id, contract_id, agreement_data)
            if position:
                tx.execute('INSERT INTO payroll_contract_positions(id,organisation_id,contract_id,start_date,position,occupation_code) VALUES (?,?,?,?,?,?)',
                           (new_id(), organisation_id, contract_id, start_date, position['position'], position.get('occupation_code')))
            audit(tx, organisation_id, actor, 'payroll.contract.created', 'payroll_contract', contract_id)
        return next(c for c in self.list(organisation_id, employee_id) if c['id'] == contract_id)

    def add_agreement(self, organisation_id, contract_id, *, start_date, actor, **agreement):
        data = self._agreement(agreement, start_date)
        agreement_id = new_id()
        with self.db.transaction() as tx:
            if not tx.one('SELECT id FROM payroll_contracts WHERE organisation_id=? AND id=?', (organisation_id, contract_id)):
                raise ValueError('Contract not found')
            self._insert_agreement(tx, organisation_id, contract_id, data, agreement_id)
            audit(tx, organisation_id, actor, 'payroll.salary_agreement.created', 'payroll_salary_agreement', agreement_id)
            result = tx.one('SELECT * FROM payroll_salary_agreements WHERE organisation_id=? AND id=?', (organisation_id, agreement_id))
        return result

    def update(self, organisation_id, contract_id, *, actor, **changes):
        allowed = {'contract_type', 'start_date', 'end_date', 'document_name', 'workplace_address',
                   'monthly_net_advance', 'payday_rule', 'payday_day', 'department_id', 'position_id'}
        if set(changes) - allowed:
            raise ValueError('Unknown contract field')
        with self.db.transaction() as tx:
            current = tx.one('SELECT * FROM payroll_contracts WHERE organisation_id=? AND id=?',
                             (organisation_id, contract_id))
            if not current:
                raise ValueError('Contract not found')
            values = dict(current)
            values.update(changes)
            values['start_date'] = _date(values['start_date'], 'Contract start date')
            values['end_date'] = _date(values['end_date'], 'Contract end date') if values.get('end_date') else None
            if values['end_date'] and values['end_date'] < values['start_date']:
                raise ValueError('Contract end date cannot precede start date')
            if values['contract_type'] not in CONTRACT_TYPES:
                raise ValueError('Invalid contract type')
            if values['payday_rule'] is not None and values['payday_rule'] not in PAYDAY_RULES:
                raise ValueError('Invalid payday rule')
            if values['payday_rule'] == 'next_month_first_working_day' and values['payday_day'] is not None:
                raise ValueError('Payday rule and day do not match')
            if values['payday_rule'] in {'next_month_day', 'current_month_day'} and values['payday_day'] is None:
                raise ValueError('Payday rule and day do not match')
            if values['payday_day'] is not None and (type(values['payday_day']) is not int or not 1 <= values['payday_day'] <= 31):
                raise ValueError('Payday day must be between 1 and 31')
            values['monthly_net_advance'] = _amount(values['monthly_net_advance'], 'Monthly net advance')
            from payroll_dimensions import validate_employee_dimensions
            validate_employee_dimensions(tx, organisation_id, values)
            tx.execute('UPDATE payroll_contracts SET contract_type=?,start_date=?,end_date=?,document_name=?,workplace_address=?,monthly_net_advance=?,payday_rule=?,payday_day=?,department_id=?,position_id=? WHERE organisation_id=? AND id=?',
                       tuple(values[key] for key in ('contract_type', 'start_date', 'end_date', 'document_name',
                                                      'workplace_address', 'monthly_net_advance', 'payday_rule', 'payday_day', 'department_id', 'position_id')) +
                       (organisation_id, contract_id))
            audit(tx, organisation_id, actor, 'payroll.contract.updated', 'payroll_contract', contract_id)
        return next(item for item in self.list(organisation_id, current['employee_id']) if item['id'] == contract_id)

    def add_position(self, organisation_id, contract_id, *, start_date, position, actor, occupation_code=None):
        start_date = _date(start_date, 'Position start date')
        if not isinstance(position, str) or not position.strip() or len(position.strip()) > 180:
            raise ValueError('Position must contain 1 to 180 characters')
        position_id = new_id()
        with self.db.transaction() as tx:
            if not tx.one('SELECT id FROM payroll_contracts WHERE organisation_id=? AND id=?',
                          (organisation_id, contract_id)):
                raise ValueError('Contract not found')
            existing = tx.one('SELECT * FROM payroll_contract_positions WHERE organisation_id=? AND contract_id=? AND start_date=?',
                              (organisation_id, contract_id, start_date))
            if existing:
                tx.execute('UPDATE payroll_contract_positions SET position=?,occupation_code=? WHERE organisation_id=? AND id=?',
                           (position.strip(), occupation_code, organisation_id, existing['id']))
                position_id = existing['id']
            else:
                tx.execute('INSERT INTO payroll_contract_positions(id,organisation_id,contract_id,start_date,position,occupation_code) VALUES (?,?,?,?,?,?)',
                           (position_id, organisation_id, contract_id, start_date, position.strip(), occupation_code))
            audit(tx, organisation_id, actor, 'payroll.contract_position.saved', 'payroll_contract_position', position_id)
            return tx.one('SELECT * FROM payroll_contract_positions WHERE organisation_id=? AND id=?',
                          (organisation_id, position_id))

    @staticmethod
    def _agreement(data, start_date):
        base_pay_type = data.get('base_pay_type')
        if base_pay_type not in PAY_TYPES:
            raise ValueError('Invalid base pay type')
        fte = Decimal(str(data.get('fte', '1')))
        if not fte.is_finite() or not Decimal('0') < fte <= Decimal('1'):
            raise ValueError('FTE must be greater than 0 and at most 1')
        hours = _amount(data.get('hours_per_day', '8'), 'Hours per day', positive=True)
        if Decimal(hours) > 24:
            raise ValueError('Hours per day cannot exceed 24')
        return {'start_date': _date(start_date, 'Agreement start date'), 'base_pay_type': base_pay_type,
                'hours_per_day': hours, 'rate': _amount(data.get('rate'), 'Rate'), 'fte': format(fte, 'f'),
                'is_full_time': int(bool(data.get('is_full_time', True))),
                'automatic_working_time': int(bool(data.get('automatic_working_time', True))),
                'account_override': data.get('account_override'), 'department_id': data.get('department_id'),
                'cost_centre_id': data.get('cost_centre_id'), 'project_id': data.get('project_id')}

    @staticmethod
    def _insert_agreement(tx, organisation_id, contract_id, data, agreement_id=None):
        agreement_id = agreement_id or new_id()
        from payroll_dimensions import validate_agreement_dimensions
        validate_agreement_dimensions(tx, organisation_id, data)
        tx.execute('INSERT INTO payroll_salary_agreements(id,organisation_id,contract_id,start_date,base_pay_type,hours_per_day,rate,fte,is_full_time,automatic_working_time,account_override,department_id,cost_centre_id,project_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)',
                   (agreement_id, organisation_id, contract_id, data['start_date'], data['base_pay_type'],
                    data['hours_per_day'], data['rate'], data['fte'], data['is_full_time'],
                    data['automatic_working_time'], data['account_override'], data.get('department_id'),
                    data.get('cost_centre_id'), data.get('project_id')))
