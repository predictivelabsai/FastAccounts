"""Offline e-MTA TÖR CSV review staging."""
import csv
import hashlib
import io
import json
from decimal import Decimal, InvalidOperation

from core_utils import audit, new_id, utc_now

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
        return record
