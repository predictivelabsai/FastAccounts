-- Purchase expense transfers preserve the original bill and its VAT timing.
CREATE UNIQUE INDEX IF NOT EXISTS idx_bills_tenant_id ON bills(organisation_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_tenant_id ON accounts(organisation_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_posting_batches_tenant_id ON posting_batches(organisation_id,id);

CREATE TABLE IF NOT EXISTS purchase_schedules (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id),
    bill_id TEXT NOT NULL,
    expense_account_id TEXT NOT NULL,
    deferred_account_id TEXT NOT NULL,
    start_period TEXT NOT NULL,
    number_of_periods INTEGER NOT NULL CHECK(number_of_periods BETWEEN 1 AND 120),
    split_rule TEXT NOT NULL DEFAULT 'equal_first' CHECK(split_rule IN ('equal_first','equal_last')),
    net_amount NUMERIC(20,4) NOT NULL CHECK(net_amount>0),
    vat_amount NUMERIC(20,4) NOT NULL DEFAULT 0 CHECK(vat_amount=0),
    currency TEXT NOT NULL CHECK(length(currency)=3),
    status TEXT NOT NULL DEFAULT 'Draft' CHECK(status IN ('Draft','Active','Completed','Cancelled')),
    funding_batch_id TEXT,
    notes TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(organisation_id,id),
    UNIQUE(organisation_id,bill_id),
    FOREIGN KEY(organisation_id,bill_id) REFERENCES bills(organisation_id,id),
    FOREIGN KEY(organisation_id,expense_account_id) REFERENCES accounts(organisation_id,id),
    FOREIGN KEY(organisation_id,deferred_account_id) REFERENCES accounts(organisation_id,id),
    FOREIGN KEY(organisation_id,funding_batch_id) REFERENCES posting_batches(organisation_id,id)
);
CREATE INDEX IF NOT EXISTS idx_purchase_schedules_status ON purchase_schedules(organisation_id,status,start_period);
CREATE TABLE IF NOT EXISTS purchase_schedule_periods (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id),
    schedule_id TEXT NOT NULL,
    period_date TEXT NOT NULL,
    net_amount NUMERIC(20,4) NOT NULL CHECK(net_amount>0),
    vat_amount NUMERIC(20,4) NOT NULL DEFAULT 0 CHECK(vat_amount=0),
    posted_journal_id TEXT,
    status TEXT NOT NULL DEFAULT 'Pending' CHECK(status IN ('Pending','Posted','Cancelled')),
    UNIQUE(organisation_id,schedule_id,period_date),
    UNIQUE(organisation_id,posted_journal_id),
    CHECK((status='Posted' AND posted_journal_id IS NOT NULL)
          OR (status<>'Posted' AND posted_journal_id IS NULL)),
    FOREIGN KEY(organisation_id,schedule_id) REFERENCES purchase_schedules(organisation_id,id),
    FOREIGN KEY(organisation_id,posted_journal_id) REFERENCES posting_batches(organisation_id,id)
);
CREATE INDEX IF NOT EXISTS idx_purchase_periods_due ON purchase_schedule_periods(organisation_id,status,period_date);

-- Preserve custom codes and roles when upgrading an existing organisation.
WITH RECURSIVE offsets(n) AS (
    SELECT 0 UNION ALL SELECT n+1 FROM offsets WHERE n<(SELECT COUNT(*)+1 FROM accounts)
), roles(country,code,name) AS (
    VALUES ('UK',1400,'Periodised expenses in transit'),
           ('EE',1320,'Periodiseeritud kulud')
)
INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role)
SELECT o.id || '-PERIODISED_PURCHASES',o.id,
       CAST((SELECT MIN(r.code+n) FROM offsets WHERE NOT EXISTS (
           SELECT 1 FROM accounts a WHERE a.organisation_id=o.id AND a.code=CAST(r.code+n AS TEXT)
       )) AS TEXT),r.name,'Asset','Debit','PERIODISED_PURCHASES'
FROM organisations o JOIN roles r ON r.country=o.country_code
WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE a.organisation_id=o.id AND a.system_role='PERIODISED_PURCHASES');
