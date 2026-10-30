"""Tenant-filtered payroll bureau summary for the signed-in user."""
from datetime import date
from decimal import Decimal

from database import get_database
from payroll_payday import payday_for_period


class PayrollBureauOverviewService:
    def __init__(self, db=None):
        self.db = db or get_database()

    def for_user(self, email: str, *, today: date | None = None) -> list[dict]:
        today = today or date.today()
        period = today.strftime('%Y-%m')
        from payroll import declaration_due_date
        from payroll_rules import settlement_date
        from payroll_reports import _due_date as palk_due_date
        organisations = self.db.rows(
            "SELECT o.id,o.name,o.country_code,o.base_currency,m.role FROM organisations o "
            "JOIN memberships m ON m.organisation_id=o.id WHERE lower(m.email)=lower(?) "
            "AND o.active=1 ORDER BY o.name,o.id", (email.strip(),))
        result = []
        with self.db.transaction() as tx:
            for org in organisations:
                run = tx.one('SELECT id,status,settlement_date FROM pay_runs WHERE organisation_id=? AND period=? ORDER BY created_at DESC,id DESC LIMIT 1',
                             (org['id'], period))
                unpaid = tx.one(
                    "SELECT COALESCE(SUM(CASE WHEN CAST(i.net AS NUMERIC)-COALESCE(p.paid,0)-COALESCE(o.offsets,0)>0 "
                    "THEN CAST(i.net AS NUMERIC)-COALESCE(p.paid,0)-COALESCE(o.offsets,0) ELSE 0 END),0) amount "
                    "FROM pay_run_items i JOIN pay_runs r ON r.organisation_id=i.organisation_id AND r.id=i.pay_run_id "
                    "LEFT JOIN (SELECT b.organisation_id,b.pay_run_id,l.employee_id,SUM(l.amount) paid FROM payroll_payout_batches b "
                    "JOIN payroll_payout_lines l ON l.organisation_id=b.organisation_id AND l.payout_batch_id=b.id "
                    "WHERE b.status!='Cancelled' AND (b.payout_type!='advance' OR b.status='Paid') GROUP BY b.organisation_id,b.pay_run_id,l.employee_id) p "
                    "ON p.organisation_id=i.organisation_id AND p.pay_run_id=i.pay_run_id AND p.employee_id=i.employee_id "
                    "LEFT JOIN (SELECT b.organisation_id,b.pay_run_id,o.employee_id,SUM(o.amount) offsets FROM payroll_payout_batches b "
                    "JOIN payroll_receivable_offsets o ON o.organisation_id=b.organisation_id AND o.payout_batch_id=b.id "
                    "WHERE b.status!='Cancelled' AND o.status IN ('Proposed','Posted') GROUP BY b.organisation_id,b.pay_run_id,o.employee_id) o "
                    "ON o.organisation_id=i.organisation_id AND o.pay_run_id=i.pay_run_id AND o.employee_id=i.employee_id "
                    "WHERE i.organisation_id=? AND r.period=? AND r.status='Approved'",
                    (org['id'], period))
                apa = tx.one('SELECT created_at,status FROM tsd_apa_exports WHERE organisation_id=? ORDER BY created_at DESC,id DESC LIMIT 1',
                             (org['id'],))
                preparation = tx.one("SELECT id FROM sync_runs WHERE organisation_id=? AND provider='emta' "
                    "AND object_type='tsd' AND direction='export' AND status='Completed' AND cursor_before=? "
                    "ORDER BY created_at DESC,id DESC LIMIT 1", (org['id'], run['id'])) if run else None
                payday = payday_for_period(tx, org['id'], period)
                payout = tx.one("SELECT payout_date FROM payroll_payout_batches WHERE organisation_id=? AND pay_run_id=? "
                    "AND payout_type='salary' AND status!='Cancelled' ORDER BY payout_date,id LIMIT 1",
                    (org['id'], run['id'])) if run else None
                payment_date = settlement_date(period, salary_payout_date=payout['payout_date'] if payout else None,
                    payday_rule_date=(run.get('settlement_date') or payday) if run else payday)
                tsd_due = declaration_due_date(period, payment_date)
                result.append({**org, 'period': period, 'payday': payday.isoformat() if payday else None,
                    'run_status': run['status'] if run else 'none',
                    'unpaid_net_pay': str(Decimal(str(unpaid['amount'] or 0)).quantize(Decimal('0.01'))),
                    'last_apa_export_date': apa['created_at'] if apa else None,
                    'last_apa_export_status': apa['status'] if apa else None,
                    'open_blocking_findings': 0,
                    '_preparation_id': preparation['id'] if preparation else None,
                    'palk_due_date': palk_due_date(period), 'tsd_due_date': tsd_due.isoformat()})
        from tsd import TSDExportService
        for company in result:
            preparation_id = company.pop('_preparation_id')
            if preparation_id:
                try:
                    payouts = TSDExportService(self.db).apa_payouts_for_review(company['id'], preparation_id)
                    company['open_blocking_findings'] = sum(
                        1 for payout in payouts for finding in payout['findings'] if finding['blocking'])
                except (KeyError, ValueError):
                    pass
        return result
