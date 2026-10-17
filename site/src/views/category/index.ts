import { loadCategory } from "../../api";
import { BUILD_SLOTS, isProductCompatibleWithBuild, slotForCategory } from "../../build";
import { categoryLabel, categoryMetaDesc, t } from "../../i18n";
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
import { bindList, renderList } from "./table";
import { bindToolbar, toolbarMarkup, updateResultsBar } from "./toolbar";

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
    visible: PAGE_SIZE,
    filterable: computeFilterable(products, category),
    ranges: computeRanges(products, category),
    columns: pickColumns(products, category),
    signals: new Map(),
  };

  mount(
    container,
    html`
    <nav class="crumbs"><a href="${categoriesHash()}">${icon("back", 14)}${t(lang, "backToCategories")}</a></nav>
    <header class="page-head"><h1>${categoryLabel(category, lang)}</h1></header>
    ${pickBannerMarkup(ctx)}
    <div class="catalog">
      <div class="sheet-backdrop" data-role="backdrop" hidden></div>
      <aside class="sheet rail" id="filter-rail" aria-label="${t(lang, "filtersHeading")}">
        <div class="sheet__head">
          <span class="sheet__title">${t(lang, "filtersHeading")}</span>
          ${button({ label: t(lang, "close"), icon: icon("close", 18), variant: "ghost", size: "sm", iconOnly: true, data: { role: "filters-close" } })}
        </div>
        <div class="sheet__body" data-role="rail-body"></div>
        <div class="sheet__foot">
          ${button({ label: t(lang, "clearFilters"), data: { role: "sheet-clear" } })}
          ${button({ label: t(lang, "filtersShowResults"), variant: "primary", data: { role: "filters-apply" } })}
        </div>
      </aside>
      <div class="catalog__main">
        ${toolbarMarkup(ctx)}
        <div class="list" data-role="list"></div>
        <div class="sentinel" data-role="sentinel" hidden></div>
        <div class="visually-hidden" data-role="status" role="status" aria-live="polite"></div>
      </div>
    </div>`
  );

  const listEl = container.querySelector<HTMLElement>('[data-role="list"]')!;
  const sentinel = container.querySelector<HTMLElement>('[data-role="sentinel"]')!;
  const railBody = container.querySelector<HTMLElement>('[data-role="rail-body"]')!;

  // The table needs width; phones always get the card rows.
  const wide = window.matchMedia("(min-width: 640px)");
  let observer: IntersectionObserver | null = null;

  const actions: CategoryActions = {
    update() {
      ctx.visible = PAGE_SIZE;
      replaceRoute(categoryHash(category, { ...ctx.params, q: ctx.query }));
      refreshRailStates(ctx);
      actions.redrawList();
    },
    redrawList() {
      const filtered = currentList(ctx);
      updateResultsBar(ctx, filtered.length);
      renderList(ctx, listEl, filtered, wide.matches);
      const more = filtered.length > ctx.visible;
      sentinel.hidden = !more;
      sentinel.textContent = more ? t(lang, "loading") : "";
      observer?.disconnect();
      if (more) observer?.observe(sentinel);
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
  observer = new IntersectionObserver(
    (entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      ctx.visible += PAGE_SIZE;
      actions.redrawList();
    },
    { rootMargin: "320px" }
  );
  const onWidth = (): void => actions.redrawList();
  wide.addEventListener("change", onWidth);

  bindToolbar(ctx, actions);
  bindList(ctx, listEl, actions);
  bindActiveChips(ctx, actions);
  container
    .querySelector('[data-role="sheet-clear"]')!
    .addEventListener("click", () => clearAllFilters(ctx, actions));

  actions.rebuildRail();
  actions.redrawList();

  // Price-drop badges arrive after the first paint; a missing history file just means none.
  void loadSignals(category).then((signals) => {
    if (signals.size === 0 || !listEl.isConnected) return;
    ctx.signals = signals;
    actions.redrawList();
  });

  // Leaving the route releases the observers and the scroll lock.
  window.addEventListener(
    "hashchange",
    () => {
      observer?.disconnect();
      wide.removeEventListener("change", onWidth);
      sheet.dispose();
    },
    { once: true }
  );
}
