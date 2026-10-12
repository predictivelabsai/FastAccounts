-- Local URL templates only. No provider credentials or payment postings.
CREATE UNIQUE INDEX IF NOT EXISTS idx_invoices_tenant_id ON invoices(organisation_id,id);
CREATE TABLE IF NOT EXISTS payment_link_configs (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id),
    provider TEXT NOT NULL CHECK(provider IN ('everypay','linkpay','custom')),
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
    url_template TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT '' CHECK(currency='' OR length(currency)=3),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(organisation_id,id)
);
CREATE TABLE IF NOT EXISTS invoice_payment_links (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id),
    invoice_id TEXT NOT NULL,
    method_id TEXT NOT NULL,
    token TEXT NOT NULL UNIQUE,
    url TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(organisation_id,invoice_id,method_id),
    FOREIGN KEY(organisation_id,invoice_id) REFERENCES invoices(organisation_id,id),
    FOREIGN KEY(organisation_id,method_id) REFERENCES payment_link_configs(organisation_id,id)
);
