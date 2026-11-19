// Data access for the admin console. The ops files are static assets under
// /admin/data/ (copied by scripts/copy-data.mjs); the Worker serves them,
// and the page, only after the ADMIN_PASSWORD check. Runs and alerts come
// from the Worker's admin API (same password; the browser resends it).

import type { OpsChanges, OpsChecks, OpsStatus } from "../ops/types";
import { CHECKS_SCHEMA, OPS_SCHEMA } from "../ops/types";

export interface RunRow {
  vendor: string;
  at: string;
  ok: number;
  outcome: string;
  detail: string | null;
  items: number | null;
}

export interface AlertRow {
  key: string;
  severity: string;
  title: string;
  detail: string;
  opened_at: string;
  last_push: string | null;
  closed_at: string | null;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path, { cache: "no-store", credentials: "same-origin" });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return (await res.json()) as T;
}

export async function loadStatus(): Promise<OpsStatus> {
  const status = await getJson<OpsStatus>("/admin/data/status.json");
  if (status.schema !== OPS_SCHEMA) throw new Error(`status.json schema ${status.schema}, expected ${OPS_SCHEMA}`);
  return status;
}

export async function loadChanges(): Promise<OpsChanges> {
  const changes = await getJson<OpsChanges>("/admin/data/changes.json");
  if (changes.schema !== OPS_SCHEMA) throw new Error(`changes.json schema ${changes.schema}, expected ${OPS_SCHEMA}`);
  if (!Array.isArray(changes.events) || !Array.isArray(changes.absent)) throw new Error("changes.json is missing event history");
  return changes;
}

/** The last publish's check results; null before the first run_checks.py publish. */
export async function loadChecks(): Promise<OpsChecks | null> {
  try {
    const checks = await getJson<OpsChecks>("/admin/data/checks.json");
    return checks.schema === CHECKS_SCHEMA && Array.isArray(checks.checks) ? checks : null;
  } catch {
    return null;
  }
}

/** Runs/alerts live in D1; unavailable locally (vite dev) or before setup. */
export async function loadRuns(): Promise<RunRow[] | null> {
  try {
    const { runs } = await getJson<{ runs: RunRow[] }>("/api/admin/runs");
    return Array.isArray(runs) ? runs : null;
  } catch {
    return null;
  }
}

export async function loadAlerts(): Promise<AlertRow[] | null> {
  try {
    const { alerts } = await getJson<{ alerts: AlertRow[] }>("/api/admin/alerts");
    return Array.isArray(alerts) ? alerts : null;
  } catch {
    return null;
  }
}
