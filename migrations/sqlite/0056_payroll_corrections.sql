ALTER TABLE pay_runs ADD COLUMN kind TEXT NOT NULL DEFAULT 'regular' CHECK(kind IN ('regular','correction','supplementary'));
ALTER TABLE pay_runs ADD COLUMN original_run_id TEXT;
CREATE INDEX idx_pay_runs_original ON pay_runs(organisation_id,original_run_id,created_at,id);
DROP INDEX idx_pay_runs_period;
CREATE UNIQUE INDEX idx_pay_runs_regular_period ON pay_runs(organisation_id,period) WHERE kind='regular';
