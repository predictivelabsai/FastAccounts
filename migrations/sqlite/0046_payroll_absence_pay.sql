CREATE TABLE payroll_absence_pay (
  id TEXT PRIMARY KEY,
  organisation_id TEXT NOT NULL,
  absence_id TEXT NOT NULL,
  employee_id TEXT NOT NULL,
  method TEXT NOT NULL CHECK(method IN ('average','unchanged_salary','best_of','fixed_sum')),
  fixed_amount NUMERIC(14,2),
  gross NUMERIC(14,2) NOT NULL DEFAULT 0,
  breakdown_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','in_payout','paid')),
  payout_batch_id TEXT,
  payment_date TEXT NOT NULL,
  payment_month TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (organisation_id, absence_id),
  FOREIGN KEY (organisation_id, absence_id) REFERENCES payroll_absences(organisation_id,id),
  FOREIGN KEY (organisation_id, employee_id) REFERENCES employees(organisation_id,id),
  FOREIGN KEY (organisation_id, payout_batch_id) REFERENCES payroll_payout_batches(organisation_id,id),
  CHECK((method='fixed_sum' AND fixed_amount IS NOT NULL) OR (method!='fixed_sum' AND fixed_amount IS NULL))
);
CREATE INDEX idx_payroll_absence_pay_pending ON payroll_absence_pay(organisation_id,status,payment_date);