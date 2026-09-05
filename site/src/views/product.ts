import { loadCategory, loadHistory } from "../api";
import { slotForCategory } from "../build";
import { formatPrice } from "../format";
import { attributeLabel, categoryLabel, t, vendorLabel } from "../i18n";
import { sortSpecKeys } from "../specs";
import {
  addToBuild,
  buildHash,
  categoryHash,
  getStoredBuild,
  homeHash,
  navigate,
  productHash,
  setStoredBuild,
} from "../state";
import type { Currency, Lang, Product } from "../types";
import { displayName, errorPanel, esc, skuOf } from "../utils";

// Attribute keys that make good "series" variant groups (PCPP's
// "Wattage: 850 W / 750 W / 1000 W" pills), most useful first.
const VARIANT_KEY_PRIORITY = [
  "wattage_w",
  "wattage",
  "tdp_w",
  "tdp",
  "capacity_gb",
  "total_gb",
  "capacity",
  "vram_gb",
  "memory",
  "speed_mhz",
  "speed",
  "cores",
  "length_mm",
  "color",
  "form_factor",
  "memory_type",
  "efficiency",
  "modular",
  "type",
];

const NOISE_KEYS = new Set([
  "brand",
  "model",
  "vendor",
  "mpn",
  "upc",
  "packaging",
  "bundle_only",
  "clearance_item",
  "revision",
]);

interface VariantGroup {
  key: string;
  values: Array<{ value: string; productId: string; active: boolean }>;
}

/** Scraped attribute values arrive as mixed ints/strings/bools. */
function attrText(value: unknown): string {
  if (value === undefined || value === null) return "";
  return String(value);
}

function computeVariantGroups(
  product: Product,
  sameBrand: Product[]
): VariantGroup[] {
  if (sameBrand.length < 2) return [];
  const groups: VariantGroup[] = [];

  for (const key of VARIANT_KEY_PRIORITY) {
    // Attribute values are mixed types across vendors (850 vs "850 W"),
    // so normalize to strings before comparing, sorting, or rendering.
    const current = attrText(product.attributes[key]);
    if (!current) continue;
    const distinct = new Map<string, Product[]>();
    for (const p of sameBrand) {
      const v = attrText(p.attributes[key]);
      if (!v) continue;
      const list = distinct.get(v) ?? [];
      list.push(p);
      distinct.set(v, list);
    }
    if (distinct.size < 2 || distinct.size > 8) continue;

    const values = Array.from(distinct.entries()).map(([value, owners]) => {
      // Prefer the owner sharing the most attribute values with current.
      let best = owners[0];
      let bestScore = -1;
      for (const cand of owners) {
        let score = 0;
        for (const [k, v] of Object.entries(product.attributes)) {
          if (NOISE_KEYS.has(k)) continue;
          if (attrText(cand.attributes[k]) === attrText(v)) score++;
        }
        if (score > bestScore) {
          bestScore = score;
          best = cand;
        }
      }
      return { value, productId: best.id, active: value === current };
    });

    values.sort((a, b) =>
      Number(a.active) - Number(b.active) || a.value.localeCompare(b.value, undefined, { numeric: true })
    );
    // Active last like PCPP? PCPP lists in order; keep numeric order with active marked.
    groups.push({ key, values });
    if (groups.length >= 4) break;
  }

  return groups;
}

function similarProducts(product: Product, all: Product[]): Product[] {
  const scored: Array<{ p: Product; score: number }> = [];
  for (const p of all) {
    if (p.id === product.id) continue;
    let score = 0;
    if (p.brand && product.brand && p.brand === product.brand) score += 5;
    for (const [k, v] of Object.entries(product.attributes)) {
      if (NOISE_KEYS.has(k)) continue;
      if (p.attributes[k] === v) score += 1;
    }
    scored.push({ p, score });
  }
  scored.sort(
    (a, b) =>
      b.score - a.score || (a.p.min_price ?? Infinity) - (b.p.min_price ?? Infinity)
  );
  return scored.slice(0, 8).map((s) => s.p);
}

export async function renderProduct(
  container: HTMLElement,
  lang: Lang,
  currency: Currency,
  category: string,
  productId: string
): Promise<void> {
  container.innerHTML = `<div class="empty-state">${t(lang, "loading")}</div>`;

  let products: Product[];
  try {
    products = await loadCategory(category);
  } catch (err) {
    container.innerHTML = errorPanel(
      t(lang, "loadError"),
      t(lang, "retry"),
      err
    );
    return;
  }

  const product = products.find((p) => p.id === productId);
  if (!product) {
    container.innerHTML = `
      <div class="crumbs"><a href="${homeHash()}">← ${t(lang, "backToCategories")}</a></div>
      <div class="empty-state">${t(lang, "productNotFound")}</div>
    `;
    return;
  }

  const sameBrand = product.brand
    ? products.filter((p) => p.brand === product.brand)
    : [];
  const variantGroups = computeVariantGroups(product, sameBrand);
  const similar = similarProducts(product, products);
  const slot = slotForCategory(product.category);
  const sku = skuOf(product);
  const name = displayName(product);

  const orderedSpecKeys = sortSpecKeys(
    product.category,
    Object.keys(product.attributes).filter((k) => product.attributes[k])
  );
  const referenceSpecs: Record<string, string | number | boolean> = {
    ...(product.pcpartdb?.specs ?? {}),
    ...(product.pckombo?.specs ?? {}),
  };
  const referenceKeys = Object.keys(referenceSpecs).filter(
    (k) =>
      referenceSpecs[k] !== null &&
      referenceSpecs[k] !== undefined &&
      referenceSpecs[k] !== "" &&
      !(k in product.attributes)
  );

  const specRows =
    orderedSpecKeys
      .map(
        (k) =>
          `<div class="spec-row"><span class="spec-key">${esc(attributeLabel(k, lang))}</span><span class="spec-val">${esc(product.attributes[k])}</span></div>`
      )
      .join("") +
    referenceKeys
      .map(
        (k) =>
          `<div class="spec-row"><span class="spec-key">${esc(attributeLabel(k, lang))}</span><span class="spec-val">${esc(referenceSpecs[k])}</span></div>`
      )
      .join("");

  const variantHtml = variantGroups
    .map(
      (g) => `
      <div class="variant-group">
        <h3>${esc(attributeLabel(g.key, lang))}: ${esc(product.attributes[g.key])}</h3>
        <div class="variant-pills">
          ${g.values
            .map((v) =>
              v.active
                ? `<span class="variant-pill active">${esc(v.value)}</span>`
                : `<a class="variant-pill" href="${productHash(category, v.productId)}">${esc(v.value)}</a>`
            )
            .join("")}
        </div>
      </div>`
    )
    .join("");

  const sortedOffers = [...product.offers].sort((a, b) => {
    if (a.in_stock !== b.in_stock) return a.in_stock ? -1 : 1;
    return (a.price ?? Infinity) - (b.price ?? Infinity);
  });

  const priceRows = sortedOffers
    .map((offer) => {
      const total = (offer.price ?? 0) + (offer.shipping ?? 0);
      const shipping =
        offer.shipping === null || offer.shipping === undefined
          ? `<span class="dim">-</span>`
          : offer.shipping === 0
            ? `<span class="free-ship">+${t(lang, "freeShipping")}</span>`
            : esc(formatPrice(offer.shipping, currency, lang));
      const stale = offer.stale
        ? ` <span class="tag-stale">${t(lang, "staleData")}</span>`
        : "";
      return `
      <tr class="${offer.in_stock ? "" : "is-out"}">
        <td class="pt-merchant">${esc(vendorLabel(offer.vendor))}</td>
        <td class="pt-num">${offer.price === null ? "-" : esc(formatPrice(offer.price, currency, lang))}</td>
        <td class="pt-ship">${shipping}</td>
        <td class="pt-avail"><span class="status-dot ${offer.in_stock ? "in" : "out"}"></span>${offer.in_stock ? t(lang, "inStock") : t(lang, "outOfStock")}${stale}</td>
        <td class="pt-total">${offer.price === null ? "-" : esc(formatPrice(total, currency, lang))}</td>
        <td class="pt-buy"><a class="offer-link" href="${esc(offer.url)}" target="_blank" rel="noopener noreferrer">${t(lang, "buyLabel")}</a></td>
      </tr>`;
    })
    .join("");

  const imageHtml = product.image
    ? `<img class="pdp-image" src="${esc(product.image)}" alt="${esc(name)}" loading="eager">`
    : `<div class="thumb thumb-lg">${esc((product.brand ?? name).slice(0, 2).toUpperCase())}</div>`;

  const similarHtml = similar
    .map(
      (p) => `
      <a class="pdp-similar-card" href="${productHash(p.category, p.id)}">
        ${p.image ? `<img src="${esc(p.image)}" alt="${esc(displayName(p))}" loading="lazy">` : `<span class="plThumb" aria-hidden="true">${esc((p.brand ?? p.name).slice(0, 2).toUpperCase())}</span>`}
        <span class="pdp-similar-name">${esc(displayName(p))}</span>
        <span class="pdp-similar-price">${formatPrice(p.min_price, currency, lang)}</span>
      </a>`
    )
    .join("");

  container.innerHTML = `
    <div class="crumbs">
      <a href="${homeHash()}">← ${t(lang, "backToCategories")}</a>
      &nbsp;·&nbsp;
      <a href="${categoryHash(category)}">${esc(categoryLabel(category, lang))}</a>
    </div>

    <div class="title-band title-band--product">
      <div class="title-band-eyebrow">${esc(categoryLabel(category, lang))}</div>
      <h1>${esc(name)}</h1>
      <p>${esc(product.brand ?? "")}${sku ? ` · SKU: ${esc(sku)}` : ""}</p>
    </div>

    <div class="pdp-layout">
      <aside class="pdp-side">
        <div class="pdp-card">
          ${imageHtml}
          ${
            slot
              ? `<button class="btn-primary pdp-add" type="button" id="pdp-add">+ ${t(lang, "addToPartList")}</button>`
              : ""
          }
        </div>

        ${
          variantHtml
            ? `<div class="pdp-card"><h2 class="pdp-card-title">${t(lang, "variantsHeading")}</h2>${variantHtml}</div>`
            : ""
        }

        <div class="pdp-card">
          <h2 class="pdp-card-title">${t(lang, "specsHeading")}</h2>
          <div class="spec-list">${specRows || `<span class="dim">-</span>`}</div>
          ${
            referenceKeys.length > 0
              ? `<p class="reference-note" style="margin:10px 0 0">${t(lang, product.pckombo ? "pckomboReferenceNote" : "referenceSpecsNote")}</p>`
              : ""
          }
        </div>
      </aside>

      <div class="pdp-main">
        <div class="pdp-card">
          <h2 class="pdp-card-title">${t(lang, "pricesHeading")}</h2>
          <div class="price-table-wrap">
            <table class="price-table">
              <thead>
                <tr>
                  <th>${t(lang, "merchantHeading")}</th>
                  <th>${t(lang, "baseHeading")}</th>
                  <th>${t(lang, "shippingHeading")}</th>
                  <th>${t(lang, "availability")}</th>
                  <th>${t(lang, "totalHeading")}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>${priceRows}</tbody>
            </table>
          </div>
          <p class="pdp-disclaimer">* ${t(lang, "disclaimer")}</p>
        </div>

        <div class="pdp-card" id="pdp-history" hidden></div>

        ${
          similarHtml
            ? `<div class="pdp-card">
                <h2 class="pdp-card-title">${t(lang, "similarHeading")}</h2>
                <div class="pdp-similar-grid">${similarHtml}</div>
              </div>`
            : ""
        }
      </div>
    </div>
  `;

  const addBtn = container.querySelector<HTMLButtonElement>("#pdp-add");
  if (addBtn && slot) {
    addBtn.addEventListener("click", () => {
      const build = getStoredBuild();
      addToBuild(build, slot.id, product.id);
      setStoredBuild(build);
      navigate(buildHash(build));
    });
  }

  const historyHost = container.querySelector<HTMLElement>("#pdp-history");
  if (historyHost) {
    void renderPriceHistory(historyHost, lang, currency, category, product.id);
  }
}

// Flat step-line palette, readable on light and dark cards.
const HISTORY_COLORS = [
  "#ca8a04",
  "#0284c7",
  "#dc2626",
  "#16a34a",
  "#9333ea",
  "#ea580c",
  "#0d9488",
  "#db2777",
];

async function renderPriceHistory(
  host: HTMLElement,
  lang: Lang,
  currency: Currency,
  category: string,
  productId: string
): Promise<void> {
  let file;
  try {
    file = await loadHistory(category);
  } catch {
    return;
  }
  if (!file) return;
  let entry;
  try {
    entry = file[productId];
  } catch {
    return;
  }
  if (!entry || Array.isArray(entry)) return;

  const dates = Array.isArray(file.dates) ? file.dates : [];
  if (dates.length < 2) return;
  let vendors: string[];
  try {
    vendors = Object.keys(entry.v).filter(
      (v) =>
        Array.isArray(entry.v[v]) &&
        entry.v[v].some((p) => p !== null && p !== undefined)
    );
  } catch {
    return;
  }
  if (vendors.length === 0) return;

  let dayWindow = dates.length;
  const colorOf = (vendor: string): string =>
    HISTORY_COLORS[vendors.indexOf(vendor) % HISTORY_COLORS.length];

  const shortDate = (iso: string): string => {
    const parts = iso.split("-");
    return parts.length === 3 ? `${parts[2]}.${parts[1]}` : iso;
  };

  const draw = (): void => {
    const end = dates.length;
    const start = Math.max(0, end - dayWindow);
    const visDates = dates.slice(start, end);

    let lo = Infinity;
    let hi = -Infinity;
    for (const v of vendors) {
      for (const p of entry.v[v].slice(start, end)) {
        if (p === null || p === undefined) continue;
        if (p < lo) lo = p;
        if (p > hi) hi = p;
      }
    }
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) return;
    if (lo === hi) {
      lo = Math.max(0, lo - 1);
      hi = hi + 1;
    }
    const pad = (hi - lo) * 0.12;
    lo = Math.max(0, lo - pad);
    hi = hi + pad;

    const W = 640;
    const H = 260;
    const L = 64;
    const R = 12;
    const T = 12;
    const B = 30;
    const n = visDates.length;
    const x = (i: number): number =>
      n === 1 ? (L + W - R) / 2 : L + (W - L - R) * (i / (n - 1));
    const y = (v: number): number =>
      T + (1 - (v - lo) / (hi - lo)) * (H - T - B);

    const ticks = 4;
    let grid = "";
    for (let g = 0; g <= ticks; g++) {
      const value = lo + ((hi - lo) * g) / ticks;
      const gy = y(value);
      grid += `<line x1="${L}" y1="${gy}" x2="${W - R}" y2="${gy}" class="ph-grid"/>`;
      grid += `<text x="${L - 8}" y="${gy + 4}" text-anchor="end" class="ph-tick">${esc(formatPrice(Math.round(value), currency, lang))}</text>`;
    }

    const xLabels = [0, Math.floor((n - 1) / 2), n - 1]
      .filter((v, i, a) => a.indexOf(v) === i)
      .map(
        (i) =>
          `<text x="${x(i)}" y="${H - 8}" text-anchor="middle" class="ph-tick">${esc(shortDate(visDates[i]))}</text>`
      )
      .join("");

    const paths = vendors
      .map((vendor) => {
        const points = entry.v[vendor].slice(start, end);
        let d = "";
        let penDown = false;
        for (let i = 0; i < points.length; i++) {
          const p = points[i];
          if (p === null || p === undefined) {
            penDown = false;
            continue;
          }
          const cx = x(i);
          const cy = y(p);
          if (!penDown) {
            d += `M ${cx.toFixed(1)} ${cy.toFixed(1)}`;
            penDown = true;
          } else {
            d += ` H ${cx.toFixed(1)} V ${cy.toFixed(1)}`;
          }
        }
        if (!d) return "";
        return `<path d="${d}" fill="none" stroke="${colorOf(vendor)}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"><title>${esc(vendorLabel(vendor))}</title></path>`;
      })
      .join("");

    const legend = vendors
      .map(
        (vendor) =>
          `<span class="ph-legend-item"><span class="ph-swatch" style="background:${colorOf(vendor)}"></span>${esc(vendorLabel(vendor))}</span>`
      )
      .join("");

    const rangeOptions = [7, 14, 30, 120]
      .filter((days, i, arr) => days < dates.length || i === arr.length - 1)
      .map((days) => {
        const label =
          days >= dates.length
            ? t(lang, "historyAll")
            : `${Math.min(days, dates.length)} ${t(lang, "historyDays")}`;
        return `<option value="${days}" ${dayWindow === (days >= dates.length ? dates.length : days) ? "selected" : ""}>${esc(label)}</option>`;
      })
      .join("");

    host.hidden = false;
    host.innerHTML = `
      <div class="pdp-card-head">
        <h2 class="pdp-card-title" style="border:none; padding:0; margin:0;">${t(lang, "priceHistory")}</h2>
        <select class="sort-select ph-range" aria-label="${t(lang, "priceHistory")}">
          ${rangeOptions}
        </select>
      </div>
      <div class="ph-legend">${legend}</div>
      <svg class="ph-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${t(lang, "priceHistory")}">
        ${grid}
        ${paths}
        ${xLabels}
      </svg>
    `;

    host.querySelector(".ph-range")!.addEventListener("change", (e) => {
      const days = Number((e.target as HTMLSelectElement).value);
      dayWindow =
        Number.isFinite(days) && days > 0
          ? Math.min(days, dates.length)
          : dates.length;
      draw();
    });
  };

  draw();
}
