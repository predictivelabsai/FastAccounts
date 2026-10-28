CREATE TABLE payroll_employee_receivables (
 id TEXT PRIMARY KEY,
 organisation_id TEXT NOT NULL,
 employee_id TEXT NOT NULL,
 source_run_id TEXT NOT NULL,
 amount NUMERIC(12,2) NOT NULL CHECK(amount > 0),
 remaining_amount NUMERIC(12,2) NOT NULL CHECK(remaining_amount >= 0 AND remaining_amount <= amount),
 status TEXT NOT NULL DEFAULT 'Open' CHECK(status IN ('Open','Settled')),
 created_at TEXT NOT NULL,
 created_by TEXT NOT NULL,
 UNIQUE(organisation_id,id),
 UNIQUE(organisation_id,source_run_id,employee_id),
 FOREIGN KEY(organisation_id,employee_id) REFERENCES employees(organisation_id,id),
 FOREIGN KEY(organisation_id,source_run_id) REFERENCES pay_runs(organisation_id,id)
);
CREATE INDEX idx_payroll_receivables_open ON payroll_employee_receivables(organisation_id,employee_id,status,created_at,id);

CREATE TABLE payroll_receivable_offsets (
 id TEXT PRIMARY KEY,
 organisation_id TEXT NOT NULL,
 receivable_id TEXT NOT NULL,
 payout_batch_id TEXT NOT NULL,
 employee_id TEXT NOT NULL,
 amount NUMERIC(12,2) NOT NULL CHECK(amount > 0),
 status TEXT NOT NULL DEFAULT 'Proposed' CHECK(status IN ('Proposed','Posted','Cancelled')),
 created_at TEXT NOT NULL,
 created_by TEXT NOT NULL,
 confirmed_at TEXT,
 confirmed_by TEXT,
 posting_batch_id TEXT REFERENCES posting_batches(id),
 UNIQUE(organisation_id,id),
 UNIQUE(organisation_id,receivable_id,payout_batch_id),
 FOREIGN KEY(organisation_id,receivable_id) REFERENCES payroll_employee_receivables(organisation_id,id),
 FOREIGN KEY(organisation_id,payout_batch_id) REFERENCES payroll_payout_batches(organisation_id,id),
 FOREIGN KEY(organisation_id,employee_id) REFERENCES employees(organisation_id,id)
);
CREATE INDEX idx_payroll_receivable_offsets_payout ON payroll_receivable_offsets(organisation_id,payout_batch_id,status);
