-- SQLITE_DOCUMENT_IMMUTABILITY
CREATE TRIGGER IF NOT EXISTS invoices_issued_core_immutable
BEFORE UPDATE ON invoices
WHEN OLD.status<>'Draft' AND (
    NEW.organisation_id IS NOT OLD.organisation_id OR NEW.contact_id IS NOT OLD.contact_id OR
    NEW.document_type IS NOT OLD.document_type OR NEW.number IS NOT OLD.number OR
    NEW.issue_date IS NOT OLD.issue_date OR NEW.tax_point_date IS NOT OLD.tax_point_date OR
    NEW.due_date IS NOT OLD.due_date OR NEW.currency IS NOT OLD.currency OR
    NEW.exchange_rate IS NOT OLD.exchange_rate OR NEW.subtotal IS NOT OLD.subtotal OR
    NEW.tax_total IS NOT OLD.tax_total OR NEW.total IS NOT OLD.total
)
BEGIN SELECT RAISE(ABORT,'issued invoice accounting fields are immutable'); END;

CREATE TRIGGER IF NOT EXISTS invoices_issued_delete
BEFORE DELETE ON invoices WHEN OLD.status<>'Draft'
BEGIN SELECT RAISE(ABORT,'issued invoices cannot be deleted'); END;

CREATE TRIGGER IF NOT EXISTS invoice_lines_issued_update
BEFORE UPDATE ON invoice_lines
WHEN (SELECT status FROM invoices WHERE id=OLD.invoice_id)<>'Draft'
BEGIN SELECT RAISE(ABORT,'issued invoice lines are immutable'); END;

CREATE TRIGGER IF NOT EXISTS invoice_lines_issued_delete
BEFORE DELETE ON invoice_lines
WHEN (SELECT status FROM invoices WHERE id=OLD.invoice_id)<>'Draft'
BEGIN SELECT RAISE(ABORT,'issued invoice lines are immutable'); END;

CREATE TRIGGER IF NOT EXISTS bills_approved_core_immutable
BEFORE UPDATE ON bills
WHEN OLD.status IN ('Approved','Part Paid','Paid') AND (
    NEW.organisation_id IS NOT OLD.organisation_id OR NEW.contact_id IS NOT OLD.contact_id OR
    NEW.document_type IS NOT OLD.document_type OR NEW.supplier_number IS NOT OLD.supplier_number OR
    NEW.bill_date IS NOT OLD.bill_date OR NEW.due_date IS NOT OLD.due_date OR
    NEW.currency IS NOT OLD.currency OR NEW.exchange_rate IS NOT OLD.exchange_rate OR
    NEW.subtotal IS NOT OLD.subtotal OR NEW.tax_total IS NOT OLD.tax_total OR NEW.total IS NOT OLD.total
)
BEGIN SELECT RAISE(ABORT,'approved bill accounting fields are immutable'); END;

CREATE TRIGGER IF NOT EXISTS bills_approved_delete
BEFORE DELETE ON bills WHEN OLD.status IN ('Approved','Part Paid','Paid')
BEGIN SELECT RAISE(ABORT,'approved bills cannot be deleted'); END;

CREATE TRIGGER IF NOT EXISTS bill_lines_approved_update
BEFORE UPDATE ON bill_lines
WHEN (SELECT status FROM bills WHERE id=OLD.bill_id) IN ('Approved','Part Paid','Paid')
BEGIN SELECT RAISE(ABORT,'approved bill lines are immutable'); END;

CREATE TRIGGER IF NOT EXISTS bill_lines_approved_delete
BEFORE DELETE ON bill_lines
WHEN (SELECT status FROM bills WHERE id=OLD.bill_id) IN ('Approved','Part Paid','Paid')
BEGIN SELECT RAISE(ABORT,'approved bill lines are immutable'); END;
