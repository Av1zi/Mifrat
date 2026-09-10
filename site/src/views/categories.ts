import { loadMeta } from "../api";
import { formatPrice } from "../format";
import { CATEGORY_ORDER, categoryLabel, t } from "../i18n";
import { CATEGORY_ICONS, icon } from "../icons";
import { categoryHash, homeHash } from "../state";
import type { Currency, Lang } from "../types";
import { errorPanel, esc } from "../utils";
import { setPageTitle } from "../titles";

export async function renderCategories(
  container: HTMLElement,
  lang: Lang,
  currency: Currency
): Promise<void> {
  setPageTitle(lang, lang === "he" ? "כל הקטגוריות" : "All categories");
  container.innerHTML = `<div class="empty-state">${t(lang, "loading")}</div>`;

  let meta;
  try {
    meta = await loadMeta();
  } catch (err) {
    container.innerHTML = errorPanel(t(lang, "loadError"), t(lang, "retry"), err);
    return;
  }

  const byId = new Map(meta.categories.map((c) => [c.id, c]));
  const orderedIds = [
    ...CATEGORY_ORDER.filter((id) => byId.has(id)),
    ...meta.categories.map((c) => c.id).filter((id) => !(CATEGORY_ORDER as readonly string[]).includes(id)),
  ];
  const cards = orderedIds
    .map((id) => byId.get(id)!)
    .filter((cat) => cat.count > 0)
    .map((cat) => {
      const range = cat.min_price !== null && cat.max_price !== null
        ? `${formatPrice(cat.min_price, currency, lang)} - ${formatPrice(cat.max_price, currency, lang)}`
        : "";
      return `<a class="category-card categories-page-card" href="${categoryHash(cat.id)}">
        <span class="category-card-icon">${icon(CATEGORY_ICONS[cat.id] ?? "grid", 24)}</span>
        <span class="category-card-body">
          <span class="cat-name">${esc(categoryLabel(cat.id, lang))}</span>
          <span class="cat-meta">${cat.count} · ${range}</span>
        </span>
        <span class="category-card-arrow">${icon("arrow-right", 16)}</span>
      </a>`;
    })
    .join("");

  container.innerHTML = `
    <div class="crumbs"><a href="${homeHash()}">← ${lang === "he" ? "חזרה לדף הבית" : "Back to home"}</a></div>
    <section class="categories-intro">
      <p class="hero-eyebrow">${lang === "he" ? "קטלוג רכיבי מחשב" : "PC component catalog"}</p>
      <h1>${lang === "he" ? "כל הקטגוריות" : "All categories"}</h1>
      <p>${lang === "he" ? "בחרו קטגוריה כדי להשוות מחירים, מפרטים וזמינות." : "Choose a category to compare prices, specifications, and availability."}</p>
    </section>
    <div class="category-grid categories-page-grid">${cards}</div>
  `;
}
