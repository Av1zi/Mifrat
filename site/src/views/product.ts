import { loadCategory } from "../api";
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
import { displayName, esc, skuOf } from "../utils";

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

function computeVariantGroups(
  product: Product,
  sameBrand: Product[]
): VariantGroup[] {
  if (sameBrand.length < 2) return [];
  const groups: VariantGroup[] = [];

  for (const key of VARIANT_KEY_PRIORITY) {
    const current = product.attributes[key];
    if (!current) continue;
    const distinct = new Map<string, Product[]>();
    for (const p of sameBrand) {
      const v = p.attributes[key];
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
          if (cand.attributes[k] === v) score++;
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
  } catch {
    container.innerHTML = `<div class="empty-state">${t(lang, "loadError")}</div>`;
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
}
