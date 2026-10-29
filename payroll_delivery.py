"""Payroll email delivery with per-recipient audit history."""
import base64
import os
from email.utils import parseaddr

from core_utils import new_id, utc_now
from database import get_database
from payroll import PayrollService

LANGUAGES = {'et', 'en', 'lv', 'lt'}


class PayrollDeliveryService:
    def __init__(self, db=None, *, client_factory=None):
        self.db = db or get_database()
        self.client_factory = client_factory

    def settings(self, organisation_id):
        with self.db.transaction() as tx:
            row = tx.one('SELECT * FROM payroll_report_settings WHERE organisation_id=?', (organisation_id,))
            org = tx.one('SELECT language FROM organisations WHERE id=?', (organisation_id,))
        return row or {'organisation_id': organisation_id, 'sender_name': '', 'reply_to': '', 'cc': '', 'default_language': (org or {}).get('language') or 'et'}

    def save_settings(self, organisation_id, data):
        values = {k: str(data.get(k) or '').strip() for k in ('sender_name', 'reply_to', 'cc')}
        if len(values['sender_name']) > 120 or len(values['reply_to']) > 254 or len(values['cc']) > 1000:
            raise ValueError('Payroll email settings exceed the allowed length')
        for address in [values['reply_to'], *[v.strip() for v in values['cc'].split(',') if v.strip()]]:
            if address and (parseaddr(address)[1] != address or '@' not in address):
                raise ValueError('Enter valid reply-to and CC email addresses')
        with self.db.transaction() as tx:
            tx.execute('INSERT INTO payroll_report_settings(organisation_id,sender_name,reply_to,cc) VALUES(?,?,?,?) '
                       'ON CONFLICT(organisation_id) DO UPDATE SET sender_name=excluded.sender_name,reply_to=excluded.reply_to,cc=excluded.cc',
                       (organisation_id, *values.values()))
        return self.settings(organisation_id)

    def history(self, organisation_id, run_id):
        with self.db.transaction() as tx:
            if not tx.one('SELECT id FROM pay_runs WHERE organisation_id=? AND id=?', (organisation_id, run_id)):
                raise KeyError('Pay run not found')
            return tx.rows('SELECT * FROM payroll_deliveries WHERE organisation_id=? AND pay_run_id=? ORDER BY created_at DESC,id', (organisation_id, run_id))

    def send_payslips(self, organisation_id, run_id, employee_ids, *, actor, client=None):
        if not employee_ids or len(set(employee_ids)) != len(employee_ids):
            raise ValueError('Select one or more unique employees')
        with self.db.transaction() as tx:
            run = PayrollService(self.db)._run(tx, organisation_id, run_id)
        selected = set(employee_ids)
        items = [item for item in run['items'] if item['employee_id'] in selected]
        if len(items) != len(selected):
            raise KeyError('One or more selected employees are not in this pay run')
        with self.db.transaction() as tx:
            org = tx.one('SELECT * FROM organisations WHERE id=?', (organisation_id,))
            employees = {r['id']: r for r in tx.rows('SELECT id,email,report_language FROM employees WHERE organisation_id=? AND id IN (' + ','.join('?' for _ in selected) + ')', (organisation_id, *selected))}
        results = []
        for item in items:
            emp = employees[item['employee_id']]
            results.append(self._deliver(organisation_id, run_id, emp['id'], 'payslip', emp.get('email') or '',
                f"Payslip {run['period']}", f"Please find your payslip for {run['period']} attached.",
                PayrollService(self.db).payslip_pdf(organisation_id, run_id, emp['id'], language=emp.get('report_language') or (org.get('language') or 'et')), f"payslip-{run['period']}.pdf", actor, org, client))
        return results

    def send_for_review(self, organisation_id, run_id, recipient, *, include_payslips=True, actor, client=None):
        recipient = str(recipient or '').strip()
        if parseaddr(recipient)[1] != recipient or '@' not in recipient:
            raise ValueError('Enter a valid reviewer email address')
        with self.db.transaction() as tx:
            run = PayrollService(self.db)._run(tx, organisation_id, run_id)
        org = self.settings(organisation_id)
        from excel_export import pay_run_workbook
        attachments = [{'Name': f"pay-list-{run['period']}.xlsx", 'Content': base64.b64encode(pay_run_workbook({'name': 'Pay list'}, run, run['items'], None)).decode(), 'ContentType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}]
        if include_payslips:
            attachments.append({'Name': f"payslips-{run['period']}.pdf", 'Content': base64.b64encode(PayrollService(self.db).payslips_pdf(organisation_id, run_id)).decode(), 'ContentType': 'application/pdf'})
        return self._deliver(organisation_id, run_id, None, 'review', recipient, f"Payroll for review: {run['period']}", f"Please review the payroll for {run['period']}.", None, f"{run['period']} review pack", actor, org, client, attachments=attachments)

    def retry(self, organisation_id, delivery_id, *, actor, client=None):
        with self.db.transaction() as tx:
            previous = tx.one('SELECT * FROM payroll_deliveries WHERE organisation_id=? AND id=?', (organisation_id, delivery_id))
        if not previous:
            raise KeyError('Payroll delivery not found')
        if previous['status'] == 'Sent':
            raise ValueError('A sent payroll delivery cannot be retried')
        if previous['kind'] == 'payslip':
            return self.send_payslips(organisation_id, previous['pay_run_id'], [previous['employee_id']], actor=actor, client=client)
        return self.send_for_review(organisation_id, previous['pay_run_id'], previous['recipient'], actor=actor, client=client)
    def _deliver(self, organisation_id, run_id, employee_id, kind, recipient, subject, body, pdf, filename, actor, org, client, attachments=None):
        delivery_id = new_id(); now = utc_now()
        status, error = 'Failed', None
        try:
            if not recipient:
                raise ValueError('Employee has no email address')
            token = os.getenv('POSTMARK_API_TOKEN', '').strip(); from_email = os.getenv('FROM_EMAIL', '').strip()
            if not token or not from_email:
                raise RuntimeError('Email delivery is not connected')
            if attachments is None:
                attachments = [{'Name': filename, 'Content': base64.b64encode(pdf).decode(), 'ContentType': 'application/pdf'}]
            settings = self.settings(organisation_id)
            payload = {'From': f"{settings['sender_name']} <{from_email}>" if settings['sender_name'] else from_email,
                'To': recipient, 'Subject': subject, 'TextBody': body, 'MessageStream': 'outbound', 'Attachments': attachments}
            if settings.get('reply_to'): payload['ReplyTo'] = settings['reply_to']
            if settings.get('cc'): payload['Cc'] = settings['cc']
            if self.client_factory:
                http = self.client_factory()
            elif client is not None:
                http = client
            else:
                import httpx
                http = httpx.Client(timeout=20)
            response = http.post('https://api.postmarkapp.com/email', json=payload, headers={'X-Postmark-Server-Token': token, 'Accept': 'application/json'})
            response.raise_for_status(); result = response.json()
            if result.get('ErrorCode', 0): raise RuntimeError(result.get('Message') or 'Email provider rejected the message')
            status = 'Sent'
        except Exception as exc:
            error = str(exc)[:500]
        with self.db.transaction() as tx:
            tx.execute('INSERT INTO payroll_deliveries(id,organisation_id,pay_run_id,employee_id,kind,recipient,status,subject,error,created_at,sent_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (delivery_id, organisation_id, run_id, employee_id, kind, recipient, status, subject, error, now, now if status == 'Sent' else None))
            row = tx.one('SELECT * FROM payroll_deliveries WHERE id=? AND organisation_id=?', (delivery_id, organisation_id))
        return row
