import { loadCategory } from "../../api";
import { BUILD_SLOTS, isProductCompatibleWithBuild, slotForCategory } from "../../build";
import { categoryLabel, categoryMetaDesc, t } from "../../i18n";
import { pageHero } from "../../ui/pageHero";
import { icon } from "../../icons";
import {
  categoriesHash,
  categoryHash,
  getListView,
  getStoredBuild,
  navigate,
  productHash,
  replaceRoute,
  type CategoryParams,
} from "../../state";
import { loadSignals } from "../../signals";
import { setPageTitle } from "../../titles";
import type { Currency, Lang, Product } from "../../types";
import { button } from "../../ui/button";
import { html, mount } from "../../ui/html";
import { errorState, loadingState } from "../../ui/state";
import { pickColumns } from "./columns";
import {
  PAGE_SIZE,
  computeFilterable,
  computeRanges,
  currentList,
  loadBuildParts,
  type CategoryActions,
  type CategoryCtx,
} from "./data";
import {
  applyImpliedFilters,
  bindActiveChips,
  bindFilters,
  clearAllFilters,
  filtersMarkup,
  refreshRailStates,
} from "./filters";
import { bindMobileSheet } from "./mobileSheet";
import { pickBannerMarkup } from "./picker";
import { bindList, pagerMarkup, renderList } from "./table";
import { bindToolbar, buildCardMarkup, toolbarMarkup, updateResultsBar } from "./toolbar";

export async function renderCategory(
  container: HTMLElement,
  lang: Lang,
  currency: Currency,
  category: string,
  params: CategoryParams
): Promise<void> {
  mount(container, loadingState(lang));

  let all: Product[];
  try {
    all = await loadCategory(category);
  } catch (err) {
    mount(container, errorState(lang, err));
    return;
  }

  // Legacy ?p=<id> links (from before per-product pages) go to the product page.
  if (!params.pick && params.productId) {
    const product = all.find((p) => p.id === params.productId);
    if (product) {
      navigate(productHash(category, product.id));
      return;
    }
  }

  setPageTitle(lang, categoryLabel(category, lang), categoryMetaDesc(lang, categoryLabel(category, lang), all.length));

  const pickSlot = params.pick ? BUILD_SLOTS.find((s) => s.id === params.pick) ?? null : null;
  const storedBuild = getStoredBuild();
  const build = await loadBuildParts(storedBuild);
  const targetSlotId = pickSlot?.id ?? slotForCategory(category)?.id ?? null;

  const products = pickSlot
    ? all.filter((p) => isProductCompatibleWithBuild(p, pickSlot.id, build.first))
    : all;

  // An explicit sort from the URL is respected; otherwise searching ranks by relevance.
  const sortTouched = params.sort !== "price_asc" && params.sort !== "relevance";
  if (!sortTouched && params.q.trim()) params.sort = "relevance";

  const ctx: CategoryCtx = {
    container,
    lang,
    currency,
    category,
    params,
    products,
    byId: new Map(products.map((p) => [p.id, p])),
    pickSlot,
    hiddenIncompatible: all.length - products.length,
    storedBuild,
    build,
    targetSlotId,
    // The compat filter starts on when there is something to be compatible with.
    compatOn: build.items.length > 0 && targetSlotId !== null,
    compatAutoKeys: new Set(),
    query: params.q,
    sortTouched,
    view: getListView(),
    page: 0,
    filterable: computeFilterable(products, category),
    ranges: computeRanges(products, category),
    columns: pickColumns(products, category),
    signals: new Map(),
  };

  const label = categoryLabel(category, lang);
  mount(
    container,
    html`
    ${pageHero({
      lang,
      crumbs: [
        { label: t(lang, "allCategoriesTitle"), href: categoriesHash() },
        { label, href: pickSlot ? categoryHash(category) : undefined },
      ],
      title: pickSlot ? pickSlot.choose[lang] : label,
      sub: pickSlot ? t(lang, "pickHeroSub") : categoryMetaDesc(lang, label, all.length),
    })}
    ${pickBannerMarkup(ctx)}
    <div class="catalog">
      <div class="sheet-backdrop" data-role="backdrop" hidden></div>
      <aside class="sheet rail" id="filter-rail" aria-label="${t(lang, "filtersHeading")}">
        <div class="sheet__head">
          <span class="sheet__title">${t(lang, "filtersHeading")}</span>
          ${button({ label: t(lang, "close"), icon: icon("close", 18), variant: "ghost", size: "sm", iconOnly: true, data: { role: "filters-close" } })}
        </div>
        <div class="sheet__body">
          ${buildCardMarkup(ctx)}
          <section class="card rail-card">
            <header class="rail-card__head">
              <span>${t(lang, "filtersHeading")}</span>
              <button type="button" class="link-btn" data-role="rail-clear">${t(lang, "resetLabel")}</button>
            </header>
            <details class="acc" open>
              <summary>${t(lang, "availability")}</summary>
              <div class="acc__body"><label class="check"><input type="checkbox" data-role="stock"${ctx.params.stockOnly ? html` checked` : ""}>${t(lang, "inStockOnly")}</label></div>
            </details>
            <div data-role="rail-body"></div>
          </section>
        </div>
        <div class="sheet__foot">
          ${button({ label: t(lang, "clearFilters"), data: { role: "sheet-clear" } })}
          ${button({ label: t(lang, "filtersShowResults"), variant: "primary", data: { role: "filters-apply" } })}
        </div>
      </aside>
      <div class="catalog__main">
        ${toolbarMarkup(ctx)}
        <div class="list" data-role="list"></div>
        <nav class="pager" data-role="pager" aria-label="${t(lang, "pagesLabel")}"></nav>
        <div class="visually-hidden" data-role="status" role="status" aria-live="polite"></div>
      </div>
    </div>`
  );

  const listEl = container.querySelector<HTMLElement>('[data-role="list"]')!;
  const pagerEl = container.querySelector<HTMLElement>('[data-role="pager"]')!;
  const railBody = container.querySelector<HTMLElement>('[data-role="rail-body"]')!;

  // The scan table needs room: below this list width (phones, narrow
  // windows beside the rail) the card rows are used whatever the toggle says.
  const TABLE_MIN = 720;
  const tableFits = (): boolean => listEl.clientWidth >= TABLE_MIN;
  let lastFits = tableFits();

  const actions: CategoryActions = {
    update() {
      ctx.page = 0;
      replaceRoute(categoryHash(category, { ...ctx.params, q: ctx.query }));
      refreshRailStates(ctx);
      actions.redrawList();
    },
    redrawList() {
      const filtered = currentList(ctx);
      const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
      ctx.page = Math.min(ctx.page, pages - 1);
      updateResultsBar(ctx, filtered);
      lastFits = tableFits();
      renderList(ctx, listEl, filtered, lastFits);
      // The view toggle only means something where the table fits.
      const toggle = container.querySelector<HTMLElement>(".toolbar__view");
      if (toggle) toggle.hidden = !lastFits;
      mount(pagerEl, pagerMarkup(ctx, filtered.length));
    },
    rebuildRail() {
      const openStates = Array.from(railBody.querySelectorAll("details")).map((d) => d.open);
      applyImpliedFilters(ctx);
      mount(railBody, filtersMarkup(ctx));
      railBody.querySelectorAll("details").forEach((d, i) => {
        if (openStates[i] !== undefined) d.open = openStates[i];
      });
      bindFilters(ctx, actions);
    },
    openSheet(open) {
      sheet.open(open);
    },
  };

  const sheet = bindMobileSheet(container);
  const resize = new ResizeObserver(() => {
    if (tableFits() !== lastFits) actions.redrawList();
  });
  resize.observe(listEl);

  pagerEl.addEventListener("click", (e) => {
    const btn = (e.target as HTMLElement).closest<HTMLButtonElement>("[data-page]");
    if (!btn || btn.disabled) return;
    ctx.page = Number(btn.dataset.page) || 0;
    actions.redrawList();
    const top = container.querySelector<HTMLElement>(".list-head");
    top?.scrollIntoView({ block: "start", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  });

  bindToolbar(ctx, actions);
  bindList(ctx, listEl, actions);
  bindActiveChips(ctx, actions);
  for (const role of ["sheet-clear", "rail-clear"]) {
    container.querySelector(`[data-role="${role}"]`)!.addEventListener("click", () => clearAllFilters(ctx, actions));
  }

  actions.rebuildRail();
  actions.redrawList();

  // Price-drop badges arrive after the first paint; a missing history file just means none.
  void loadSignals(category).then((signals) => {
    if (signals.size === 0 || !listEl.isConnected) return;
    ctx.signals = signals;
    actions.redrawList();
  });

  // Leaving the route releases the listeners and the scroll lock.
  window.addEventListener(
    "hashchange",
    () => {
      resize.disconnect();
      sheet.dispose();
    },
    { once: true }
  );
}
