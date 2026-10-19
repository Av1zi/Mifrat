import type { Product } from "./types";

/**
Escapes scraped/dynamic text before inserting it via innerHTML. Product
titles come from vendor sites and can contain "&", quotes (inch marks),
or stray angle brackets — none of it is trusted markup.
*/
export function esc(value: unknown): string {
  if (value === null || value === undefined) return "";
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * URL scheme allowlist for scraped href/src sinks.
 *
 * esc() neutralizes <>"'& but `href="javascript:..."` needs no special
 * chars — so every offer.url / product.image goes through here first.
 * Buy links allow https/http + same-origin paths + fragments; anything
 * else (javascript:, data:, vbscript:, file:) returns null and the caller
 * must skip the link.
 */
export function safeUrl(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  const v = raw.trim();
  if (/^(https?:\/\/|\/[^/]|#)/i.test(v)) return v;
  return null;
}

/**
 * Stricter variant for <img> sinks: same-origin /images/... only.
 * Combined with the local-only image policy in scraper/site_data.py
 * (no remote fallback), the Network tab shows zero vendor-host image
 * requests. Remote URLs — even https: — return null so the caller
 * renders the initials-thumb fallback instead of hotlinking.
 */
export function safeImageUrl(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  const v = raw.trim();
  if (v.startsWith("/images/")) return v;
  return null;
}

/**
 * Search normalization + ranking (shared by the nav search and the category
 * page search so both agree on what "a match" is).
 *
 * Matching is token-based: every whitespace-separated token of the query
 * must appear somewhere in the haystack ("gigabyte 5070 oc" no longer
 * matches nothing just because the words are not adjacent). Ranking adds
 * brand/category scoping: a query token that equals the brand or the
 * category label lifts those products above the rest.
 */
export function normSearch(value: string): string {
  return value
    .toLowerCase()
    .normalize("NFKC")
    .replace(/["'`׳״־–—]/g, " ")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function searchTokens(query: string): string[] {
  const norm = normSearch(query);
  return norm ? norm.split(" ") : [];
}

interface SearchScoreInput {
  /** Pre-normalized haystack the tokens must all appear in. */
  haystack: string;
  /** Pre-normalized product name (used for the exact/prefix bonuses). */
  name: string;
  /** Pre-normalized brand, for brand scoping. */
  brand: string;
  /** Pre-normalized category label, for category scoping. */
  category: string;
}

/**
 * Score >= 0 when every query token matches (higher = more relevant);
 * -1 when it is not a match. Callers sort descending.
 */
export function searchScore(
  tokens: string[],
  input: SearchScoreInput
): number {
  if (tokens.length === 0) return -1;
  for (const token of tokens) {
    if (!input.haystack.includes(token)) return -1;
  }
  const query = tokens.join(" ");
  let score = 0;
  if (input.name === query) score += 120;
  else if (input.name.startsWith(query)) score += 80;
  else if (input.name.includes(query)) score += 50;
  for (const token of tokens) {
    const fromBrand = input.brand ? input.brand.split(" ") : [];
    if (fromBrand.includes(token)) score += 26; // brand scoping
    if (input.category && input.category.split(" ").includes(token)) {
      score += 20; // category scoping
    }
  }
  // Every token inside the name itself is a stronger signal than one that
  // only appears in a spec value; shorter names win ties.
  const nameTokens = input.name.split(" ");
  const inName = tokens.filter((t) => nameTokens.includes(t)).length;
  score += inName * 6;
  score += Math.max(0, 12 - Math.floor(input.name.length / 8));
  return score;
}

export function skuOf(p: Product): string {
  // The manufacturer part number IS the SKU ("CSK750DC-W"); `model` is a
  // model name ("CSK 750 DC") and only stands in when no part number is known.
  // GTIN/EAN/UPC barcodes ("4711377290623") are identifiers, not SKUs - the
  // same rule matching.py applies to `model`.
  const parts = p.specs?.part_numbers;
  if (Array.isArray(parts)) {
    const first = parts.find(
      (v): v is string => typeof v === "string" && v.trim() !== "" && !/^(?:\d{8}|\d{12,14})$/.test(v.trim())
    );
    if (first) return first.trim();
  }
  if (p.model) return p.model;
  return p.id.split(":").pop() || p.id;
}

export function displayName(p: Product): string {
  const name = p.name.trim();
  // Scraped rows sometimes carry no real title ("unknown"/empty); show
  // the SKU (or brand) instead of the literal placeholder.
  if (!name || /^(unknown|n\/?a|none)$/i.test(name)) {
    const sku = skuOf(p).trim();
    if (sku && !/^unknown$/i.test(sku)) return sku;
    return p.brand?.trim() || sku || p.id;
  }
  const firstSpace = name.search(/\s/);
  if (firstSpace <= 0) return name;
  const firstToken = name.slice(0, firstSpace).toLowerCase();
  const candidates = [p.model, p.id.split(":").pop() ?? ""];
  for (const c of candidates) {
    if (c && c.toLowerCase() === firstToken) {
      return name.slice(firstSpace + 1).trim();
    }
  }
  return name;
}
