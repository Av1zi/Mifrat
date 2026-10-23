import { loadMeta } from "../api";
import { CATEGORY_ORDER, homeCatsSub, t } from "../i18n";
import { setPageTitle } from "../titles";
import type { Currency, Lang } from "../types";
import { categoryTile } from "../ui/categoryTile";
import { html, mount } from "../ui/html";
import { pageHero } from "../ui/pageHero";
import { errorState, loadingState } from "../ui/state";

export async function renderCategories(
  container: HTMLElement,
  lang: Lang,
  currency: Currency
): Promise<void> {
  setPageTitle(lang, t(lang, "allCategoriesTitle"), t(lang, "metaCategoriesDesc"));
  mount(container, loadingState(lang));

  let meta;
  try {
    meta = await loadMeta();
  } catch (err) {
    mount(container, errorState(lang, err));
    return;
  }

  const byId = new Map(meta.categories.map((c) => [c.id, c]));
  const known = CATEGORY_ORDER as readonly string[];
  const ids = [
    ...known.filter((id) => byId.has(id)),
    ...meta.categories.map((c) => c.id).filter((id) => !known.includes(id)),
  ];
  const cats = ids.map((id) => byId.get(id)!).filter((c) => c.count > 0);

  mount(
    container,
    html`
    ${pageHero({
      lang,
      crumbs: [{ label: t(lang, "allCategoriesTitle") }],
      title: t(lang, "allCategoriesTitle"),
      sub: homeCatsSub(lang, cats.length, cats.reduce((n, c) => n + c.count, 0).toLocaleString(lang === "he" ? "he-IL" : "en-US")),
    })}
    <div class="cat-grid">${cats.map((c) => categoryTile(c, currency, lang))}</div>`
  );
}
