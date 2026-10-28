ALTER TABLE pay_item_components ADD COLUMN is_generated INTEGER NOT NULL DEFAULT 0 CHECK (is_generated IN (0,1));
UPDATE pay_item_components SET is_generated=1 WHERE breakdown_json IS NOT NULL;
