-- Master-data maintenance: contacts gain an active flag (items already have
-- one since 0003). Column additions are guarded by the migration runner on
-- SQLite reruns the same way migrations 0027 and 0029 are.
ALTER TABLE contacts ADD COLUMN active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1));