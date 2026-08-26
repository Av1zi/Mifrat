export interface Offer {
  vendor: string;
  url: string;
  price: number | null;
  in_stock: boolean;
  last_seen: string;
  stale: boolean;
  shipping?: number | null; // optional
}

export interface Product {
  id: string;
  name: string;
  category: string;
  brand: string | null;
  model: string | null;
  attributes: Record<string, string>;
  vendor_count: number;
  min_price: number | null;
  in_stock: boolean;
  offers: Offer[];
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
