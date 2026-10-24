import { loadCategory, loadIndex } from "../../api";
import { BUILD_SLOTS, type BuildSlot } from "../../build";
import {
  filterableSpecs,
  formatSpecValue,
  isNumericSpec,
  specFieldMap,
  specFields,
  specValue,
} from "../../specs";
import type { BuildMap, CategoryParams, ListView } from "../../state";
import type { PriceSignal } from "../../signals";
import type { Currency, Lang, Product, SortKey } from "../../types";
import { normSearch, searchScore, searchTokens, skuOf } from "../../utils";
import { positivePrice } from "../../ui/price";

export const PAGE_SIZE = 60;

export type OptionCounts = Array<[string, number]>;
export type Range = { min: number; max: number };

/** Everything one category page needs. Built once in index.ts, passed explicitly. */
export interface CategoryCtx {
  container: HTMLElement;
  lang: Lang;
  currency: Currency;
  category: string;
  params: CategoryParams;
  /** The universe on show: all products, or the slot-compatible ones when picking. */
  products: Product[];
  byId: Map<string, Product>;
  pickSlot: BuildSlot | null;
  hiddenIncompatible: number;
  storedBuild: BuildMap;
  build: LoadedBuild;
  targetSlotId: string | null;
  compatOn: boolean;
  /** Filter keys the compat logic applied itself (removed when toggled off). */
  compatAutoKeys: Set<string>;
  query: string;
  sortTouched: boolean;
  view: ListView;
  /** Extra batches revealed by scrolling (rows shown = (page + 1) * PAGE_SIZE). */
  page: number;
  filterable: Map<string, OptionCounts>;
  ranges: Map<string, Range>;
  columns: string[];
  /** Price-drop signals by product id; filled once the history file arrives. */
  signals: Map<string, PriceSignal>;
}

/** Callbacks the view modules use to ask index.ts to re-render. */
export interface CategoryActions {
  /** Filters/query/sort changed: sync the URL, refresh rail states, redraw the list. */
  update(): void;
  /** Redraw the list only (view toggle, infinite scroll). */
  redrawList(): void;
  /** Rebuild the rail markup (compat toggled, filters cleared). */
  rebuildRail(): void;
  openSheet(open: boolean): void;
}

// ---- spec text ------------------------------------------------------------

/**
 * Canonical (lang-independent) text of one typed spec value: the filter key
 * and checkbox value, so URL params, strict equality and labels agree.
 */
export function canonicalSpecText(product: Product, field: string): string {
  return formatSpecValue(specValue(product, field), "en");
}

const listFieldMemo = new Map<string, Set<string>>();

/** List-valued fields filter per element ("AM4", not the 40 whole combinations). */
export function listFieldsFor(category: string): Set<string> {
  let set = listFieldMemo.get(category);
  if (!set) {
    set = new Set(
      specFields(category)
        .filter((field) => field.type === "list_str")
        .map((field) => field.name)
    );
    listFieldMemo.set(category, set);
  }
  return set;
}

/** Filter option values one product contributes for a field. */
export function specOptionValues(product: Product, field: string, list: boolean): string[] {
  if (list) {
    const value = specValue(product, field);
    if (Array.isArray(value)) return value.map((item) => String(item)).filter(Boolean);
  }
  const text = canonicalSpecText(product, field);
  return text ? [text] : [];
}

// ---- filter universe ---------------------------------------------------------

const filterableCache = new WeakMap<Product[], Map<string, OptionCounts>>();

export function computeFilterable(products: Product[], category: string): Map<string, OptionCounts> {
  const cached = filterableCache.get(products);
  if (cached) return cached;

  const fields = specFieldMap(category);
  const listFields = listFieldsFor(category);
  const counts = new Map<string, Map<string, number>>();

  // Schema order is rail order (identity -> core -> power -> physical -> io).
  // Only fields the schema flags `filterable` become checkbox filters.
  for (const p of products) {
    for (const field of filterableSpecs(category)) {
      if (isNumericSpec(fields.get(field))) continue;
      let values = counts.get(field);
      if (!values) {
        values = new Map();
        counts.set(field, values);
      }
      for (const value of specOptionValues(p, field, listFields.has(field))) {
        values.set(value, (values.get(value) ?? 0) + 1);
      }
    }
    const vendors = new Set(p.offers.map((o) => o.vendor));
    if (vendors.size > 0 && !counts.has("vendor")) counts.set("vendor", new Map());
    for (const v of vendors) {
      const values = counts.get("vendor")!;
      values.set(v, (values.get(v) ?? 0) + 1);
    }
  }

  const out = new Map<string, OptionCounts>();
  for (const [key, values] of counts) {
    // Long lists collapse behind "show more"; the cap only stops runaway
    // free-text keys.
    const max = key === "vendor" ? 30 : 70;
    if (values.size < 2 || values.size > max) continue;
    out.set(key, Array.from(values.entries()).sort((a, b) => b[1] - a[1]));
  }
  filterableCache.set(products, out);
  return out;
}

export function computeRanges(products: Product[], category: string): Map<string, Range> {
  const fields = specFieldMap(category);
  const numeric = filterableSpecs(category).filter((field) => isNumericSpec(fields.get(field)));
  const ranges = new Map<string, Range>();
  const widen = (key: string, value: number): void => {
    const range = ranges.get(key) ?? { min: Infinity, max: -Infinity };
    range.min = Math.min(range.min, value);
    range.max = Math.max(range.max, value);
    ranges.set(key, range);
  };
  for (const p of products) {
    for (const field of numeric) {
      const value = specValue(p, field);
      if (typeof value === "number" && Number.isFinite(value)) widen(field, value);
    }
    const price = positivePrice(p.min_price);
    if (price !== null) widen("price", price);
  }
  for (const [key, range] of ranges) {
    if (range.min === Infinity || range.max === -Infinity) ranges.delete(key);
  }
  return ranges;
}

// ---- filtering / sorting --------------------------------------------------------

function productSearchHay(p: Product): {
  haystack: string;
  name: string;
  brand: string;
  category: string;
} {
  const partNumbers = specValue(p, "part_numbers");
  const mpn = Array.isArray(partNumbers) ? partNumbers.join(" ") : "";
  return {
    haystack: normSearch(`${p.name} ${p.brand ?? ""} ${p.model ?? ""} ${skuOf(p)} ${mpn}`),
    name: normSearch(p.name),
    brand: normSearch(p.brand ?? ""),
    category: "",
  };
}

function numericValue(p: Product, field: string): number | null {
  if (field === "price") return positivePrice(p.min_price);
  const value = specValue(p, field);
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function applyFilters(products: Product[], params: CategoryParams, query: string): Product[] {
  const tokens = searchTokens(query);
  const listFields = listFieldsFor(products[0]?.category ?? "");

  return products.filter((p) => {
    if (params.stockOnly && !p.in_stock) return false;
    if (tokens.length > 0 && searchScore(tokens, productSearchHay(p)) < 0) return false;

    for (const [key, values] of Object.entries(params.filters)) {
      if (values.length === 0) continue;
      if (key === "vendor") {
        if (!p.offers.some((o) => values.includes(o.vendor))) return false;
        continue;
      }
      const text = canonicalSpecText(p, key);
      if (text && values.includes(text)) continue;
      const own = listFields.has(key)
        ? specOptionValues(p, key, true)
        : text
          ? text.split(", ")
          : [];
      if (!values.some((v) => own.includes(v))) return false;
    }

    for (const [key, range] of Object.entries(params.ranges)) {
      const value = numericValue(p, key);
      if (value === null) return false;
      if (range.min !== null && value < range.min) return false;
      if (range.max !== null && value > range.max) return false;
    }
    return true;
  });
}

function sortProducts(products: Product[], sort: SortKey, query = ""): Product[] {
  const arr = [...products];
  // Unknown prices sort last in both directions.
  const asc = (p: Product): number => positivePrice(p.min_price) ?? Infinity;

  switch (sort) {
    case "relevance": {
      const tokens = searchTokens(query);
      if (tokens.length === 0) {
        arr.sort((a, b) => asc(a) - asc(b));
        break;
      }
      const scores = new Map(arr.map((p) => [p, searchScore(tokens, productSearchHay(p))]));
      arr.sort((a, b) => (scores.get(b) ?? 0) - (scores.get(a) ?? 0) || asc(a) - asc(b));
      break;
    }
    case "price_asc":
      arr.sort((a, b) => asc(a) - asc(b));
      break;
    case "price_desc":
      arr.sort((a, b) => asc(b) - asc(a));
      break;
    case "vendors_desc":
      arr.sort((a, b) => b.vendor_count - a.vendor_count || asc(a) - asc(b));
      break;
    case "name":
      arr.sort((a, b) => a.name.localeCompare(b.name, "en", { numeric: true }));
      break;
    case "name_desc":
      arr.sort((a, b) => b.name.localeCompare(a.name, "en", { numeric: true }));
      break;
  }
  return arr;
}

export function currentList(ctx: CategoryCtx): Product[] {
  return sortProducts(applyFilters(ctx.products, ctx.params, ctx.query), ctx.params.sort, ctx.query);
}

// ---- current build ------------------------------------------------------------

interface LoadedBuild {
  /** First picked product per slot (compatibility checks + wattage). */
  first: Record<string, Product>;
  /** Every picked product (totals). */
  items: Array<{ slotId: string; product: Product }>;
}

/**
 * Resolves the stored draft to products: each id's category comes from
 * index.json, then only those category files are fetched (cached). Ids that
 * no longer resolve simply drop out.
 */
export async function loadBuildParts(build: BuildMap): Promise<LoadedBuild> {
  const first: Record<string, Product> = {};
  const items: LoadedBuild["items"] = [];
  const wanted: Array<{ slotId: string; productId: string }> = [];
  for (const slot of BUILD_SLOTS) {
    for (const productId of build[slot.id] ?? []) wanted.push({ slotId: slot.id, productId });
  }
  if (wanted.length === 0) return { first, items };

  let catOf: Map<string, string>;
  try {
    catOf = new Map((await loadIndex()).map((row) => [row[0], row[1]]));
  } catch {
    return { first, items };
  }
  const byCategory = new Map<string, typeof wanted>();
  for (const w of wanted) {
    const category = catOf.get(w.productId);
    if (!category) continue;
    byCategory.set(category, [...(byCategory.get(category) ?? []), w]);
  }
  await Promise.all(
    [...byCategory].map(async ([category, list]) => {
      let products: Product[];
      try {
        products = await loadCategory(category);
      } catch {
        return;
      }
      for (const w of list) {
        const product = products.find((p) => p.id === w.productId);
        if (!product) continue;
        items.push({ slotId: w.slotId, product });
        if (!first[w.slotId]) first[w.slotId] = product;
      }
    })
  );
  return { first, items };
}
