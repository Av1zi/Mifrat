// Shapes of data/ops/*.json (scraper/ops/report.py, SCHEMA_VERSION 1).
// Shared by the admin page and the Worker's alert cron.

export const OPS_SCHEMA = 1;

export interface OpsVendor {
  id: string;
  label: string;
  host: "home" | "cloud";
  active: boolean;
  min_rows: number;
  due_utc: string;
  dropped: string | null;
}

export interface OpsCrawl {
  vendor: string;
  file_day: string;
  start: string;
  end: string;
  rows: number;
  keys: number;
  crawls_in_file: number;
  misfiled: boolean;
  outside_window: boolean;
  suspect: string | null;
  baseline: boolean;
  onboarding: boolean;
  new: number;
  missing: number;
  gone: number;
  returned: number;
  price_changes: number;
}

export interface OpsCatalogVendor {
  listings: number;
  stale: number;
  last_seen: string | null;
}

export interface OpsCatalog {
  generated_at: string | null;
  products: number;
  listings: number;
  skipped_vendors: string[];
  review_queue: number | null;
  vendors: Record<string, OpsCatalogVendor>;
  categories: Record<string, number>;
  qa: Record<string, number>;
  spec_counts: Record<string, number>;
}

export interface OpsStatus {
  schema: number;
  generated_at: string;
  window_days: number;
  vendors: OpsVendor[];
  first_snapshot: Record<string, string>;
  crawls: Record<string, OpsCrawl[]>;
  catalog: OpsCatalog;
}

export type OpsEventType =
  | "new"
  | "gone"
  | "returned"
  | "price"
  | "new_product"
  | "vendor_added"
  | "vendor_lost"
  | "product_gone";

export interface OpsEvent {
  at: string;
  type: OpsEventType;
  vendor?: string;
  key?: string;
  title?: string;
  url?: string;
  price?: number | null;
  old?: number;
  pid?: string;
  product?: string;
  category?: string;
  vendors?: string[];
  last_seen?: string;
  gone_days?: number;
}

export interface OpsAbsent {
  key: string;
  vendor: string;
  state: "missing" | "gone";
  title: string;
  url: string;
  price: number | null;
  last_seen: string;
  since: string;
  pid: string | null;
  product: string;
  category: string;
  product_live: boolean;
}

export interface OpsChanges {
  schema: number;
  generated_at: string;
  event_days: number;
  events: OpsEvent[];
  dropped: Record<string, number>;
  absent: OpsAbsent[];
}
