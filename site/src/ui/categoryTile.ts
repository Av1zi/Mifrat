import { formatPrice } from "../format";
import { categoryLabel, t } from "../i18n";
import { CATEGORY_ICONS, icon } from "../icons";
import { categoryHash } from "../state";
import type { CategoryMeta, Currency, Lang } from "../types";
import { emptyValue } from "./empty";
import { html, type Html } from "./html";

function rangeText(cat: CategoryMeta, currency: Currency, lang: Lang): string | null {
  // Zero minimums in the scraped meta mean "unknown", not free.
  const min = cat.min_price !== null && cat.min_price > 0 ? cat.min_price : null;
  const max = cat.max_price !== null && cat.max_price > 0 ? cat.max_price : null;
  if (min !== null && max !== null && max > min) {
    return `${formatPrice(min, currency, lang)} – ${formatPrice(max, currency, lang)}`;
  }
  if (min !== null) return formatPrice(min, currency, lang);
  if (max !== null) return `${t(lang, "upTo")} ${formatPrice(max, currency, lang)}`;
  return null;
}

/**
 * Category card: a large category icon, name, count, price range. Icons only
 * (no product photo): a category tile is a signpost, and a single cheapest
 * product was never representative of the whole category.
 */
export function categoryTile(cat: CategoryMeta, currency: Currency, lang: Lang): Html {
  const range = rangeText(cat, currency, lang);
  return html`<a class="cat-tile" href="${categoryHash(cat.id)}">
    <span class="cat-tile__media" aria-hidden="true"><span class="cat-tile__icon">${icon(CATEGORY_ICONS[cat.id] ?? "grid", 36)}</span></span>
    <span class="cat-tile__body">
      <span class="cat-tile__name">${categoryLabel(cat.id, lang)}</span>
      <span class="cat-tile__meta">${cat.count.toLocaleString(lang === "he" ? "he-IL" : "en-US")} ${t(lang, "homeTileProducts")}</span>
      <span class="cat-tile__range">${range ?? emptyValue(lang)}</span>
    </span>
  </a>`;
}
