ALTER TABLE tsd_apa_exports ADD COLUMN operation TEXT NOT NULL DEFAULT 'R' CHECK(operation IN ('R','M'));
CREATE TABLE tsd_apa_export_cancellations (
 id TEXT PRIMARY KEY,
 organisation_id TEXT NOT NULL,
 export_id TEXT NOT NULL,
 file_xml BLOB NOT NULL,
 created_at TEXT NOT NULL,
 created_by TEXT NOT NULL,
 UNIQUE(organisation_id,id),
 FOREIGN KEY(organisation_id,export_id) REFERENCES tsd_apa_exports(organisation_id,id)
);
CREATE INDEX idx_tsd_apa_cancellations_export ON tsd_apa_export_cancellations(organisation_id,export_id,created_at);
