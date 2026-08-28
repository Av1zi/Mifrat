import { loadMeta } from "../api";
import { formatPrice } from "../format";
import { CATEGORY_ORDER, categoryLabel, t } from "../i18n";
import { categoryHash } from "../state";
import type { Currency, Lang } from "../types";

export async function renderHome(container: HTMLElement, lang: Lang, currency: Currency): Promise<void> {
  container.innerHTML = `<div class="empty-state">${t(lang, "loading")}</div>`;

  let meta;
  try {
    meta = await loadMeta();
  } catch {
    container.innerHTML = `<div class="empty-state">${t(lang, "loadError")}</div>`;
    return;
  }

  const byId = new Map(meta.categories.map((c) => [c.id, c]));
  const orderedIds = [
    ...CATEGORY_ORDER.filter((id) => byId.has(id) && id !== "other"),
    ...meta.categories.map((c) => c.id).filter((id) => !(CATEGORY_ORDER as readonly string[]).includes(id) && id !== "other"),
  ];

  const cards = orderedIds
    .map((id) => byId.get(id)!)
    .filter((cat) => cat.count > 0)
    .map((cat) => {
      const range =
        cat.min_price !== null && cat.max_price !== null
          ? `${formatPrice(cat.min_price, currency, lang)} – ${formatPrice(cat.max_price, currency, lang)}`
          : "";
      return `
        <a class="category-card" href="${categoryHash(cat.id)}">
          <div class="cat-name">${categoryLabel(cat.id, lang)}</div>
          <div class="cat-meta">${cat.count} · ${range}</div>
        </a>
      `;
    })
    .join("");

  container.innerHTML = `
    <div class="hero">
      <h1>${t(lang, "appName")}</h1>
      <p>${t(lang, "tagline")}</p>
    </div>
    <div class="trace"><span class="trace-via"></span></div>
    <div class="category-grid">${cards}</div>
  `;
}
