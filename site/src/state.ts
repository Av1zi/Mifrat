import type { Currency, Lang, SortKey } from "./types";

const LANG_KEY = "mifrat:lang";
const CURRENCY_KEY = "mifrat:currency";
const BUILD_KEY = "mifrat:build";
const THEME_KEY = "mifrat:theme";

export type Theme = "light" | "dark";

export function getTheme(): Theme {
  const saved = localStorage.getItem(THEME_KEY);
  if (saved === "dark" || saved === "light") return saved;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function setTheme(theme: Theme): void {
  localStorage.setItem(THEME_KEY, theme);
  document.documentElement.dataset.theme = theme;
}

export function applyStoredTheme(): Theme {
  const theme = getTheme();
  document.documentElement.dataset.theme = theme;
  return theme;
}

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

/** Draft build (slot id -> product id), survives reloads; shared URLs override it. */
export function getStoredBuild(): Record<string, string> {
  try {
    const raw = localStorage.getItem(BUILD_KEY);
    if (raw) {
      const parsed: unknown = JSON.parse(raw);
      if (parsed && typeof parsed === "object") {
        return parsed as Record<string, string>;
      }
    }
  } catch {
    // corrupt entry — start fresh
  }
  return {};
}

export function setStoredBuild(build: Record<string, string>): void {
  localStorage.setItem(BUILD_KEY, JSON.stringify(build));
}

export interface CategoryParams {
  q: string;
  sort: SortKey;
  stockOnly: boolean;
  filters: Record<string, string[]>;
  ranges: Record<string, { min: number | null; max: number | null }>;
  productId: string | null;

  /**
   * Builder slot id when this category page is being used as a part picker.
   * Example: #/c/motherboard?pick=motherboard
   */
  pick: string | null;
}

export type Route =
  | { view: "home" }
  | { view: "build"; shared: Record<string, string> | null }
  | { view: "category"; category: string; params: CategoryParams }
  | { view: "product"; category: string; productId: string };

function defaultCategoryParams(): CategoryParams {
  return {
    q: "",
    sort: "price_asc",
    stockOnly: false,
    filters: {},
    ranges: {},
    productId: null,
    pick: null,
  };
}

const VALID_SORTS: SortKey[] = [
  "price_asc",
  "price_desc",
  "vendors_desc",
  "name",
];

export function parseRoute(): Route {
  const raw = location.hash.replace(/^#/, "");
  const [path, queryStr] = raw.split("?");

  if (path === "/build" || path === "/build/") {
    const search = new URLSearchParams(queryStr ?? "");
    const shared: Record<string, string> = {};

    for (const [key, value] of search.entries()) {
      if (value) shared[key] = value;
    }

    return {
      view: "build",
      shared: Object.keys(shared).length ? shared : null,
    };
  }

  const productMatch = /^\/p\/([^/]+)\/([^/]+)/.exec(path ?? "");
  if (productMatch) {
    return {
      view: "product",
      category: decodeURIComponent(productMatch[1]),
      productId: decodeURIComponent(productMatch[2]),
    };
  }

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
  params.pick = search.get("pick");

  for (const [key, value] of search.entries()) {
    if (key.startsWith("f.")) {
      const attrKey = key.slice(2);
      params.filters[attrKey] = value.split("|").filter(Boolean);
    } else if (key.startsWith("r.")) {
      const attrKey = key.slice(2);
      const [minStr, maxStr] = value.split(",");
      const min = minStr ? parseFloat(minStr) : null;
      const max = maxStr ? parseFloat(maxStr) : null;
      const minValid = min !== null && !isNaN(min);
      const maxValid = max !== null && !isNaN(max);
      if (minValid || maxValid) {
        params.ranges[attrKey] = { min: minValid ? min : null, max: maxValid ? max : null };
      }
    }
  }

  return { view: "category", category, params };
}

export function categoryHash(
  category: string,
  params: Partial<CategoryParams> = {}
): string {
  const merged: CategoryParams = {
    ...defaultCategoryParams(),
    ...params,
  };

  const search = new URLSearchParams();

  if (merged.q) search.set("q", merged.q);
  if (merged.sort !== "price_asc") search.set("sort", merged.sort);
  if (merged.stockOnly) search.set("stock", "1");
  if (merged.productId) search.set("p", merged.productId);
  if (merged.pick) search.set("pick", merged.pick);

  for (const [key, values] of Object.entries(merged.filters)) {
    if (values.length > 0) search.set(`f.${key}`, values.join("|"));
  }

  for (const [key, range] of Object.entries(merged.ranges)) {
    const minStr = range.min !== null ? String(range.min) : "";
    const maxStr = range.max !== null ? String(range.max) : "";
    if (minStr || maxStr) search.set(`r.${key}`, `${minStr},${maxStr}`);
  }

  const query = search.toString();
  return `#/c/${encodeURIComponent(category)}${query ? `?${query}` : ""}`;
}

/** Shareable per-product page: #/p/<category>/<productId>. */
export function productHash(category: string, productId: string): string {
  return `#/p/${encodeURIComponent(category)}/${encodeURIComponent(productId)}`;
}

/** The build IS the URL — shareable with no backend. */
export function buildHash(build: Record<string, string>): string {
  const search = new URLSearchParams();

  for (const [slot, id] of Object.entries(build)) {
    if (id) search.set(slot, id);
  }

  const query = search.toString();
  return `#/build${query ? `?${query}` : ""}`;
}

export function homeHash(): string {
  return "#/";
}

/** Real navigation: adds a history entry. */
export function navigate(hash: string): void {
  location.hash = hash;
}

/**
In-page state changes: updates address bar without adding history entry.
Does NOT fire hashchange — callers re-render locally.
*/
export function replaceRoute(hash: string): void {
  history.replaceState(null, "", hash);
}