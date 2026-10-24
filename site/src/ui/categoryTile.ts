import { formatPrice } from "../format";
import { categoryLabel, t } from "../i18n";
import { CATEGORY_ICONS, icon } from "../icons";
import { categoryHash } from "../state";
import type { CategoryMeta, Currency, Lang } from "../types";
import { safeImageUrl } from "../utils";
import { html, type Html } from "./html";

/**
 * Category card: the category's cover photo (chosen by the scraper; the
 * category icon when there is none), name, count and starting price.
 */
export function categoryTile(cat: CategoryMeta, currency: Currency, lang: Lang): Html {
  // Zero minimums in the scraped meta mean "unknown", not free.
  const min = cat.min_price !== null && cat.min_price > 0 ? cat.min_price : null;
  const cover = safeImageUrl(cat.cover);
  const count = `${cat.count.toLocaleString(lang === "he" ? "he-IL" : "en-US")} ${t(lang, "homeTileProducts")}`;
  return html`<a class="card ccard" href="${categoryHash(cat.id)}">
    <span class="ccard__img">${cover
      ? html`<img src="${cover}" alt="" loading="lazy" decoding="async" width="256" height="256">`
      : icon(CATEGORY_ICONS[cat.id] ?? "grid", 44)}</span>
    <span class="ccard__body">
      <span class="ccard__text">
        <span class="ccard__name">${categoryLabel(cat.id, lang)}</span>
        <span class="ccard__meta">${count}${min !== null ? html` · ${t(lang, "fromPrice")}${formatPrice(min, currency, lang)}` : ""}</span>
      </span>
      <span class="ccard__go" aria-hidden="true">${icon("forward", 15)}</span>
    </span>
  </a>`;
}
