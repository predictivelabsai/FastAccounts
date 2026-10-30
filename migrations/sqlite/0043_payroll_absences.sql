CREATE TABLE payroll_absence_type_settings (
  organisation_id TEXT NOT NULL REFERENCES organisations(id),
  absence_type TEXT NOT NULL CHECK (absence_type IN ('annual_leave','extended_leave','child_leave','paternity_leave','maternity_leave','parental_leave','study_leave','care_leave','sick_leave','permitted_absence','truancy','unpaid_leave','alternative_service','other')),
  paid_salary INTEGER NOT NULL DEFAULT 0 CHECK (paid_salary IN (0,1)),
  PRIMARY KEY (organisation_id, absence_type)
);
CREATE TABLE payroll_absences (
  id TEXT PRIMARY KEY,
  organisation_id TEXT NOT NULL,
  employee_id TEXT NOT NULL,
  absence_type TEXT NOT NULL CHECK (absence_type IN ('annual_leave','extended_leave','child_leave','paternity_leave','maternity_leave','parental_leave','study_leave','care_leave','sick_leave','permitted_absence','truancy','unpaid_leave','alternative_service','other')),
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  document_reference TEXT NOT NULL DEFAULT '',
  comment TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (start_date <= end_date),
  UNIQUE (organisation_id, id),
  FOREIGN KEY (organisation_id, employee_id) REFERENCES employees(organisation_id, id)
);
CREATE INDEX idx_payroll_absences_employee_dates ON payroll_absences(organisation_id, employee_id, start_date, end_date);
CREATE TABLE payroll_absence_run_items (
  id TEXT PRIMARY KEY,
  organisation_id TEXT NOT NULL,
  pay_run_id TEXT NOT NULL,
  employee_id TEXT NOT NULL,
  absence_id TEXT NOT NULL,
  calendar_days INTEGER NOT NULL,
  leave_days INTEGER NOT NULL,
  working_days INTEGER NOT NULL,
  FOREIGN KEY (organisation_id, absence_id) REFERENCES payroll_absences(organisation_id, id),
  FOREIGN KEY (organisation_id, pay_run_id) REFERENCES pay_runs(organisation_id, id),
  UNIQUE (organisation_id, pay_run_id, absence_id)
);
CREATE INDEX idx_payroll_absence_frozen ON payroll_absence_run_items(organisation_id, absence_id);
