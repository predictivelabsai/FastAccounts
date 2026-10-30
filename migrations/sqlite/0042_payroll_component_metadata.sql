ALTER TABLE pay_component_types ADD COLUMN is_wage INTEGER NOT NULL DEFAULT 1 CHECK (is_wage IN (0,1));
ALTER TABLE pay_component_types ADD COLUMN active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1));
ALTER TABLE pay_item_components ADD COLUMN is_wage INTEGER NOT NULL DEFAULT 1 CHECK (is_wage IN (0,1));
UPDATE pay_component_types SET is_wage=0
WHERE preset_key IN ('bailiff','parental','annual_leave','unused_leave','employer_sick_pay',
                     'severance','expense_reimbursement','salary_advance','advance_recovery',
                     'alimony','union_fee','agreed_deduction');
DROP TRIGGER guard_pay_item_components_update;
UPDATE pay_item_components SET is_wage=(SELECT is_wage FROM pay_component_types t
  WHERE t.organisation_id=pay_item_components.organisation_id AND t.id=pay_item_components.type_id);
CREATE TRIGGER guard_pay_item_components_update BEFORE UPDATE ON pay_item_components WHEN EXISTS (SELECT 1 FROM pay_run_items i JOIN pay_runs r ON r.organisation_id=i.organisation_id AND r.id=i.pay_run_id WHERE i.organisation_id=OLD.organisation_id AND i.id=OLD.item_id AND r.status='Approved') OR EXISTS (SELECT 1 FROM pay_run_items i JOIN pay_runs r ON r.organisation_id=i.organisation_id AND r.id=i.pay_run_id WHERE i.organisation_id=NEW.organisation_id AND i.id=NEW.item_id AND r.status='Approved') BEGIN SELECT RAISE(ABORT,'approved payroll components are immutable'); END;
