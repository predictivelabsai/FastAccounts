"""Effective-dated employee elections and frozen payroll context."""
from datetime import date
from decimal import InvalidOperation

from core_utils import audit, db_number, decimal, money, new_id
from payroll_rules import rules_for
import payroll_tax_repository as repository


class TaxSettingConflict(ValueError):
    """An election is already frozen or duplicates an effective date."""


class TaxSettingValidationError(ValueError):
    """A translated validation message for an employee election."""


def serialise(row, *, used=False):
    result = dict(row, frozen=used)
    if result.get('amount') is not None:
        result['amount'] = db_number(money(result['amount']))
    if result.get('rate') is not None:
        result['rate'] = int(result['rate'])
    if result.get('applies') is not None:
        result['applies'] = bool(result['applies'])
    return result


def resolve(tx, organisation_id, employee, applies_on):
    """Resolve elections once, using the caller's settlement date boundary."""
    repository.employee(tx, organisation_id, employee['id'])
    rows = repository.histories(tx, organisation_id, employee['id'])
    selected = {kind: next((r for r in reversed(rows) if r['kind'] == kind and
                           r['start_date'] <= applies_on.isoformat()), None)
                for kind in ('tax_free', 'pension', 'unemployment')}
    tax, pension, ui = (selected[k] for k in ('tax_free', 'pension', 'unemployment'))
    # Missing earlier elections imply no application, no membership, ordinary UI.
    return dict(tax_free_mode=tax['mode'] if tax else 'none',
                tax_free_amount=tax['amount'] if tax else None,
                apply_tax_free_minimum=bool(tax and tax['mode'] != 'none'),
                funded_pension_percent=pension['rate'] if pension else 0,
                unemployment_applies=bool(ui['applies']) if ui else True,
                tax_free_setting_id=tax['id'] if tax else None,
                pension_setting_id=pension['id'] if pension else None,
                unemployment_setting_id=ui['id'] if ui else None)


class EmployeeTaxSettingsService:
    def __init__(self, db):
        self.db = db

    def list(self, organisation_id, employee_id):
        with self.db.transaction() as tx:
            repository.employee(tx, organisation_id, employee_id, lock=False)
            return [serialise(r, used=repository.frozen(tx, organisation_id, r['id']))
                    for r in repository.histories(tx, organisation_id, employee_id)]

    def save(self, organisation_id, employee_id, *, actor, kind, start_date,
             setting_id=None, mode=None, amount=None, rate=None, applies=None, tx=None):
        if tx is None:
            with self.db.transaction() as owned:
                return self.save(organisation_id, employee_id, actor=actor, kind=kind,
                                 start_date=start_date, setting_id=setting_id, mode=mode,
                                 amount=amount, rate=rate, applies=applies, tx=owned)
        repository.employee(tx, organisation_id, employee_id)
        try:
            start = date.fromisoformat(start_date)
            if start.isoformat() != start_date:
                raise ValueError()
        except (ValueError, TypeError):
            raise TaxSettingValidationError('Tax setting start date must use YYYY-MM-DD') from None
        rows = repository.histories(tx, organisation_id, employee_id)
        old = next((r for r in rows if r['id'] == setting_id), None)
        if setting_id and not old:
            raise KeyError('Tax setting not found')
        if old and repository.frozen(tx, organisation_id, setting_id):
            raise TaxSettingConflict('Tax settings used in an approved run cannot be changed or deleted')
        if old and old['kind'] != kind:
            raise TaxSettingValidationError('Tax setting kind cannot be changed')
        if any(r['kind'] == kind and r['start_date'] == start_date and r['id'] != setting_id for r in rows):
            raise TaxSettingConflict('A tax setting already exists for this date')
        valid = False
        try:
            if kind == 'tax_free' and rate is None and applies is None:
                if mode == 'limited' and amount is not None:
                    amount = decimal(amount)
                    valid = amount.is_finite() and 0 <= amount <= rules_for(start).basic_exemption and amount == money(amount)
                    if valid:
                        amount = db_number(amount)
                else:
                    valid = mode in ('maximum', 'none') and amount is None
            elif kind == 'pension':
                valid = rate is not None and decimal(rate) in (0, 2, 4, 6) and mode is None and amount is None and applies is None
                if valid:
                    rate = int(decimal(rate))
            elif kind == 'unemployment':
                valid = isinstance(applies, bool) and rate is None and mode is None and amount is None
        except InvalidOperation:
            valid = False
        if not valid:
            raise TaxSettingValidationError('Invalid employee tax setting')
        row = dict(id=setting_id or new_id(), organisation_id=organisation_id, employee_id=employee_id,
                   kind=kind, start_date=start_date, mode=mode, amount=amount, rate=rate,
                   applies=None if applies is None else int(applies))
        repository.save(tx, row)
        audit(tx, organisation_id, actor, 'payroll.tax_setting.updated' if old else 'payroll.tax_setting.created',
              'employee_tax_setting', row['id'])
        return serialise(row)

    def delete(self, organisation_id, employee_id, setting_id, *, actor):
        with self.db.transaction() as tx:
            repository.employee(tx, organisation_id, employee_id)
            row = next((r for r in repository.histories(tx, organisation_id, employee_id) if r['id'] == setting_id), None)
            if not row:
                raise KeyError('Tax setting not found')
            if repository.frozen(tx, organisation_id, setting_id):
                raise TaxSettingConflict('Tax settings used in an approved run cannot be changed or deleted')
            repository.delete(tx, organisation_id, setting_id)
            audit(tx, organisation_id, actor, 'payroll.tax_setting.deleted', 'employee_tax_setting', setting_id)

    def legacy_write(self, tx, organisation_id, employee, changes, *, actor, period=None, creating=False):
        """Keep old API fields writable without rewriting approved elections."""
        if creating:
            start = employee.get('employment_start_date') or '2026-01-01'
        elif period:
            from payroll_rules import settlement_date
            rules_for(settlement_date(period))
            start = period + '-01'
        else:
            run = tx.one('SELECT period FROM pay_runs WHERE organisation_id=? ORDER BY period DESC LIMIT 1', (organisation_id,))
            start = (run['period'] + '-01') if run else (employee.get('employment_start_date') or '2026-01-01')
        rows = repository.histories(tx, organisation_id, employee['id'])
        for field, kind, values in (
            ('apply_tax_free_minimum', 'tax_free', dict(mode='maximum' if employee['apply_tax_free_minimum'] else 'none')),
            ('funded_pension_percent', 'pension', dict(rate=employee['funded_pension_percent'])),
            ('board_member', 'unemployment', dict(applies=not employee['board_member'])),
        ):
            if not creating and field not in changes:
                continue
            old = next((r for r in rows if r['kind'] == kind and r['start_date'] == start), None)
            if old and all(old[k] == v or str(old[k]) == str(v) for k, v in values.items()):
                continue
            self.save(organisation_id, employee['id'], actor=actor, kind=kind, start_date=start,
                      setting_id=old['id'] if old else None, tx=tx, **values)
