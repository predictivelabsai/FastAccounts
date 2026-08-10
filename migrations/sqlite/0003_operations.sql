CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    item_type TEXT NOT NULL CHECK (item_type IN ('service','product')),
    sales_account_id TEXT REFERENCES accounts(id),
    purchase_account_id TEXT REFERENCES accounts(id),
    tax_code_id TEXT REFERENCES tax_codes(id),
    unit_price NUMERIC(20,4),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (organisation_id,code)
);

CREATE TABLE IF NOT EXISTS exchange_rates (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    rate_date TEXT NOT NULL,
    from_currency TEXT NOT NULL,
    to_currency TEXT NOT NULL,
    rate NUMERIC(20,10) NOT NULL CHECK (rate>0),
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (organisation_id,rate_date,from_currency,to_currency,source)
);

CREATE TABLE IF NOT EXISTS invoice_deliveries (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    invoice_id TEXT NOT NULL REFERENCES invoices(id),
    channel TEXT NOT NULL CHECK (channel IN ('email','pdf','e_invoice','integration')),
    recipient TEXT,
    status TEXT NOT NULL CHECK (status IN ('Prepared','Sent','Failed')),
    provider TEXT,
    provider_message_id TEXT,
    error_message TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bank_rules (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    counterparty_contains TEXT,
    reference_contains TEXT,
    amount_sign TEXT CHECK (amount_sign IN ('credit','debit')),
    target_account_id TEXT REFERENCES accounts(id),
    tax_code_id TEXT REFERENCES tax_codes(id),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invitations (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('owner','administrator','accountant','approver','viewer')),
    token_hash TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'Pending' CHECK (status IN ('Pending','Accepted','Expired','Revoked')),
    expires_at TEXT NOT NULL,
    invited_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (organisation_id,email,status)
);

CREATE TABLE IF NOT EXISTS filing_declarations (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    vat_return_id TEXT NOT NULL REFERENCES vat_returns(id),
    declaration_type TEXT NOT NULL CHECK (declaration_type IN ('business','agent')),
    declaration_text_version TEXT NOT NULL,
    confirmed_by TEXT NOT NULL,
    confirmed_at TEXT NOT NULL,
    confirmation_ip_hash TEXT,
    UNIQUE (vat_return_id,declaration_type)
);

CREATE TABLE IF NOT EXISTS month_end_checklists (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    period_id TEXT NOT NULL REFERENCES fiscal_periods(id),
    item_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Open' CHECK (status IN ('Open','Complete','Not Applicable')),
    completed_by TEXT,
    completed_at TEXT,
    notes TEXT,
    UNIQUE (organisation_id,period_id,item_key)
);

CREATE TABLE IF NOT EXISTS retention_holds (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    retain_until TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    released_at TEXT
);

CREATE TABLE IF NOT EXISTS accounting_exports (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    export_type TEXT NOT NULL,
    period_start TEXT,
    period_end TEXT,
    sha256 TEXT NOT NULL,
    row_count INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_items_org ON items(organisation_id,active,code);
CREATE INDEX IF NOT EXISTS idx_deliveries_invoice ON invoice_deliveries(invoice_id,created_at);
CREATE INDEX IF NOT EXISTS idx_exchange_rates ON exchange_rates(organisation_id,rate_date);
CREATE INDEX IF NOT EXISTS idx_retention_object ON retention_holds(organisation_id,object_type,object_id);
