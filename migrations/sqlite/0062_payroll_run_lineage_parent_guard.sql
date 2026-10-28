CREATE TRIGGER pay_runs_original_parent_update
BEFORE UPDATE OF id,organisation_id ON pay_runs
WHEN (NEW.id<>OLD.id OR NEW.organisation_id<>OLD.organisation_id)
 AND EXISTS (
  SELECT 1 FROM pay_runs child
  WHERE child.organisation_id=OLD.organisation_id AND child.original_run_id=OLD.id
 )
BEGIN
 SELECT RAISE(ABORT,'payroll original run has related runs');
END;

CREATE TRIGGER pay_runs_original_parent_delete
BEFORE DELETE ON pay_runs
WHEN EXISTS (
  SELECT 1 FROM pay_runs child
  WHERE child.organisation_id=OLD.organisation_id AND child.original_run_id=OLD.id
)
BEGIN
 SELECT RAISE(ABORT,'payroll original run has related runs');
END;
