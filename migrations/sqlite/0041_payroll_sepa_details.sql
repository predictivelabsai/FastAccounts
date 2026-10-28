ALTER TABLE bank_accounts ADD COLUMN bic TEXT;
ALTER TABLE organisations ADD COLUMN language TEXT NOT NULL DEFAULT 'en';
UPDATE organisations SET language='et' WHERE country_code='EE';
