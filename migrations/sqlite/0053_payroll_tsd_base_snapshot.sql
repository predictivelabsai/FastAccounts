ALTER TABLE pay_run_items ADD COLUMN tsd_payment_type INTEGER NOT NULL DEFAULT 10;
UPDATE pay_run_items SET tsd_payment_type=CASE pay_basis WHEN 'board_fee' THEN 21 WHEN 'income_line' THEN 17 ELSE 10 END;
