-- Realised settlement differences and retained prepayment booking rates.
ALTER TABLE prepayments ADD COLUMN exchange_rate NUMERIC(20,10) NOT NULL DEFAULT 1;
-- Retain each allocation's exact share of the aggregate control leg. NULL
-- identifies legacy rows, whose shares are apportioned from their stored batch.
ALTER TABLE payment_allocations ADD COLUMN booked_base_amount NUMERIC(20,4);

WITH RECURSIVE offsets(n) AS (
    SELECT 0 UNION ALL SELECT n+1 FROM offsets WHERE n<(SELECT COUNT(*)+1 FROM accounts)
), roles(country,code,name,kind,balance,role) AS (
    VALUES ('UK',7900,'Foreign exchange gains and losses','Expense','Debit','FX_GAIN_LOSS'),
           ('EE',6990,'Valuutakursi kasum ja kahjum','Expense','Debit','FX_GAIN_LOSS')
)
INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role)
SELECT o.id || '-' || r.role,o.id,
       CAST((SELECT MIN(r.code+n) FROM offsets WHERE NOT EXISTS (
           SELECT 1 FROM accounts a WHERE a.organisation_id=o.id AND a.code=CAST(r.code+n AS TEXT)
       )) AS TEXT),r.name,r.kind,r.balance,r.role
FROM organisations o JOIN roles r ON r.country=o.country_code
WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE a.organisation_id=o.id AND a.system_role=r.role);

