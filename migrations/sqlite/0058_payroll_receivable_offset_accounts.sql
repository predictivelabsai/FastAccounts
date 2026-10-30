ALTER TABLE payroll_payout_lines ADD COLUMN requested_amount NUMERIC(12,2);
UPDATE payroll_payout_lines SET requested_amount=amount WHERE requested_amount IS NULL;
ALTER TABLE pay_run_items ADD COLUMN payout_net_delta NUMERIC(12,2);
ALTER TABLE payroll_employee_receivables ADD COLUMN posted_batch_id TEXT REFERENCES posting_batches(id);
INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role)
 SELECT id || '-PAYROLL_EMPLOYEE_RECEIVABLE',id,'2270','Employee payroll receivable','Asset','Debit','PAYROLL_EMPLOYEE_RECEIVABLE'
 FROM organisations WHERE country_code='EE'
 AND NOT EXISTS (SELECT 1 FROM accounts a WHERE a.organisation_id=organisations.id AND a.system_role='PAYROLL_EMPLOYEE_RECEIVABLE');
