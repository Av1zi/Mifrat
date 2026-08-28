import { loadCategory } from "../api";
import { BUILD_SLOTS, isProductCompatibleWithBuild } from "../build";
import { formatPrice } from "../format";
import {
  attributeLabel,
  categoryLabel,
  resultsCount,
  t,
  vendorLabel,
  vendorsCount,
} from "../i18n";
import {
  buildHash,
  categoryHash,
  getStoredBuild,
  homeHash,
  navigate,
  replaceRoute,
  setStoredBuild,
  type CategoryParams,
} from "../state";
import type { Currency, Lang, Product, SortKey } from "../types";
import { displayName, esc } from "../utils";
import { closeDetail, openDetail } from "./detail";

const PAGE_SIZE = 60;

const ATTR_PRIORITY = [
  "brand",
  "socket",
  "chipset",
  "memory_type",
  "form_factor",
  "color",
  "wifi",
  "vendor",
];

const NUMERIC_ATTRS = new Set([
  "price",
  "cores",
  "threads",
  "cache_mb",
  "base_clock_ghz",
  "boost_clock_ghz",
  "tdp",
  "vram_gb",
  "wattage_w",
  "capacity_gb",
  "rpm",
  "cooler_height_mm",
  "radiator_size_mm",
  "fan_size_mm",
  "gpu_length_mm",
  "length_mm",
  "memory_clock_mhz",
  "speed_mhz",
  "cas_latency",
  "pcie_gen",
]);

const MAX_SPEC_COLUMNS = 4;

function computeFilterableAttributes(
  products: Product[]
): Map<string, Array<[string, number]>> {
  const counts = new Map<string, Map<string, number>>();
  const numericRanges = new Map<string, { min: number; max: number }>();

  for (const p of products) {
    for (const [key, value] of Object.entries(p.attributes)) {
      if (!value) continue;

      if (!counts.has(key)) counts.set(key, new Map());
      const values = counts.get(key)!;
      values.set(value, (values.get(value) ?? 0) + 1);

      if (NUMERIC_ATTRS.has(key)) {
        const num = parseNumericAttr(value);
        if (num !== null) {
          const range = numericRanges.get(key) ?? { min: Infinity, max: -Infinity };
          range.min = Math.min(range.min, num);
          range.max = Math.max(range.max, num);
          numericRanges.set(key, range);
        }
      }
    }

    const vendors = new Set(p.offers.map((o) => o.vendor));
    for (const v of vendors) {
      if (!counts.has("vendor")) counts.set("vendor", new Map());
      const values = counts.get("vendor")!;
      values.set(v, (values.get(v) ?? 0) + 1);
    }

    if (p.min_price !== null) {
      const range = numericRanges.get("price") ?? { min: Infinity, max: -Infinity };
      range.min = Math.min(range.min, p.min_price);
      range.max = Math.max(range.max, p.min_price);
      numericRanges.set("price", range);
    }
  }

  const filterable = new Map<string, Array<[string, number]>>();

  for (const [key, values] of counts) {
    const maxValues = key === "vendor" ? 30 : 40;
    if (values.size < 2 || values.size > maxValues) continue;

    filterable.set(
      key,
      Array.from(values.entries()).sort((a, b) => b[1] - a[1])
    );
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

function parseNumericAttr(value: string | undefined): number | null {
  if (!value) return null;
  const m = /(\d+(?:\.\d+)?)/.exec(value);
  return m ? parseFloat(m[1]) : null;
}

function computeNumericRanges(
  products: Product[]
): Map<string, { min: number; max: number }> {
  const numericRanges = new Map<string, { min: number; max: number }>();

  for (const p of products) {
    for (const [key, value] of Object.entries(p.attributes)) {
      if (!value) continue;

      if (NUMERIC_ATTRS.has(key)) {
        const num = parseNumericAttr(value);
        if (num !== null) {
          const range = numericRanges.get(key) ?? { min: Infinity, max: -Infinity };
          range.min = Math.min(range.min, num);
          range.max = Math.max(range.max, num);
          numericRanges.set(key, range);
        }
      }
    }

    if (p.min_price !== null) {
      const range = numericRanges.get("price") ?? { min: Infinity, max: -Infinity };
      range.min = Math.min(range.min, p.min_price);
      range.max = Math.max(range.max, p.min_price);
      numericRanges.set("price", range);
    }
  }

  for (const [key, range] of numericRanges) {
    if (range.min === Infinity || range.max === -Infinity) {
      numericRanges.delete(key);
    }
  }

  return numericRanges;
}

function applyFilters(
  products: Product[],
  params: CategoryParams
): Product[] {
  const q = params.q.trim().toLowerCase();

  return products.filter((p) => {
    if (params.stockOnly && !p.in_stock) return false;

    if (q) {
      const haystack = `${p.name} ${p.brand ?? ""} ${p.model ?? ""}`.toLowerCase();
      if (!haystack.includes(q)) return false;
    }

    for (const [key, values] of Object.entries(params.filters)) {
      if (values.length === 0) continue;

      if (key === "vendor") {
        if (!p.offers.some((o) => values.includes(o.vendor))) return false;
      } else {
        if (!values.includes(p.attributes[key])) return false;
      }
    }

    for (const [key, range] of Object.entries(params.ranges)) {
      const value = getNumericValue(p, key);
      if (value === null) return false;
      if (range.min !== null && value < range.min) return false;
      if (range.max !== null && value > range.max) return false;
    }

    return true;
  });
}

function getNumericValue(p: Product, key: string): number | null {
  switch (key) {
    case "price":
      return p.min_price;
    case "cores":
    case "threads":
    case "cache_mb":
    case "base_clock_ghz":
    case "boost_clock_ghz":
    case "tdp":
    case "vram_gb":
    case "wattage_w":
    case "capacity_gb":
    case "rpm":
    case "cooler_height_mm":
    case "radiator_size_mm":
    case "fan_size_mm":
    case "speed_mhz":
    case "cas_latency":
    case "pcie_gen":
      return parseNumericAttr(p.attributes[key]);
    default:
      return parseNumericAttr(p.attributes[key]);
  }
}

function sortProducts(products: Product[], sort: SortKey): Product[] {
  const arr = [...products];

  switch (sort) {
    case "price_asc":
      arr.sort((a, b) => (a.min_price ?? Infinity) - (b.min_price ?? Infinity));
      break;

    case "price_desc":
      arr.sort(
        (a, b) => (b.min_price ?? -Infinity) - (a.min_price ?? -Infinity)
      );
      break;

    case "vendors_desc":
      arr.sort(
        (a, b) =>
          b.vendor_count - a.vendor_count ||
          (a.min_price ?? Infinity) - (b.min_price ?? Infinity)
      );
      break;

    case "name":
      arr.sort((a, b) => a.name.localeCompare(b.name));
      break;
  }

  return arr;
}

async function loadBuildParts(
  build: Record<string, string>
): Promise<Record<string, Product>> {
  const result: Record<string, Product> = {};

  await Promise.all(
    BUILD_SLOTS.map(async (slot) => {
      const productId = build[slot.id];
      if (!productId) return;

      for (const category of slot.categories) {
        try {
          const products = await loadCategory(category);
          const found = products.find((p) => p.id === productId);

          if (found) {
            result[slot.id] = found;
            return;
          }
        } catch {
          // Ignore category load failures.
        }
      }
    })
  );

  return result;
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

  const pickSlot = params.pick
    ? BUILD_SLOTS.find((slot) => slot.id === params.pick) ?? null
    : null;

  const storedBuild = getStoredBuild();

  let buildParts: Record<string, Product> = {};

  if (pickSlot) {
    buildParts = await loadBuildParts(storedBuild);
  }

  let compatibleProducts = products;
  let hiddenIncompatible = 0;

  if (pickSlot) {
    compatibleProducts = products.filter((product) =>
      isProductCompatibleWithBuild(product, pickSlot.id, buildParts)
    );

    hiddenIncompatible = products.length - compatibleProducts.length;
  }

  const productById = new Map(compatibleProducts.map((p) => [p.id, p]));

  let localQuery = params.q;
  let visibleCount = PAGE_SIZE;

  const filterableAttrs = computeFilterableAttributes(compatibleProducts);
  const specColumns = Array.from(filterableAttrs.keys()).slice(
    0,
    MAX_SPEC_COLUMNS
  );

  const specColDefs = specColumns
    .map(() => "minmax(110px, 1fr)")
    .join(" ");

  // +56px thumb column at start, spiced distinct
  const plCols = `56px minmax(220px, 2.2fr) ${specColDefs} minmax(108px, 1fr) minmax(110px, 1fr) minmax(112px, auto)`.replace(
    /\s{2,}/g,
    " "
  );

  function addPartToBuild(product: Product): void {
    if (!pickSlot) return;

    if (!pickSlot.categories.includes(product.category)) return;

    const build = getStoredBuild();
    build[pickSlot.id] = product.id;
    setStoredBuild(build);

    navigate(buildHash(build));
  }

  function pickBannerHtml(): string {
    if (!pickSlot) return "";

    const tabs =
      pickSlot.categories.length > 1
        ? `
            <div class="pick-tabs">
              ${pickSlot.categories
                .map((catId) => {
                  const active = catId === category ? "active" : "";

                  return `
                    <a
                      class="${active}"
                      href="${categoryHash(catId, { pick: pickSlot.id })}"
                    >
                      ${esc(categoryLabel(catId, lang))}
                    </a>
                  `;
                })
                .join("")}
            </div>
          `
        : "";

    const hiddenNote =
      hiddenIncompatible > 0
        ? `
            <span class="pick-note">
              ${
                lang === "he"
                  ? `${hiddenIncompatible} לא תואמים הוסתרו`
                  : `${hiddenIncompatible} known-incompatible hidden`
              }
            </span>
          `
        : "";

    return `
      <div class="pick-banner">
        <span class="pick-label">${esc(pickSlot.label[lang])}</span>
        ${tabs}
        ${hiddenNote}
        <a class="pick-cancel" href="${buildHash(storedBuild)}">
          ${t(lang, "cancel")}
        </a>
      </div>
    `;
  }

  container.innerHTML = `
    <div class="crumbs">
      <a href="${homeHash()}">← ${t(lang, "backToCategories")}</a>
    </div>

    <h1 class="category-title">${categoryLabel(category, lang)}</h1>

    ${pickBannerHtml()}

    <div class="category-layout">
      <aside class="filter-rail" id="filter-rail"></aside>

      <div>
        <div class="toolbar">
          <span class="toolbar-label">${t(lang, "searchPlaceholder")}</span>
          <input
            class="search-input"
            id="search-input"
            type="search"
            placeholder="${esc(t(lang, "searchPlaceholder"))}"
            value="${esc(localQuery)}"
          />

          <span class="toolbar-label">${t(lang, "sortLabel")}</span>
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

        <div class="product-list" id="product-list"></div>

        <div style="text-align:center; margin-top:20px;">
          <button
            class="btn-primary"
            id="load-more"
            type="button"
            style="display:none;"
          ></button>
        </div>
      </div>
    </div>
  `;

  (container.querySelector("#sort-select") as HTMLSelectElement).value =
    params.sort;

  function currentFiltered(): Product[] {
    return sortProducts(
      applyFilters(compatibleProducts, { ...params, q: localQuery }),
      params.sort
    );
  }

  function activeFiltersHtml(): string {
    const chips: string[] = [];

    for (const [key, values] of Object.entries(params.filters)) {
      for (const v of values) {
        const label = key === "vendor" ? vendorLabel(v) : v;

        chips.push(
          `<button
            class="active-filter-chip"
            data-key="${esc(key)}"
            data-value="${esc(v)}"
            type="button"
          >
            ${esc(attributeLabel(key, lang))}: ${esc(label)}
            <span class="chip-remove">✕</span>
          </button>`
        );
      }
    }

    for (const [key, range] of Object.entries(params.ranges)) {
      if (range.min !== null || range.max !== null) {
        const label = attributeLabel(key, lang);
        let display = "";
        if (range.min !== null && range.max !== null) {
          display = `${range.min} – ${range.max}`;
        } else if (range.min !== null) {
          display = `${t(lang, "min")}: ${range.min}`;
        } else if (range.max !== null) {
          display = `${t(lang, "max")}: ${range.max}`;
        }

        chips.push(
          `<button
            class="active-filter-chip"
            data-range-key="${esc(key)}"
            type="button"
          >
            ${esc(label)}: ${esc(display)}
            <span class="chip-remove">✕</span>
          </button>`
        );
      }
    }

    if (chips.length === 0) return "";

    return `<div class="active-filters">${chips.join("")}</div>`;
  }

  function syncAndRerender(): void {
    visibleCount = PAGE_SIZE;
    replaceRoute(categoryHash(category, { ...params, q: localQuery }));
    renderGrid();
  }

  function thumbLabel(p: Product): string {
    const s = (p.brand ?? p.name).trim();
    return s.slice(0, 2).toUpperCase() || "•";
  }

  function headerHtml(): string {
    const specHeaders = specColumns
      .map(
        (key) =>
          `<div class="pl-cell">${esc(attributeLabel(key, lang))}</div>`
      )
      .join("");

    // Price header is sortable — clicking toggles low→high / high→low
    const priceSort = params.sort === "price_asc" ? "price_desc" : "price_asc";
    const priceArrow = params.sort === "price_asc" ? "↑" : params.sort === "price_desc" ? "↓" : "↕";

    return `
      <div class="pl-header">
        <div class="pl-cell" aria-hidden="true"></div>
        <div class="pl-cell">${t(lang, "sortName")}</div>
        ${specHeaders}
        <div class="pl-cell">${t(lang, "availability")}</div>
        <div class="pl-cell" style="cursor:pointer" data-sort="${esc(priceSort)}" title="${t(lang, "sortLabel")}">${t(lang, "priceHeading")} <span style="font-weight:800">${priceArrow}</span></div>
        <div class="pl-cell"></div>
      </div>
    `;
  }

  function rowHtml(p: Product): string {
    const specCells = specColumns
      .map((key) => {
        const text =
          key === "vendor"
            ? vendorsCount(lang, p.vendor_count)
            : p.attributes[key] ?? "";

        return `<div class="pl-cell spec">${text ? esc(text) : "—"}</div>`;
      })
      .join("");

    const actionCell = pickSlot
      ? `<span class="btn-small btn-add">${t(lang, "addToBuild")}</span>`
      : `<span class="btn-small">${t(lang, "viewOffers")}</span>`;

    return `
      <button
        class="pl-row${pickSlot ? " pl-row--pick" : ""}"
        type="button"
        data-id="${esc(p.id)}"
      >
        <div class="pl-cell" style="display:flex; align-items:center; justify-content:center;">
          <span class="plThumb" aria-hidden="true">${esc(thumbLabel(p))}</span>
        </div>
        <div class="pl-cell pl-name">
          <span class="pl-title">${esc(displayName(p))}</span>
          ${p.brand ? `<span class="pl-brand">${esc(p.brand)}</span>` : ""}
        </div>

        ${specCells}

        <div class="pl-cell pl-stock">
          <span class="status-dot ${p.in_stock ? "in" : "out"}"></span>
          ${p.in_stock ? t(lang, "inStock") : t(lang, "outOfStock")}
        </div>

        <div class="pl-cell pl-price">
          ${formatPrice(p.min_price, currency, lang)}
        </div>

        <div class="pl-cell pl-action">
          ${actionCell}
        </div>
      </button>
    `;
  }

  function renderGrid(): void {
    const filtered = currentFiltered();

    const activeFiltersEl = container.querySelector("#active-filters")!;
    activeFiltersEl.innerHTML = activeFiltersHtml();

    activeFiltersEl
      .querySelectorAll(".active-filter-chip")
      .forEach((el) => {
        el.addEventListener("click", () => {
          const rangeKey = (el as HTMLElement).dataset.rangeKey;
          if (rangeKey) {
            delete params.ranges[rangeKey];
            syncAndRerender();
            return;
          }

          const key = (el as HTMLElement).dataset.key!;
          const value = (el as HTMLElement).dataset.value!;

          const set = new Set(params.filters[key] ?? []);
          set.delete(value);

          params.filters[key] = Array.from(set);
          if (params.filters[key].length === 0) delete params.filters[key];

          syncAndRerender();
        });
      });

    container.querySelector("#results-count")!.textContent = resultsCount(
      lang,
      filtered.length
    );

    const listEl = container.querySelector("#product-list") as HTMLElement;
    listEl.style.setProperty("--pl-cols", plCols);

    const visible = filtered.slice(0, visibleCount);

    if (visible.length === 0) {
      listEl.innerHTML = `<div class="empty-state">${t(lang, "noResults")}</div>`;
    } else {
      listEl.innerHTML = headerHtml() + visible.map(rowHtml).join("");

      const sortEl = listEl.querySelector<HTMLElement>("[data-sort]");
      if (sortEl) {
        sortEl.addEventListener("click", (e) => {
          e.stopPropagation();
          const next = sortEl.dataset.sort as SortKey;
          params.sort = next;
          (container.querySelector("#sort-select") as HTMLSelectElement).value = next;
          syncAndRerender();
        });
      }

      listEl.querySelectorAll(".pl-row").forEach((el) => {
        el.addEventListener("click", () => {
          const id = (el as HTMLElement).dataset.id!;

          if (pickSlot) {
            const product = productById.get(id);
            if (product) addPartToBuild(product);
            return;
          }

          navigate(
            categoryHash(category, {
              ...params,
              q: localQuery,
              productId: id,
            })
          );
        });
      });
    }

    const loadMoreBtn = container.querySelector(
      "#load-more"
    ) as HTMLButtonElement;

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
  }

  function renderFilterRail(): void {
    const rail = container.querySelector("#filter-rail")!;
    const numericRanges = computeNumericRanges(compatibleProducts);

    // ---- Mini Part List card (like PP's top-left) ----
    const buildCount = Object.keys(storedBuild).length;
    // Total/wattage: try to compute from loaded buildParts (when picking), otherwise show dashes
    let totalStr = formatPrice(0, currency, lang);
    let wattStr = "0W";
    if (buildCount > 0 && Object.keys(buildParts).length > 0) {
      // Estimate from currently loaded buildParts
      let sum = 0;
      let estW = 0;
      // We don't have product objects for all slots without async load, so keep placeholder.
      // Use compatibleProducts not needed — will be refreshed after pick.
      for (const p of Object.values(buildParts)) {
        sum += p.min_price ?? 0;
      }
      // Simple wattage sum for mini card: sum of tdp-like attrs if present
      for (const p of Object.values(buildParts)) {
        const w = p.attributes["tdp"] || p.attributes["wattage_w"] || "";
        const m = /(\d+)/.exec(w);
        if (m) estW += parseInt(m[1], 10);
      }
      totalStr = formatPrice(sum, currency, lang);
      wattStr = estW + "W";
    }
    const miniCard = `
      <div class="miniPart">
        <div class="miniPart-head">
          <span class="miniPart-title">Part <span class="miniPart-icon">◈</span> List</span>
        </div>
        <label class="miniPart-compat">
          <input type="checkbox" checked disabled />
          <span>${lang === "he" ? "מסנן תאימות" : "Compatibility Filter"}</span>
        </label>
        <div class="miniPart-stats">
          <div><span class="miniPart-label">PARTS</span><span class="miniPart-value">${buildCount}</span></div>
          <div><span class="miniPart-label">TOTAL</span><span class="miniPart-value miniPart-total">${totalStr}</span></div>
          <div><span class="miniPart-label">ESTIMATED WATTAGE</span><span class="miniPart-value miniPart-watt">${wattStr}</span></div>
        </div>
      </div>
    `;

    // ---- Merchants / Pricing (mirrors PP) ----
    const vendorValues = filterableAttrs.get("vendor") ?? [];
    const merchantsBody = vendorValues.length
      ? `
        <div class="group__content" id="merchants-content" style="display:none">
          <label class="filter-option"><input type="checkbox" data-merchant-all /> All</label>
          ${vendorValues.map(([v,cnt]) => `
            <label class="filter-option">
              <input type="checkbox" data-attr="vendor" value="${esc(v)}" ${ (params.filters["vendor"] ?? []).includes(v) ? "checked" : "" } />
              ${esc(vendorLabel(v))} <span class="fo-count">(${cnt})</span>
            </label>
          `).join("")}
        </div>
      `
      : `<div class="group__content" style="display:none; padding:6px 0; font-size:0.82rem; color:var(--text-dim)">No vendor data</div>`;

    const pricingBody = `
      <div class="group__content" style="padding:8px 0">
        <label class="checkbox-row" style="margin-top:8px; border-top:none; padding-top:6px">
          <input type="checkbox" id="stock-checkbox" ${params.stockOnly ? "checked" : ""} />
          ${t(lang, "inStockOnly")}
        </label>
      </div>
    `;

    const checkboxAttrs = new Set(filterableAttrs.keys());
    for (const key of NUMERIC_ATTRS) {
      checkboxAttrs.delete(key);
    }
    checkboxAttrs.delete("price");
    checkboxAttrs.delete("vendor");

    const checkboxGroups = Array.from(checkboxAttrs)
      .filter((key) => filterableAttrs.has(key))
      .map((key) => {
        const values = filterableAttrs.get(key)!;
        const selected = new Set(params.filters[key] ?? []);

        const options = values
          .map(([value, count]) => {
            const displayValue = value;

            return `
              <label class="filter-option">
                <input
                  type="checkbox"
                  data-attr="${esc(key)}"
                  value="${esc(value)}"
                  ${selected.has(value) ? "checked" : ""}
                />
                ${esc(displayValue)}
                <span class="fo-count">(${count})</span>
              </label>
            `;
          })
          .join("");

        return `
          <details class="filter-group">
            <summary><span>${esc(attributeLabel(key, lang))}</span><span class="collapse-toggle">+</span></summary>
            <div class="group__content">${options}</div>
          </details>
        `;
      })
      .join("");

    const sliderGroups: string[] = [];

    if (numericRanges.has("price")) {
      const range = numericRanges.get("price")!;
      const currentMin = params.ranges.price?.min ?? range.min;
      const currentMax = params.ranges.price?.max ?? range.max;
      const step = Math.max(1, Math.floor((range.max - range.min) / 100));
      const minPct = ((currentMin - range.min) / (range.max - range.min)) * 100;
      const maxPct = ((currentMax - range.min) / (range.max - range.min)) * 100;

      sliderGroups.push(`
        <details class="filter-group">
          <summary><span>${t(lang, "priceRange") || "Price"}</span><span class="collapse-toggle">+</span></summary>
          <div class="group__content">
            <div class="filter-slider" dir="ltr">
              <div class="price-label-row"><span>$${range.min}</span><span>$${range.max}</span></div>
              <div class="range-slider-track" style="--range-start: ${minPct}%; --range-end: ${100 - maxPct}%;" id="price-track">
                <input type="range" class="range-slider" id="price-min-slider" min="${range.min}" max="${range.max}" step="${step}" value="${currentMin}" />
                <input type="range" class="range-slider" id="price-max-slider" min="${range.min}" max="${range.max}" step="${step}" value="${currentMax}" />
              </div>
              <div style="display:flex; gap:6px; margin-top:8px">
                <input type="number" id="price-min" value="${currentMin}" min="${range.min}" max="${range.max}" step="${step}" style="flex:1; border:1px solid var(--border); border-radius:6px; padding:4px 6px; font-size:0.78rem" />
                <input type="number" id="price-max" value="${currentMax}" min="${range.min}" max="${range.max}" step="${step}" style="flex:1; border:1px solid var(--border); border-radius:6px; padding:4px 6px; font-size:0.78rem" />
              </div>
            </div>
          </div>
        </details>
      `);
    }

    for (const [key, range] of numericRanges) {
      if (key === "price") continue;
      if (!NUMERIC_ATTRS.has(key)) continue;

      const label = attributeLabel(key, lang);
      const currentMin = params.ranges[key]?.min ?? range.min;
      const currentMax = params.ranges[key]?.max ?? range.max;
      const step = key.includes("ghz") || key.includes("clock") ? 0.1 : 1;
      const minPct = ((currentMin - range.min) / (range.max - range.min)) * 100;
      const maxPct = ((currentMax - range.min) / (range.max - range.min)) * 100;

      sliderGroups.push(`
        <details class="filter-group">
          <summary><span>${esc(label)}</span><span class="collapse-toggle">+</span></summary>
          <div class="group__content">
            <div class="filter-slider" dir="ltr">
              <div class="price-label-row"><span>${range.min}</span><span>${range.max}</span></div>
              <div class="range-slider-track" style="--range-start: ${minPct}%; --range-end: ${100 - maxPct}%;" id="${key}-track">
                <input type="range" class="range-slider" id="${key}-min-slider" min="${range.min}" max="${range.max}" step="${step}" value="${currentMin}" />
                <input type="range" class="range-slider" id="${key}-max-slider" min="${range.min}" max="${range.max}" step="${step}" value="${currentMax}" />
              </div>
              <div style="display:flex; gap:6px; margin-top:8px">
                <input type="number" id="${key}-min" value="${currentMin}" min="${range.min}" max="${range.max}" step="${step}" style="flex:1; border:1px solid var(--border); border-radius:6px; padding:4px 6px; font-size:0.78rem" />
                <input type="number" id="${key}-max" value="${currentMax}" min="${range.min}" max="${range.max}" step="${step}" style="flex:1; border:1px solid var(--border); border-radius:6px; padding:4px 6px; font-size:0.78rem" />
              </div>
            </div>
          </div>
        </details>
      `);
    }

    rail.innerHTML = `
      ${miniCard}

      <div class="railSection">
        <h3 class="railSectionTitle">Merchants / Pricing</h3>
        <div class="group group--filter">
          <h3 class="group__title group__title--trigger js-trigger-filter" data-toggle="merchants">MERCHANTS<span class="collapse-toggle">+</span></h3>
          ${merchantsBody}
        </div>
        <div class="group group--filter">
          <h3 class="group__title group__title--trigger js-trigger-filter" data-toggle="pricing">PRICING OPTIONS<span class="collapse-toggle">+</span></h3>
          ${pricingBody}
        </div>
      </div>

      <div class="railSection">
        <h3 class="railSectionTitle">Filters</h3>

        ${sliderGroups.join("")}

        ${checkboxGroups}

        <button
          class="clear-filters"
          id="clear-filters-btn"
          type="button"
        >
          ${t(lang, "clearFilters")}
        </button>
      </div>
    `;

    rail
      .querySelector("#stock-checkbox")!
      .addEventListener("change", (e) => {
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

    for (const key of numericRanges.keys()) {
      if (key === "price") {
        const minInput = rail.querySelector("#price-min") as HTMLInputElement;
        const maxInput = rail.querySelector("#price-max") as HTMLInputElement;
        const minSlider = rail.querySelector("#price-min-slider") as HTMLInputElement;
        const maxSlider = rail.querySelector("#price-max-slider") as HTMLInputElement;
        const track = rail.querySelector("#price-track") as HTMLElement;

        const updatePriceRange = () => {
          const min = minInput.value ? parseFloat(minInput.value) : null;
          const max = maxInput.value ? parseFloat(maxInput.value) : null;
          params.ranges.price = { min, max };
          syncAndRerender();
        };

        const updateTrack = () => {
          if (!track) return;
          const range = numericRanges.get("price")!;
          const minPct = ((Number(minSlider.value) - range.min) / (range.max - range.min)) * 100;
          const maxPct = ((Number(maxSlider.value) - range.min) / (range.max - range.min)) * 100;
          track.style.setProperty("--range-start", `${minPct}%`);
          track.style.setProperty("--range-end", `${100 - maxPct}%`);
        };

        minInput.addEventListener("change", updatePriceRange);
        maxInput.addEventListener("change", updatePriceRange);

        minSlider.addEventListener("input", () => {
          minInput.value = minSlider.value;
          maxSlider.min = minSlider.value;
          updateTrack();
        });
        minSlider.addEventListener("change", updatePriceRange);

        maxSlider.addEventListener("input", () => {
          maxInput.value = maxSlider.value;
          minSlider.max = maxSlider.value;
          updateTrack();
        });
        maxSlider.addEventListener("change", updatePriceRange);
      } else {
        const minInput = rail.querySelector(`#${key}-min`) as HTMLInputElement;
        const maxInput = rail.querySelector(`#${key}-max`) as HTMLInputElement;
        const minSlider = rail.querySelector(`#${key}-min-slider`) as HTMLInputElement;
        const maxSlider = rail.querySelector(`#${key}-max-slider`) as HTMLInputElement;
        const track = rail.querySelector(`#${key}-track`) as HTMLElement;

        const updateRange = () => {
          const min = minInput.value ? parseFloat(minInput.value) : null;
          const max = maxInput.value ? parseFloat(maxInput.value) : null;
          params.ranges[key] = { min, max };
          syncAndRerender();
        };

        const updateTrack = () => {
          if (!track) return;
          const range = numericRanges.get(key)!;
          const minPct = ((Number(minSlider.value) - range.min) / (range.max - range.min)) * 100;
          const maxPct = ((Number(maxSlider.value) - range.min) / (range.max - range.min)) * 100;
          track.style.setProperty("--range-start", `${minPct}%`);
          track.style.setProperty("--range-end", `${100 - maxPct}%`);
        };

        minInput.addEventListener("change", updateRange);
        maxInput.addEventListener("change", updateRange);

        minSlider.addEventListener("input", () => {
          minInput.value = minSlider.value;
          maxSlider.min = minSlider.value;
          updateTrack();
        });
        minSlider.addEventListener("change", updateRange);

        maxSlider.addEventListener("input", () => {
          maxInput.value = maxSlider.value;
          minSlider.max = maxSlider.value;
          updateTrack();
        });
        maxSlider.addEventListener("change", updateRange);
      }
    }

    // PP-style collapsible headers (MERCHANTS / PRICING OPTIONS / Filters groups)
    rail.querySelectorAll<HTMLHeadingElement>(".group__title--trigger").forEach((h) => {
      h.addEventListener("click", () => {
        const content = h.nextElementSibling as HTMLElement | null;
        if (!content) return;
        const isOpen = content.style.display !== "none";
        content.style.display = isOpen ? "none" : "block";
        const tog = h.querySelector<HTMLElement>(".collapse-toggle");
        if (tog) tog.textContent = isOpen ? "+" : "−";
      });
    });
    rail.querySelectorAll<HTMLDetailsElement>(".filter-group").forEach((d) => {
      const tog = d.querySelector<HTMLElement>(".collapse-toggle");
      d.addEventListener("toggle", () => {
        if (tog) tog.textContent = d.open ? "−" : "+";
      });
    });
    const stockEl = rail.querySelector<HTMLInputElement>("#stock-checkbox");
    if (stockEl) {
      // already wired below, but keep here for pricing section duplicate
    }
    const merchantAll = rail.querySelector<HTMLInputElement>("[data-merchant-all]");
    if (merchantAll) {
      merchantAll.addEventListener("change", () => {
        const checked = merchantAll.checked;
        rail.querySelectorAll<HTMLInputElement>('input[data-attr="vendor"]').forEach((el) => {
          el.checked = checked;
          const key = "vendor";
          const set = new Set(params.filters[key] ?? []);
          if (checked) set.add(el.value);
          else set.delete(el.value);
          params.filters[key] = Array.from(set);
          if (params.filters[key].length === 0) delete params.filters[key];
        });
        syncAndRerender();
      });
    }

    rail
      .querySelector("#clear-filters-btn")!
      .addEventListener("click", () => {
        params.filters = {};
        params.ranges = {};
        params.stockOnly = false;
        syncAndRerender();
      });
  }

  renderFilterRail();
  renderGrid();

  const searchInput = container.querySelector(
    "#search-input"
  ) as HTMLInputElement;

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

  const sortSelect = container.querySelector(
    "#sort-select"
  ) as HTMLSelectElement;

  sortSelect.addEventListener("change", () => {
    params.sort = sortSelect.value as SortKey;
    syncAndRerender();
  });

  if (!pickSlot && params.productId) {
    const product = products.find((p) => p.id === params.productId);

    if (product) {
      openDetail(lang, currency, product, () => {
        if (history.length > 1) history.back();
        else
          replaceRoute(
            categoryHash(category, {
              ...params,
              q: localQuery,
              productId: null,
            })
          );
      });
    }
  }
}