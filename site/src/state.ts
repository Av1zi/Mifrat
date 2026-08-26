import type { Currency, Lang, SortKey } from "./types";

const LANG_KEY = "mifrat:lang";
const CURRENCY_KEY = "mifrat:currency";

export function getLang(): Lang {
  return localStorage.getItem(LANG_KEY) === "en" ? "en" : "he";
}

export function setLang(lang: Lang): void {
  localStorage.setItem(LANG_KEY, lang);
}

export function getCurrency(): Currency {
  return localStorage.getItem(CURRENCY_KEY) === "USD" ? "USD" : "ILS";
}

export function setCurrency(currency: Currency): void {
  localStorage.setItem(CURRENCY_KEY, currency);
}

export interface CategoryParams {
  q: string;
  sort: SortKey;
  stockOnly: boolean;
  /** attribute key -> selected values (OR within a key, AND across keys) */
  filters: Record<string, string[]>;
  /** product id currently shown in the detail overlay, if any */
  productId: string | null;
}

export type Route =
  | { view: "home" }
  | { view: "category"; category: string; params: CategoryParams };

function defaultCategoryParams(): CategoryParams {
  return { q: "", sort: "price_asc", stockOnly: false, filters: {}, productId: null };
}

const VALID_SORTS: SortKey[] = ["price_asc", "price_desc", "vendors_desc", "name"];

export function parseRoute(): Route {
  const raw = location.hash.replace(/^#/, "");
  const [path, queryStr] = raw.split("?");

  const match = /^\/c\/([^/]+)/.exec(path ?? "");
  if (!match) {
    return { view: "home" };
  }

  const category = decodeURIComponent(match[1]);
  const params = defaultCategoryParams();
  const search = new URLSearchParams(queryStr ?? "");

  params.q = search.get("q") ?? "";
  const sort = search.get("sort");
  if (sort && (VALID_SORTS as string[]).includes(sort)) {
    params.sort = sort as SortKey;
  }
  params.stockOnly = search.get("stock") === "1";
  params.productId = search.get("p");

  for (const [key, value] of search.entries()) {
    if (key.startsWith("f.")) {
      const attrKey = key.slice(2);
      params.filters[attrKey] = value.split("|").filter(Boolean);
    }
  }

  return { view: "category", category, params };
}

export function categoryHash(category: string, params: Partial<CategoryParams> = {}): string {
  const merged: CategoryParams = { ...defaultCategoryParams(), ...params };
  const search = new URLSearchParams();

  if (merged.q) search.set("q", merged.q);
  if (merged.sort !== "price_asc") search.set("sort", merged.sort);
  if (merged.stockOnly) search.set("stock", "1");
  if (merged.productId) search.set("p", merged.productId);

  for (const [key, values] of Object.entries(merged.filters)) {
    if (values.length > 0) search.set(`f.${key}`, values.join("|"));
  }

  const query = search.toString();
  return `#/c/${encodeURIComponent(category)}${query ? `?${query}` : ""}`;
}

export function homeHash(): string {
  return "#/";
}

/** Real navigation (home <-> category, opening a product): adds a history entry. */
export function navigate(hash: string): void {
  location.hash = hash;
}

/**
 * In-page state changes (search/sort/filters/stock toggle): updates the
 * address bar for shareability without adding a history entry per click,
 * and deliberately does NOT fire 'hashchange' — callers re-render locally.
 */
export function replaceRoute(hash: string): void {
  history.replaceState(null, "", hash);
}
