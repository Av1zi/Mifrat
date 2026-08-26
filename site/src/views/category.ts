import { loadCategory } from "../api";
import { formatPrice } from "../format";
import { attributeLabel, categoryLabel, resultsCount, t, vendorLabel, vendorsCount } from "../i18n";
import {
  categoryHash,
  homeHash,
  navigate,
  replaceRoute,
  type CategoryParams,
} from "../state";
import type { Currency, Lang, Product, SortKey } from "../types";
import { esc } from "../utils";
import { closeDetail, openDetail } from "./detail";

const PAGE_SIZE = 60;
// Added "vendor" to priority list
const ATTR_PRIORITY = ["brand", "socket", "chipset", "memory_type", "form_factor", "color", "wifi", "vendor"];

function computeFilterableAttributes(products: Product[]): Map<string, Array<[string, number]>> {
  const counts = new Map<string, Map<string, number>>();
  for (const p of products) {
    for (const [key, value] of Object.entries(p.attributes)) {
      if (!value) continue;
      if (!counts.has(key)) counts.set(key, new Map());
      const values = counts.get(key)!;
      values.set(value, (values.get(value) ?? 0) + 1);
    }
    // Add vendors to filterable attributes
    const vendors = new Set(p.offers.map(o => o.vendor));
    for (const v of vendors) {
      if (!counts.has('vendor')) counts.set('vendor', new Map());
      const values = counts.get('vendor')!;
      values.set(v, (values.get(v) ?? 0) + 1);
    }
  }
  const filterable = new Map<string, Array<[string, number]>>();
  for (const [key, values] of counts) {
    const maxValues = key === 'vendor' ? 30 : 20;
    if (values.size < 2 || values.size > maxValues) continue;
    filterable.set(key, Array.from(values.entries()).sort((a, b) => b[1] - a[1]));
  }
  const orderedKeys = Array.from(filterable.keys()).sort((a, b) => {
    const ai = ATTR_PRIORITY.indexOf(a);
    const bi = ATTR_PRIORITY.indexOf(b);
    if (ai === -1 && bi === -1) return a.localeCompare(b);
    if (ai === -1) return 1;
    if (bi === -1) return -1;
    return ai - bi;
  });
  return new Map(orderedKeys.map((k) => [k, filterable.get(k)!]));
}

function applyFilters(products: Product[], params: CategoryParams): Product[] {
  const q = params.q.trim().toLowerCase();
  return products.filter((p) => {
    if (params.stockOnly && !p.in_stock) return false;
    if (q) {
      const haystack = `${p.name} ${p.brand ?? ""} ${p.model ?? ""}`.toLowerCase();
      if (!haystack.includes(q)) return false;
    }
    for (const [key, values] of Object.entries(params.filters)) {
      if (values.length === 0) continue;
      if (key === 'vendor') {
        // For vendor filter, check if ANY offer matches the selected shops
        if (!p.offers.some(o => values.includes(o.vendor))) return false;
      } else {
        if (!values.includes(p.attributes[key])) return false;
      }
    }
    return true;
  });
}

function sortProducts(products: Product[], sort: SortKey): Product[] {
  const arr = [...products];
  switch (sort) {
    case "price_asc":
      arr.sort((a, b) => (a.min_price ?? Infinity) - (b.min_price ?? Infinity));
      break;
    case "price_desc":
      arr.sort((a, b) => (b.min_price ?? -Infinity) - (a.min_price ?? -Infinity));
      break;
    case "vendors_desc":
      arr.sort((a, b) => b.vendor_count - a.vendor_count || (a.min_price ?? Infinity) - (b.min_price ?? Infinity));
      break;
    case "name":
      arr.sort((a, b) => a.name.localeCompare(b.name));
      break;
  }
  return arr;
}

export async function renderCategory(
  container: HTMLElement,
  lang: Lang,
  currency: Currency,
  category: string,
  params: CategoryParams
): Promise<void> {
  closeDetail();
  container.innerHTML = `<div class="empty-state">${t(lang, "loading")}</div>`;
  let products: Product[];
  try {
    products = await loadCategory(category);
  } catch {
    container.innerHTML = `<div class="empty-state">${t(lang, "loadError")}</div>`;
    return;
  }

  let localQuery = params.q;
  let visibleCount = PAGE_SIZE;

  container.innerHTML = `
    <div class="crumbs"><a href="${homeHash()}">← ${t(lang, "backToCategories")}</a></div>
    <h1 class="category-title">${categoryLabel(category, lang)}</h1>
    <div class="category-layout">
      <aside class="filter-rail" id="filter-rail"></aside>
      <div>
        <div class="toolbar">
          <input class="search-input" id="search-input" type="search" placeholder="${esc(t(lang, "searchPlaceholder"))}" value="${esc(localQuery)}" />
          <select class="sort-select" id="sort-select">
            <option value="price_asc">${t(lang, "sortPriceAsc")}</option>
            <option value="price_desc">${t(lang, "sortPriceDesc")}</option>
            <option value="vendors_desc">${t(lang, "sortVendorsDesc")}</option>
            <option value="name">${t(lang, "sortName")}</option>
          </select>
        </div>
        <div class="results-meta">
          <div id="active-filters"></div>
          <div id="results-count"></div>
        </div>
        <div class="product-grid" id="product-grid"></div>
        <div style="text-align:center; margin-top:20px;">
          <button class="clear-filters" id="load-more" type="button" style="display:none; width:auto; padding:10px 20px;"></button>
        </div>
      </div>
    </div>`;

  (container.querySelector("#sort-select") as HTMLSelectElement).value = params.sort;

  function currentFiltered(): Product[] {
    return sortProducts(applyFilters(products, { ...params, q: localQuery }), params.sort);
  }

  function activeFiltersHtml(): string {
    const chips: string[] = [];
    for (const [key, values] of Object.entries(params.filters)) {
      for (const v of values) {
        const label = key === 'vendor' ? vendorLabel(v) : v;
        chips.push(`<button class="active-filter-chip" data-key="${esc(key)}" data-value="${esc(v)}" type="button">
          ${esc(attributeLabel(key, lang))}: ${esc(label)} <span class="chip-remove">✕</span>
        </button>`);
      }
    }
    if (chips.length === 0) return '';
    return `<div class="active-filters">${chips.join('')}</div>`;
  }

  function syncAndRerender(): void {
    visibleCount = PAGE_SIZE;
    replaceRoute(categoryHash(category, { ...params, q: localQuery }));
    renderGrid();
  }

  function cardHtml(p: Product): string {
    const chips = Object.entries(p.attributes)
      .filter(([, v]) => typeof v === "string" && v.trim() !== "")
      .slice(0, 3)
      .map(([, v]) => `<span class="chip">${esc(v)}</span>`)
      .join("");
    return `
      <button class="product-card" type="button" data-id="${esc(p.id)}">
        <div class="p-brand">${esc(p.brand ?? "")}</div>
        <div class="p-name">${esc(p.name)}</div>
        <div class="chip-row">${chips}</div>
        <div class="p-footer">
          <span class="p-price"><span class="status-dot ${p.in_stock ? "in" : "out"}"></span>${formatPrice(p.min_price, currency, lang)}</span>
          <span class="p-vendors">${vendorsCount(lang, p.vendor_count)}</span>
        </div>
      </button>
    `;
  }

  function renderGrid(): void {
    const filtered = currentFiltered();
    // Compute sidebar options based on CURRENTLY filtered products (Cascading Filters)
    const unsortedFiltered = applyFilters(products, { ...params, q: localQuery });
    const filterableAttrs = computeFilterableAttributes(unsortedFiltered);

    // Render Active Filters Chips
    const activeFiltersEl = container.querySelector("#active-filters")!;
    activeFiltersEl.innerHTML = activeFiltersHtml();
    activeFiltersEl.querySelectorAll(".active-filter-chip").forEach(el => {
      el.addEventListener("click", () => {
        const key = (el as HTMLElement).dataset.key!;
        const value = (el as HTMLElement).dataset.value!;
        const set = new Set(params.filters[key] ?? []);
        set.delete(value);
        params.filters[key] = Array.from(set);
        if (params.filters[key].length === 0) delete params.filters[key];
        syncAndRerender();
      });
    });

    container.querySelector("#results-count")!.textContent = resultsCount(lang, filtered.length);

    const gridEl = container.querySelector("#product-grid")!;
    const visible = filtered.slice(0, visibleCount);
    if (visible.length === 0) {
      gridEl.innerHTML = `<div class="empty-state">${t(lang, "noResults")}</div>`;
    } else {
      gridEl.innerHTML = visible.map(cardHtml).join("");
      gridEl.querySelectorAll(".product-card").forEach((el) => {
        el.addEventListener("click", () => {
          const id = (el as HTMLElement).dataset.id!;
          navigate(categoryHash(category, { ...params, q: localQuery, productId: id }));
        });
      });
    }

    const loadMoreBtn = container.querySelector("#load-more") as HTMLButtonElement;
    if (filtered.length > visibleCount) {
      loadMoreBtn.style.display = "inline-block";
      loadMoreBtn.textContent = lang === "he" ? "טען עוד" : "Load more";
      loadMoreBtn.onclick = () => {
        visibleCount += PAGE_SIZE;
        renderGrid();
      };
    } else {
      loadMoreBtn.style.display = "none";
    }

    renderFilterRail(filterableAttrs);
  }

  function renderFilterRail(filterableAttrs: Map<string, Array<[string, number]>>): void {
    const rail = container.querySelector("#filter-rail")!;
    const groups = Array.from(filterableAttrs.entries())
      .map(([key, values]) => {
        const selected = new Set(params.filters[key] ?? []);
        const options = values
          .map(
            ([value, count]) => {
              const displayValue = key === 'vendor' ? vendorLabel(value) : value;
              return `
                <label class="filter-option">
                  <input type="checkbox" data-attr="${esc(key)}" value="${esc(value)}" ${selected.has(value) ? "checked" : ""} />
                  ${esc(displayValue)} <span style="color:var(--ink-dim)">(${count})</span>
                </label>
              `;
            }
          )
          .join("");
        return `<details class="filter-group" open><summary>${esc(attributeLabel(key, lang))}</summary>${options}</details>`;
      })
      .join("");
    rail.innerHTML = `
      <h3>${t(lang, "filtersHeading")}</h3>
      <label class="checkbox-row">
        <input type="checkbox" id="stock-checkbox" ${params.stockOnly ? "checked" : ""} />
        ${t(lang, "inStockOnly")}
      </label>
      ${groups}
      <button class="clear-filters" id="clear-filters-btn" type="button">${t(lang, "clearFilters")}</button>
    `;
    rail.querySelector("#stock-checkbox")!.addEventListener("change", (e) => {
      params.stockOnly = (e.target as HTMLInputElement).checked;
      syncAndRerender();
    });
    rail.querySelectorAll("input[data-attr]").forEach((el) => {
      el.addEventListener("change", (e) => {
        const input = e.target as HTMLInputElement;
        const key = input.dataset.attr!;
        const set = new Set(params.filters[key] ?? []);
        if (input.checked) set.add(input.value);
        else set.delete(input.value);
        params.filters[key] = Array.from(set);
        if (params.filters[key].length === 0) delete params.filters[key];
        syncAndRerender();
      });
    });
    rail.querySelector("#clear-filters-btn")!.addEventListener("click", () => {
      params.filters = {};
      params.stockOnly = false;
      syncAndRerender();
    });
  }

  renderGrid();

  const searchInput = container.querySelector("#search-input") as HTMLInputElement;
  let debounceTimer: number | undefined;
  searchInput.addEventListener("input", () => {
    localQuery = searchInput.value;
    visibleCount = PAGE_SIZE;
    renderGrid();
    window.clearTimeout(debounceTimer);
    debounceTimer = window.setTimeout(() => {
      replaceRoute(categoryHash(category, { ...params, q: localQuery }));
    }, 400);
  });

  const sortSelect = container.querySelector("#sort-select") as HTMLSelectElement;
  sortSelect.addEventListener("change", () => {
    params.sort = sortSelect.value as SortKey;
    syncAndRerender();
  });

  if (params.productId) {
    const product = products.find((p) => p.id === params.productId);
    if (product) {
      openDetail(lang, currency, product, () => {
        if (history.length > 1) history.back();
        else replaceRoute(categoryHash(category, { ...params, q: localQuery, productId: null }));
      });
    }
  }
}