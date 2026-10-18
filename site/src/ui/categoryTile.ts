import { loadCategoryRepImage } from "../api";
import { formatPrice } from "../format";
import { categoryLabel, t } from "../i18n";
import { CATEGORY_ICONS, icon } from "../icons";
import { categoryHash } from "../state";
import type { CategoryMeta, Currency, Lang } from "../types";
import { safeImageUrl } from "../utils";
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

/** Category card: icon (upgraded to a product photo), name, count, price range. */
export function categoryTile(cat: CategoryMeta, currency: Currency, lang: Lang): Html {
  const range = rangeText(cat, currency, lang);
  return html`<a class="cat-tile" href="${categoryHash(cat.id)}">
    <span class="cat-tile__media" data-cat-photo="${cat.id}" aria-hidden="true"><span class="cat-tile__icon">${icon(CATEGORY_ICONS[cat.id] ?? "grid", 30)}</span></span>
    <span class="cat-tile__body">
      <span class="cat-tile__name">${categoryLabel(cat.id, lang)}</span>
      <span class="cat-tile__meta">${cat.count.toLocaleString(lang === "he" ? "he-IL" : "en-US")} ${t(lang, "homeTileProducts")}</span>
      <span class="cat-tile__range">${range ?? emptyValue(lang)}</span>
    </span>
  </a>`;
}

/** Swaps each tile's icon for a real product photo as soon as it resolves. */
export function fillCategoryPhotos(root: ParentNode): void {
  root.querySelectorAll<HTMLElement>("[data-cat-photo]").forEach((slot) => {
    const id = slot.dataset.catPhoto;
    if (!id) return;
    void loadCategoryRepImage(id).then((src) => {
      const safe = safeImageUrl(src);
      if (!safe || !slot.isConnected) return;
      const img = document.createElement("img");
      img.alt = "";
      img.loading = "lazy";
      img.addEventListener("error", () => img.remove(), { once: true });
      img.addEventListener(
        "load",
        () => slot.querySelector(".cat-tile__icon")?.remove(),
        { once: true }
      );
      img.src = safe;
      slot.append(img);
    });
  });
}
