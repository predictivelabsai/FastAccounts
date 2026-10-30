CREATE TABLE tsd_apa_exports (
 id TEXT PRIMARY KEY,
 organisation_id TEXT NOT NULL,
 payout_id TEXT NOT NULL,
 transaction_id TEXT NOT NULL,
 version INTEGER NOT NULL,
 file_sha256 TEXT NOT NULL,
 file_xml BLOB NOT NULL,
 created_at TEXT NOT NULL,
 created_by TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('Exported','Cancelled','Accepted','Rejected','PartiallyRejected')),
 FOREIGN KEY(organisation_id) REFERENCES organisations(id),
 UNIQUE(organisation_id,id),
 UNIQUE(organisation_id,payout_id,version),
 UNIQUE(organisation_id,transaction_id)
);
CREATE INDEX idx_tsd_apa_exports_org_created ON tsd_apa_exports(organisation_id,created_at DESC,id);
CREATE TABLE tsd_apa_feedback (
 id TEXT PRIMARY KEY,
 organisation_id TEXT NOT NULL,
 export_id TEXT,
 transaction_id TEXT NOT NULL,
 file_result TEXT NOT NULL,
 imported_at TEXT NOT NULL,
 imported_by TEXT NOT NULL,
 FOREIGN KEY(organisation_id) REFERENCES organisations(id),
 FOREIGN KEY(organisation_id,export_id) REFERENCES tsd_apa_exports(organisation_id,id),
 UNIQUE(organisation_id,id)
);
CREATE TABLE tsd_apa_feedback_messages (
 id TEXT PRIMARY KEY,
 organisation_id TEXT NOT NULL,
 feedback_id TEXT NOT NULL,
 rule_code TEXT NOT NULL,
 category TEXT NOT NULL,
 message_text TEXT NOT NULL,
 line_internal_id TEXT,
 line_number_counter TEXT,
 FOREIGN KEY(organisation_id) REFERENCES organisations(id),
 FOREIGN KEY(organisation_id,feedback_id) REFERENCES tsd_apa_feedback(organisation_id,id)
);
CREATE INDEX idx_tsd_apa_feedback_org_export ON tsd_apa_feedback(organisation_id,export_id,imported_at DESC);
