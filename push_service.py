"""Explicit preparation, review and execution of local ledger exports."""
from __future__ import annotations

import json
import sqlite3
from decimal import Decimal

import httpx
from psycopg.errors import UniqueViolation

import connectors.registry as connector_registry
from connectors.providers import ProviderError
from core_utils import audit, canonical_json, money, new_id, utc_now
from database import Database, get_database
from integration_service import AccountMappingService, IntegrationService


class PushService:
    def __init__(self, db: Database | None = None, *, integration: IntegrationService | None = None):
        self.db = db or get_database()
        self.integration = integration or IntegrationService(self.db)
        self.account_mappings = AccountMappingService(self.db)

    def _payload(self, organisation_id, provider, object_type, local_ref):
        if provider not in {'merit', 'smartaccounts'}:
            raise ValueError('Reviewed pushes support Merit and SmartAccounts only')
        org = self.db.one('SELECT country_code,base_currency FROM organisations WHERE id=?', (organisation_id,))
        if not org:
            raise KeyError('Organisation not found')
        if org['country_code'] != 'EE' or org['base_currency'] != 'EUR':
            raise ValueError('Push requires an Estonian organisation with EUR books')
        if object_type == 'pay_runs':
            run = self.db.one('SELECT * FROM pay_runs WHERE organisation_id=? AND id=?', (organisation_id, local_ref))
            if not run:
                raise KeyError('Pay run not found')
            if run['status'] != 'Approved':
                raise ValueError('Pay run must be Approved before preparing a push')
            if not run['posted_batch_id']:
                raise ValueError('Pay run must have a posted ledger batch before preparing a push')
            batch_ref = run['posted_batch_id']
        elif object_type == 'journals':
            batch_ref = local_ref
        else:
            raise ValueError('Push object type must be pay_runs or journals')
        batch = self.db.one(
            'SELECT * FROM posting_batches WHERE organisation_id=? AND (id=? OR voucher_code=?) ORDER BY id',
            (organisation_id, batch_ref, batch_ref),
        )
        if not batch:
            raise KeyError('Posting batch not found')
        entries = self.db.rows(
            'SELECT g.*,a.code account_code FROM gl_entries g JOIN accounts a '
            'ON a.id=g.account_id AND a.organisation_id=g.organisation_id '
            'WHERE g.organisation_id=? AND g.posting_batch_id=? ORDER BY g.line_number,g.id',
            (organisation_id, batch['id']),
        )
        lines, missing = [], set()
        for entry in entries:
            code = entry['account_code']
            mapping = self.account_mappings.resolve(organisation_id, provider, code)
            if not mapping or mapping['status'] != 'Confirmed':
                missing.add(code)
            if entry['currency'] != 'EUR':
                raise ValueError('Push ledger lines must be in EUR')
            debit, credit = money(entry['debit']), money(entry['credit'])
            if not debit.is_finite() or not credit.is_finite() or min(debit, credit) < 0 or (debit > 0) == (credit > 0):
                raise ValueError('Push requires valid single-sided ledger lines')
            lines.append({'account_code': code, 'external_account_code': mapping['external_account_code'] if mapping else '',
                          'debit': debit, 'credit': credit, 'memo': entry['memo'] or ''})
        if missing:
            raise ValueError('Confirmed account mappings missing: ' + ', '.join(sorted(missing)))
        debit = sum((line['debit'] for line in lines), Decimal('0'))
        credit = sum((line['credit'] for line in lines), Decimal('0'))
        if len(lines) < 2 or debit <= 0 or debit != credit:
            raise ValueError('Push requires a balanced ledger batch')
        payload = {'doc_no': f"PAY-{run['period']}" if object_type == 'pay_runs' else batch['voucher_code'],
                   'posting_date': batch['posting_date'], 'currency': 'EUR',
                   'comment': batch['voucher_code'], 'lines': lines}
        return payload, (run['id'] if object_type == 'pay_runs' else batch['id']), batch['id']

    def prepare(self, organisation_id, provider, object_type, local_ref, actor):
        provider = provider.strip().lower()
        payload, local_ref, _ = self._payload(organisation_id, provider, object_type, str(local_ref))
        push_id = new_id()
        try:
            with self.db.transaction() as tx:
                if tx.one("SELECT id FROM sync_runs WHERE organisation_id=? AND provider=? AND object_type=? "
                          "AND local_ref=? AND direction='export' AND status IN ('Queued','Running','Review Required')",
                          (organisation_id, provider, object_type, local_ref)):
                    raise ValueError('a prepared push is already pending for this document')
                tx.execute("INSERT INTO sync_runs(id,organisation_id,provider,direction,object_type,status,read_count,"
                           "payload_json,local_ref,created_at) VALUES (?,?,?,'export',?,'Review Required',?,?,?,?)",
                           (push_id, organisation_id, provider, object_type, len(payload['lines']), canonical_json(payload), local_ref, utc_now()))
                audit(tx, organisation_id, actor, 'integration.push_prepared', 'sync_run', push_id)
        except (sqlite3.IntegrityError, UniqueViolation) as error:
            raise ValueError('a prepared push is already pending for this document') from error
        return self.get(organisation_id, push_id)

    def get(self, organisation_id, push_id):
        row = self.db.one("SELECT * FROM sync_runs WHERE organisation_id=? AND id=? AND direction='export' AND payload_json IS NOT NULL",
                          (organisation_id, push_id))
        if not row:
            raise KeyError('Push not found')
        return row

    def list(self, organisation_id, provider=None, object_type=None, pay_run_id=None):
        query = "SELECT * FROM sync_runs WHERE organisation_id=? AND direction='export' AND payload_json IS NOT NULL"
        params = [organisation_id]
        for column, value in [('provider', provider.strip().lower() if provider else None), ('object_type', object_type)]:
            if value is not None:
                query += f' AND {column}=?'
                params.append(value)
        if pay_run_id is not None:
            if not self.db.one('SELECT id FROM pay_runs WHERE organisation_id=? AND id=?', (organisation_id, pay_run_id)):
                raise KeyError('Pay run not found')
            query += " AND object_type='pay_runs' AND local_ref=?"
            params.append(pay_run_id)
        return self.db.rows(query + ' ORDER BY created_at DESC,id DESC', params)

    def review(self, organisation_id, push_id, actor):
        row = self.get(organisation_id, push_id)
        payload, _, _ = self._payload(organisation_id, row['provider'], row['object_type'], row['local_ref'])
        if canonical_json(payload) != row['payload_json']:
            self._invalidate(organisation_id, push_id, actor)
            raise ValueError('prepared payload changed; prepare again')
        with self.db.transaction() as tx:
            changed = tx.execute("UPDATE sync_runs SET reviewed_at=?,reviewed_by=? WHERE organisation_id=? AND id=? "
                                 "AND direction='export' AND status IN ('Review Required','Failed')",
                                 (utc_now(), actor, organisation_id, push_id))
            if changed.rowcount != 1:
                raise ValueError('Only pending or failed pushes can be reviewed')
            audit(tx, organisation_id, actor, 'integration.push_reviewed', 'sync_run', push_id)
        return self.get(organisation_id, push_id)

    def _invalidate(self, organisation_id, push_id, actor):
        """Release an obsolete preparation so the bookkeeper can prepare again."""
        with self.db.transaction() as tx:
            tx.execute("UPDATE sync_runs SET status='Failed',reviewed_at=NULL,reviewed_by=NULL,"
                       "error_message='prepared payload changed; prepare again',completed_at=? "
                       "WHERE organisation_id=? AND id=? AND direction='export' AND status IN ('Review Required','Failed')",
                       (utc_now(), organisation_id, push_id))
            audit(tx, organisation_id, actor, 'integration.push_invalidated', 'sync_run', push_id)

    def execute(self, organisation_id, push_id, actor):
        row = self.get(organisation_id, push_id)
        if not row['reviewed_at']:
            raise ValueError('Push must be reviewed before execution')
        payload, _, batch_id = self._payload(organisation_id, row['provider'], row['object_type'], row['local_ref'])
        if canonical_json(payload) != row['payload_json']:
            self._invalidate(organisation_id, push_id, actor)
            raise ValueError('prepared payload changed; prepare again')
        with self.db.transaction() as tx:
            # Serialise claims for aliases of the same ledger source in PostgreSQL.
            if self.db.dialect == 'postgres':
                tx.one('SELECT id FROM posting_batches WHERE organisation_id=? AND id=? FOR UPDATE', (organisation_id, batch_id))
            if tx.one("SELECT id FROM sync_runs WHERE organisation_id=? AND provider=? AND object_type=? AND local_ref=? "
                      "AND direction='export' AND id<>? AND status IN ('Queued','Running','Review Required')",
                      (organisation_id, row['provider'], row['object_type'], row['local_ref'], push_id)):
                raise ValueError('a prepared push is already pending for this document')
            changed = tx.execute("UPDATE sync_runs SET status='Running',started_at=?,completed_at=NULL,error_message=NULL "
                                 "WHERE organisation_id=? AND id=? AND direction='export' "
                                 "AND status IN ('Review Required','Failed') AND reviewed_at IS NOT NULL",
                                 (utc_now(), organisation_id, push_id))
            refs = {batch_id, row['local_ref']}
            refs.update(r['id'] for r in tx.rows('SELECT id FROM pay_runs WHERE organisation_id=? AND posted_batch_id=?', (organisation_id, batch_id)))
            placeholders = ','.join('?' for _ in refs)
            if tx.one("SELECT id FROM external_mappings WHERE organisation_id=? AND provider=? AND object_type='gl_batch' "
                      f"AND direction='export' AND local_id IN ({placeholders})", (organisation_id, row['provider'], *sorted(refs))):
                raise ValueError('Document has already been pushed')
            if changed.rowcount != 1:
                raise ValueError('Push is already running or completed')
            if tx.one("SELECT id FROM sync_runs WHERE organisation_id=? AND provider=? AND direction='export' "
                      f"AND status='Running' AND id<>? AND local_ref IN ({placeholders})",
                      (organisation_id, row['provider'], push_id, *sorted(refs))):
                raise ValueError('Document push is already running')
            audit(tx, organisation_id, actor, 'integration.push_started', 'sync_run', push_id)
        try:
            connection = self.db.one('SELECT encrypted_credentials,config_json,status FROM integration_connections '
                                     'WHERE organisation_id=? AND provider=?', (organisation_id, row['provider']))
            if not connection or connection['status'] == 'Disconnected':
                raise ValueError('An enabled integration connection is required')
            credentials = self.integration.vault.decrypt(connection['encrypted_credentials']) if connection['encrypted_credentials'] else {}
            connector = connector_registry.connector_for(row['provider'], credentials=credentials, config=json.loads(connection['config_json']))
            # A posting request must never be retried silently by the HTTP layer.
            if hasattr(connector, 'retries'):
                connector.retries = 0
            record = json.loads(row['payload_json'], parse_float=Decimal)
            for line in record['lines']:
                line['debit'], line['credit'] = money(line['debit']), money(line['credit'])
                # Merit prefers account_code, so only send the resolved external code.
                line.pop('account_code', None)
            result = connector.push('gl_batch', [record])
            expected_count = (len(record['lines']) + 499) // 500 if row['provider'] == 'merit' else 1
            external_ids = [response.get('external_id') or (response.get('GLBId') if row['provider'] == 'merit' else None)
                            for response in result.records]
            if not result.ok or len(external_ids) != expected_count or any(value in (None, '') for value in external_ids):
                raise ProviderError('Provider did not acknowledge the GL batch with an external ID')
        except (ProviderError, ValueError, httpx.RequestError) as error:
            with self.db.transaction() as tx:
                tx.execute("UPDATE sync_runs SET status='Failed',error_message=?,conflict_count=conflict_count+1,completed_at=? "
                           "WHERE organisation_id=? AND id=? AND direction='export'", (str(error), utc_now(), organisation_id, push_id))
                audit(tx, organisation_id, actor, 'integration.push_failed', 'sync_run', push_id)
            return self.get(organisation_id, push_id)
        with self.db.transaction() as tx:
            # 'fastaccounts' is the schema's existing ownership value for local data.
            tx.execute("INSERT INTO external_mappings(id,organisation_id,provider,object_type,local_id,external_id,external_version,ownership,direction,updated_at) "
                       "VALUES (?,?,?,'gl_batch',?,?,?,'fastaccounts','export',?)",
                       (new_id(), organisation_id, row['provider'], row['local_ref'], str(external_ids[0]),
                        canonical_json({'external_ids': [str(value) for value in external_ids]}) if len(external_ids) > 1 else None, utc_now()))
            tx.execute("UPDATE sync_runs SET status='Completed',write_count=?,completed_at=? WHERE organisation_id=? AND id=? AND direction='export'",
                       (len(record['lines']), utc_now(), organisation_id, push_id))
            audit(tx, organisation_id, actor, 'integration.push_completed', 'sync_run', push_id)
        return self.get(organisation_id, push_id)
