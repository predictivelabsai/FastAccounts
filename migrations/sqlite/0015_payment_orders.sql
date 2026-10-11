ALTER TABLE bank_accounts ADD COLUMN iban TEXT;
ALTER TABLE contacts ADD COLUMN iban TEXT;

CREATE TABLE IF NOT EXISTS payment_orders (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    bank_account_id TEXT NOT NULL REFERENCES bank_accounts(id),
    execution_date TEXT NOT NULL,
    bill_count INTEGER NOT NULL,
    total NUMERIC(20,4) NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    debtor_name TEXT NOT NULL,
    debtor_iban TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payment_order_lines (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    payment_order_id TEXT NOT NULL REFERENCES payment_orders(id) ON DELETE CASCADE,
    bill_id TEXT NOT NULL,
    amount NUMERIC(20,4) NOT NULL,
    currency TEXT NOT NULL,
    created_at TEXT NOT NULL,
    creditor_name TEXT NOT NULL,
    creditor_iban TEXT NOT NULL,
    reference TEXT NOT NULL,
    UNIQUE(payment_order_id, bill_id)
);
