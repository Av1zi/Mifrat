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
 * Failure panel for data views: friendly message, a retry button, and the
 * technical reason tucked into a details element so a bug report can
 * include the exact error instead of "it didn't load".
 */
export function errorPanel(
  message: string,
  retryLabel: string,
  err: unknown
): string {
  const detail =
    err instanceof Error && err.message
      ? `<details class="err-details"><summary>Details</summary><code>${esc(err.message)}</code></details>`
      : "";
  return `
    <div class="empty-state">
      <p style="margin-bottom:14px;">${esc(message)}</p>
      <button class="btn-small" type="button" onclick="location.reload()">${esc(retryLabel)}</button>
      ${detail}
    </div>`;
}

export function skuOf(p: Product): string {
  if (p.model) return p.model;
  return p.id.split(":").pop() || p.id;
}

export function displayName(p: Product): string {
  const name = p.name.trim();
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