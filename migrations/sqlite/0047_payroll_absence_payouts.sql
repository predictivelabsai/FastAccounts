CREATE TABLE payroll_absence_payout_batches (
 id TEXT PRIMARY KEY, organisation_id TEXT NOT NULL, payout_date TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'Draft' CHECK(status IN ('Draft','Approved','Paid','Cancelled')),
 bank_account_id TEXT, approved_at TEXT, approved_by TEXT, paid_at TEXT, paid_by TEXT,
 posted_batch_id TEXT REFERENCES posting_batches(id), paid_batch_id TEXT REFERENCES posting_batches(id),
 reversal_batch_id TEXT REFERENCES posting_batches(id), created_at TEXT NOT NULL,
 UNIQUE(organisation_id,id),
 FOREIGN KEY(organisation_id) REFERENCES organisations(id),
 FOREIGN KEY(organisation_id,bank_account_id) REFERENCES bank_accounts(organisation_id,id)
);
ALTER TABLE payroll_absence_pay ADD COLUMN absence_payout_batch_id TEXT REFERENCES payroll_absence_payout_batches(id);
ALTER TABLE payroll_absence_pay ADD COLUMN calculation_json TEXT NOT NULL DEFAULT '{}';
CREATE INDEX idx_payroll_absence_payout_status ON payroll_absence_payout_batches(organisation_id,status,payout_date);
CREATE INDEX idx_payroll_absence_pay_batch ON payroll_absence_pay(organisation_id,absence_payout_batch_id,status);
