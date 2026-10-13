-- Stage 0 remains the existing pre-due notice. No rows are seeded.
CREATE TABLE IF NOT EXISTS reminder_rules (
    organisation_id TEXT PRIMARY KEY REFERENCES organisations(id),
    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
    stage_1_days INTEGER NOT NULL CHECK(stage_1_days BETWEEN 1 AND 13),
    stage_2_days INTEGER NOT NULL CHECK(stage_2_days BETWEEN 2 AND 14),
    stop_stage INTEGER CHECK(stop_stage IN (0,1,2)),
    updated_at TEXT NOT NULL,
    CHECK(stage_1_days < stage_2_days)
);
