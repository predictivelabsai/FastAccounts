CREATE TABLE import_staged_records (
 id TEXT PRIMARY KEY,
 organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
 sync_run_id TEXT NOT NULL REFERENCES sync_runs(id) ON DELETE CASCADE,
 provider TEXT NOT NULL,
 object_type TEXT NOT NULL,
 external_id TEXT,
 external_payload_json TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'Pending' CHECK(status IN ('Pending','Approved','Rejected','Applied','Failed')),
 matched_local_employee_id TEXT,
 review_note TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 FOREIGN KEY(organisation_id,matched_local_employee_id) REFERENCES employees(organisation_id,id)
);
CREATE INDEX idx_import_staged_records_org_status ON import_staged_records(organisation_id,status);
CREATE INDEX idx_import_staged_records_sync_run ON import_staged_records(sync_run_id);
