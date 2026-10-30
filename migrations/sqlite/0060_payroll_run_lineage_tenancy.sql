CREATE TRIGGER pay_runs_original_same_organisation_insert
BEFORE INSERT ON pay_runs
WHEN NEW.original_run_id IS NOT NULL
 AND NOT EXISTS (
  SELECT 1 FROM pay_runs original
  WHERE original.id=NEW.original_run_id
    AND original.organisation_id=NEW.organisation_id
 )
BEGIN
 SELECT RAISE(ABORT,'original pay run must belong to the same organisation');
END;

CREATE TRIGGER pay_runs_original_same_organisation_update
BEFORE UPDATE OF original_run_id,organisation_id ON pay_runs
WHEN NEW.original_run_id IS NOT NULL
 AND NOT EXISTS (
  SELECT 1 FROM pay_runs original
  WHERE original.id=NEW.original_run_id
    AND original.organisation_id=NEW.organisation_id
 )
BEGIN
 SELECT RAISE(ABORT,'original pay run must belong to the same organisation');
END;
