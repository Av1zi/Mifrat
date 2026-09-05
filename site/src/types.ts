export interface Offer {
  vendor: string;
  url: string;
  price: number | null;
  in_stock: boolean;
  last_seen: string;
  stale: boolean;
  shipping?: number | null; // optional
}

/**
 * Reference specs from the MIT-licensed docyx/pc-part-dataset (Aug 2026,
 * see DECISIONS.md), attached server-side by scraper/matching.py's
 * enrich_products_with_pcpartdb() when a confident name match is found.
 *
 * Deliberately separate from `attributes`: these are specs for "a product
 * like this one" from a third-party dataset, not something scraped from
 * this exact vendor listing. `score` is the match confidence (0-100) —
 * the UI should label this block as a reference, not present it as a
 * verified fact about the listing.
 */
export interface PcPartDbRef {
  name: string;
  score: number;
  specs: Record<string, string | number | boolean>;
}

export interface PcKomboRef {
  mpn: string;
  url: string;
  specs: Record<string, string>;
}

export interface Product {
  id: string;
  name: string;
  category: string;
  brand: string | null;
  model: string | null;
  image?: string | null;
  attributes: Record<string, string>;
  vendor_count: number;
  min_price: number | null;
  in_stock: boolean;
  offers: Offer[];
  pcpartdb?: PcPartDbRef;
  pckombo?: PcKomboRef;
}

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
} & Record<string, { v: Record<string, Array<number | null>> } | string[]>;

export interface PriceSeries {
  vendor: string;
  prices: Array<number | null>;
}