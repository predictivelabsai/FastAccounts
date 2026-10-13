-- Quotes are offers, with no voucher or ledger posting of their own.
CREATE UNIQUE INDEX idx_invoices_tenant_id ON invoices(organisation_id,id);
CREATE UNIQUE INDEX idx_tax_codes_tenant_id ON tax_codes(organisation_id,id);
INSERT INTO document_sequences(organisation_id,document_type,prefix,next_number)
SELECT id,'quote','QUO-',1 FROM organisations o
WHERE NOT EXISTS (SELECT 1 FROM document_sequences s WHERE s.organisation_id=o.id AND s.document_type='quote');

CREATE TABLE quotes (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id),
    quote_number TEXT NOT NULL,
    contact_id TEXT NOT NULL,
    currency TEXT NOT NULL CHECK(length(currency)=3),
    quote_date TEXT NOT NULL,
    valid_until TEXT NOT NULL CHECK(valid_until>=quote_date),
    status TEXT NOT NULL DEFAULT 'Draft' CHECK(status IN ('Draft','Sent','Accepted','Declined','Expired','Converted')),
    notes TEXT NOT NULL DEFAULT '',
    line_amount_type TEXT NOT NULL DEFAULT 'exclusive' CHECK(line_amount_type IN ('exclusive','inclusive','no_tax')),
    subtotal NUMERIC(20,4) NOT NULL CHECK(subtotal>=0),
    tax_total NUMERIC(20,4) NOT NULL CHECK(tax_total>=0),
    total NUMERIC(20,4) NOT NULL CHECK(total>=0),
    accepted_at TEXT,
    accepted_by TEXT,
    converted_invoice_id TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(organisation_id,id),
    UNIQUE(organisation_id,quote_number),
    UNIQUE(organisation_id,converted_invoice_id),
    CHECK((status IN ('Accepted','Converted') AND accepted_at IS NOT NULL AND accepted_by IS NOT NULL)
          OR (status NOT IN ('Accepted','Converted') AND accepted_at IS NULL AND accepted_by IS NULL)),
    CHECK((status='Converted' AND converted_invoice_id IS NOT NULL)
          OR (status<>'Converted' AND converted_invoice_id IS NULL)),
    FOREIGN KEY(organisation_id,contact_id) REFERENCES contacts(organisation_id,id),
    FOREIGN KEY(organisation_id,converted_invoice_id) REFERENCES invoices(organisation_id,id)
);
CREATE INDEX idx_quotes_status_expiry ON quotes(organisation_id,status,valid_until);
CREATE TABLE quote_lines (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id),
    quote_id TEXT NOT NULL,
    line_number INTEGER NOT NULL CHECK(line_number>0),
    description TEXT NOT NULL,
    quantity NUMERIC(20,4) NOT NULL CHECK(quantity>0),
    unit_price NUMERIC(20,4) NOT NULL CHECK(unit_price>=0),
    account_id TEXT NOT NULL,
    tax_code_id TEXT,
    net_amount NUMERIC(20,4) NOT NULL CHECK(net_amount>=0),
    tax_amount NUMERIC(20,4) NOT NULL CHECK(tax_amount>=0),
    gross_amount NUMERIC(20,4) NOT NULL CHECK(gross_amount>=0),
    UNIQUE(organisation_id,quote_id,line_number),
    FOREIGN KEY(organisation_id,quote_id) REFERENCES quotes(organisation_id,id),
    FOREIGN KEY(organisation_id,account_id) REFERENCES accounts(organisation_id,id),
    FOREIGN KEY(organisation_id,tax_code_id) REFERENCES tax_codes(organisation_id,id)
);
