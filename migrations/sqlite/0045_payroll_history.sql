CREATE TABLE payroll_leave_entitlements (
  id TEXT PRIMARY KEY,
  organisation_id TEXT NOT NULL,
  employee_id TEXT NOT NULL,
  effective_from TEXT NOT NULL,
  days_per_year NUMERIC(8,2) NOT NULL CHECK(days_per_year >= 0),
  created_at TEXT NOT NULL,
  FOREIGN KEY (organisation_id, employee_id) REFERENCES employees(organisation_id, id),
  UNIQUE (organisation_id, employee_id, effective_from)
);
CREATE TABLE payroll_leave_openings (
  organisation_id TEXT NOT NULL,
  employee_id TEXT NOT NULL,
  cutover_date TEXT NOT NULL,
  unused_days NUMERIC(8,2) NOT NULL CHECK(unused_days >= 0),
  source TEXT NOT NULL DEFAULT 'manual',
  reviewed_at TEXT,
  reviewed_by TEXT,
  PRIMARY KEY (organisation_id, employee_id, cutover_date),
  FOREIGN KEY (organisation_id, employee_id) REFERENCES employees(organisation_id, id)
);
CREATE TABLE payroll_historical_earnings (
  id TEXT PRIMARY KEY,
  organisation_id TEXT NOT NULL,
  employee_id TEXT NOT NULL,
  earning_month TEXT NOT NULL,
  wage_total NUMERIC(14,2) NOT NULL CHECK(wage_total >= 0),
  worked_days NUMERIC(8,2),
  unpaid_absence_days NUMERIC(8,2) NOT NULL DEFAULT 0 CHECK(unpaid_absence_days >= 0),
  source_key TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'Pending' CHECK(status IN ('Pending','Approved','Rejected')),
  reviewed_at TEXT,
  reviewed_by TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (organisation_id, employee_id) REFERENCES employees(organisation_id, id),
  UNIQUE (organisation_id, source_key)
);
CREATE INDEX idx_payroll_historical_earnings_period ON payroll_historical_earnings(organisation_id, employee_id, earning_month, status);
