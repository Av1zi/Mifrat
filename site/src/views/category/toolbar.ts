import { knownPartWattage } from "../../build";
import { formatPrice } from "../../format";
import { resultsCount, t } from "../../i18n";
import { icon } from "../../icons";
import { setListView, type ListView } from "../../state";
import type { SortKey } from "../../types";
import { html, mount, type Html } from "../../ui/html";
import { effectivePrice } from "../../offers";
import { activeFilterChips, activeFilterCount } from "./filters";
import { PAGE_SIZE, type CategoryActions, type CategoryCtx } from "./data";

const SORTS: Array<{ key: SortKey; label: Parameters<typeof t>[1] }> = [
  { key: "relevance", label: "sortRelevance" },
  { key: "price_asc", label: "sortPriceAsc" },
  { key: "price_desc", label: "sortPriceDesc" },
  { key: "vendors_desc", label: "sortVendorsDesc" },
  { key: "name", label: "sortName" },
  { key: "name_desc", label: "sortNameDesc" },
];

const VIEWS: Array<{ view: ListView; glyph: "rows" | "table"; label: Parameters<typeof t>[1] }> = [
  { view: "cards", glyph: "rows", label: "viewCards" },
  { view: "table", glyph: "table", label: "viewTable" },
];

function buildSummary(ctx: CategoryCtx): Html {
  const { lang, currency, build } = ctx;
  if (build.items.length === 0) return html``;
  const total = build.items.reduce((sum, { product }) => sum + (effectivePrice(product) ?? 0), 0);
  const watts = build.items.reduce((sum, { slotId, product }) => sum + knownPartWattage(slotId, product), 0);
  return html`<a class="build-chip" href="#/build">${icon("wrench", 14)}
    <span>${build.items.length} ${t(lang, "partsShort")}</span>
    <span class="num">${formatPrice(total, currency, lang)}</span>
    ${watts > 0 ? html`<span class="num">${watts}W</span>` : ""}</a>`;
}

/** Sticky search/sort/view row plus the results bar (count, toggles, active chips). */
export function toolbarMarkup(ctx: CategoryCtx): Html {
  const { lang } = ctx;
  const showCompat = ctx.build.items.length > 0 && ctx.targetSlotId !== null;
  return html`
    <div class="toolbar">
      <button type="button" class="btn btn--ghost toolbar__filters" data-role="filters-open" aria-controls="filter-rail" aria-expanded="false">
        ${icon("sliders", 16)}<span>${t(lang, "filtersHeading")}</span><span class="badge" data-role="filters-count" hidden></span>
      </button>
      <label class="search-field toolbar__search">
        ${icon("search", 16)}
        <input data-role="search" type="search" placeholder="${t(lang, "searchPlaceholder")}" aria-label="${t(lang, "searchAriaLabel")}" value="${ctx.query}">
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
    <div class="results-bar">
      <p class="results-bar__count" data-role="count" role="status"></p>
      <label class="check"><input type="checkbox" data-role="stock"${ctx.params.stockOnly ? html` checked` : ""}>${t(lang, "inStockOnly")}</label>
      ${showCompat
        ? html`<label class="check" title="${t(lang, "compatFilterHint")}"><input type="checkbox" data-role="compat"${ctx.compatOn ? html` checked` : ""}>${t(lang, "compatFilterLabel")}</label>`
        : ""}
      ${buildSummary(ctx)}
      <div class="results-bar__chips" data-role="active-filters"></div>
    </div>`;
}

/** Refreshes the count, active-filter chips, filter badge and toggles after any change. */
export function updateResultsBar(ctx: CategoryCtx, count: number): void {
  const root = ctx.container;
  const countEl = root.querySelector<HTMLElement>('[data-role="count"]');
  if (countEl) countEl.textContent = resultsCount(ctx.lang, count);

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
      ctx.visible = PAGE_SIZE;
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
