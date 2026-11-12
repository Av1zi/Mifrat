// Data access for the admin console. The ops files are static assets under
// /admin/data/ (copied by scripts/copy-data.mjs, protected by Cloudflare
// Access with the page); runs and alerts come from the Worker's admin API.

import type { OpsChanges, OpsStatus } from "../ops/types";
import { OPS_SCHEMA } from "../ops/types";

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
  return getJson<OpsChanges>("/admin/data/changes.json");
}

/** Runs/alerts live in D1; unavailable locally (vite dev) or before setup. */
export async function loadRuns(): Promise<RunRow[] | null> {
  try {
    return (await getJson<{ runs: RunRow[] }>("/api/admin/runs")).runs;
  } catch {
    return null;
  }
}

export async function loadAlerts(): Promise<AlertRow[] | null> {
  try {
    return (await getJson<{ alerts: AlertRow[] }>("/api/admin/alerts")).alerts;
  } catch {
    return null;
  }
}
