-- Prepayments are separate from trade receivables and payables until allocated.
CREATE UNIQUE INDEX idx_contacts_tenant_id ON contacts(organisation_id,id);
CREATE UNIQUE INDEX idx_bank_accounts_tenant_id ON bank_accounts(organisation_id,id);
CREATE UNIQUE INDEX idx_posting_batches_tenant_id ON posting_batches(organisation_id,id);

CREATE TABLE prepayments (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id),
    side TEXT NOT NULL CHECK(side IN ('customer','supplier')),
    contact_id TEXT NOT NULL,
    bank_account_id TEXT NOT NULL,
    document_date TEXT NOT NULL,
    amount NUMERIC(20,4) NOT NULL CHECK(amount>0),
    currency TEXT NOT NULL CHECK(length(currency)=3),
    unallocated_balance NUMERIC(20,4) NOT NULL CHECK(unallocated_balance>=0 AND unallocated_balance<=amount),
    reference TEXT NOT NULL DEFAULT '',
    idempotency_key TEXT NOT NULL,
    posting_batch_id TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(organisation_id,id),
    UNIQUE(organisation_id,idempotency_key),
    FOREIGN KEY(organisation_id,contact_id) REFERENCES contacts(organisation_id,id),
    FOREIGN KEY(organisation_id,bank_account_id) REFERENCES bank_accounts(organisation_id,id),
    FOREIGN KEY(organisation_id,posting_batch_id) REFERENCES posting_batches(organisation_id,id)
);
CREATE INDEX idx_prepayments_contact ON prepayments(organisation_id,contact_id,side,document_date);

CREATE TABLE prepayment_allocations (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id),
    prepayment_id TEXT NOT NULL,
    document_type TEXT NOT NULL CHECK(document_type IN ('invoice','bill')),
    document_id TEXT NOT NULL,
    amount NUMERIC(20,4) NOT NULL CHECK(amount>0),
    allocation_date TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    posting_batch_id TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(organisation_id,idempotency_key),
    FOREIGN KEY(organisation_id,prepayment_id) REFERENCES prepayments(organisation_id,id),
    FOREIGN KEY(organisation_id,posting_batch_id) REFERENCES posting_batches(organisation_id,id)
);
CREATE INDEX idx_prepayment_allocations_document ON prepayment_allocations(organisation_id,document_type,document_id);
CREATE INDEX idx_prepayment_allocations_parent ON prepayment_allocations(organisation_id,prepayment_id);

CREATE TABLE prepayment_refunds (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id),
    prepayment_id TEXT NOT NULL,
    amount NUMERIC(20,4) NOT NULL CHECK(amount>0),
    refund_date TEXT NOT NULL,
    reference TEXT NOT NULL DEFAULT '',
    idempotency_key TEXT NOT NULL,
    posting_batch_id TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(organisation_id,idempotency_key),
    FOREIGN KEY(organisation_id,prepayment_id) REFERENCES prepayments(organisation_id,id),
    FOREIGN KEY(organisation_id,posting_batch_id) REFERENCES posting_batches(organisation_id,id)
);
CREATE INDEX idx_prepayment_refunds_parent ON prepayment_refunds(organisation_id,prepayment_id);

-- Preserve custom charts and existing roles. If the preferred code is occupied,
-- choose the next free numeric code, without renaming or repurposing an account.
WITH RECURSIVE offsets(n) AS (
    SELECT 0 UNION ALL SELECT n+1 FROM offsets WHERE n<(SELECT COUNT(*)+1 FROM accounts)
), roles(country,code,name,kind,balance,role) AS (
    VALUES ('UK',1300,'Supplier prepayments','Asset','Debit','SUPPLIER_PREPAYMENTS'),
           ('EE',1310,'Ettemaksed tarnijatele','Asset','Debit','SUPPLIER_PREPAYMENTS')
)
INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role)
SELECT o.id || '-' || r.role,o.id,
       CAST((SELECT MIN(r.code+n) FROM offsets WHERE NOT EXISTS (
           SELECT 1 FROM accounts a WHERE a.organisation_id=o.id AND a.code=CAST(r.code+n AS TEXT)
       )) AS TEXT),r.name,r.kind,r.balance,r.role
FROM organisations o JOIN roles r ON r.country=o.country_code
WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE a.organisation_id=o.id AND a.system_role=r.role);

-- Insert the roles sequentially so even densely customised charts cannot
-- select the same available code for both new accounts.
WITH RECURSIVE offsets(n) AS (
    SELECT 0 UNION ALL SELECT n+1 FROM offsets WHERE n<(SELECT COUNT(*)+1 FROM accounts)
), roles(country,code,name,kind,balance,role) AS (
    VALUES ('UK',2200,'Customer prepayments','Liability','Credit','CUSTOMER_PREPAYMENTS'),
           ('EE',2110,'Klientide ettemaksed','Liability','Credit','CUSTOMER_PREPAYMENTS')
)
INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role)
SELECT o.id || '-' || r.role,o.id,
       CAST((SELECT MIN(r.code+n) FROM offsets WHERE NOT EXISTS (
           SELECT 1 FROM accounts a WHERE a.organisation_id=o.id AND a.code=CAST(r.code+n AS TEXT)
       )) AS TEXT),r.name,r.kind,r.balance,r.role
FROM organisations o JOIN roles r ON r.country=o.country_code
WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE a.organisation_id=o.id AND a.system_role=r.role);
