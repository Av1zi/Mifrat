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
  /** The only price held needs a whole-PC purchase; ranks after plain offers. */
  bundle_only?: boolean;
  /** Plain price, plus a cheaper whole-PC deal (promo_price when known). */
  new_pc_deal?: boolean;
  /** Same store's cheaper clearance listing of this part ("מציאון ועודפים"). */
  clearance_price?: number | null;
  /** Store-wide sale: the old, crossed-out price (price is what everyone pays now). */
  was_price?: number | null;
  /** Store-wide sale sticker text, e.g. "-12%". */
  sale_text?: string;
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
  kind:
    | "duplicate_vendor"
    | "naming_conflict"
    | "spec_conflict"
    | "core_gap"
    | "identity_merge"
    | "packaging_conflict"
    | "variant_conflict"
    | "split_candidate"
    | "unflagged_deal";
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
  /** core_gap: every missing core-compatibility field of the product. */
  fields?: string[];
  /** Identity decisions (scraper/identity.py): the model code involved. */
  model_code?: string | null;
  /** identity_merge: the retired product id whose listings moved here. */
  merged_from?: string | null;
  /** variant_conflict: the disagreeing manufacturer part numbers. */
  manufacturer_pn?: string[];
  /** packaging_conflict: whether the mislabelled listing was moved. */
  resolved?: boolean;
  /** packaging_conflict: why it was not moved. */
  reason?: string;
  /** packaging_conflict: the vendor SKU that moved. */
  moved?: string | null;
  /** duplicate_vendor: the vendor's listings already fold into one offer. */
  collapsed?: boolean;
  offers: Array<{
    listing_key: string;
    vendor_sku: string | null;
    title: string | null;
    price: number | null;
    /** duplicate_vendor: the primary listing this one folds into. */
    alias_of?: string;
  }>;
}

export interface QaFile {
  generated_at: string;
  cases: QaCase[];
  /** Identity cases per kind before the per-kind display cap. */
  identity_counts?: Record<string, number>;
}

/**
 * data/site/spec_report.json — the spec coverage dashboard for one normalize
 * run (scraper/specs/report.py, compacted by scraper/site_data.py). Numbers
 * are integer percentages; `tier0` is the share filled by the reference
 * dataset, `reference_matches` the share matched to a Tier-0 row at all.
 */
interface SpecReportCategory {
  products: number;
  reference_matches: number;
  derived?: number;
  unknown?: number;
  sources?: Record<string, number>;
  fields: Record<
    string,
    {
      filled: number;
      null?: number;
      tier0: number;
      sources?: Record<string, number>;
      unknown_reasons?: Record<string, number>;
    }
  >;
}

export interface SpecReport {
  products: number;
  reference: Record<string, number>;
  derived?: number;
  sources?: Record<string, number>;
  categories: Record<string, SpecReportCategory>;
  counts: {
    conflicts: number;
    invalid: number;
    issues: number;
    unknown?: number;
    core_gaps?: number;
  };
  unknown?: Array<{ product_id: string; category: string; field: string; reason: string }>;
  core_gaps?: Array<{
    product_id: string;
    category: string;
    field: string;
    reason: string;
  }>;
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
  /** Same-origin cover photo for the header menu (chosen by the scraper). */
  cover?: string | null;
}

export interface SiteMeta {
  generated_at: string;
  skipped_vendors: string[];
  categories: CategoryMeta[];
  /**
   * Retired product id -> the product that now holds its listings (§3.6).
   * Saved builds are insert-only and bookmarks outlive a catalog rework, so
   * an unknown id is resolved through this map before it is treated as gone.
   */
  pid_aliases?: Record<string, string>;
}

export type Lang = "he" | "en";
export type Currency = "ILS" | "USD";
export type SortKey =
  | "relevance"
  | "price_asc"
  | "price_desc"
  | "vendors_desc"
  | "name"
  | "name_desc";

/** data/site/history/<category>.json (see scraper/build_price_history.py). */
export type PriceHistoryFile = {
  dates: string[];
  timestamps?: string[];
} & Record<string, { v: Record<string, Array<number | null>> } | string[]>;
