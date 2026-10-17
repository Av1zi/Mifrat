import { loadMeta } from "../api";
import { CATEGORY_ORDER, t } from "../i18n";
import { icon } from "../icons";
import { homeHash } from "../state";
import { setPageTitle } from "../titles";
import type { Currency, Lang } from "../types";
import { categoryTile, fillCategoryPhotos } from "../ui/categoryTile";
import { html, mount } from "../ui/html";
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
    <nav class="crumbs"><a href="${homeHash()}">${icon("back", 14)}${t(lang, "backToHome")}</a></nav>
    <header class="page-head">
      <p class="eyebrow">${t(lang, "categoriesEyebrow")}</p>
      <h1>${t(lang, "allCategoriesTitle")}</h1>
      <p>${t(lang, "categoriesIntro")}</p>
    </header>
    <div class="cat-grid">${cats.map((c) => categoryTile(c, currency, lang))}</div>`
  );
  fillCategoryPhotos(container);
}
