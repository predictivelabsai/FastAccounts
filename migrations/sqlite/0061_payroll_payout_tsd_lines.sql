CREATE TABLE payroll_payout_tsd_lines (
 id TEXT PRIMARY KEY,
 organisation_id TEXT NOT NULL,
 payout_batch_id TEXT NOT NULL,
 pay_run_item_id TEXT NOT NULL,
 payment_type INTEGER NOT NULL,
 payment_type_name TEXT NOT NULL,
 amount NUMERIC(20,2) NOT NULL,
 social_tax_base NUMERIC(20,2) NOT NULL,
 social_tax NUMERIC(20,2) NOT NULL,
 social_tax_minimum_topup NUMERIC(20,2) NOT NULL,
 ui_employee_base NUMERIC(20,2) NOT NULL,
 ui_employee NUMERIC(20,2) NOT NULL,
 ui_employer_base NUMERIC(20,2) NOT NULL,
 ui_employer NUMERIC(20,2) NOT NULL,
 ii_pillar_base NUMERIC(20,2) NOT NULL,
 ii_pillar NUMERIC(20,2) NOT NULL,
 exemption_610 NUMERIC(20,2) NOT NULL,
 taxable_amount NUMERIC(20,2) NOT NULL,
 income_tax NUMERIC(20,2) NOT NULL,
 UNIQUE(organisation_id,payout_batch_id,pay_run_item_id,payment_type),
 FOREIGN KEY(organisation_id,payout_batch_id) REFERENCES payroll_payout_batches(organisation_id,id),
 FOREIGN KEY(organisation_id,pay_run_item_id) REFERENCES pay_run_items(organisation_id,id)
);
-- SQLITE_PAYOUT_TSD_IMMUTABILITY
CREATE TRIGGER guard_payroll_payout_tsd_update BEFORE UPDATE ON payroll_payout_tsd_lines
BEGIN SELECT RAISE(ABORT,'approved payout TSD lines are immutable'); END;
CREATE TRIGGER guard_payroll_payout_tsd_delete BEFORE DELETE ON payroll_payout_tsd_lines
BEGIN SELECT RAISE(ABORT,'approved payout TSD lines are immutable'); END;
