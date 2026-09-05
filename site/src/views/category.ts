import { loadCategory } from "../api";
import {
  BUILD_SLOTS,
  impliedFilterValues,
  isProductCompatibleWithBuild,
  knownPartWattage,
  optionMatchesTokens,
  slotForCategory,
} from "../build";
import { formatPrice } from "../format";
import {
  attributeLabel,
  categoryLabel,
  resultsCount,
  t,
  vendorLabel,
  vendorsCount,
} from "../i18n";
import { filterAllowlist, sortSpecKeys } from "../specs";
import {
  addToBuild,
  buildHash,
  categoryHash,
  getStoredBuild,
  homeHash,
  navigate,
  productHash,
  replaceRoute,
  setStoredBuild,
  type BuildMap,
  type CategoryParams,
} from "../state";
import type { Currency, Lang, Product, SortKey } from "../types";
import { displayName, esc } from "../utils";
import { icon } from "../icons";

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
  "tdp_w",
  "vram_gb",
  "wattage_w",
  "wattage",
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
  "l2_cache",
  "l3_cache",
  "first_word_latency_ns",
  "memory_max",
  "max_gpu_length_mm",
  "m2_slots",
]);

const MAX_SPEC_COLUMNS = 4;

// Minimum share of products that must carry a key before it becomes a
// table column — keeps one-off trivia rows from producing near-empty
// columns.
const MIN_COLUMN_COVERAGE = 0.05;

function computeFilterableAttributes(
  products: Product[],
  category: string
): Map<string, Array<[string, number]>> {
  const allowlist = filterAllowlist(category);
  const counts = new Map<string, Map<string, number>>();
  const numericRanges = new Map<string, { min: number; max: number }>();

  for (const p of products) {
    for (const [key, rawValue] of Object.entries(p.attributes)) {
      if (rawValue === undefined || rawValue === null || rawValue === "") continue;
      // Attribute values arrive as mixed ints/strings across vendors
      // (m2_slots: 2 vs "2"). Stringify once so checkbox values, URL
      // params and strict-equality matching all speak one type.
      const value = String(rawValue);

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
    // Curated filters per category: only allowlisted keys (plus vendor)
    // become checkbox filters. Deep-trivia keys (mosfet phases, exact
    // port counts) stay visible on the product page but never clutter the
    // rail. Categories without a curated list keep the old behavior.
    if (key !== "vendor" && allowlist && !allowlist.includes(key)) continue;

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
        const actual = p.attributes[key];
        if (!values.includes(actual === undefined || actual === null ? actual : String(actual))) return false;
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

interface LoadedBuild {
  /** First picked product per slot (for compatibility checks + wattage). */
  first: Record<string, Product>;
  /** Every picked product (for totals). */
  items: Array<{ slotId: string; product: Product }>;
}

async function loadBuildParts(build: BuildMap): Promise<LoadedBuild> {
  const first: Record<string, Product> = {};
  const items: Array<{ slotId: string; product: Product }> = [];

  await Promise.all(
    BUILD_SLOTS.map(async (slot) => {
      for (const productId of build[slot.id] ?? []) {
        for (const category of slot.categories) {
          try {
            const products = await loadCategory(category);
            const found = products.find((p) => p.id === productId);

            if (found) {
              items.push({ slotId: slot.id, product: found });
              if (!first[slot.id]) first[slot.id] = found;
              break;
            }
          } catch {
            // Ignore category load failures.
          }
        }
      }
    })
  );

  return { first, items };
}

export async function renderCategory(
  container: HTMLElement,
  lang: Lang,
  currency: Currency,
  category: string,
  params: CategoryParams
): Promise<void> {
  container.innerHTML = `<div class="empty-state">${t(lang, "loading")}</div>`;

  let products: Product[];

  try {
    products = await loadCategory(category);
  } catch {
    container.innerHTML = `<div class="empty-state"><p style="margin-bottom:14px;">${t(lang, "loadError")}</p><button class="btn-small" type="button" onclick="location.reload()">${t(lang, "retry")}</button></div>`;
    return;
  }

  const pickSlot = params.pick
    ? BUILD_SLOTS.find((slot) => slot.id === params.pick) ?? null
    : null;

  const storedBuild = getStoredBuild();

  // Always resolve the current build: the Parts List card shows live
  // totals, and the compatibility filter needs the picked parts.
  const loadedBuild = await loadBuildParts(storedBuild);
  const buildParts = loadedBuild.first;

  // The slot this category fills (for implied compat values), if any.
  const targetSlot = slotForCategory(category);
  const targetSlotId = pickSlot ? pickSlot.id : targetSlot?.id ?? null;

  // Compatibility filter starts on when there is something to be
  // compatible with; the checkbox in the Parts List card toggles it.
  let compatOn = loadedBuild.items.length > 0 && targetSlotId !== null;
  // Filter keys the compat logic applied itself (removed when toggled off).
  const compatAutoKeys = new Set<string>();

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
  let gridObserver: IntersectionObserver | null = null;

  const filterableAttrs = computeFilterableAttributes(compatibleProducts, category);

  // Table columns follow the curated per-category priority (not "whatever
  // filters exist"): the important specs first, skipping keys too sparse
  // to make a useful column.
  const specColumns = (() => {
    const coverage = new Map<string, number>();
    for (const p of compatibleProducts) {
      for (const key of Object.keys(p.attributes)) {
        if (p.attributes[key]) coverage.set(key, (coverage.get(key) ?? 0) + 1);
      }
    }
    const n = Math.max(1, compatibleProducts.length);
    const candidates = sortSpecKeys(
      category,
      Array.from(coverage.keys()).filter(
        (k) => k !== "brand" && k !== "model" && (coverage.get(k) ?? 0) / n >= MIN_COLUMN_COVERAGE
      )
    );
    return candidates.slice(0, MAX_SPEC_COLUMNS);
  })();

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
    addToBuild(build, pickSlot.id, product.id);
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

        <div
          id="infinite-sentinel"
          style="text-align:center; margin-top:20px; min-height:32px; display:none;"
        ></div>
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
      // Compat-applied tags stay locked while the filter is on; turn it
      // off to edit them.
      const locked = compatOn && compatAutoKeys.has(key);

      for (const v of values) {
        const label = key === "vendor" ? vendorLabel(v) : v;

        if (locked) {
          chips.push(
            `<span
              class="active-filter-chip is-locked"
              title="${esc(t(lang, "compatLocked"))}"
            >
              ${esc(attributeLabel(key, lang))}: ${esc(label)}
            </span>`
          );
          continue;
        }

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
          display = `${range.min} - ${range.max}`;
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

        return `<div class="pl-cell spec">${text ? esc(text) : "-"}</div>`;
      })
      .join("");

    const actionCell = pickSlot
      ? `<span class="btn-small btn-add">${t(lang, "addToBuild")}</span>`
      : `<button type="button" class="btn-small btn-quickadd" data-quickadd="${esc(p.id)}">${t(lang, "quickAdd")}</button>`;

    // Shared inner cells for both modes; only the wrapper differs:
    // plain product rows are real links to the product page, while
    // picker rows are buttons that add the part to the build.
    const inner = `
        <div class="pl-cell" style="display:flex; align-items:center; justify-content:center;">
          ${p.image
            ? `<img class="plThumb" src="${esc(p.image)}" alt="${esc(displayName(p))}" loading="lazy" style="object-fit:contain; background:#fff;">`
            : `<span class="plThumb" aria-hidden="true">${esc(thumbLabel(p))}</span>`}
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
        </div>`;

    if (!pickSlot) {
      return `
      <a
        class="pl-row"
        data-id="${esc(p.id)}"
        href="${productHash(category, p.id)}"
      >
        ${inner}
      </a>`;
    }

    return `
      <button
        class="pl-row pl-row--pick"
        type="button"
        data-id="${esc(p.id)}"
      >
        ${inner}
      </button>`;
  }

  function renderGrid(): void {
    const filtered = currentFiltered();

    const activeFiltersEl = container.querySelector("#active-filters")!;
    activeFiltersEl.innerHTML = activeFiltersHtml();

    activeFiltersEl
      .querySelectorAll("button.active-filter-chip")
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

          // The user took over this key; compat no longer owns it.
          compatAutoKeys.delete(key);

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

      // Picker rows are <button>s that add to the build; plain rows
      // are <a> links and navigate natively (middle-click safe).
      listEl.querySelectorAll("button.pl-row").forEach((el) => {
        el.addEventListener("click", () => {
          if (!pickSlot) return;
          const id = (el as HTMLElement).dataset.id!;
          const product = productById.get(id);
          if (product) addPartToBuild(product);
        });
      });

      // Quick-add drops the part straight into the builder without
      // leaving the list; the row itself still links to the product.
      listEl.querySelectorAll("[data-quickadd]").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.preventDefault();
          e.stopPropagation();
          const id = (btn as HTMLElement).dataset.quickadd!;
          const product = productById.get(id);
          if (!product) return;
          const slot = slotForCategory(product.category);
          if (!slot) return;
          const build = getStoredBuild();
          addToBuild(build, slot.id, product.id);
          setStoredBuild(build);
          const el = btn as HTMLButtonElement;
          el.classList.add("is-added");
          el.innerHTML = `${icon("check", 13)}<span>${esc(t(lang, "addedLabel"))}</span>`;
          window.setTimeout(() => {
            el.classList.remove("is-added");
            el.textContent = t(lang, "quickAdd");
          }, 1300);
        });
      });
    }

    const sentinel = container.querySelector(
      "#infinite-sentinel"
    ) as HTMLElement;

    if (gridObserver) {
      gridObserver.disconnect();
      gridObserver = null;
    }

    if (filtered.length > visibleCount) {
      sentinel.style.display = "block";
      sentinel.textContent = t(lang, "loading");

      gridObserver = new IntersectionObserver(
        (entries) => {
          if (entries.some((entry) => entry.isIntersecting)) {
            visibleCount += PAGE_SIZE;
            renderGrid();
          }
        },
        { rootMargin: "600px" }
      );
      gridObserver.observe(sentinel);
    } else {
      sentinel.style.display = "none";
      sentinel.textContent = "";
    }
  }

  function renderFilterRail(): void {
    const rail = container.querySelector("#filter-rail")!;
    const numericRanges = computeNumericRanges(compatibleProducts);

    // ---- Parts List card: live builder totals, hidden when empty ----
    let buildSum = 0;
    for (const { product } of loadedBuild.items) {
      buildSum += product.min_price ?? 0;
    }
    const buildCount = loadedBuild.items.length;
    let buildWatts = 0;
    for (const { slotId, product } of loadedBuild.items) {
      buildWatts += knownPartWattage(slotId, product);
    }
    const showCompatToggle = buildCount > 0 && targetSlotId !== null;
    const miniCard =
      buildCount === 0
        ? ""
        : `
      <div class="miniPart">
        <div class="miniPart-head">
          <span class="miniPart-title">Parts List</span>
        </div>
        ${
          showCompatToggle
            ? `
        <label class="miniPart-compat" title="${
          lang === "he"
            ? "הצגת ערכים תואמים בלבד"
            : "Grey out options that conflict with the picked parts"
        }">
          <input type="checkbox" id="compat-checkbox" ${compatOn ? "checked" : ""} />
          <span>${lang === "he" ? "מסנן תאימות" : "Compatibility Filter"}</span>
        </label>`
            : ""
        }
        <div class="miniPart-stats">
          <div><span class="miniPart-label">PARTS</span><span class="miniPart-value">${buildCount}</span></div>
          <div><span class="miniPart-label">TOTAL</span><span class="miniPart-value miniPart-total">${esc(formatPrice(buildSum, currency, lang))}</span></div>
          <div><span class="miniPart-label">ESTIMATED WATTAGE</span><span class="miniPart-value miniPart-watt">${buildWatts}W</span></div>
        </div>
      </div>
    `;

    // ---- Compatibility: pre-select build-implied values (AM5 etc.) ----
    if (compatOn && targetSlotId) {
      const implied = impliedFilterValues(targetSlotId, buildParts);
      let applied = false;
      for (const [key, tokens] of Object.entries(implied)) {
        if ((params.filters[key] ?? []).length > 0) continue;
        const candidates = filterableAttrs.get(key) ?? [];
        const matched = candidates
          .map(([value]) => value)
          .filter((value) => optionMatchesTokens(value, tokens));
        if (matched.length > 0) {
          params.filters[key] = matched;
          compatAutoKeys.add(key);
          applied = true;
        }
      }
      if (applied) {
        replaceRoute(categoryHash(category, { ...params, q: localQuery }));
      }
    }

    // ---- Per-option compatibility: values no compatible product carries ----
    // Rendered greyed-out (and locked while the filter is on); when the
    // filter is off they stay visible, only slightly muted, and clickable.
    const goodByOption = new Map<string, Set<string>>();
    if (buildCount > 0 && targetSlotId) {
      for (const p of compatibleProducts) {
        if (!isProductCompatibleWithBuild(p, targetSlotId, buildParts)) {
          continue;
        }
        for (const key of filterableAttrs.keys()) {
          let set = goodByOption.get(key);
          if (!set) {
            set = new Set<string>();
            goodByOption.set(key, set);
          }
          if (key === "vendor") {
            for (const offer of p.offers) set.add(offer.vendor);
          } else if (p.attributes[key]) {
            set.add(String(p.attributes[key]));
          }
        }
      }
    }
    const optionDead = (key: string, value: string): boolean =>
      goodByOption.size > 0 && !(goodByOption.get(key)?.has(value) ?? false);

    const optionHtml = (key: string, value: string, count: number): string => {
      const selected = new Set(params.filters[key] ?? []);
      const dead = optionDead(key, value);
      const stateClass = dead ? (compatOn ? "is-off" : "is-soft-off") : "";
      return `
        <label class="filter-option ${stateClass}">
          <input
            type="checkbox"
            data-attr="${esc(key)}"
            value="${esc(value)}"
            ${selected.has(value) ? "checked" : ""}
            ${dead && compatOn ? "disabled" : ""}
          />
          ${key === "vendor" ? esc(vendorLabel(value)) : esc(value)}
          <span class="fo-count">(${count})</span>
        </label>
      `;
    };

    // ---- Merchants / Pricing (mirrors PP) ----
    const vendorValues = filterableAttrs.get("vendor") ?? [];
    const merchantsBody = vendorValues.length
      ? `
        <div class="group__content" id="merchants-content" style="display:none">
          <label class="filter-option"><input type="checkbox" data-merchant-all /> All</label>
          ${vendorValues.map(([v, cnt]) => optionHtml("vendor", v, cnt)).join("")}
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

    // Long option lists collapse behind a Show more toggle (PCPP style).
    const MAX_VISIBLE_OPTIONS = 6;

    const checkboxGroups = Array.from(checkboxAttrs)
      .filter((key) => filterableAttrs.has(key))
      .map((key) => {
        const values = filterableAttrs.get(key)!;
        const shown = values.slice(0, MAX_VISIBLE_OPTIONS);
        const extra = values.slice(MAX_VISIBLE_OPTIONS);

        const shownHtml = shown
          .map(([value, count]) => optionHtml(key, value, count))
          .join("");
        const extraHtml =
          extra.length > 0
            ? `<span class="extra-opts" hidden>${extra
                .map(([value, count]) => optionHtml(key, value, count))
                .join("")}</span>
              <button class="moreless" type="button" data-more="${esc(t(lang, "showMore"))} (${extra.length})" data-less="${esc(t(lang, "showLess"))}">${esc(t(lang, "showMore"))} (${extra.length})</button>`
            : "";

        return `
          <details class="filter-group">
            <summary><span>${esc(attributeLabel(key, lang))}</span><span class="collapse-toggle">+</span></summary>
            <div class="group__content">${shownHtml}${extraHtml}</div>
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

        // Compat-owned values can't be toggled while the filter is on.
        if (compatOn && compatAutoKeys.has(key)) {
          input.checked = (params.filters[key] ?? []).includes(input.value);
          return;
        }

        const set = new Set(params.filters[key] ?? []);

        if (input.checked) set.add(input.value);
        else set.delete(input.value);

        params.filters[key] = Array.from(set);
        if (params.filters[key].length === 0) delete params.filters[key];

        // The user took over this key; compat no longer owns it.
        compatAutoKeys.delete(key);

        syncAndRerender();
      });
    });

    const compatBox = rail.querySelector<HTMLInputElement>("#compat-checkbox");
    if (compatBox) {
      compatBox.addEventListener("change", () => {
        compatOn = compatBox.checked;
        if (!compatOn) {
          for (const key of compatAutoKeys) delete params.filters[key];
          compatAutoKeys.clear();
        }
        renderFilterRail();
        syncAndRerender();
      });
    }

    rail.querySelectorAll<HTMLButtonElement>(".moreless").forEach((btn) => {
      btn.addEventListener("click", () => {
        const extra = btn.previousElementSibling as HTMLElement | null;
        if (!extra) return;
        const willShow = extra.hidden;
        extra.hidden = !willShow;
        btn.textContent = willShow ? btn.dataset.less! : `${btn.dataset.more}`;
        btn.classList.toggle("open", willShow);
      });
    });

    // Dual-handle sliders: the thumbs may cross freely while dragging
    // (values are ordered, never clamped against each other), the track
    // repaints live, and the filter commits once on release or box edit.
    // A full-span selection clears the constraint instead of storing it.
    const wireRange = (key: string, prefix: string): void => {
      const range = numericRanges.get(key)!;
      const span = range.max - range.min;
      const minInput = rail.querySelector(`#${prefix}-min`) as HTMLInputElement | null;
      const maxInput = rail.querySelector(`#${prefix}-max`) as HTMLInputElement | null;
      const minSlider = rail.querySelector(`#${prefix}-min-slider`) as HTMLInputElement | null;
      const maxSlider = rail.querySelector(`#${prefix}-max-slider`) as HTMLInputElement | null;
      const track = rail.querySelector(`#${prefix}-track`) as HTMLElement | null;
      if (!minInput || !maxInput || !minSlider || !maxSlider) return;

      const paint = (lo: number, hi: number): void => {
        if (!track || span <= 0) return;
        const clampPct = (v: number): number =>
          Math.max(0, Math.min(100, ((v - range.min) / span) * 100));
        track.style.setProperty("--range-start", `${clampPct(lo)}%`);
        track.style.setProperty("--range-end", `${100 - clampPct(hi)}%`);
      };

      const ordered = (a: number, b: number): [number, number] =>
        a <= b ? [a, b] : [b, a];

      const commit = (lo: number, hi: number): void => {
        if (lo <= range.min && hi >= range.max) {
          delete params.ranges[key];
        } else {
          params.ranges[key] = { min: lo, max: hi };
        }
        syncAndRerender();
      };

      const readSliders = (): [number, number] => {
        let lo = Number(minSlider.value);
        let hi = Number(maxSlider.value);
        if (Number.isNaN(lo)) lo = range.min;
        if (Number.isNaN(hi)) hi = range.max;
        return ordered(lo, hi);
      };

      minSlider.addEventListener("input", () => {
        const [lo, hi] = readSliders();
        minInput.value = String(lo);
        maxInput.value = String(hi);
        paint(lo, hi);
      });
      maxSlider.addEventListener("input", () => {
        const [lo, hi] = readSliders();
        minInput.value = String(lo);
        maxInput.value = String(hi);
        paint(lo, hi);
      });
      minSlider.addEventListener("change", () => {
        const [lo, hi] = readSliders();
        commit(lo, hi);
      });
      maxSlider.addEventListener("change", () => {
        const [lo, hi] = readSliders();
        commit(lo, hi);
      });

      const commitFromBoxes = (): void => {
        const clampBox = (raw: string, fallback: number): number => {
          if (raw.trim() === "") return fallback;
          const n = Number(raw);
          if (Number.isNaN(n)) return fallback;
          return Math.max(range.min, Math.min(range.max, n));
        };
        const [lo, hi] = ordered(
          clampBox(minInput.value, range.min),
          clampBox(maxInput.value, range.max)
        );
        minSlider.value = String(lo);
        maxSlider.value = String(hi);
        minInput.value = String(lo);
        maxInput.value = String(hi);
        paint(lo, hi);
        commit(lo, hi);
      };

      minInput.addEventListener("change", commitFromBoxes);
      maxInput.addEventListener("change", commitFromBoxes);

      const [lo0, hi0] = readSliders();
      paint(lo0, hi0);
    };

    for (const key of numericRanges.keys()) {
      wireRange(key, key);
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
        compatAutoKeys.clear();
        renderFilterRail();
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

  // Legacy ?p=<id> links (from before per-product pages existed)
  // redirect to the dedicated product page.
  if (!pickSlot && params.productId) {
    const product = products.find((p) => p.id === params.productId);
    if (product) {
      navigate(productHash(category, product.id));
      return;
    }
  }
}