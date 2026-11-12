-- Ops alerting state (site/ops-worker.ts). Same database as the short links;
-- these tables are written only by the alert cron and the Nano's
-- authenticated run events, never by visitor requests.

-- One row per finding key (scraper missing, site down, ...): an alert is
-- open while closed_at IS NULL. Re-opening a closed key reuses its row.
CREATE TABLE IF NOT EXISTS ops_alerts (
  key TEXT PRIMARY KEY,
  severity TEXT NOT NULL,
  title TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  opened_at TEXT NOT NULL,
  last_push TEXT,
  closed_at TEXT
);

-- Nano scrape runs reported by nano/ops_notify.sh (POST /api/ops/event).
-- Pruned to 60 days by the cron.
CREATE TABLE IF NOT EXISTS ops_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  vendor TEXT NOT NULL,
  at TEXT NOT NULL,
  ok INTEGER NOT NULL,
  outcome TEXT NOT NULL,
  detail TEXT,
  items INTEGER
);
CREATE INDEX IF NOT EXISTS ops_runs_vendor ON ops_runs (vendor, id);
CREATE INDEX IF NOT EXISTS ops_runs_at ON ops_runs (at);

-- Small key/value state: the Israel date of the last daily report.
CREATE TABLE IF NOT EXISTS ops_meta (
  name TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
