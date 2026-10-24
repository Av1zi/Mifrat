import { knownPartWattage } from "../../build";
import { formatPrice } from "../../format";
import { ACTIVE_VENDORS, categoryLabel, inStockCount, storesCount, t } from "../../i18n";
import { icon } from "../../icons";
import { setListView, type ListView } from "../../state";
import type { Product, SortKey } from "../../types";
import { html, mount, type Html } from "../../ui/html";
import { effectivePrice } from "../../offers";
import { activeFilterChips, activeFilterCount } from "./filters";
import { type CategoryActions, type CategoryCtx } from "./data";

const SORTS: Array<{ key: SortKey; label: Parameters<typeof t>[1] }> = [
  { key: "relevance", label: "sortRelevance" },
  { key: "price_asc", label: "sortPriceAsc" },
  { key: "price_desc", label: "sortPriceDesc" },
  { key: "vendors_desc", label: "sortVendorsDesc" },
  { key: "name", label: "sortName" },
  { key: "name_desc", label: "sortNameDesc" },
];

const VIEWS: Array<{ view: ListView; glyph: "rows" | "table"; label: Parameters<typeof t>[1] }> = [
  { view: "table", glyph: "table", label: "viewTable" },
  { view: "cards", glyph: "rows", label: "viewCards" },
];

/**
 * Rail head card: the current build (parts, total, known wattage) and the
 * "only compatible with my build" toggle. Absent while the build is empty.
 */
export function buildCardMarkup(ctx: CategoryCtx): Html {
  const { lang, currency, build } = ctx;
  if (build.items.length === 0) return html``;
  const total = build.items.reduce((sum, { product }) => sum + (effectivePrice(product) ?? 0), 0);
  const watts = build.items.reduce((sum, { slotId, product }) => sum + knownPartWattage(slotId, product), 0);
  const showCompat = ctx.targetSlotId !== null;
  return html`<section class="card rail-build" aria-label="${t(lang, "yourBuildTitle")}">
    <header class="rail-build__head"><span>${t(lang, "yourBuildTitle")}</span><a href="#/build">${t(lang, "toBuild")}</a></header>
    <dl class="rail-build__stats">
      <div><dt>${t(lang, "partsShort")}</dt><dd>${build.items.length}</dd></div>
      <div><dt>${t(lang, "totalShort")}</dt><dd>${formatPrice(total, currency, lang)}</dd></div>
      ${watts > 0 ? html`<div><dt>${t(lang, "wattageShort")}</dt><dd>${watts}W</dd></div>` : ""}
    </dl>
    ${showCompat
      ? html`<label class="check rail-build__compat" title="${t(lang, "compatFilterHint")}"><input type="checkbox" data-role="compat"${ctx.compatOn ? html` checked` : ""}>${t(lang, "compatFilterLabel")}</label>
        <p class="rail-build__hint">${t(lang, "compatFilterHint")}</p>`
      : ""}
  </section>`;
}

/** Results head: live count, search, sort, view toggle (and the filters button below lg). */
export function toolbarMarkup(ctx: CategoryCtx): Html {
  const { lang } = ctx;
  return html`
    <div class="list-head">
      <div class="list-head__count">
        <b data-role="count" role="status"></b>
        <span data-role="count-sub"></span>
      </div>
      <div class="toolbar">
        <button type="button" class="btn btn--ghost toolbar__filters" data-role="filters-open" aria-controls="filter-rail" aria-expanded="false">
          ${icon("sliders", 16)}<span>${t(lang, "filtersHeading")}</span><span class="badge" data-role="filters-count" hidden></span>
        </button>
        <label class="search-field toolbar__search">
          ${icon("search", 16)}
          <input data-role="search" type="search" placeholder="${t(lang, "searchInCategory").replace("{c}", categoryLabel(ctx.category, lang))}" aria-label="${t(lang, "searchAriaLabel")}" value="${ctx.query}">
        </label>
        <select class="select toolbar__sort" data-role="sort" aria-label="${t(lang, "sortAriaLabel")}">
          ${SORTS.map((s) => html`<option value="${s.key}"${ctx.params.sort === s.key ? html` selected` : ""}>${t(lang, s.label)}</option>`)}
        </select>
        <div class="seg toolbar__view" role="group" aria-label="${t(lang, "viewLabel")}">
          ${VIEWS.map(
            (v) => html`<button type="button" class="seg__btn" data-view="${v.view}" aria-pressed="${ctx.view === v.view ? "true" : "false"}" title="${t(lang, v.label)}" aria-label="${t(lang, v.label)}">${icon(v.glyph, 17)}</button>`
          )}
        </div>
      </div>
    </div>
    <div class="results-bar__chips" data-role="active-filters"></div>`;
}

/** Refreshes the counts, active-filter chips, filter badge and toggles after any change. */
export function updateResultsBar(ctx: CategoryCtx, filtered: Product[]): void {
  const root = ctx.container;
  const locale = ctx.lang === "he" ? "he-IL" : "en-US";
  const countEl = root.querySelector<HTMLElement>('[data-role="count"]');
  if (countEl) countEl.textContent = `${filtered.length.toLocaleString(locale)} ${categoryLabel(ctx.category, ctx.lang)}`;
  const subEl = root.querySelector<HTMLElement>('[data-role="count-sub"]');
  if (subEl) {
    const inStock = filtered.filter((p) => p.in_stock).length;
    subEl.textContent = `${inStockCount(ctx.lang, inStock.toLocaleString(locale))} · ${t(ctx.lang, "pricesFrom")}${storesCount(ctx.lang, ACTIVE_VENDORS.length)}`;
  }

  const chips = root.querySelector<HTMLElement>('[data-role="active-filters"]');
  if (chips) mount(chips, activeFilterChips(ctx));

  const badge = root.querySelector<HTMLElement>('[data-role="filters-count"]');
  if (badge) {
    const active = activeFilterCount(ctx);
    badge.textContent = String(active);
    badge.hidden = active === 0;
  }

  const stock = root.querySelector<HTMLInputElement>('[data-role="stock"]');
  if (stock) stock.checked = ctx.params.stockOnly;
  const compat = root.querySelector<HTMLInputElement>('[data-role="compat"]');
  if (compat) compat.checked = ctx.compatOn;
}

export function bindToolbar(ctx: CategoryCtx, actions: CategoryActions): void {
  const root = ctx.container;
  const search = root.querySelector<HTMLInputElement>('[data-role="search"]')!;
  const sort = root.querySelector<HTMLSelectElement>('[data-role="sort"]')!;

  let timer: number | undefined;
  search.addEventListener("input", () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => {
      ctx.query = search.value;
      // An explicit sort sticks; otherwise searching ranks by relevance.
      if (!ctx.sortTouched) {
        ctx.params.sort = ctx.query.trim() ? "relevance" : "price_asc";
        sort.value = ctx.params.sort;
      }
      actions.update();
    }, 220);
  });

  sort.addEventListener("change", () => {
    ctx.sortTouched = true;
    ctx.params.sort = sort.value as SortKey;
    actions.update();
  });

  root.querySelectorAll<HTMLButtonElement>("[data-view]").forEach((btn) => {
    btn.addEventListener("click", () => {
      ctx.view = btn.dataset.view as ListView;
      setListView(ctx.view);
      root.querySelectorAll<HTMLButtonElement>("[data-view]").forEach((other) => {
        other.setAttribute("aria-pressed", other === btn ? "true" : "false");
      });
      actions.redrawList();
    });
  });

  root.querySelector<HTMLInputElement>('[data-role="stock"]')!.addEventListener("change", (e) => {
    ctx.params.stockOnly = (e.target as HTMLInputElement).checked;
    actions.update();
  });

  root.querySelector<HTMLInputElement>('[data-role="compat"]')?.addEventListener("change", (e) => {
    ctx.compatOn = (e.target as HTMLInputElement).checked;
    if (!ctx.compatOn) {
      for (const key of ctx.compatAutoKeys) delete ctx.params.filters[key];
      ctx.compatAutoKeys.clear();
    }
    actions.rebuildRail();
    actions.update();
  });

  root.querySelector('[data-role="filters-open"]')!.addEventListener("click", () => actions.openSheet(true));
}
