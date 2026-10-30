from io import BytesIO

import pytest
from openpyxl import load_workbook
from fastapi.testclient import TestClient

from employee_details import EmployeeDetailsError, birth_date_from_personal_code
from payroll import PayrollService
from excel_export import employees_workbook

ACTOR = 'owner@example.test'
IBAN = 'GB82WEST12345698765432'


def test_contact_details_api_export_and_audit(db, ee_org, monkeypatch):
    monkeypatch.setenv('FASTACCOUNTS_DB', db.path)
    monkeypatch.setenv('DB_URL', '')
    from api_app import api
    client = TestClient(api)
    base = f"/organisations/{ee_org['id']}/employees"
    headers = {'X-Test-User': ACTOR}
    details = dict(name='Synthetic employee', gross_salary='2000', phone='+372 555 0100',
                   iban='gb82 west 1234 5698 7654 32', bank_account_owner='Synthetic owner',
                   address='Synthetic street 1', personal_id='49001010018')
    response = client.post(base, headers=headers, json=details)
    assert response.status_code == 201, response.text
    person = response.json()
    assert person['iban'] == IBAN and person['date_of_birth'] == '1990-01-01'
    updated = client.patch(base + '/' + person['id'], headers=headers,
                           json={'date_of_birth': '1989-12-31', 'phone': None})
    assert updated.status_code == 200, updated.text
    assert updated.json()['date_of_birth'] == '1989-12-31' and updated.json()['phone'] is None
    sheet = load_workbook(BytesIO(employees_workbook(ee_org, [updated.json()]))).active
    values = dict(zip((cell.value for cell in sheet[1]), (cell.value for cell in sheet[2])))
    assert values['IBAN'] == IBAN
    assert values['Bank account owner'] == 'Synthetic owner'
    assert values['Address'] == details['address']
    assert values['Date of birth'] == '1989-12-31'
    assert db.scalar("SELECT COUNT(*) FROM audit_events WHERE organisation_id=? AND object_id=? "
                     "AND action IN ('payroll.employee.created','payroll.employee.updated')",
                     (ee_org['id'], person['id'])) == 2


@pytest.mark.parametrize('iban', ['GB83WEST12345698765432', 'EE00', '=SUM(A1)', 'GB82WEST1234569876543!'])
def test_invalid_iban_is_atomic(db, ee_org, iban):
    with pytest.raises(EmployeeDetailsError, match='checksum'):
        PayrollService(db).save_employee(ee_org['id'], actor=ACTOR, name='Invalid', gross_salary='2000', iban=iban)
    assert PayrollService(db).employees(ee_org['id']) == []


@pytest.mark.parametrize('code,expected', [('49001010018', '1990-01-01'), ('38002020029', '1980-02-02'),
                                         ('not-an-id', None), ('49913319999', None)])
def test_estonian_birth_date_derivation(code, expected):
    assert birth_date_from_personal_code(code) == expected

