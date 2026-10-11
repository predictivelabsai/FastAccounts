ALTER TABLE sync_runs ADD COLUMN payload_json TEXT;
ALTER TABLE sync_runs ADD COLUMN local_ref TEXT;

CREATE UNIQUE INDEX idx_pending_push_document ON sync_runs
    (organisation_id,provider,object_type,local_ref)
    WHERE direction='export' AND status IN ('Queued','Running','Review Required');
