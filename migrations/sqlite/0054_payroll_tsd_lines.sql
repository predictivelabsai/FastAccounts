CREATE TABLE pay_item_tsd_lines (
 id TEXT PRIMARY KEY,
 organisation_id TEXT NOT NULL,
 source_kind TEXT NOT NULL CHECK(source_kind IN ('pay_run_item','absence_pay')),
 source_id TEXT NOT NULL,
 payout_batch_id TEXT,
 payment_type INTEGER NOT NULL,
 payment_type_name TEXT NOT NULL,
 amount NUMERIC(20,2) NOT NULL,
 social_tax_base NUMERIC(20,2) NOT NULL,
 social_tax NUMERIC(20,2) NOT NULL,
 social_tax_minimum_topup NUMERIC(20,2) NOT NULL DEFAULT 0,
 ui_employee_base NUMERIC(20,2) NOT NULL,
 ui_employee NUMERIC(20,2) NOT NULL,
 ui_employer_base NUMERIC(20,2) NOT NULL,
 ui_employer NUMERIC(20,2) NOT NULL,
 ii_pillar_base NUMERIC(20,2) NOT NULL,
 ii_pillar NUMERIC(20,2) NOT NULL,
 exemption_610 NUMERIC(20,2) NOT NULL DEFAULT 0,
 taxable_amount NUMERIC(20,2) NOT NULL,
 income_tax NUMERIC(20,2) NOT NULL,
 FOREIGN KEY(organisation_id) REFERENCES organisations(id),
 FOREIGN KEY(organisation_id,payout_batch_id) REFERENCES payroll_absence_payout_batches(organisation_id,id)
);
CREATE INDEX idx_pay_item_tsd_lines_source ON pay_item_tsd_lines(organisation_id,source_kind,source_id,payout_batch_id,payment_type);
CREATE UNIQUE INDEX idx_pay_item_tsd_lines_run_unique ON pay_item_tsd_lines(organisation_id,source_id,payment_type) WHERE source_kind='pay_run_item';
CREATE UNIQUE INDEX idx_pay_item_tsd_lines_absence_unique ON pay_item_tsd_lines(organisation_id,source_id,payout_batch_id,payment_type) WHERE source_kind='absence_pay';
CREATE TRIGGER guard_pay_item_tsd_lines_update BEFORE UPDATE ON pay_item_tsd_lines BEGIN SELECT RAISE(ABORT,'approved TSD lines are immutable'); END;
CREATE TRIGGER guard_pay_item_tsd_lines_delete BEFORE DELETE ON pay_item_tsd_lines BEGIN SELECT RAISE(ABORT,'approved TSD lines are immutable'); END;
