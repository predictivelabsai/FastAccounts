"""Offline e-MTA TÖR CSV review staging."""
import csv
import hashlib
import io
import json
from decimal import Decimal, InvalidOperation

from core_utils import audit, new_id, utc_now
from payroll import PayrollConflict, PayrollService

ALIASES = {
    'personal_id': {'personalcode', 'isikukood', 'isikukoodnumber'},
    'name': {'name', 'nimi', 'employeesname', 'tootajanimi'},
    'start_date': {'startdate', 'alguskuupaev', 'alguskuupäev', 'kehtivusalates'},
    'end_date': {'enddate', 'lopukuupaev', 'lõppkuupäev', 'kehtivuskuni'},
    'contract_type': {'typeofwork', 'typeofcontract', 'contracttype', 'toolepinguliik', 'töölepinguliik', 'tootamiseviis'},
    'position': {'position', 'ametikoht', 'occupation'},
    'occupation_code': {'occupationcode', 'ametialakood', 'ametialagrupp'},
    'fte': {'workload', 'fte', 'koormus', 'tooajamaht'},
    'workplace_address': {'workplaceaddress', 'tookohaaadress', 'töökohaaadress', 'tegemiskohaaadress'},
}
TYPES = {
    'employment': 'employment', 'tooleping': 'employment', 'tööleping': 'employment', 'toolepinguline': 'employment', 'toolepinguleping': 'employment',
    'boardmember': 'board_member', 'juhatuseliige': 'board_member', 'juhatuseliimeleping': 'board_member',
    'services': 'services', 'toovotuleping': 'services', 'vooleping': 'services',
    'other': 'other', 'muu': 'other', 'none': 'none', 'lepingpuudub': 'none',
}
PARSE_ERRORS = {
    'Personal code and name are required',
    'Start Date must use YYYY-MM-DD',
    'End Date must use YYYY-MM-DD',
    'Unsupported contract type',
    'Workload must be greater than 0 and at most 1, or a percentage',
}


def _key(value):
    return ''.join(ch for ch in str(value).casefold() if ch.isalnum())


def parse_tor_csv(content: bytes):
    try:
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('TÖR CSV must be UTF-8 encoded') from exc
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError('CSV header row is missing')
    columns = {_key(header): header for header in reader.fieldnames}
    mapping = {field: next((columns[key] for key in aliases if key in columns), None)
               for field, aliases in ALIASES.items()}
    required = ('personal_id', 'name', 'start_date', 'contract_type')
    if any(not mapping[field] for field in required):
        raise ValueError('CSV needs personal code, name, start date and contract type columns')
    rows = []
    for number, raw in enumerate(reader, 2):
        row = {field: (raw.get(column) or '').strip() if column else '' for field, column in mapping.items()}
        errors = []
        if not row['personal_id'] or not row['name']:
            errors.append('Personal code and name are required')
        for field in ('start_date', 'end_date'):
            if row[field]:
                try:
                    from datetime import date
                    row[field] = date.fromisoformat(row[field]).isoformat()
                except ValueError:
                    errors.append(f'{field.replace("_", " ").title()} must use YYYY-MM-DD')
        kind = TYPES.get(_key(row['contract_type']))
        if not kind:
            errors.append('Unsupported contract type')
        row['contract_type'] = kind
        if row['fte']:
            try:
                workload = Decimal(row['fte'].rstrip('%')) / (Decimal('100') if row['fte'].endswith('%') else Decimal('1'))
                if not workload.is_finite() or not 0 < workload <= 1:
                    raise ValueError
                row['fte'] = format(workload, 'f')
            except (ValueError, InvalidOperation):
                errors.append('Workload must be greater than 0 and at most 1, or a percentage')
        else:
            row['fte'] = None
        rows.append({'row_number': number, **row, 'errors': errors})
    return rows


class TORImportService:
    def __init__(self, db):
        self.db = db
        self.payroll = PayrollService(db)

    def stage(self, organisation_id, content: bytes, *, actor):
        rows = parse_tor_csv(content)
        source_hash = hashlib.sha256(content).hexdigest()
        import_id = new_id()
        with self.db.transaction() as tx:
            existing = tx.one('SELECT id FROM payroll_tor_imports WHERE organisation_id=? AND source_hash=?',
                              (organisation_id, source_hash))
            if existing:
                return self.get(organisation_id, existing['id'], tx=tx)
            tx.execute("INSERT INTO payroll_tor_imports(id,organisation_id,source_hash,status,assumptions,created_by,created_at) VALUES (?,?,?,'review',?,?,?)",
                       (import_id, organisation_id, source_hash,
                        json.dumps(['UTF-8 CSV; ISO YYYY-MM-DD dates; workload is 0..1 or percent; unrecognised contract types require manual correction.']),
                        actor, utc_now()))
            for row in rows:
                tx.execute('INSERT INTO payroll_tor_import_rows(id,organisation_id,import_id,row_number,personal_id,source_name,start_date,end_date,contract_type,position,occupation_code,fte,workplace_address,errors) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (new_id(), organisation_id, import_id, row['row_number'], row['personal_id'], row['name'],
                            row['start_date'] or None, row['end_date'] or None, row['contract_type'], row['position'] or None,
                            row['occupation_code'] or None, row['fte'], row['workplace_address'] or None,
                            json.dumps(row['errors'], ensure_ascii=False)))
            audit(tx, organisation_id, actor, 'payroll.tor_import.staged', 'payroll_tor_import', import_id)
            return self.get(organisation_id, import_id, tx=tx)

    def get(self, organisation_id, import_id, *, tx=None):
        if tx is None:
            with self.db.transaction() as owned:
                return self.get(organisation_id, import_id, tx=owned)
        record = tx.one('SELECT * FROM payroll_tor_imports WHERE organisation_id=? AND id=?', (organisation_id, import_id))
        if not record:
            raise KeyError('TÖR import not found')
        record['assumptions'] = json.loads(record['assumptions'])
        record['rows'] = tx.rows('SELECT * FROM payroll_tor_import_rows WHERE organisation_id=? AND import_id=? ORDER BY row_number',
                                 (organisation_id, import_id))
        for row in record['rows']:
            row['errors'] = json.loads(row['errors'])
            if row['personal_id']:
                matches = tx.rows('SELECT id,name FROM employees WHERE organisation_id=? AND personal_id=? ORDER BY id',
                                  (organisation_id, row['personal_id']))
                row['match_conflict'] = 'Personal code matches more than one employee' if len(matches) > 1 else None
                row['matched_employee_id'] = matches[0]['id'] if len(matches) == 1 else None
                row['matched_employee_name'] = matches[0]['name'] if len(matches) == 1 else None
        return record

    def apply(self, organisation_id, import_id, *, actor, row_ids=None):
        requested = set(row_ids or [])
        result = {'applied': 0, 'updated': 0, 'unchanged': 0, 'failed': 0, 'outcomes': []}
        with self.db.transaction() as tx:
            tx.execute('UPDATE organisations SET name=name WHERE id=?', (organisation_id,))
            record = tx.one('SELECT * FROM payroll_tor_imports WHERE organisation_id=? AND id=?',
                            (organisation_id, import_id))
            if not record:
                raise KeyError('TÖR import not found')
            rows = tx.rows('SELECT * FROM payroll_tor_import_rows WHERE organisation_id=? AND import_id=? ORDER BY row_number',
                           (organisation_id, import_id))
            for row in rows:
                if requested and row['id'] not in requested:
                    continue
                if row['applied_contract_id']:
                    result['unchanged'] += 1
                    result['outcomes'].append({'row_id': row['id'], 'outcome': 'unchanged',
                                               'contract_id': row['applied_contract_id']})
                    continue
                # Retry transient match and employee conflicts after the tenant
                # fixes source data. Keep only errors that originate in the CSV.
                errors = [error for error in json.loads(row['errors']) if error in PARSE_ERRORS]
                matches = tx.rows('SELECT * FROM employees WHERE organisation_id=? AND personal_id=? ORDER BY id',
                                  (organisation_id, row['personal_id'])) if row['personal_id'] else []
                if len(matches) > 1:
                    errors.append('Personal code matches more than one employee')
                if errors:
                    tx.execute('UPDATE payroll_tor_import_rows SET errors=? WHERE organisation_id=? AND id=?',
                               (json.dumps(list(dict.fromkeys(errors)), ensure_ascii=False), organisation_id, row['id']))
                    result['failed'] += 1
                    result['outcomes'].append({'row_id': row['id'], 'outcome': 'failed', 'reason': errors[-1]})
                    continue
                try:
                    employee = matches[0] if matches else None
                    employee_existed = employee is not None
                    if employee:
                        employee_id = employee['id']
                        if employee['name'] != row['source_name']:
                            self.payroll.save_employee(organisation_id, employee_id=employee_id, actor=actor,
                                                       tx=tx, name=row['source_name'])
                    else:
                        # No salary is provided by TÖR. This employee waits for an
                        # agreement and is excluded from regular payroll until then.
                        employee = self.payroll.save_employee(
                            organisation_id, actor=actor, tx=tx, name=row['source_name'],
                            personal_id=row['personal_id'], pay_basis='income_line',
                            fte=row['fte'] or '1', employment_start_date=row['start_date'],
                        )
                        employee_id = employee['id']
                    existing_contract = tx.one(
                        'SELECT * FROM payroll_contracts WHERE organisation_id=? AND employee_id=? AND contract_type=? AND start_date=?',
                        (organisation_id, employee_id, row['contract_type'], row['start_date']),
                    )
                    if existing_contract:
                        contract_id = existing_contract['id']
                        tx.execute('UPDATE payroll_contracts SET end_date=?,workplace_address=? WHERE organisation_id=? AND id=?',
                                   (row['end_date'], row['workplace_address'], organisation_id, contract_id))
                    else:
                        contract_id = new_id()
                        tx.execute('INSERT INTO payroll_contracts(id,organisation_id,employee_id,contract_type,start_date,end_date,workplace_address,created_at) '
                                   'VALUES (?,?,?,?,?,?,?,?)',
                                   (contract_id, organisation_id, employee_id, row['contract_type'], row['start_date'],
                                    row['end_date'], row['workplace_address'], utc_now()))
                    if row['position']:
                        position = tx.one('SELECT id FROM payroll_contract_positions WHERE organisation_id=? AND contract_id=? AND start_date=?',
                                          (organisation_id, contract_id, row['start_date']))
                        if position:
                            tx.execute('UPDATE payroll_contract_positions SET position=?,occupation_code=? WHERE organisation_id=? AND id=?',
                                       (row['position'], row['occupation_code'], organisation_id, position['id']))
                        else:
                            tx.execute('INSERT INTO payroll_contract_positions(id,organisation_id,contract_id,start_date,position,occupation_code) VALUES (?,?,?,?,?,?)',
                                       (new_id(), organisation_id, contract_id, row['start_date'], row['position'], row['occupation_code']))
                    tx.execute('UPDATE payroll_tor_import_rows SET applied_contract_id=?,errors=? WHERE organisation_id=? AND id=?',
                               (contract_id, '[]', organisation_id, row['id']))
                    audit(tx, organisation_id, actor, 'payroll.tor_row.applied', 'payroll_tor_import_row', row['id'],
                          {'employee_id': employee_id, 'contract_id': contract_id})
                    key = 'updated' if employee_existed else 'applied'
                    result[key] += 1
                    result['outcomes'].append({'row_id': row['id'], 'outcome': key,
                                               'employee_id': employee_id, 'contract_id': contract_id})
                except (ValueError, KeyError, PayrollConflict) as exc:
                    reason = str(exc)
                    tx.execute('UPDATE payroll_tor_import_rows SET errors=? WHERE organisation_id=? AND id=?',
                               (json.dumps([reason], ensure_ascii=False), organisation_id, row['id']))
                    result['failed'] += 1
                    result['outcomes'].append({'row_id': row['id'], 'outcome': 'failed', 'reason': reason})
            pending = tx.scalar('SELECT COUNT(*) FROM payroll_tor_import_rows WHERE organisation_id=? AND import_id=? AND applied_contract_id IS NULL',
                                (organisation_id, import_id))
            if pending == 0:
                tx.execute("UPDATE payroll_tor_imports SET status='applied' WHERE organisation_id=? AND id=?",
                           (organisation_id, import_id))
            if result['applied'] or result['updated']:
                audit(tx, organisation_id, actor, 'payroll.tor_import.applied', 'payroll_tor_import', import_id,
                      {key: result[key] for key in ('applied', 'updated', 'unchanged', 'failed')})
        return result
