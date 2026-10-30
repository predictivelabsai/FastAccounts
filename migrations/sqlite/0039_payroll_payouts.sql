CREATE TABLE payroll_payout_batches (
 id TEXT PRIMARY KEY, organisation_id TEXT NOT NULL, pay_run_id TEXT NOT NULL,
 payout_type TEXT NOT NULL CHECK(payout_type IN ('salary','advance','absence_pay','bonus','withholding')),
 payout_date TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Draft' CHECK(status IN ('Draft','Paid','Cancelled')),
 bank_account_id TEXT, paid_at TEXT, paid_by TEXT, posted_batch_id TEXT REFERENCES posting_batches(id),
 reversal_batch_id TEXT REFERENCES posting_batches(id), created_at TEXT NOT NULL,
 UNIQUE(organisation_id,id),
 FOREIGN KEY(organisation_id,pay_run_id) REFERENCES pay_runs(organisation_id,id)
);
CREATE TABLE payroll_payout_lines (
 id TEXT PRIMARY KEY, organisation_id TEXT NOT NULL, payout_batch_id TEXT NOT NULL,
 employee_id TEXT NOT NULL, amount NUMERIC(12,2) NOT NULL CHECK(amount > 0),
 iban TEXT, account_owner TEXT NOT NULL,
 UNIQUE(organisation_id,id), UNIQUE(organisation_id,payout_batch_id,employee_id),
 FOREIGN KEY(organisation_id,payout_batch_id) REFERENCES payroll_payout_batches(organisation_id,id),
 FOREIGN KEY(organisation_id,employee_id) REFERENCES employees(organisation_id,id)
);
CREATE INDEX idx_payroll_payout_run ON payroll_payout_batches(organisation_id,pay_run_id,status);
