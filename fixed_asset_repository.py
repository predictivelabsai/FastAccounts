"""Tenant-scoped fixed asset persistence and serialised accounting workflows."""
from contextlib import contextmanager


class FixedAssetRepository:
    def __init__(self, db):
        self.db = db

    @contextmanager
    def transaction(self, organisation_id):
        with self.db.transaction() as tx:
            if tx.dialect == 'sqlite':
                tx.execute('BEGIN IMMEDIATE')
            suffix = ' FOR UPDATE' if tx.dialect == 'postgres' else ''
            if not tx.one('SELECT id FROM organisations WHERE id=?' + suffix, (organisation_id,)):
                raise KeyError('Organisation not found')
            yield tx

    @staticmethod
    def base_currency(tx, org):
        return tx.scalar('SELECT base_currency FROM organisations WHERE id=?', (org,))

    @staticmethod
    def country(tx, org):
        return tx.scalar('SELECT country_code FROM organisations WHERE id=?', (org,))

    @staticmethod
    def role_account(tx, org, role):
        row = tx.one('SELECT id FROM accounts WHERE organisation_id=? AND system_role=? AND active=1', (org, role))
        if not row:
            raise ValueError('Fixed asset account is missing or inactive')
        return row['id']

    @staticmethod
    def bank(tx, org, bank_id):
        return tx.one('SELECT * FROM bank_accounts WHERE organisation_id=? AND id=?', (org, bank_id))

    @staticmethod
    def insert(tx, table, row):
        assert table in {'asset_groups', 'fixed_assets', 'depreciation_runs', 'depreciation_run_assets'}
        columns = list(row)
        tx.execute(f"INSERT INTO {table}({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                   tuple(row[column] for column in columns))

    @staticmethod
    def group(tx, org, group_id):
        row = tx.one('SELECT * FROM asset_groups WHERE organisation_id=? AND id=?', (org, group_id))
        if not row:
            raise KeyError('Asset group not found')
        return row

    @staticmethod
    def asset(tx, org, asset_id):
        row = tx.one('SELECT * FROM fixed_assets WHERE organisation_id=? AND id=?', (org, asset_id))
        if not row:
            raise KeyError('Fixed asset not found')
        return row

    @staticmethod
    def assets(tx, org):
        return tx.rows('SELECT a.*,g.name group_name FROM fixed_assets a JOIN asset_groups g '
                       'ON g.organisation_id=a.organisation_id AND g.id=a.group_id '
                       'WHERE a.organisation_id=? ORDER BY a.acquisition_date,a.id', (org,))

    @staticmethod
    def history(tx, org, asset_id):
        return tx.rows('SELECT ra.amount,r.period_date FROM depreciation_run_assets ra '
                       'JOIN depreciation_runs r ON r.organisation_id=ra.organisation_id AND r.id=ra.run_id '
                       'WHERE ra.organisation_id=? AND ra.asset_id=? ORDER BY r.period_date', (org, asset_id))

    @staticmethod
    def runs(tx, org):
        return tx.rows('SELECT * FROM depreciation_runs WHERE organisation_id=? ORDER BY period_date,kind', (org,))

    @staticmethod
    def run(tx, org, kind, day):
        return tx.one('SELECT * FROM depreciation_runs WHERE organisation_id=? AND kind=? AND period_date=?',
                      (org, kind, day))

    @staticmethod
    def groups(tx, org):
        return tx.rows('SELECT * FROM asset_groups WHERE organisation_id=? ORDER BY created_at,id', (org,))

    @staticmethod
    def acquisition(tx, org, key):
        return tx.one('SELECT * FROM fixed_assets WHERE organisation_id=? AND idempotency_key=?', (org, key))

    @staticmethod
    def account(tx, org, account_id, kind, balance):
        row = tx.one('SELECT * FROM accounts WHERE organisation_id=? AND id=? AND active=1', (org, account_id))
        if not row or row['account_type'] != kind or row['normal_balance'] != balance:
            raise ValueError('Invalid fixed asset account')
        return account_id

    @staticmethod
    def dispose(tx, org, asset_id, row):
        columns = list(row)
        tx.execute(f"UPDATE fixed_assets SET {','.join(c+'=?' for c in columns)} WHERE organisation_id=? AND id=?",
                   (*[row[c] for c in columns], org, asset_id))
