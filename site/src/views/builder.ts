// src/views/builder.ts
import { loadCategory } from "../api";
import { BUILD_SLOTS, checkCompatibility, estimateWattage, type BuildSlot } from "../build";
import { formatPrice, canConvertToUsd } from "../format";
import { t, vendorLabel, categoryLabel } from "../i18n";
import { buildHash, getStoredBuild, replaceRoute, setStoredBuild } from "../state";
import type { Currency, Lang, Offer, Product } from "../types";
import { displayName, esc, skuOf } from "../utils";
import { closeDetail } from "./detail";

// ============================================================================
//  State for merchant preferences per part (stored in localStorage)
// ============================================================================

const MERCHANT_PREF_KEY = "mifrat:merchant_prefs";

type MerchantPrefs = Record<string, { merchant: string; customPrice: number | null }>;

function getMerchantPrefs(): MerchantPrefs {
  try {
    const raw = localStorage.getItem(MERCHANT_PREF_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function setMerchantPrefs(prefs: MerchantPrefs): void {
  localStorage.setItem(MERCHANT_PREF_KEY, JSON.stringify(prefs));
}

// ============================================================================
//  Helper: get the best offer for a product, optionally preferring a merchant
// ============================================================================

function getBestOffer(product: Product, preferredMerchant?: string): Offer | null {
  // filter to in-stock with price
  let candidates = product.offers.filter(o => o.in_stock && o.price !== null);
  if (candidates.length === 0) {
    // fallback: any offer with price (even out of stock)
    candidates = product.offers.filter(o => o.price !== null);
  }
  if (candidates.length === 0) return null;

  // if preferred merchant is given and has an offer, use it
  if (preferredMerchant) {
    const pref = candidates.find(o => o.vendor === preferredMerchant);
    if (pref) return pref;
  }

  // otherwise cheapest
  return candidates.reduce((a, b) => (a.price! < b.price! ? a : b));
}

// ============================================================================
//  Main render function
// ============================================================================

export async function renderBuilder(
  container: HTMLElement,
  lang: Lang,
  currency: Currency,
  shared: Record<string, string> | null
): Promise<void> {
  closeDetail();

  const validSlots = new Set(BUILD_SLOTS.map(s => s.id));
  let buildIds: Record<string, string> = Object.fromEntries(
    Object.entries(shared ?? getStoredBuild())
      .filter(([k, v]) => validSlots.has(k) && typeof v === "string" && v)
  );
  let parts: Record<string, Product> = {};
  let merchantPrefs = getMerchantPrefs();

  // We'll store per-slot selected offer (merchant) and custom price
  // We'll also keep a set of products for storage slots to allow multiple.

  // For storage, we allow multiple items. We'll treat it as an array in buildIds?
  // We'll keep it simple: only one storage for now, but we can extend later.
  // The PCPP builder has "Add Additional Storage" – we'll implement that later.

  container.innerHTML = `<div class="empty-state">${t(lang, "loading")}</div>`;

  const slotById = (id: string): BuildSlot => BUILD_SLOTS.find(s => s.id === id)!;

  // ----- helper to get offer for a slot -----
  function getOfferForSlot(slotId: string): Offer | null {
    const product = parts[slotId];
    if (!product) return null;
    const prefs = merchantPrefs[slotId];
    const preferredMerchant = prefs?.merchant || null;
    const offer = getBestOffer(product, preferredMerchant || undefined);
    return offer;
  }

  // ----- render the table -----
  function render(): void {
    const estWatts = estimateWattage(parts);
    const issues = checkCompatibility(parts, estWatts, lang);
    const hasParts = Object.keys(parts).length > 0;
    const total = Object.values(parts).reduce((sum, p) => sum + (p.min_price ?? 0), 0);
    const shareUrl = location.origin + location.pathname + buildHash(buildIds);

    // Build rows for each slot
    const rowsHtml = BUILD_SLOTS.map(slot => {
      const product = parts[slot.id];
      const offer = product ? getOfferForSlot(slot.id) : null;
      const isStorage = slot.id === "storage"; // we'll handle extra later

      if (!product) {
        // Empty slot: show "Choose A ..." button
        return `
          <tr class="tr__product">
            <td class="td__component">${esc(slot.label[lang])}</td>
            <td class="td__placement--empty"></td>
            <td class="td__addComponent" colspan="14">
              <a href="#/c/${slot.categories[0]}" class="button button--icon button--small choose-part" data-slot="${slot.id}">
                <svg class="icon shape-add"><use xlink:href="#shape-add"></use></svg>
                + ${esc(slot.choose[lang])}
              </a>
            </td>
          </tr>
        `;
      }

      // Build the row for a filled slot
      const img = product.attributes.image || ""; // placeholder if we have image
      const name = displayName(product);
      const brand = product.brand || "";
      const basePrice = offer?.price ?? null;
      // shipping not in data – show FREE
      const shipping = null;
      const tax = 0; // not in data
      const availability = product.in_stock ? t(lang, "inStock") : t(lang, "outOfStock");
      const totalPrice = basePrice; // we'll add shipping+tax later if we have them

      // Merchant info
      const merchant = offer ? vendorLabel(offer.vendor) : "";
      const merchantLogo = offer ? `/img/merchants/${offer.vendor}.png` : ""; // placeholder
      const buyUrl = offer?.url || "#";

      // Determine if we have a custom price override
      const prefs = merchantPrefs[slot.id];
      const customPrice = prefs?.customPrice ?? null;
      const displayedPrice = customPrice !== null ? customPrice : totalPrice;

      return `
        <tr class="tr__product" data-slot="${slot.id}">
          <td class="td__component">${esc(slot.label[lang])}</td>
          <td class="td__placement--empty"></td>
          <td class="td__image">
            ${img ? `<img src="${esc(img)}" alt="${esc(name)}" />` : ""}
          </td>
          <td class="td__name">
            <a href="#/c/${slot.categories[0]}?p=${encodeURIComponent(product.id)}">${esc(name)}</a>
            ${brand ? `<div class="td__brand">${esc(brand)}</div>` : ""}
          </td>
          <td class="td__base"><h6 class="xs-block md-hide">Base</h6>${basePrice !== null ? formatPrice(basePrice, currency, lang) : "—"}</td>
          <td class="td__promo td--empty"><h6 class="xs-block md-hide">Promo</h6></td>
          <td class="td__shipping"><h6 class="xs-block md-hide">Shipping</h6>FREE</td>
          <td class="td__tax td--empty"><h6 class="xs-block md-hide">Tax</h6></td>
          <td class="td__availability ${product.in_stock ? "td__availability--inStock" : "td__availability--outOfStock"}">
            <h6 class="xs-block md-hide">Availability</h6>${availability}
          </td>
          <td class="td__price">
            <h6 class="xs-block md-hide">Price</h6>
            ${displayedPrice !== null ? formatPrice(displayedPrice, currency, lang) : "—"}
          </td>
          <td class="td__where">
            <h6 class="xs-block md-hide">Where</h6>
            ${offer ? `<a href="${esc(buyUrl)}" target="_blank" rel="nofollow"><img src="${esc(merchantLogo)}" alt="${esc(merchant)}" /></a>` : ""}
          </td>
          <td class="td__buy">
            ${offer ? `<a href="${esc(buyUrl)}" target="_blank" rel="nofollow" class="button button--small button--success">Buy</a>` : ""}
          </td>
          <td class="td__settingsButton">
            <a href="#" class="button button--secondary button--neutral button--icon button--small configure-part" data-slot="${slot.id}">
              <svg class="icon shape-settings"><use xlink:href="#shape-settings"></use></svg>
              Configure
            </a>
          </td>
          <td class="td__removeButton">
            <a href="#" class="button button--secondary button--icon button--neutral button--small remove-part" data-slot="${slot.id}">
              <svg class="icon shape-delete"><use xlink:href="#shape-delete"></use></svg>
              Remove
            </a>
          </td>
          <td class="td__remove">
            <a href="#" class="remove-part" data-slot="${slot.id}">
              <svg class="icon shape-delete"><use xlink:href="#shape-delete"></use></svg>
            </a>
          </td>
        </tr>
      `;
    }).join("");

    // Add "Add Additional Storage" row after storage if storage is present
    const storageRow = (() => {
      if (!parts.storage) return "";
      return `
        <tr class="tr__product tr__product--another">
          <td class="td__addBlank"></td>
          <td></td>
          <td class="td__addComponent" colspan="14">
            <a href="#/c/storage" class="button button--icon button--small choose-part" data-slot="storage_extra">
              <svg class="icon shape-add"><use xlink:href="#shape-add"></use></svg>
              Add Additional Storage
            </a>
          </td>
        </tr>
      `;
    })();

    // Total row
    const totalRow = `
      <tr class="tr__total tr__total--final">
        <td class="td__label" colspan="10">Total:</td>
        <td class="td__price">${formatPrice(total, currency, lang)}</td>
        <td colspan="5"></td>
      </tr>
    `;

    // Compatibility notes
    let compatHtml = "";
    if (hasParts) {
      if (issues.length) {
        compatHtml = `<div class="compat-banner bad">⚠ ${esc(issues.join(" · "))}</div>`;
      } else {
        compatHtml = `<div class="compat-banner ok">✓ ${t(lang, "compatibilityOk")}</div>`;
      }
    } else {
      compatHtml = `<div class="compat-banner idle">${t(lang, "compatibilityIdle")}</div>`;
    }

    // Estimated wattage
    const wattHtml = estWatts > 0 ? `<div class="watt-badge">⚡ ${t(lang, "estimatedWattage")} ${estWatts}W</div>` : "";

    // Build full HTML
    container.innerHTML = `
      <div class="hero build-hero"><h1>${t(lang, "builderTitle")}</h1></div>
      <div class="build-share">
        <input class="share-input" id="share-link" type="text" readonly dir="ltr" value="${esc(shareUrl)}" />
        <button class="btn-primary" id="copy-link" type="button">${t(lang, "copyLink")}</button>
      </div>
      <div class="compat-row">
        ${compatHtml}
        ${wattHtml}
      </div>
      <div class="block partlist partlist--edit partlist--edit-2025 clearfix">
        <table class="xs-col-12">
          <thead>
            <tr>
              <th class="th__component">Component</th>
              <th></th>
              <th class="th__image">Image</th>
              <th class="th__selection">Selection</th>
              <th class="th__base">Base</th>
              <th class="th__promo">Promo</th>
              <th class="th__shipping">Shipping</th>
              <th class="th__tax">Tax</th>
              <th class="th__availability">Availability</th>
              <th class="th__price">Price</th>
              <th class="th__where">Where</th>
              <th class="th__buy"></th>
              <th class="th__settingsButton"></th>
              <th class="th__removeButton"></th>
              <th class="th__remove"></th>
            </tr>
          </thead>
          <tbody>
            ${rowsHtml}
            ${storageRow}
            ${totalRow}
          </tbody>
        </table>
      </div>
    `;

    // ----- Event listeners -----
    // Choose part buttons
    container.querySelectorAll(".choose-part").forEach(el => {
      el.addEventListener("click", (e) => {
        e.preventDefault();
        const slotId = (el as HTMLElement).dataset.slot!;
        // For storage extra, we might want to open the storage category; we'll just navigate.
        // In a real implementation, we'd open a picker modal.
        // For simplicity, we'll navigate to the category page.
        const slot = BUILD_SLOTS.find(s => s.id === slotId);
        if (slot) {
          location.hash = `#/c/${slot.categories[0]}`;
        } else if (slotId === "storage_extra") {
          location.hash = "#/c/storage";
        }
      });
    });

    // Remove buttons
    container.querySelectorAll(".remove-part").forEach(el => {
      el.addEventListener("click", (e) => {
        e.preventDefault();
        const slotId = (el as HTMLElement).dataset.slot!;
        delete buildIds[slotId];
        delete merchantPrefs[slotId];
        setMerchantPrefs(merchantPrefs);
        void refresh();
      });
    });

    // Configure buttons
    container.querySelectorAll(".configure-part").forEach(el => {
      el.addEventListener("click", (e) => {
        e.preventDefault();
        const slotId = (el as HTMLElement).dataset.slot!;
        const product = parts[slotId];
        if (!product) return;
        openConfigureDialog(lang, currency, slotId, product, (newPrefs) => {
          merchantPrefs[slotId] = newPrefs;
          setMerchantPrefs(merchantPrefs);
          void refresh();
        });
      });
    });

    // Copy link
    const copyBtn = container.querySelector("#copy-link") as HTMLButtonElement;
    copyBtn.addEventListener("click", () => {
      const input = container.querySelector("#share-link") as HTMLInputElement;
      input.select();
      navigator.clipboard?.writeText(input.value).catch(() => {});
      copyBtn.textContent = t(lang, "copied");
      window.setTimeout(() => {
        copyBtn.textContent = t(lang, "copyLink");
      }, 1500);
    });
  }

  // ----- Refresh function (fetch products and re-render) -----
  async function refresh(): Promise<void> {
    setStoredBuild(buildIds);
    replaceRoute(buildHash(buildIds));
    const next: Record<string, Product> = {};
    await Promise.all(
      BUILD_SLOTS.map(async (slot) => {
        const id = buildIds[slot.id];
        if (!id) return;
        const list = await loadCategory(slot.categories[0]).catch(() => []);
        const found = list.find(p => p.id === id);
        if (found) next[slot.id] = found;
        else delete buildIds[slot.id];
      })
    );
    parts = next;
    render();
  }

  await refresh();
}

// ============================================================================
//  Configure Dialog (Modal)
// ============================================================================

function openConfigureDialog(
  lang: Lang,
  currency: Currency,
  slotId: string,
  product: Product,
  onSave: (prefs: { merchant: string; customPrice: number | null }) => void
): void {
  // Create backdrop and panel
  const backdrop = document.createElement("div");
  backdrop.className = "overlay-backdrop";
  const panel = document.createElement("div");
  panel.className = "overlay-panel";
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-modal", "true");

  // Get current prefs
  const prefs = getMerchantPrefs()[slotId] || { merchant: "", customPrice: null };

  // Build list of merchants with offers
  const offers = product.offers.filter(o => o.price !== null);
  const merchantOptions = offers.map(o => `
    <option value="${esc(o.vendor)}" ${o.vendor === prefs.merchant ? "selected" : ""}>
      ${esc(vendorLabel(o.vendor))} (${formatPrice(o.price, currency, lang)})
    </option>
  `).join("");

  panel.innerHTML = `
    <button class="overlay-close" type="button">${t(lang, "close")} ✕</button>
    <div class="overlay-title">${t(lang, "configurePrice") || "Configure Price"}</div>
    <div class="overlay-body">
      <p><strong>${esc(displayName(product))}</strong></p>
      <div class="form-group">
        <label for="merchant-select">${t(lang, "selectMerchant") || "Select Merchant"}</label>
        <select id="merchant-select" class="select">
          <option value="">${t(lang, "cheapest") || "Cheapest"}</option>
          ${merchantOptions}
        </select>
      </div>
      <div class="form-group">
        <label for="custom-price-input">${t(lang, "customPrice") || "Custom Price"}</label>
        <input id="custom-price-input" type="number" step="0.01" min="0" value="${prefs.customPrice ?? ""}" placeholder="${t(lang, "enterPrice") || "Enter price"}" />
      </div>
    </div>
    <div class="form-actions">
      <button class="btn-primary" id="save-config">${t(lang, "save") || "Save"}</button>
      <button class="btn-secondary" id="cancel-config">${t(lang, "cancel") || "Cancel"}</button>
    </div>
  `;

  backdrop.appendChild(panel);
  document.body.appendChild(backdrop);
  document.body.style.overflow = "hidden";

  const close = () => {
    document.body.style.overflow = "";
    backdrop.remove();
  };

  backdrop.addEventListener("click", (e) => {
    if (e.target === backdrop) close();
  });
  panel.querySelector("#cancel-config")!.addEventListener("click", close);
  panel.querySelector(".overlay-close")!.addEventListener("click", close);

  panel.querySelector("#save-config")!.addEventListener("click", () => {
    const merchantSelect = panel.querySelector("#merchant-select") as HTMLSelectElement;
    const customPriceInput = panel.querySelector("#custom-price-input") as HTMLInputElement;
    const merchant = merchantSelect.value;
    const customPrice = customPriceInput.value ? parseFloat(customPriceInput.value) : null;
    onSave({ merchant, customPrice });
    close();
  });
}