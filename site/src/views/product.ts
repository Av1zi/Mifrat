import { loadCategory, loadHistory } from "../api";
import { slotForCategory } from "../build";
import { formatPrice } from "../format";
import { attributeLabel, categoryLabel, t, vendorLabel } from "../i18n";
import {
  displaySpecFields,
  formatSpecValue,
  specPriority,
  specValue,
  VARIANT_IDENTITY_KEYS,
  VARIANT_KEY_PRIORITY,
} from "../specs";
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
import type { Currency, Lang, Product, SpecValue } from "../types";
import { displayName, errorPanel, esc, safeImageUrl, safeUrl, skuOf } from "../utils";
import { icon } from "../icons";

/** Schema fields with no discriminating power for similarity scoring. */
const NOISE_KEYS = new Set([
  "manufacturer",
  "model",
  "part_numbers",
  "packaging",
]);

interface VariantGroup {
  key: string;
  values: Array<{ value: string; productId: string; active: boolean }>;
}

/** Lang-independent text form of a typed spec value (for comparisons). */
function rawText(value: SpecValue | undefined): string {
  if (value === undefined || value === null) return "";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function computeVariantGroups(
  product: Product,
  sameBrand: Product[]
): VariantGroup[] {
  if (sameBrand.length < 2) return [];
  // Identity gate: no variant pills without identity. A missing model —
  // or a missing category identity key (chipset/socket on boards,
  // gpu_chip on GPUs, ...) — means same-brand different-line products
  // would pose as close variants.
  if (!product.model) return [];
  const identityKeys = VARIANT_IDENTITY_KEYS[product.category] ?? [];
  for (const k of identityKeys) {
    if (!rawText(specValue(product, k))) return [];
  }
  const groups: VariantGroup[] = [];

  for (const key of VARIANT_KEY_PRIORITY) {
    // Attribute values are mixed types across vendors (850 vs "850 W"),
    // so normalize to strings before comparing, sorting, or rendering.
    const current = rawText(specValue(product, key));
    if (!current) continue;
    // Signature = brand + model + identity + everything EXCEPT the
    // candidate key: variants must be identical in all other dimensions
    // (same model line, same specs). Identity values ride along so
    // same-brand/different-chipset products can never share a signature
    // even when their priority dims are all empty. Without this a
    // "DDR4/DDR5" pill jumps across chipsets and sockets, and same-brand
    // different-line products pose as close variants.
    // Unit separator (U+0001): can never occur inside scraped attribute
    // text, so joined signatures cannot collide the way " " or "|" could.
    const SEP = "";
    const sigOf = (p: Product): string =>
      [
        p.brand ?? "",
        p.model ?? "",
        ...identityKeys.map((k) => rawText(specValue(p, k))),
        ...VARIANT_KEY_PRIORITY.filter((k) => k !== key).map((k) =>
          rawText(specValue(p, k))
        ),
      ].join(SEP);
    const mySig = sigOf(product);
    const distinct = new Map<string, Product[]>();
    for (const p of sameBrand) {
      if (sigOf(p) !== mySig) continue;
      const v = rawText(specValue(p, key));
      if (!v) continue;
      const list = distinct.get(v) ?? [];
      list.push(p);
      distinct.set(v, list);
    }
    if (distinct.size < 2 || distinct.size > 8) continue;

    // Belt-and-braces: a color pill must never span chipsets
    // (same-brand different-line boards could otherwise share a
    // signature when identity dims are missing upstream). Skip color
    // groups whose members carry >1 distinct chipset.
    if (key === "color") {
      const chips = new Set<string>();
      for (const owners of distinct.values()) {
        for (const p of owners) {
          const chip = rawText(specValue(p, "chipset"));
          if (chip) chips.add(chip);
        }
      }
      if (chips.size > 1) continue;
    }

    const values = Array.from(distinct.entries()).map(([value, owners]) => {
      // Prefer the owner sharing the most attribute values with current.
      let best = owners[0];
      let bestScore = -1;
      for (const cand of owners) {
        let score = 0;
        for (const k of [...VARIANT_KEY_PRIORITY, ...identityKeys]) {
          if (NOISE_KEYS.has(k)) continue;
          if (rawText(specValue(cand, k)) === rawText(specValue(product, k))) score++;
        }
        if (score > bestScore) {
          bestScore = score;
          best = cand;
        }
      }
      return { value, productId: best.id, active: value === current };
    });

    // Stable order, value-only: the active pill keeps its position when
    // navigating between variants (clicking DDR5 must not swap it with
    // the DDR4 pill). Active is only a marker, never a sort key.
    // Explicit locale for determinism across browsers.
    values.sort((a, b) =>
      a.value.localeCompare(b.value, "en", { numeric: true })
    );
    groups.push({ key, values });
    if (groups.length >= 4) break;
  }

  return groups;
}

function similarProducts(product: Product, all: Product[]): Product[] {
  // Score only curated spec keys: shared trivia rows (motherboards carry
  // hundreds of attribute keys) used to fill all 8 slots with unrelated
  // items. Identity keys weigh triple so same-chipset/socket/chip parts
  // surface first.
  const priority = specPriority(product.category);
  const identity = new Set<string>(
    VARIANT_IDENTITY_KEYS[product.category] ?? []
  );
  const scored: Array<{ p: Product; score: number }> = [];
  for (const p of all) {
    if (p.id === product.id) continue;
    let score = 0;
    if (p.brand && product.brand && p.brand === product.brand) score += 5;
    for (const k of priority) {
      if (NOISE_KEYS.has(k)) continue;
      const value = rawText(specValue(product, k));
      if (value !== "" && rawText(specValue(p, k)) === value) {
        score += identity.has(k) ? 3 : 1;
      }
    }
    scored.push({ p, score });
  }
  scored.sort(
    (a, b) =>
      b.score - a.score || (a.p.min_price ?? Infinity) - (b.p.min_price ?? Infinity)
  );
  // Min-score threshold: unrelated items must not fill all 8 slots.
  const relevant = scored.filter((s) => s.score >= 6);
  return relevant.slice(0, 8).map((s) => s.p);
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
      <div class="crumbs"><a href="${homeHash()}">${icon("arrow-right", 14)} ${t(lang, "backToCategories")}</a></div>
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

  // Typed spec sheet (scraper/specs/): render the schema's own field order.
  // Every schema field is present by construction; `null` (nothing any source
  // could supply) renders as a muted "Unknown". Reference-dataset values are
  // merged upstream at Tier 0, so there is no separate reference sidebox.
  const specRows = displaySpecFields(product.category)
    .map((field) => {
      const text = formatSpecValue(specValue(product, field.name), lang);
      return `<div class="spec-row"><span class="spec-key">${esc(
        attributeLabel(field.name, lang)
      )}</span><span class="${text ? "spec-val" : "spec-val is-unknown"}">${esc(
        text || t(lang, "unknownValue")
      )}</span></div>`;
    })
    .join("");

  const variantHtml = variantGroups
    .map(
      (g) => `
      <div class="variant-group">
        <h3>${esc(attributeLabel(g.key, lang))}: ${esc(formatSpecValue(specValue(product, g.key), lang))}</h3>
        <div class="variant-pills">
          ${g.values
            .map((v) =>
              v.active
                ? `<button type="button" class="variant-pill active" aria-current="true" data-variant="${esc(v.productId)}">${esc(v.value)}</button>`
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
      const buyUrl = safeUrl(offer.url);
      const buyCell = buyUrl
        ? `<a class="offer-link" href="${esc(buyUrl)}" target="_blank" rel="noopener noreferrer">${t(lang, "buyLabel")}</a>`
        : `<span class="dim">-</span>`;
      return `
      <tr class="${offer.in_stock ? "" : "is-out"}">
        <td class="pt-merchant">${esc(vendorLabel(offer.vendor))}</td>
        <td class="pt-num">${offer.price === null ? "-" : esc(formatPrice(offer.price, currency, lang))}</td>
        <td class="pt-ship">${shipping}</td>
        <td class="pt-avail"><span class="status-dot ${offer.in_stock ? "in" : "out"}"></span>${offer.in_stock ? t(lang, "inStock") : t(lang, "outOfStock")}${stale}</td>
        <td class="pt-total">${offer.price === null ? "-" : esc(formatPrice(total, currency, lang))}</td>
        <td class="pt-buy">${buyCell}</td>
      </tr>`;
    })
    .join("");

  const mainImg = safeImageUrl(product.image);
  const imageHtml = mainImg
    ? `<img class="pdp-image" src="${esc(mainImg)}" alt="${esc(name)}" loading="eager" fetchpriority="high" width="600" height="600" style="object-fit:contain;background:transparent;">`
    : `<div class="thumb thumb-lg" aria-hidden="true">${esc((product.brand ?? name).slice(0, 2).toUpperCase())}</div>`;

  const similarHtml = similar
    .map((p) => {
      const simImg = safeImageUrl(p.image);
      return `
      <a class="pdp-similar-card" href="${productHash(p.category, p.id)}">
        ${simImg ? `<img src="${esc(simImg)}" alt="${esc(displayName(p))}" loading="lazy" width="200" height="200" style="object-fit:contain;background:transparent;">` : `<span class="plThumb" aria-hidden="true">${esc((p.brand ?? p.name).slice(0, 2).toUpperCase())}</span>`}
        <span class="pdp-similar-name">${esc(displayName(p))}</span>
        <span class="pdp-similar-price">${p.min_price === null ? "-" : esc(formatPrice(p.min_price, currency, lang))}</span>
      </a>`;
    })
    .join("");

  container.innerHTML = `
    <div class="crumbs">
      <a href="${homeHash()}">${icon("arrow-right", 14)} ${t(lang, "backToCategories")}</a>
      &nbsp;·&nbsp;
      <a href="${categoryHash(category)}">${esc(categoryLabel(category, lang))}</a>
    </div>

    <div class="title-band title-band--product">
      <div class="title-band-eyebrow">${esc(categoryLabel(category, lang))}</div>
      <h1>${esc(name)}</h1>
      ${product.description ? `<p class="pdp-desc">${esc(product.description)}</p>` : ""}
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
        </div>
      </aside>

      <div class="pdp-main">
        <div class="pdp-card">
          <h2 class="pdp-card-title">${t(lang, "pricesHeading")}</h2>
          <div class="price-table-wrap">
            <table class="price-table">
              <thead>
                <tr>
                  <th scope="col">${t(lang, "merchantHeading")}</th>
                  <th scope="col">${t(lang, "baseHeading")}</th>
                  <th scope="col">${t(lang, "shippingHeading")}</th>
                  <th scope="col">${t(lang, "availability")}</th>
                  <th scope="col">${t(lang, "totalHeading")}</th>
                  <th scope="col"><span class="visually-hidden">${esc(t(lang, "buyHeaderLabel"))}</span><span aria-hidden="true"></span></th>
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

let historyResizeObserver: ResizeObserver | null = null;

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
  const timestamps = Array.isArray(file.timestamps) ? file.timestamps : [];
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

  const locale = lang === "he" ? "he-IL" : "en-GB";
  const shortDate = (iso: string): string => {
    const d = new Date(iso);
    if (!Number.isNaN(d.getTime()))
      return new Intl.DateTimeFormat(locale, { day: "numeric", month: "numeric" }).format(d);
    const parts = iso.split("-");
    return parts.length === 3 ? `${parts[2]}.${parts[1]}` : iso;
  };

  let lastDrawnWidth = 0;
  const draw = (restoreFocusId?: string): void => {
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
    // Keep enough breathing room around spikes so normal price changes remain
    // readable instead of filling the entire plot.
    const pad = Math.max((hi - lo) * 0.22, 5);
    lo = Math.max(0, lo - pad);
    hi = hi + pad;

    // Match the viewBox to the card's real pixel width so 1 SVG user-unit
    // stays ~1 CSS pixel. Previously this was a fixed 1000x320 viewBox
    // stretched to fill much wider cards via CSS width:100% — the browser
    // scales everything inside proportionally, including CSS font-size,
    // which is why the axis labels rendered oversized on wide screens.
    const measuredWidth =
      host.clientWidth > 0
        ? host.clientWidth
        : Math.max(320, (host.parentElement?.clientWidth ?? 940) - 44);
    const W = Math.max(320, Math.min(1400, Math.round(measuredWidth)));
    const H = Math.max(200, Math.min(340, Math.round(W * 0.32)));
    const L = 88;
    const R = 18;
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

    const rangeDefs = [7, 14, 30, 120].filter(
      (days, i, arr) => days < dates.length || i === arr.length - 1
    );
    const singleAll = rangeDefs.length === 1 && rangeDefs[0] >= dates.length;
    const rangeOptions = rangeDefs
      .map((days) => {
        const label =
          days >= dates.length
            ? t(lang, "historyAll")
            : `${Math.min(days, dates.length)} ${t(lang, "historyDays")}`;
        return `<option value="${days}" ${dayWindow === (days >= dates.length ? dates.length : days) ? "selected" : ""}>${esc(label)}</option>`;
      })
      .join("");
    const rangeControl = singleAll
      ? `<span class="parts-count">${esc(t(lang, "historyAll"))}</span>`
      : `<label class="visually-hidden" for="ph-range-select">${esc(t(lang, "priceHistory"))}</label><select class="sort-select ph-range" id="ph-range-select">${rangeOptions}</select>`;

    // Preserve focus across redraws (range select keeps keyboard context).
    const activeId =
      restoreFocusId ??
      (host.contains(document.activeElement)
        ? (document.activeElement as HTMLElement).id || ""
        : "");
    host.hidden = false;
    host.innerHTML = `
      <div class="pdp-card-head">
        <h2 class="pdp-card-title pdp-card-title--plain">${t(lang, "priceHistory")}</h2>
        ${rangeControl}
      </div>
      <div class="ph-legend">${legend}</div>
      <div class="ph-wrap">
        <svg class="ph-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(t(lang, "priceHistory"))}" tabindex="0">
          ${grid}
          ${paths}
          <line class="ph-cross" y1="${T}" y2="${H - B}" visibility="hidden" />
          ${xLabels}
        </svg>
        <div class="ph-tip" hidden></div>
      </div>
    `;
    if (activeId) {
      const el = host.querySelector<HTMLElement>(`#${activeId}`);
      if (el) el.focus({ preventScroll: true });
    }
    lastDrawnWidth = W;

    const wrap = host.querySelector(".ph-wrap") as HTMLElement;
    const svg = wrap.querySelector(".ph-chart") as SVGSVGElement;
    const tip = wrap.querySelector(".ph-tip") as HTMLElement;
    const cross = svg.querySelector(".ph-cross") as SVGLineElement;
    const series = vendors.map((v) => entry.v[v].slice(start, end));
    const fmtDay = (index: number): string => {
      const raw = timestamps[start + index] ?? visDates[index];
      const d = new Date(raw);
      if (!Number.isNaN(d.getTime()))
        return new Intl.DateTimeFormat(locale, { day: "numeric", month: "numeric", year: "numeric" }).format(d);
      return shortDate(visDates[index]);
    };
    let focusIdx = n - 1;
    const showAt = (best: number, anchorX?: number, anchorY?: number): void => {
      const rows = vendors
        .map((vendor, vi) => ({ vendor, price: series[vi][best] as number | null }))
        .filter((r) => r.price !== null && r.price !== undefined);
      if (rows.length === 0) {
        tip.hidden = true;
        cross.setAttribute("visibility", "hidden");
        return;
      }
      const cheapest = Math.min(...rows.map((r) => r.price as number));
      cross.setAttribute("visibility", "visible");
      cross.setAttribute("x1", x(best).toFixed(1));
      cross.setAttribute("x2", x(best).toFixed(1));
      tip.innerHTML =
        `<div class="ph-tip-date">${esc(fmtDay(best))}</div>` +
        rows
          .map(({ vendor, price }) => {
            const vi = vendors.indexOf(vendor);
            return `<div class="ph-tip-row${(price as number) === cheapest ? " cheapest" : ""}"><span class="ph-tip-swatch" style="background:${HISTORY_COLORS[vi % HISTORY_COLORS.length]}"></span><span class="ph-tip-vendor">${esc(vendorLabel(vendor))}</span><span class="ph-tip-price">${esc(formatPrice(price as number, currency, lang))}</span></div>`;
          })
          .join("");
      tip.hidden = false;
      const wrapRect = wrap.getBoundingClientRect();
      let lx: number;
      let ly: number;
      if (anchorX !== undefined && anchorY !== undefined) {
        lx = anchorX - wrapRect.left + 14;
        ly = anchorY - wrapRect.top - 10;
      } else {
        const r = svg.getBoundingClientRect();
        lx = ((x(best) / W) * r.width) / (r.width / wrapRect.width);
        lx = (x(best) / W) * wrapRect.width;
        ly = 20;
      }
      tip.style.visibility = "hidden";
      tip.style.left = "0px";
      const tw = tip.offsetWidth;
      const th = tip.offsetHeight;
      if (anchorX !== undefined) {
        if (lx + tw + 8 > wrapRect.width) lx = anchorX - wrapRect.left - tw - 14;
      } else if (lx + tw + 8 > wrapRect.width) {
        lx = lx - tw - 28;
      }
      ly = Math.max(4, Math.min(ly, wrapRect.height - th - 4));
      tip.style.left = `${lx}px`;
      tip.style.top = `${ly}px`;
      tip.style.visibility = "";
    };
    svg.addEventListener("mousemove", (e) => {
      const rect = svg.getBoundingClientRect();
      const px = ((e.clientX - rect.left) / rect.width) * W;
      let best = 0;
      let bestDist = Infinity;
      for (let i = 0; i < n; i++) {
        const d = Math.abs(x(i) - px);
        if (d < bestDist) { bestDist = d; best = i; }
      }
      focusIdx = best;
      showAt(best, e.clientX, e.clientY);
    });
    svg.addEventListener("mouseleave", () => {
      tip.hidden = true;
      cross.setAttribute("visibility", "hidden");
    });
    // Touch + keyboard: focus the chart and arrow through points.
    svg.addEventListener("touchstart", (e) => {
      const touch = e.touches[0];
      if (!touch) return;
      const rect = svg.getBoundingClientRect();
      const px = ((touch.clientX - rect.left) / rect.width) * W;
      let best = 0;
      let bestDist = Infinity;
      for (let i = 0; i < n; i++) {
        const d = Math.abs(x(i) - px);
        if (d < bestDist) { bestDist = d; best = i; }
      }
      focusIdx = best;
      showAt(best, touch.clientX, touch.clientY);
    }, { passive: true });
    svg.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight" && e.key !== "Home" && e.key !== "End") return;
      e.preventDefault();
      if (e.key === "ArrowLeft") focusIdx = Math.max(0, focusIdx - 1);
      else if (e.key === "ArrowRight") focusIdx = Math.min(n - 1, focusIdx + 1);
      else if (e.key === "Home") focusIdx = 0;
      else focusIdx = n - 1;
      showAt(focusIdx);
    });
    svg.addEventListener("blur", () => {
      tip.hidden = true;
      cross.setAttribute("visibility", "hidden");
    });

    host.querySelector(".ph-range")?.addEventListener("change", (e) => {
      const days = Number((e.target as HTMLSelectElement).value);
      dayWindow =
        Number.isFinite(days) && days > 0
          ? Math.min(days, dates.length)
          : dates.length;
      draw("ph-range-select");
    });
  };

  // Redraw when the card's width changes (window resize, sidebar
  // collapse, etc.) so the chart stays sized to real pixels — see the
  // measuredWidth comment above. Guarded by width so draws don't loop.
  historyResizeObserver?.disconnect();
  if (typeof ResizeObserver !== "undefined" && host.parentElement) {
    let pending = false;
    historyResizeObserver = new ResizeObserver(() => {
      if (pending) return;
      const w = host.clientWidth || 0;
      if (Math.abs(w - lastDrawnWidth) < 24) return;
      pending = true;
      requestAnimationFrame(() => {
        pending = false;
        const w2 = host.clientWidth || 0;
        if (Math.abs(w2 - lastDrawnWidth) < 24) return;
        draw(document.activeElement?.id);
      });
    });
    historyResizeObserver.observe(host.parentElement);
  }

  draw();
}