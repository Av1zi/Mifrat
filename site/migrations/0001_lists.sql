-- Short permanent build links (/list/<id>).
-- Rows are INSERT-ONLY: builds are never updated or deleted, which is what
-- makes links permanent (and lets GET /api/lists/:id be cached immutably).
-- Identical builds share one row via the build_hash unique column.
CREATE TABLE IF NOT EXISTS lists (
  id TEXT PRIMARY KEY,
  build TEXT NOT NULL,
  build_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
