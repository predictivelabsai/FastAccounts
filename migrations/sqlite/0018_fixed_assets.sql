-- Fixed asset events and reproducible depreciation runs are tenant scoped.
CREATE UNIQUE INDEX idx_accounts_tenant_id ON accounts(organisation_id,id);
CREATE TABLE asset_groups (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id),
    name TEXT NOT NULL,
    default_key TEXT,
    annual_percentage NUMERIC(8,4) NOT NULL CHECK(annual_percentage>0 AND annual_percentage<=100),
    frequency TEXT NOT NULL CHECK(frequency IN ('monthly','quarterly','yearly')),
    asset_account_id TEXT NOT NULL,
    accumulated_depreciation_account_id TEXT NOT NULL,
    expense_account_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(organisation_id,id),
    UNIQUE(organisation_id,default_key),
    FOREIGN KEY(organisation_id,asset_account_id) REFERENCES accounts(organisation_id,id),
    FOREIGN KEY(organisation_id,accumulated_depreciation_account_id) REFERENCES accounts(organisation_id,id),
    FOREIGN KEY(organisation_id,expense_account_id) REFERENCES accounts(organisation_id,id)
);
CREATE TABLE fixed_assets (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id),
    group_id TEXT NOT NULL,
    name TEXT NOT NULL,
    acquisition_date TEXT NOT NULL,
    acquisition_cost NUMERIC(20,4) NOT NULL CHECK(acquisition_cost>0),
    bank_account_id TEXT NOT NULL,
    contact_id TEXT,
    idempotency_key TEXT NOT NULL,
    posting_batch_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Active' CHECK(status IN ('Active','Disposed')),
    annual_percentage NUMERIC(8,4) NOT NULL CHECK(annual_percentage>0 AND annual_percentage<=100),
    frequency TEXT NOT NULL CHECK(frequency IN ('monthly','quarterly','yearly')),
    asset_account_id TEXT NOT NULL,
    accumulated_depreciation_account_id TEXT NOT NULL,
    expense_account_id TEXT NOT NULL,
    disposal_date TEXT,
    disposal_amount NUMERIC(20,4) CHECK(disposal_amount>=0),
    disposal_depreciation_amount NUMERIC(20,4) NOT NULL DEFAULT 0 CHECK(disposal_depreciation_amount>=0),
    disposal_posting_batch_id TEXT,
    disposal_bank_account_id TEXT,
    disposal_idempotency_key TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(organisation_id,id),
    UNIQUE(organisation_id,idempotency_key),
    UNIQUE(organisation_id,disposal_idempotency_key),
    CHECK(disposal_date IS NULL OR disposal_date>=acquisition_date),
    FOREIGN KEY(organisation_id,group_id) REFERENCES asset_groups(organisation_id,id),
    FOREIGN KEY(organisation_id,bank_account_id) REFERENCES bank_accounts(organisation_id,id),
    FOREIGN KEY(organisation_id,contact_id) REFERENCES contacts(organisation_id,id),
    FOREIGN KEY(organisation_id,posting_batch_id) REFERENCES posting_batches(organisation_id,id),
    FOREIGN KEY(organisation_id,disposal_posting_batch_id) REFERENCES posting_batches(organisation_id,id),
    FOREIGN KEY(organisation_id,disposal_bank_account_id) REFERENCES bank_accounts(organisation_id,id),
    FOREIGN KEY(organisation_id,asset_account_id) REFERENCES accounts(organisation_id,id),
    FOREIGN KEY(organisation_id,accumulated_depreciation_account_id) REFERENCES accounts(organisation_id,id),
    FOREIGN KEY(organisation_id,expense_account_id) REFERENCES accounts(organisation_id,id)
);
CREATE INDEX idx_fixed_assets_group ON fixed_assets(organisation_id,group_id,status,acquisition_date);
CREATE TABLE depreciation_runs (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id),
    kind TEXT NOT NULL CHECK(kind IN ('monthly','quarterly','yearly')),
    period_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('Posted','Empty')),
    posting_batch_id TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(organisation_id,id),
    UNIQUE(organisation_id,period_date,kind),
    FOREIGN KEY(organisation_id,posting_batch_id) REFERENCES posting_batches(organisation_id,id)
);
CREATE TABLE depreciation_run_assets (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id),
    run_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    amount NUMERIC(20,4) NOT NULL CHECK(amount>=0),
    posting_batch_id TEXT,
    UNIQUE(organisation_id,run_id,asset_id),
    FOREIGN KEY(organisation_id,run_id) REFERENCES depreciation_runs(organisation_id,id),
    FOREIGN KEY(organisation_id,asset_id) REFERENCES fixed_assets(organisation_id,id),
    FOREIGN KEY(organisation_id,posting_batch_id) REFERENCES posting_batches(organisation_id,id)
);
CREATE INDEX idx_depreciation_run_assets_asset ON depreciation_run_assets(organisation_id,asset_id);

-- Add roles sequentially, preserving existing roles and occupied account codes.
WITH RECURSIVE offsets(n) AS (
    SELECT 0 UNION ALL SELECT n+1 FROM offsets WHERE n<(SELECT COUNT(*)+1 FROM accounts)
), roles(country,code,name,kind,balance,role) AS (
    VALUES ('UK',1500,'Fixed assets','Asset','Debit','FIXED_ASSETS'),
           ('EE',1410,'Põhivara','Asset','Debit','FIXED_ASSETS')
)
INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role)
SELECT o.id || '-' || r.role,o.id,
       CAST((SELECT MIN(r.code+n) FROM offsets WHERE NOT EXISTS (
           SELECT 1 FROM accounts a WHERE a.organisation_id=o.id AND a.code=CAST(r.code+n AS TEXT)
       )) AS TEXT),r.name,r.kind,r.balance,r.role
FROM organisations o JOIN roles r ON r.country=o.country_code
WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE a.organisation_id=o.id AND a.system_role=r.role);

WITH RECURSIVE offsets(n) AS (
    SELECT 0 UNION ALL SELECT n+1 FROM offsets WHERE n<(SELECT COUNT(*)+1 FROM accounts)
), roles(country,code,name,kind,balance,role) AS (
    VALUES ('UK',1550,'Accumulated depreciation','Asset','Credit','ACCUMULATED_DEPRECIATION'),
           ('EE',1419,'Põhivara kulum','Asset','Credit','ACCUMULATED_DEPRECIATION')
)
INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role)
SELECT o.id || '-' || r.role,o.id,
       CAST((SELECT MIN(r.code+n) FROM offsets WHERE NOT EXISTS (
           SELECT 1 FROM accounts a WHERE a.organisation_id=o.id AND a.code=CAST(r.code+n AS TEXT)
       )) AS TEXT),r.name,r.kind,r.balance,r.role
FROM organisations o JOIN roles r ON r.country=o.country_code
WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE a.organisation_id=o.id AND a.system_role=r.role);

WITH RECURSIVE offsets(n) AS (
    SELECT 0 UNION ALL SELECT n+1 FROM offsets WHERE n<(SELECT COUNT(*)+1 FROM accounts)
), roles(country,code,name,kind,balance,role) AS (
    VALUES ('UK',6500,'Depreciation expense','Expense','Debit','DEPRECIATION_EXPENSE'),
           ('EE',6410,'Põhivara kulumi kulu','Expense','Debit','DEPRECIATION_EXPENSE')
)
INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role)
SELECT o.id || '-' || r.role,o.id,
       CAST((SELECT MIN(r.code+n) FROM offsets WHERE NOT EXISTS (
           SELECT 1 FROM accounts a WHERE a.organisation_id=o.id AND a.code=CAST(r.code+n AS TEXT)
       )) AS TEXT),r.name,r.kind,r.balance,r.role
FROM organisations o JOIN roles r ON r.country=o.country_code
WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE a.organisation_id=o.id AND a.system_role=r.role);
