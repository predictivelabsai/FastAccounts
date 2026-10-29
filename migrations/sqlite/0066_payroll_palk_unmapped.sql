-- Preserve the existing PALK row field for old clients while storing the
-- nullable designation used by new reports and frozen payroll components.
ALTER TABLE pay_component_types ADD COLUMN palk_designation INTEGER DEFAULT 5
 CHECK (palk_designation IS NULL OR palk_designation IN (5,6,7,8,9,10,15,16,17,18));
ALTER TABLE pay_item_components ADD COLUMN palk_designation INTEGER DEFAULT 5
 CHECK (palk_designation IS NULL OR palk_designation IN (5,6,7,8,9,10,15,16,17,18));
UPDATE pay_component_types SET palk_designation=palk_row;
DROP TRIGGER guard_pay_item_components_update;
UPDATE pay_item_components SET palk_designation=palk_row;
CREATE TRIGGER guard_pay_item_components_update BEFORE UPDATE ON pay_item_components WHEN EXISTS (SELECT 1 FROM pay_run_items i JOIN pay_runs r ON r.organisation_id=i.organisation_id AND r.id=i.pay_run_id WHERE i.organisation_id=OLD.organisation_id AND i.id=OLD.item_id AND r.status='Approved') OR EXISTS (SELECT 1 FROM pay_run_items i JOIN pay_runs r ON r.organisation_id=i.organisation_id AND r.id=i.pay_run_id WHERE i.organisation_id=NEW.organisation_id AND i.id=NEW.item_id AND r.status='Approved') BEGIN SELECT RAISE(ABORT,'approved payroll components are immutable'); END;
