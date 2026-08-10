CREATE TABLE IF NOT EXISTS organisations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    country_code TEXT NOT NULL CHECK (country_code IN ('UK','EE')),
    entity_type TEXT NOT NULL CHECK (entity_type IN ('UK_COMPANY','UK_SOLE_TRADER','EE_OU','EE_FIE')),
    base_currency TEXT NOT NULL CHECK (length(base_currency)=3),
    registration_no TEXT,
    vat_no TEXT,
    address TEXT,
    fiscal_year_start INTEGER NOT NULL DEFAULT 1 CHECK (fiscal_year_start BETWEEN 1 AND 12),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memberships (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('owner','administrator','accountant','approver','viewer')),
    created_at TEXT NOT NULL,
    UNIQUE (organisation_id,email)
);

CREATE TABLE IF NOT EXISTS fiscal_periods (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    starts_on TEXT NOT NULL,
    ends_on TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Open' CHECK (status IN ('Open','Locked')),
    locked_at TEXT,
    locked_by TEXT,
    lock_reason TEXT,
    UNIQUE (organisation_id,code),
    CHECK (ends_on>=starts_on)
);

CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    account_type TEXT NOT NULL CHECK (account_type IN ('Asset','Liability','Equity','Income','Expense')),
    normal_balance TEXT NOT NULL CHECK (normal_balance IN ('Debit','Credit')),
    system_role TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    UNIQUE (organisation_id,code),
    UNIQUE (organisation_id,system_role)
);

CREATE TABLE IF NOT EXISTS tax_codes (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    country_code TEXT NOT NULL CHECK (country_code IN ('UK','EE')),
    rate NUMERIC(8,4) NOT NULL CHECK (rate>=0),
    kind TEXT NOT NULL CHECK (kind IN ('standard','reduced','zero','exempt','out_of_scope','reverse_charge','intra_eu')),
    recoverable_percent NUMERIC(8,4) NOT NULL DEFAULT 100 CHECK (recoverable_percent BETWEEN 0 AND 100),
    return_mapping TEXT NOT NULL DEFAULT '{}',
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    UNIQUE (organisation_id,code,valid_from)
);

CREATE TABLE IF NOT EXISTS document_sequences (
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    document_type TEXT NOT NULL,
    prefix TEXT NOT NULL,
    next_number INTEGER NOT NULL DEFAULT 1 CHECK (next_number>0),
    PRIMARY KEY (organisation_id,document_type)
);

CREATE TABLE IF NOT EXISTS contacts (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    contact_type TEXT NOT NULL CHECK (contact_type IN ('customer','supplier','both')),
    name TEXT NOT NULL,
    registration_no TEXT,
    vat_no TEXT,
    email TEXT,
    phone TEXT,
    address TEXT,
    country_code TEXT NOT NULL,
    payment_terms_days INTEGER NOT NULL DEFAULT 14 CHECK (payment_terms_days>=0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invoices (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    contact_id TEXT NOT NULL REFERENCES contacts(id),
    document_type TEXT NOT NULL DEFAULT 'invoice' CHECK (document_type IN ('invoice','credit_note')),
    number TEXT,
    status TEXT NOT NULL DEFAULT 'Draft' CHECK (status IN ('Draft','Issued','Part Paid','Paid','Voided','Credited')),
    issue_date TEXT NOT NULL,
    tax_point_date TEXT NOT NULL,
    due_date TEXT NOT NULL,
    currency TEXT NOT NULL CHECK (length(currency)=3),
    exchange_rate NUMERIC(20,10) NOT NULL DEFAULT 1 CHECK (exchange_rate>0),
    line_amount_type TEXT NOT NULL DEFAULT 'exclusive' CHECK (line_amount_type IN ('exclusive','inclusive','no_tax')),
    reference TEXT,
    notes TEXT,
    original_invoice_id TEXT REFERENCES invoices(id),
    subtotal NUMERIC(20,4) NOT NULL DEFAULT 0,
    tax_total NUMERIC(20,4) NOT NULL DEFAULT 0,
    total NUMERIC(20,4) NOT NULL DEFAULT 0,
    paid_total NUMERIC(20,4) NOT NULL DEFAULT 0,
    posting_batch_id TEXT,
    issued_at TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (organisation_id,number)
);

CREATE TABLE IF NOT EXISTS invoice_lines (
    id TEXT PRIMARY KEY,
    invoice_id TEXT NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    line_number INTEGER NOT NULL,
    description TEXT NOT NULL,
    quantity NUMERIC(20,4) NOT NULL CHECK (quantity>0),
    unit_price NUMERIC(20,4) NOT NULL,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    tax_code_id TEXT REFERENCES tax_codes(id),
    tax_rate NUMERIC(8,4) NOT NULL DEFAULT 0,
    net_amount NUMERIC(20,4) NOT NULL,
    tax_amount NUMERIC(20,4) NOT NULL,
    gross_amount NUMERIC(20,4) NOT NULL,
    UNIQUE (invoice_id,line_number)
);

CREATE TABLE IF NOT EXISTS bills (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    contact_id TEXT NOT NULL REFERENCES contacts(id),
    document_type TEXT NOT NULL DEFAULT 'bill' CHECK (document_type IN ('bill','supplier_credit')),
    supplier_number TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Draft' CHECK (status IN ('Draft','In Review','Approved','Part Paid','Paid','Rejected','Voided')),
    bill_date TEXT NOT NULL,
    due_date TEXT NOT NULL,
    currency TEXT NOT NULL CHECK (length(currency)=3),
    exchange_rate NUMERIC(20,10) NOT NULL DEFAULT 1 CHECK (exchange_rate>0),
    reference TEXT,
    notes TEXT,
    original_bill_id TEXT REFERENCES bills(id),
    subtotal NUMERIC(20,4) NOT NULL DEFAULT 0,
    tax_total NUMERIC(20,4) NOT NULL DEFAULT 0,
    total NUMERIC(20,4) NOT NULL DEFAULT 0,
    paid_total NUMERIC(20,4) NOT NULL DEFAULT 0,
    posting_batch_id TEXT,
    approved_at TEXT,
    approved_by TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (organisation_id,contact_id,supplier_number)
);

CREATE TABLE IF NOT EXISTS bill_lines (
    id TEXT PRIMARY KEY,
    bill_id TEXT NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
    line_number INTEGER NOT NULL,
    description TEXT NOT NULL,
    quantity NUMERIC(20,4) NOT NULL CHECK (quantity>0),
    unit_price NUMERIC(20,4) NOT NULL,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    tax_code_id TEXT REFERENCES tax_codes(id),
    tax_rate NUMERIC(8,4) NOT NULL DEFAULT 0,
    net_amount NUMERIC(20,4) NOT NULL,
    tax_amount NUMERIC(20,4) NOT NULL,
    recoverable_tax NUMERIC(20,4) NOT NULL,
    gross_amount NUMERIC(20,4) NOT NULL,
    UNIQUE (bill_id,line_number)
);

CREATE TABLE IF NOT EXISTS posting_batches (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    voucher_type TEXT NOT NULL,
    voucher_id TEXT NOT NULL,
    voucher_code TEXT NOT NULL,
    posting_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Draft' CHECK (status IN ('Draft','Posted','Reversed')),
    reverses_batch_id TEXT REFERENCES posting_batches(id),
    posted_at TEXT,
    posted_by TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (organisation_id,voucher_type,voucher_id)
);

CREATE TABLE IF NOT EXISTS gl_entries (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    posting_batch_id TEXT NOT NULL REFERENCES posting_batches(id),
    line_number INTEGER NOT NULL,
    entry_date TEXT NOT NULL,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    debit NUMERIC(20,4) NOT NULL DEFAULT 0 CHECK (debit>=0),
    credit NUMERIC(20,4) NOT NULL DEFAULT 0 CHECK (credit>=0),
    currency TEXT NOT NULL,
    transaction_amount NUMERIC(20,4) NOT NULL DEFAULT 0,
    transaction_currency TEXT NOT NULL,
    exchange_rate NUMERIC(20,10) NOT NULL DEFAULT 1,
    contact_id TEXT REFERENCES contacts(id),
    due_date TEXT,
    memo TEXT,
    source_line_type TEXT,
    source_line_id TEXT,
    reverses_entry_id TEXT REFERENCES gl_entries(id),
    UNIQUE (posting_batch_id,line_number),
    CHECK ((debit>0 AND credit=0) OR (credit>0 AND debit=0))
);

CREATE TABLE IF NOT EXISTS bank_accounts (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    ledger_account_id TEXT NOT NULL REFERENCES accounts(id),
    name TEXT NOT NULL,
    currency TEXT NOT NULL,
    iban_masked TEXT,
    sort_code_masked TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE (organisation_id,name)
);

CREATE TABLE IF NOT EXISTS payments (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    payment_type TEXT NOT NULL CHECK (payment_type IN ('customer_receipt','supplier_payment','transfer')),
    contact_id TEXT REFERENCES contacts(id),
    bank_account_id TEXT NOT NULL REFERENCES bank_accounts(id),
    payment_date TEXT NOT NULL,
    amount NUMERIC(20,4) NOT NULL CHECK (amount>0),
    currency TEXT NOT NULL,
    reference TEXT,
    status TEXT NOT NULL DEFAULT 'Posted' CHECK (status IN ('Posted','Reversed')),
    posting_batch_id TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payment_allocations (
    id TEXT PRIMARY KEY,
    payment_id TEXT NOT NULL REFERENCES payments(id) ON DELETE CASCADE,
    document_type TEXT NOT NULL CHECK (document_type IN ('invoice','bill')),
    document_id TEXT NOT NULL,
    amount NUMERIC(20,4) NOT NULL CHECK (amount>0),
    UNIQUE (payment_id,document_type,document_id)
);

CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    owner_type TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes>=0),
    sha256 TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    uploaded_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (organisation_id,sha256,owner_type,owner_id)
);

CREATE TABLE IF NOT EXISTS bank_imports (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    bank_account_id TEXT NOT NULL REFERENCES bank_accounts(id),
    format TEXT NOT NULL CHECK (format IN ('csv','camt053','open_banking')),
    source_hash TEXT NOT NULL,
    imported_by TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    UNIQUE (organisation_id,bank_account_id,source_hash)
);

CREATE TABLE IF NOT EXISTS bank_transactions (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    bank_account_id TEXT NOT NULL REFERENCES bank_accounts(id),
    import_id TEXT REFERENCES bank_imports(id),
    external_id TEXT,
    fingerprint TEXT NOT NULL,
    booking_date TEXT NOT NULL,
    value_date TEXT,
    amount NUMERIC(20,4) NOT NULL CHECK (amount<>0),
    currency TEXT NOT NULL,
    counterparty TEXT,
    reference TEXT,
    raw_payload TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'Unmatched' CHECK (status IN ('Unmatched','Suggested','Reconciled','Ignored')),
    UNIQUE (organisation_id,bank_account_id,fingerprint)
);

CREATE TABLE IF NOT EXISTS reconciliation_matches (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    bank_transaction_id TEXT NOT NULL REFERENCES bank_transactions(id),
    target_type TEXT NOT NULL CHECK (target_type IN ('invoice','bill','payment','journal')),
    target_id TEXT NOT NULL,
    amount NUMERIC(20,4) NOT NULL CHECK (amount>0),
    confidence NUMERIC(8,4),
    reasons TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL CHECK (status IN ('Suggested','Confirmed','Rejected')),
    confirmed_by TEXT,
    confirmed_at TEXT,
    UNIQUE (bank_transaction_id,target_type,target_id)
);

CREATE TABLE IF NOT EXISTS vat_returns (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    country_code TEXT NOT NULL CHECK (country_code IN ('UK','EE')),
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    basis TEXT NOT NULL DEFAULT 'accrual' CHECK (basis IN ('accrual','cash')),
    status TEXT NOT NULL DEFAULT 'Draft' CHECK (status IN ('Draft','Reviewed','Exported','Submitted')),
    boxes_json TEXT NOT NULL,
    reviewed_by TEXT,
    reviewed_at TEXT,
    submission_reference TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (organisation_id,country_code,period_start,period_end,basis)
);

CREATE TABLE IF NOT EXISTS filing_attempts (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    vat_return_id TEXT NOT NULL REFERENCES vat_returns(id),
    provider TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('stub','sandbox','production','export')),
    status TEXT NOT NULL CHECK (status IN ('Planned','Prepared','Succeeded','Failed')),
    request_hash TEXT,
    response_reference TEXT,
    message TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    organisation_id TEXT REFERENCES organisations(id) ON DELETE CASCADE,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memberships_email ON memberships(lower(email));
CREATE INDEX IF NOT EXISTS idx_invoices_org_status ON invoices(organisation_id,status,issue_date);
CREATE INDEX IF NOT EXISTS idx_bills_org_status ON bills(organisation_id,status,bill_date);
CREATE INDEX IF NOT EXISTS idx_gl_org_date ON gl_entries(organisation_id,entry_date,account_id);
CREATE INDEX IF NOT EXISTS idx_bank_tx_status ON bank_transactions(organisation_id,status,booking_date);
CREATE INDEX IF NOT EXISTS idx_audit_org_date ON audit_events(organisation_id,created_at);

CREATE TRIGGER IF NOT EXISTS gl_entries_immutable_update
BEFORE UPDATE ON gl_entries BEGIN
    SELECT RAISE(ABORT,'posted ledger entries are immutable');
END;

CREATE TRIGGER IF NOT EXISTS gl_entries_immutable_delete
BEFORE DELETE ON gl_entries BEGIN
    SELECT RAISE(ABORT,'posted ledger entries are immutable');
END;

CREATE TRIGGER IF NOT EXISTS posting_batch_balance_check
BEFORE UPDATE OF status ON posting_batches
WHEN NEW.status='Posted' AND OLD.status<>'Posted'
BEGIN
    SELECT CASE WHEN (SELECT COUNT(*) FROM gl_entries WHERE posting_batch_id=NEW.id)<2
        THEN RAISE(ABORT,'posting batch needs at least two lines') END;
    SELECT CASE WHEN ROUND((SELECT COALESCE(SUM(debit),0)-COALESCE(SUM(credit),0) FROM gl_entries WHERE posting_batch_id=NEW.id),4)<>0
        THEN RAISE(ABORT,'posting batch is not balanced') END;
END;
