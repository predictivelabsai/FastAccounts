from decimal import Decimal

from payroll import PayrollService
from payroll_reports import PayrollReportsService

ACTOR = 'owner@example.test'


def test_reports_use_frozen_tenant_scoped_payroll(db, ee_org):
    payroll = PayrollService(db)
    payroll.save_employee(ee_org['id'], actor=ACTOR, name='Full time', gross_salary='2000', email='full@example.test')
    payroll.save_employee(ee_org['id'], actor=ACTOR, name='Part time', gross_salary='500', fte='0.5', email='part@example.test')
    run = payroll.create_run(ee_org['id'], period='2026-04', actor=ACTOR)
    bonus = payroll.save_component_type(ee_org['id'], actor=ACTOR, name='Performance bonus', palk_row=6,
        direction='income', income_tax=True, social_tax=True, ui_employee=True, ui_employer=True,
        funded_pension=True, social_minimum=True)
    unassigned = payroll.save_component_type(ee_org['id'], actor=ACTOR, name='Unassigned allowance',
        palk_designation=None, direction='income', income_tax=True, social_tax=True, ui_employee=True,
        ui_employer=True, funded_pension=True, social_minimum=True)
    item = next(item for item in run['items'] if item['employee_name'] == 'Full time')
    payroll.update_item(ee_org['id'], run['id'], item['id'], actor=ACTOR,
        components=[{'type_id': bonus['id'], 'amount': '100'},
                    {'type_id': unassigned['id'], 'amount': '37.25'}])
    payroll.approve(ee_org['id'], run['id'], actor=ACTOR)
    reports = PayrollReportsService(db)

    annual = reports.annual_summary(ee_org['id'], 2026)
    assert {item['employee_name'] for item in annual} == {'Full time', 'Part time'}
    full_year = next(item for item in annual if item['employee_name'] == 'Full time')
    assert full_year['gross_total'] == '2137.25'
    assert full_year['months']['2026-04']['types']['Base pay'] == '2000.00'
    assert full_year['months']['2026-04']['types']['Performance bonus'] == '100.00'
    average = reports.average_pay(ee_org['id'], '2026-04', 6)
    assert next(item for item in average if item['employee_name'] == 'Full time')['average_monthly_gross'] == '356.21'

    palk = reports.statistics_palk(ee_org['id'], '2026-04')
    assert palk['due_date'] == '2026-05-18'
    assert palk['rows']['1'] == {'full_time': '0.00', 'part_time': '0.00'}
    assert palk['rows']['2'] == {'full_time': '0.00', 'part_time': '0.00'}
    assert Decimal(palk['rows']['3']['full_time']) > 0
    assert Decimal(palk['rows']['3']['part_time']) > 0
    assert palk['rows']['5'] == {'full_time': '2000.00', 'part_time': '500.00'}
    assert palk['rows']['6']['full_time'] == '100.00'
    assert palk['rows']['5']['full_time'] == '2000.00'
    assert palk['warning'] is True
    assert palk['unmapped_types'] == [{'name': 'Unassigned allowance', 'amount': '37.25'}]

    headcount = reports.yearly_headcount(ee_org['id'], 2026)
    assert headcount['average_headcount'] == '2'
    assert headcount['average_fte'] == '1.5'
    pay_list = reports.pay_list(ee_org['id'], '2026-04', '2026-04')
    assert {row['status'] for row in pay_list} == {'Unpaid'}
    assert reports.workbook('Pay list', pay_list).startswith(b'PK')

    other = reports.annual_summary('does-not-exist', 2026)
    assert other == []

class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {'ErrorCode': 0, 'MessageID': 'test-message'}


class _Transport:
    def __init__(self):
        self.payloads = []

    def post(self, url, *, json, headers):
        assert url == 'https://api.postmarkapp.com/email'
        self.payloads.append((json, headers))
        return _Response()


def test_payslip_email_uses_mock_transport_and_records_delivery(db, ee_org, monkeypatch):
    import base64
    from pypdf import PdfReader
    from io import BytesIO
    from payroll_delivery import PayrollDeliveryService

    monkeypatch.setenv('POSTMARK_API_TOKEN', 'test-token')
    monkeypatch.setenv('FROM_EMAIL', 'payroll@example.test')
    payroll = PayrollService(db)
    employee = payroll.save_employee(ee_org['id'], actor=ACTOR, name='Mail employee', gross_salary='2000', email='worker@example.test', report_language='en')
    run = payroll.create_run(ee_org['id'], period='2026-04', actor=ACTOR)
    transport = _Transport()
    delivery = PayrollDeliveryService(db)
    delivery.save_settings(ee_org['id'], {'sender_name': 'Payroll team', 'reply_to': 'reply@example.test', 'cc': 'copy@example.test'})

    result = delivery.send_payslips(ee_org['id'], run['id'], [employee['id']], actor=ACTOR, client=transport)
    assert result[0]['status'] == 'Sent'
    payload, headers = transport.payloads[0]
    assert payload['To'] == 'worker@example.test'
    assert payload['From'] == 'Payroll team <payroll@example.test>'
    assert payload['ReplyTo'] == 'reply@example.test'
    assert payload['Cc'] == 'copy@example.test'
    assert payload['Attachments'][0]['ContentType'] == 'application/pdf'
    attachment = payload['Attachments'][0]
    assert attachment['Name'].endswith('.pdf')
    pdf_text = PdfReader(BytesIO(base64.b64decode(attachment['Content']))).pages[0].extract_text()
    assert 'PAYSLIP 2026-04' in pdf_text
    assert delivery.history(ee_org['id'], run['id'])[0]['status'] == 'Sent'

def test_review_pack_contains_pay_list_and_optional_payslip(db, ee_org, monkeypatch):
    import base64
    from payroll_delivery import PayrollDeliveryService

    monkeypatch.setenv('POSTMARK_API_TOKEN', 'test-token')
    monkeypatch.setenv('FROM_EMAIL', 'payroll@example.test')
    payroll = PayrollService(db)
    payroll.save_employee(ee_org['id'], actor=ACTOR, name='Review employee', gross_salary='2000', email='worker@example.test')
    run = payroll.create_run(ee_org['id'], period='2026-04', actor=ACTOR)
    transport = _Transport()
    delivery = PayrollDeliveryService(db)
    result = delivery.send_for_review(ee_org['id'], run['id'], 'reviewer@example.test', actor=ACTOR, client=transport)

    payload = transport.payloads[0][0]
    assert result['status'] == 'Sent'
    assert payload['To'] == 'reviewer@example.test'
    assert len(payload['Attachments']) == 2
    types = {a['ContentType'] for a in payload['Attachments']}
    assert types == {'application/pdf', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}
    decoded = [base64.b64decode(a['Content']) for a in payload['Attachments']]
    assert any(content.startswith(b'%PDF') for content in decoded)
    assert any(content.startswith(b'PK') for content in decoded)
    assert delivery.history(ee_org['id'], run['id'])[0]['kind'] == 'review'

