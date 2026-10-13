"""Straight-line fixed assets with immutable acquisitions, depreciation and disposal.

Calendar period ends are due dates. Acquisition receives a full first period.
Disposal receives all unpaid full scheduled charges through its disposal period,
in the disposal batch, then stops. There is no daily proration or residual value.
"""
import calendar
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from core_utils import audit, db_number, decimal, money, new_id, utc_now
from database import get_database
from fixed_asset_repository import FixedAssetRepository
from ledger import LedgerService, PostingLine


FREQUENCIES = {'monthly': 1, 'quarterly': 3, 'yearly': 12}
DEFAULT_NAMES = {
    'en': ('Equipment', 'Computers', 'Other assets'),
    'et': ('Inventar', 'Arvutid', 'Muud põhivarad'),
    'lt': ('Inventorius', 'Kompiuteriai', 'Kitas ilgalaikis turtas'),
    'lv': ('Inventārs', 'Datori', 'Citi pamatlīdzekļi'),
}


class FixedAssetService:
    def __init__(self, db=None):
        self.db = db or get_database()
        self.repo = FixedAssetRepository(self.db)
        self.ledger = LedgerService(self.db)

    @staticmethod
    def _date(value):
        try:
            return date.fromisoformat(value)
        except (TypeError, ValueError):
            raise ValueError('Fixed asset dates must be ISO dates') from None

    @staticmethod
    def _number(value, *, percentage=False, allow_zero=False):
        try:
            raw = decimal(value)
            if not raw.is_finite() or raw < 0 or (raw == 0 and not allow_zero):
                raise ValueError('Invalid fixed asset amount')
            if percentage and raw > 100:
                raise ValueError('Depreciation percentage must be between 0 and 100')
            result = raw if percentage else money(raw)
            if result == 0 and not allow_zero:
                raise ValueError('Invalid fixed asset amount')
            return result
        except (InvalidOperation, TypeError):
            raise ValueError('Invalid fixed asset amount') from None

    @staticmethod
    def _asset_values(row):
        for key in ('acquisition_cost', 'disposal_amount', 'disposal_depreciation_amount'):
            if row.get(key) is not None:
                row[key] = money(row[key])
        row['annual_percentage'] = decimal(row['annual_percentage'])
        return row

    @staticmethod
    def period_end(day, kind):
        if kind not in FREQUENCIES:
            raise ValueError('Invalid depreciation frequency')
        months = FREQUENCIES[kind]
        month = ((day.month - 1) // months + 1) * months
        return date(day.year, month, calendar.monthrange(day.year, month)[1])

    def _next(self, asset, history):
        day = self._date(history[-1]['period_date']) + timedelta(days=1) if history else self._date(asset['acquisition_date'])
        return self.period_end(day, asset['frequency'])

    @staticmethod
    def _accumulated(history):
        return sum((money(r['amount']) for r in history), Decimal('0.00'))

    def _charge(self, asset, history, periods=1):
        cost = money(asset['acquisition_cost'])
        # Round the cumulative theoretical target rather than repeating a rounded
        # instalment, so small rounding differences are corrected in later runs.
        target = money(cost * decimal(asset['annual_percentage']) / 100
                       * FREQUENCIES[asset['frequency']] / 12 * (len(history) + periods))
        return max(Decimal('0.00'), min(cost, target) - self._accumulated(history))

    def _group_row(self, tx, org, *, name, annual_percentage, frequency='monthly',
                   asset_account_id=None, accumulated_depreciation_account_id=None,
                   expense_account_id=None, default_key=None):
        if not isinstance(name, str) or not name.strip():
            raise ValueError('Asset name is required')
        rate = self._number(annual_percentage, percentage=True)
        self.period_end(date.today(), frequency)
        roles = [('asset_account_id', asset_account_id, 'FIXED_ASSETS', 'Asset', 'Debit'),
                 ('accumulated_depreciation_account_id', accumulated_depreciation_account_id,
                  'ACCUMULATED_DEPRECIATION', 'Asset', 'Credit'),
                 ('expense_account_id', expense_account_id, 'DEPRECIATION_EXPENSE', 'Expense', 'Debit')]
        now = utc_now()
        row = dict(id=new_id(), organisation_id=org, name=name.strip(), annual_percentage=db_number(rate),
                   frequency=frequency, default_key=default_key, created_at=now, updated_at=now)
        for key, account, role, kind, balance in roles:
            row[key] = self.repo.account(tx, org, account or self.repo.role_account(tx, org, role), kind, balance)
        self.repo.insert(tx, 'asset_groups', row)
        return row

    def groups(self, organisation_id, locale=None):
        with self.repo.transaction(organisation_id) as tx:
            if locale is None:
                country = self.repo.country(tx, organisation_id)
                locale = 'et' if country == 'EE' else 'en'
            existing = self.repo.groups(tx, organisation_id)
            seeded = {r['default_key'] for r in existing}
            for index, (name, rate) in enumerate(zip(DEFAULT_NAMES.get(locale, DEFAULT_NAMES['en']), (20, 25, 10))):
                key = str(index)
                if key not in seeded:
                    self._group_row(tx, organisation_id, name=name, annual_percentage=rate, default_key=key)
            return [{**r, 'annual_percentage': decimal(r['annual_percentage'])}
                    for r in self.repo.groups(tx, organisation_id)]

    def create_group(self, organisation_id, *, actor, **kwargs):
        with self.repo.transaction(organisation_id) as tx:
            row = self._group_row(tx, organisation_id, **kwargs)
            audit(tx, organisation_id, actor, 'asset_group.created', 'asset_group', row['id'])
            return row

    def _bank(self, tx, org, bank_id):
        bank = self.repo.bank(tx, org, bank_id)
        if not bank or bank['currency'] != self.repo.base_currency(tx, org):
            raise ValueError('Fixed assets require a bank account in the organisation base currency')
        return bank['ledger_account_id']

    def create(self, organisation_id, *, group_id, name, acquisition_date, acquisition_cost,
               bank_account_id, idempotency_key, actor):
        day = self._date(acquisition_date).isoformat()
        cost = self._number(acquisition_cost)
        if not isinstance(name, str) or not name.strip():
            raise ValueError('Asset name is required')
        if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 160:
            raise ValueError('A fixed asset idempotency key is required')
        expected = dict(group_id=group_id, name=name.strip(), acquisition_date=day,
                        acquisition_cost=cost, bank_account_id=bank_account_id)
        with self.repo.transaction(organisation_id) as tx:
            existing = self.repo.acquisition(tx, organisation_id, idempotency_key.strip())
            if existing:
                if any((money(existing[k]) if k == 'acquisition_cost' else existing[k]) != v for k, v in expected.items()):
                    raise ValueError('Fixed asset idempotency key was already used for different details')
                return self._asset_values(existing)
            group = self.repo.group(tx, organisation_id, group_id)
            if any(r['kind'] == group['frequency'] and r['period_date'] >= day for r in self.repo.runs(tx, organisation_id)):
                raise ValueError('Acquisition date overlaps an existing depreciation run')
            bank_account = self._bank(tx, organisation_id, bank_account_id)
            asset_id, now = new_id(), utc_now()
            lines = self._lines(asset_id, name, group['asset_account_id'], bank_account, cost)
            batch = self._post(tx, organisation_id, 'fixed_asset_acquisition', asset_id, day, lines, actor)
            row = dict(id=asset_id, organisation_id=organisation_id, **{**expected, 'acquisition_cost': db_number(cost)},
                       idempotency_key=idempotency_key.strip(),
                       posting_batch_id=batch['id'], status='Active', created_by=actor, created_at=now, updated_at=now)
            for key in ('annual_percentage', 'frequency', 'asset_account_id', 'accumulated_depreciation_account_id', 'expense_account_id'):
                row[key] = group[key]
            self.repo.insert(tx, 'fixed_assets', row)
            audit(tx, organisation_id, actor, 'fixed_asset.created', 'fixed_asset', asset_id)
            return self._asset_values(self.repo.asset(tx, organisation_id, asset_id))

    @staticmethod
    def _lines(asset_id, name, debit_account, credit_account, amount):
        return [PostingLine(debit_account, debit=amount, memo=name, source_line_type='fixed_asset', source_line_id=asset_id),
                PostingLine(credit_account, credit=amount, memo=name, source_line_type='fixed_asset', source_line_id=asset_id)]

    def _post(self, tx, org, kind, identifier, day, lines, actor, **kwargs):
        return self.ledger.post(organisation_id=org, voucher_type=kind, voucher_id=identifier,
                                voucher_code=f'{kind.upper()}-{identifier[:8]}', posting_date=day, lines=lines,
                                actor=actor, currency=self.repo.base_currency(tx, org), tx=tx, **kwargs)

    def run(self, organisation_id, *, period_date, kind='monthly', actor):
        day = self._date(period_date)
        if self.period_end(day, kind) != day:
            raise ValueError('Depreciation run date must be a calendar period end')
        with self.repo.transaction(organisation_id) as tx:
            existing = self.repo.run(tx, organisation_id, kind, day.isoformat())
            if existing:
                return existing
            self.ledger._validate_period(tx, organisation_id, day.isoformat())
            lines, amounts = [], []
            for asset in self.repo.assets(tx, organisation_id):
                if asset['status'] != 'Active' or asset['frequency'] != kind:
                    continue
                history = self.repo.history(tx, organisation_id, asset['id'])
                if self._accumulated(history) >= money(asset['acquisition_cost']):
                    continue
                due = self._next(asset, history)
                if due < day:
                    raise ValueError('Earlier depreciation periods must be run first')
                if due != day:
                    continue
                amount = self._charge(asset, history)
                if amount:
                    lines.extend(self._lines(asset['id'], asset['name'], asset['expense_account_id'],
                                             asset['accumulated_depreciation_account_id'], amount))
                # Keep even zero-cent instalments: their period counts contribute
                # to the cumulative rounding target and must advance the schedule.
                amounts.append((asset['id'], amount))
            run_id = new_id()
            batch = self._post(tx, organisation_id, 'depreciation', run_id, day.isoformat(), lines, actor) if lines else None
            row = dict(id=run_id, organisation_id=organisation_id, kind=kind, period_date=day.isoformat(),
                       status='Posted' if batch else 'Empty', posting_batch_id=batch['id'] if batch else None,
                       created_by=actor, created_at=utc_now())
            self.repo.insert(tx, 'depreciation_runs', row)
            for asset_id, amount in amounts:
                self.repo.insert(tx, 'depreciation_run_assets', dict(id=new_id(), organisation_id=organisation_id,
                    run_id=run_id, asset_id=asset_id, amount=db_number(amount), posting_batch_id=row['posting_batch_id']))
            audit(tx, organisation_id, actor, 'depreciation.run', 'depreciation_run', run_id)
            return row

    def dispose(self, organisation_id, asset_id, *, disposal_date, disposal_amount, bank_account_id, actor):
        day, proceeds = self._date(disposal_date), self._number(disposal_amount, allow_zero=True)
        with self.repo.transaction(organisation_id) as tx:
            asset = self.repo.asset(tx, organisation_id, asset_id)
            if asset['status'] == 'Disposed':
                if (asset['disposal_date'] != day.isoformat() or money(asset['disposal_amount']) != proceeds
                        or asset['disposal_bank_account_id'] != bank_account_id):
                    raise ValueError('Fixed asset has already been disposed with different details')
                return self._asset_values(asset)
            history = self.repo.history(tx, organisation_id, asset_id)
            if day < self._date(asset['acquisition_date']) or (history and day < self._date(history[-1]['period_date'])):
                raise ValueError('Disposal date cannot precede acquisition or posted depreciation')
            bank = self._bank(tx, organisation_id, bank_account_id)
            due, end, periods = self._next(asset, history), self.period_end(day, asset['frequency']), 0
            while due <= end:
                periods += 1
                due = self.period_end(due + timedelta(days=1), asset['frequency'])
            charge = self._charge(asset, history, periods=periods)
            accumulated = self._accumulated(history) + charge
            cost = money(asset['acquisition_cost'])
            lines = self._lines(asset_id, asset['name'], asset['expense_account_id'],
                                asset['accumulated_depreciation_account_id'], charge) if charge else []
            def leg(account, debit=Decimal('0'), credit=Decimal('0')):
                if debit or credit:
                    lines.append(PostingLine(account, debit=debit, credit=credit, memo=asset['name'],
                                             source_line_type='fixed_asset', source_line_id=asset_id))
            leg(asset['accumulated_depreciation_account_id'], debit=accumulated)
            leg(bank, debit=proceeds)
            leg(asset['asset_account_id'], credit=cost)
            difference = cost - accumulated - proceeds
            # Disposal gains/losses have explicit separate legs on the existing
            # general income/expense roles, rather than changing asset cost.
            if difference > 0:
                leg(self.repo.role_account(tx, organisation_id, 'EXPENSE'), debit=difference)
            elif difference < 0:
                leg(self.repo.role_account(tx, organisation_id, 'SALES'), credit=-difference)
            batch = self._post(tx, organisation_id, 'fixed_asset_disposal', asset_id, day.isoformat(), lines, actor,
                               reverses_batch_id=asset['posting_batch_id'])
            self.repo.dispose(tx, organisation_id, asset_id, dict(status='Disposed', disposal_date=day.isoformat(),
                disposal_amount=db_number(proceeds), disposal_depreciation_amount=db_number(charge),
                disposal_bank_account_id=bank_account_id, disposal_posting_batch_id=batch['id'], updated_at=utc_now()))
            audit(tx, organisation_id, actor, 'fixed_asset.disposed', 'fixed_asset', asset_id)
            return self._asset_values(self.repo.asset(tx, organisation_id, asset_id))

    def runs(self, organisation_id):
        with self.repo.transaction(organisation_id) as tx:
            return self.repo.runs(tx, organisation_id)

    def register(self, organisation_id):
        self.groups(organisation_id)
        with self.repo.transaction(organisation_id) as tx:
            groups = [{**r, 'annual_percentage': decimal(r['annual_percentage'])}
                      for r in self.repo.groups(tx, organisation_id)]
            assets = [self._asset_values(r) for r in self.repo.assets(tx, organisation_id)]
            fields = ('acquisition_cost', 'accumulated_depreciation', 'carrying_value')
            for asset in assets:
                asset['acquisition_cost'] = money(asset['acquisition_cost'])
                asset['accumulated_depreciation'] = self._accumulated(self.repo.history(tx, organisation_id, asset['id'])) + money(asset['disposal_depreciation_amount'])
                asset['carrying_value'] = (asset['acquisition_cost'] - asset['accumulated_depreciation']) if asset['status'] == 'Active' else Decimal('0.00')
            for group in groups:
                for key in fields:
                    group[key] = sum((a[key] for a in assets if a['group_id'] == group['id']), Decimal('0.00'))
            totals = {key: sum((a[key] for a in assets), Decimal('0.00')) for key in fields}
            return dict(assets=assets, groups=groups, totals=totals)

    def schedule(self, organisation_id):
        with self.repo.transaction(organisation_id) as tx:
            rows = []
            for asset in self.repo.assets(tx, organisation_id):
                history = self.repo.history(tx, organisation_id, asset['id'])
                if asset['status'] == 'Active' and self._accumulated(history) < money(asset['acquisition_cost']):
                    rows.append(dict(asset_id=asset['id'], name=asset['name'], group_name=asset['group_name'],
                                     frequency=asset['frequency'], next_due_date=self._next(asset, history).isoformat(),
                                     amount=self._charge(asset, history)))
            return sorted(rows, key=lambda r: (r['next_due_date'], r['asset_id']))

    def run_due(self, organisation_id, *, today=None, actor='automation'):
        through = date.today() if today is None else (today if isinstance(today, date) else self._date(today))
        results = []
        while True:
            pending = [r for r in self.schedule(organisation_id) if r['next_due_date'] <= through.isoformat()]
            if not pending:
                return results
            item = pending[0]
            results.append(self.run(organisation_id, period_date=item['next_due_date'], kind=item['frequency'], actor=actor))
