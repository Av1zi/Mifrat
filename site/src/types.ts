export interface Offer {
  vendor: string;
  url: string;
  price: number | null;
  in_stock: boolean;
  last_seen: string;
  stale: boolean;
  shipping?: number | null; // optional
  /** Conditional side-price (e.g. TMS whole-PC deal). Never the min price. */
  promo_price?: number | null;
  promo_kind?: string;
}

/**
 * One typed spec value. Units live in the field name (`_ghz`, `_mm`, `_w`,
 * ...) so every number here is already in its final unit — see
 * scraper/specs/schema.py (the single source of truth) and
 * ./specSchema.generated.ts (the field list, generated from it).
 *
 * `null` is a first-class value meaning "unknown": the schema is fixed, so a
 * missing fact is null, never an absent key and never a guess.
 */
export type SpecValue =
  | string
  | number
  | boolean
  | string[]
  | number[]
  | Record<string, number>
  | null;

/**
 * The typed spec sheet shipped per product (scraper/specs/). Keyed by schema
 * field name; site/src/api.ts re-expands the full per-category key set from
 * SPEC_FIELDS so a product always carries every field, with `null` for what no
 * source could supply.
 */
export type ProductSpecs = Record<string, SpecValue>;

export interface Product {
  id: string;
  name: string;
  /** Vendor spec prose (the long title the short name was cut from). */
  description?: string | null;
  category: string;
  brand: string | null;
  model: string | null;
  image?: string | null;
  /** 128px list-thumbnail derivative of image (list rows use this). */
  thumb?: string | null;
  /**
   * Typed, validated, fixed-key spec sheet (scraper/specs/). Every consumer
   * (PDP, category filters/columns, variant pills, compatibility) reads this;
   * the transitional `attributes` blob stays server-side in catalog.json and
   * is never shipped to the browser.
   */
  specs?: ProductSpecs;
  vendor_count: number;
  min_price: number | null;
  in_stock: boolean;
  offers: Offer[];
  /** Vendors with ≥2 distinct listings on this product (under review). */
  duplicate_vendors?: string[];
}

export interface QaCase {
  kind: "duplicate_vendor" | "naming_conflict" | "spec_conflict";
  product_id: string;
  category: string;
  vendor: string;
  /** Conflicting offer titles (naming_conflict only). */
  titles?: string[];
  /** spec_conflict: the schema field two sources disagreed on. */
  field?: string;
  /** spec_conflict: the value the merge kept (higher tier/confidence). */
  kept?: unknown;
  /** spec_conflict: the value that lost and was discarded. */
  dropped?: unknown;
  /** spec_conflict: human-readable detail (cross-field drops). */
  detail?: string;
  offers: Array<{
    listing_key: string;
    vendor_sku: string | null;
    title: string | null;
    price: number | null;
  }>;
}

export interface QaFile {
  generated_at: string;
  cases: QaCase[];
}

/**
 * data/site/spec_report.json — the spec coverage dashboard for one normalize
 * run (scraper/specs/report.py, compacted by scraper/site_data.py). Numbers
 * are integer percentages; `tier0` is the share filled by the reference
 * dataset, `reference_matches` the share matched to a Tier-0 row at all.
 */
export interface SpecReportCategory {
  products: number;
  reference_matches: number;
  fields: Record<string, { filled: number; tier0: number }>;
}

export interface SpecReport {
  products: number;
  reference: Record<string, number>;
  categories: Record<string, SpecReportCategory>;
  counts: { conflicts: number; invalid: number; issues: number };
  invalid_reasons: Record<string, number>;
  conflicts: Array<{
    product_id: string;
    category: string;
    field: string;
    kept: unknown;
    dropped: unknown;
  }>;
  issues: Array<{
    product_id: string;
    category: string;
    kind: string;
    field?: string;
    detail?: string;
  }>;
}

/**
 * One row of data/site/index.json: [id, category, min_price, brand,
 * name]. Compact global lookup — match searches and resolve build-part
 * categories without fetching any per-category file.
 */
export type IndexRow = [
  id: string,
  category: string,
  min_price: number | null,
  brand: string | null,
  name: string | null,
];

export interface CategoryMeta {
  id: string;
  count: number;
  min_price: number | null;
  max_price: number | null;
}

export interface SiteMeta {
  generated_at: string;
  skipped_vendors: string[];
  categories: CategoryMeta[];
}

export type Lang = "he" | "en";
export type Currency = "ILS" | "USD";
export type SortKey = "price_asc" | "price_desc" | "vendors_desc" | "name";

/** data/site/history/<category>.json (see scraper/build_price_history.py). */
export type PriceHistoryFile = {
  dates: string[];
  timestamps?: string[];
} & Record<string, { v: Record<string, Array<number | null>> } | string[]>;

export interface PriceSeries {
  vendor: string;
  prices: Array<number | null>;
}