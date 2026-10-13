-- Analytical dimensions use companion rows to preserve immutable parent tables.
CREATE TABLE IF NOT EXISTS objects (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id),
    object_type TEXT NOT NULL CHECK(object_type IN ('project','location','person','object')),
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    code TEXT NOT NULL CHECK(length(code) BETWEEN 1 AND 40),
    name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 180),
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(organisation_id,object_type,code)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_objects_tenant_id ON objects(organisation_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_objects_tenant_type ON objects(organisation_id,id,object_type);
CREATE UNIQUE INDEX IF NOT EXISTS idx_invoice_lines_parent_id ON invoice_lines(invoice_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bill_lines_parent_id ON bill_lines(bill_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_gl_entries_tenant_id ON gl_entries(organisation_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_gl_entries_parent_id ON gl_entries(posting_batch_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_invoices_tenant_id ON invoices(organisation_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bills_tenant_id ON bills(organisation_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_posting_batches_tenant_id ON posting_batches(organisation_id,id);
CREATE TABLE IF NOT EXISTS invoice_line_objects (
    organisation_id TEXT NOT NULL,
    parent_id TEXT NOT NULL,
    line_id TEXT NOT NULL,
    projects_project_id TEXT,
    projects_project_id_type TEXT NOT NULL DEFAULT 'project' CHECK(projects_project_id_type='project'),
    projects_location_id TEXT,
    projects_location_id_type TEXT NOT NULL DEFAULT 'location' CHECK(projects_location_id_type='location'),
    projects_person_id TEXT,
    projects_person_id_type TEXT NOT NULL DEFAULT 'person' CHECK(projects_person_id_type='person'),
    projects_object_id TEXT,
    projects_object_id_type TEXT NOT NULL DEFAULT 'object' CHECK(projects_object_id_type='object'),
    PRIMARY KEY(organisation_id,line_id),
    FOREIGN KEY(organisation_id,projects_project_id,projects_project_id_type) REFERENCES objects(organisation_id,id,object_type),
    FOREIGN KEY(organisation_id,projects_location_id,projects_location_id_type) REFERENCES objects(organisation_id,id,object_type),
    FOREIGN KEY(organisation_id,projects_person_id,projects_person_id_type) REFERENCES objects(organisation_id,id,object_type),
    FOREIGN KEY(organisation_id,projects_object_id,projects_object_id_type) REFERENCES objects(organisation_id,id,object_type),
    FOREIGN KEY(organisation_id,parent_id) REFERENCES invoices(organisation_id,id),
    FOREIGN KEY(parent_id,line_id) REFERENCES invoice_lines(invoice_id,id)
);
CREATE INDEX IF NOT EXISTS idx_invoice_line_objects_projects_project_id ON invoice_line_objects(organisation_id,projects_project_id);
CREATE INDEX IF NOT EXISTS idx_invoice_line_objects_projects_location_id ON invoice_line_objects(organisation_id,projects_location_id);
CREATE INDEX IF NOT EXISTS idx_invoice_line_objects_projects_person_id ON invoice_line_objects(organisation_id,projects_person_id);
CREATE INDEX IF NOT EXISTS idx_invoice_line_objects_projects_object_id ON invoice_line_objects(organisation_id,projects_object_id);
CREATE TABLE IF NOT EXISTS bill_line_objects (
    organisation_id TEXT NOT NULL,
    parent_id TEXT NOT NULL,
    line_id TEXT NOT NULL,
    projects_project_id TEXT,
    projects_project_id_type TEXT NOT NULL DEFAULT 'project' CHECK(projects_project_id_type='project'),
    projects_location_id TEXT,
    projects_location_id_type TEXT NOT NULL DEFAULT 'location' CHECK(projects_location_id_type='location'),
    projects_person_id TEXT,
    projects_person_id_type TEXT NOT NULL DEFAULT 'person' CHECK(projects_person_id_type='person'),
    projects_object_id TEXT,
    projects_object_id_type TEXT NOT NULL DEFAULT 'object' CHECK(projects_object_id_type='object'),
    PRIMARY KEY(organisation_id,line_id),
    FOREIGN KEY(organisation_id,projects_project_id,projects_project_id_type) REFERENCES objects(organisation_id,id,object_type),
    FOREIGN KEY(organisation_id,projects_location_id,projects_location_id_type) REFERENCES objects(organisation_id,id,object_type),
    FOREIGN KEY(organisation_id,projects_person_id,projects_person_id_type) REFERENCES objects(organisation_id,id,object_type),
    FOREIGN KEY(organisation_id,projects_object_id,projects_object_id_type) REFERENCES objects(organisation_id,id,object_type),
    FOREIGN KEY(organisation_id,parent_id) REFERENCES bills(organisation_id,id),
    FOREIGN KEY(parent_id,line_id) REFERENCES bill_lines(bill_id,id)
);
CREATE INDEX IF NOT EXISTS idx_bill_line_objects_projects_project_id ON bill_line_objects(organisation_id,projects_project_id);
CREATE INDEX IF NOT EXISTS idx_bill_line_objects_projects_location_id ON bill_line_objects(organisation_id,projects_location_id);
CREATE INDEX IF NOT EXISTS idx_bill_line_objects_projects_person_id ON bill_line_objects(organisation_id,projects_person_id);
CREATE INDEX IF NOT EXISTS idx_bill_line_objects_projects_object_id ON bill_line_objects(organisation_id,projects_object_id);
CREATE TABLE IF NOT EXISTS gl_entry_objects (
    organisation_id TEXT NOT NULL,
    parent_id TEXT NOT NULL,
    line_id TEXT NOT NULL,
    projects_project_id TEXT,
    projects_project_id_type TEXT NOT NULL DEFAULT 'project' CHECK(projects_project_id_type='project'),
    projects_location_id TEXT,
    projects_location_id_type TEXT NOT NULL DEFAULT 'location' CHECK(projects_location_id_type='location'),
    projects_person_id TEXT,
    projects_person_id_type TEXT NOT NULL DEFAULT 'person' CHECK(projects_person_id_type='person'),
    projects_object_id TEXT,
    projects_object_id_type TEXT NOT NULL DEFAULT 'object' CHECK(projects_object_id_type='object'),
    PRIMARY KEY(organisation_id,line_id),
    FOREIGN KEY(organisation_id,projects_project_id,projects_project_id_type) REFERENCES objects(organisation_id,id,object_type),
    FOREIGN KEY(organisation_id,projects_location_id,projects_location_id_type) REFERENCES objects(organisation_id,id,object_type),
    FOREIGN KEY(organisation_id,projects_person_id,projects_person_id_type) REFERENCES objects(organisation_id,id,object_type),
    FOREIGN KEY(organisation_id,projects_object_id,projects_object_id_type) REFERENCES objects(organisation_id,id,object_type),
    FOREIGN KEY(organisation_id,parent_id) REFERENCES posting_batches(organisation_id,id),
    FOREIGN KEY(parent_id,line_id) REFERENCES gl_entries(posting_batch_id,id),
    FOREIGN KEY(organisation_id,line_id) REFERENCES gl_entries(organisation_id,id)
);
CREATE INDEX IF NOT EXISTS idx_gl_entry_objects_projects_project_id ON gl_entry_objects(organisation_id,projects_project_id);
CREATE INDEX IF NOT EXISTS idx_gl_entry_objects_projects_location_id ON gl_entry_objects(organisation_id,projects_location_id);
CREATE INDEX IF NOT EXISTS idx_gl_entry_objects_projects_person_id ON gl_entry_objects(organisation_id,projects_person_id);
CREATE INDEX IF NOT EXISTS idx_gl_entry_objects_projects_object_id ON gl_entry_objects(organisation_id,projects_object_id);

-- SQLITE_ANALYTICAL_IMMUTABILITY
CREATE TRIGGER IF NOT EXISTS invoice_line_objects_immutable_insert
BEFORE INSERT ON invoice_line_objects
WHEN (SELECT status FROM invoices WHERE organisation_id=NEW.organisation_id AND id=NEW.parent_id)<>'Draft'
BEGIN SELECT RAISE(ABORT,'posted analytical dimensions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS invoice_line_objects_immutable_update
BEFORE UPDATE ON invoice_line_objects
WHEN (SELECT status FROM invoices WHERE organisation_id=OLD.organisation_id AND id=OLD.parent_id)<>'Draft' OR (SELECT status FROM invoices WHERE organisation_id=NEW.organisation_id AND id=NEW.parent_id)<>'Draft'
BEGIN SELECT RAISE(ABORT,'posted analytical dimensions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS invoice_line_objects_immutable_delete
BEFORE DELETE ON invoice_line_objects
WHEN (SELECT status FROM invoices WHERE organisation_id=OLD.organisation_id AND id=OLD.parent_id)<>'Draft'
BEGIN SELECT RAISE(ABORT,'posted analytical dimensions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS bill_line_objects_immutable_insert
BEFORE INSERT ON bill_line_objects
WHEN (SELECT status FROM bills WHERE organisation_id=NEW.organisation_id AND id=NEW.parent_id) IN ('Approved','Part Paid','Paid','Voided')
BEGIN SELECT RAISE(ABORT,'posted analytical dimensions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS bill_line_objects_immutable_update
BEFORE UPDATE ON bill_line_objects
WHEN (SELECT status FROM bills WHERE organisation_id=OLD.organisation_id AND id=OLD.parent_id) IN ('Approved','Part Paid','Paid','Voided') OR (SELECT status FROM bills WHERE organisation_id=NEW.organisation_id AND id=NEW.parent_id) IN ('Approved','Part Paid','Paid','Voided')
BEGIN SELECT RAISE(ABORT,'posted analytical dimensions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS bill_line_objects_immutable_delete
BEFORE DELETE ON bill_line_objects
WHEN (SELECT status FROM bills WHERE organisation_id=OLD.organisation_id AND id=OLD.parent_id) IN ('Approved','Part Paid','Paid','Voided')
BEGIN SELECT RAISE(ABORT,'posted analytical dimensions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS gl_entry_objects_immutable_insert
BEFORE INSERT ON gl_entry_objects
WHEN (SELECT status FROM posting_batches WHERE organisation_id=NEW.organisation_id AND id=NEW.parent_id)<>'Draft'
BEGIN SELECT RAISE(ABORT,'posted analytical dimensions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS gl_entry_objects_immutable_update
BEFORE UPDATE ON gl_entry_objects
WHEN (SELECT status FROM posting_batches WHERE organisation_id=OLD.organisation_id AND id=OLD.parent_id)<>'Draft' OR (SELECT status FROM posting_batches WHERE organisation_id=NEW.organisation_id AND id=NEW.parent_id)<>'Draft'
BEGIN SELECT RAISE(ABORT,'posted analytical dimensions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS gl_entry_objects_immutable_delete
BEFORE DELETE ON gl_entry_objects
WHEN (SELECT status FROM posting_batches WHERE organisation_id=OLD.organisation_id AND id=OLD.parent_id)<>'Draft'
BEGIN SELECT RAISE(ABORT,'posted analytical dimensions are immutable'); END;
