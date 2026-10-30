CREATE TABLE organisation_payroll_settings (
 organisation_id TEXT PRIMARY KEY REFERENCES organisations(id),
 payroll_start_date TEXT
);
CREATE TABLE organisation_payday_rules (
 id TEXT PRIMARY KEY, organisation_id TEXT NOT NULL REFERENCES organisations(id),
 start_date TEXT NOT NULL,
 rule TEXT NOT NULL CHECK(rule IN ('next_month_day','current_month_day','next_month_first_working_day')),
 day INTEGER CHECK(day IS NULL OR day BETWEEN 1 AND 31),
 UNIQUE(organisation_id,start_date), UNIQUE(organisation_id,id),
 CHECK((rule='next_month_first_working_day' AND day IS NULL) OR
       (rule IN ('next_month_day','current_month_day') AND day IS NOT NULL))
);
CREATE INDEX idx_organisation_payday_rules_effective
 ON organisation_payday_rules(organisation_id,start_date);
