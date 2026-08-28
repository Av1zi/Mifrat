import { slotForCategory } from "../build";
import { formatPrice } from "../format";
import { attributeLabel, t, vendorLabel } from "../i18n";
import { buildHash, getStoredBuild, navigate, setStoredBuild } from "../state";
import type { Currency, Lang, Product } from "../types";
import { displayName, esc, skuOf } from "../utils";

let dismiss: (() => void) | null = null;

export function closeDetail(): void {
  dismiss?.();
}

export function openDetail(lang: Lang, currency: Currency, product: Product, onClose: () => void): void {
  closeDetail();
  const backdrop = document.createElement("div");
  backdrop.className = "overlay-backdrop";
  const panel = document.createElement("div");
  panel.className = "overlay-panel";
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-modal", "true");

  const specRows = Object.entries(product.attributes)
    .filter(([, value]) => value)
    .map(([key, value]) => `<tr><td>${esc(attributeLabel(key, lang))}</td><td>${esc(value)}</td></tr>`)
    .join("");

  // Reference specs from the external pcpartdb / pckombo datasets
  // (types.ts's PcPartDbRef / PcKomboRef). These describe "a similar
  // product in an external dataset", not a fact scraped from this exact
  // vendor listing — but they're still shown in the SAME table as the
  // vendor attributes so there's one clean spec list, with a single note
  // disclaiming the external data. Keys already shown above are skipped to
  // avoid duplicate rows.
  const referenceSpecs = {
    ...(product.pcpartdb?.specs ?? {}),
    ...(product.pckombo?.specs ?? {}),
  };
  const referenceRows = Object.entries(referenceSpecs)
    .filter(([key, value]) => value !== null && value !== undefined && value !== "" && !(key in product.attributes))
    .map(([key, value]) => `<tr><td>${esc(attributeLabel(key, lang))}</td><td>${esc(value)}</td></tr>`)
    .join("");
  const hasReferenceSpecs = referenceRows.length > 0;

  const allSpecRows = specRows + referenceRows;

  const offerRows = product.offers
    .map((offer) => {
      const statusLabel = offer.in_stock ? t(lang, "inStock") : t(lang, "outOfStock");
      const stale = offer.stale ? `· <span class="tag-stale">${t(lang, "staleData")}</span>` : "";
      return `<div class="offer-row ${offer.in_stock ? "" : "is-out"}">
        <div>
          <div class="offer-vendor">${esc(vendorLabel(offer.vendor))}</div>
          <div class="offer-status">
            <span class="status-dot ${offer.in_stock ? "in" : "out"}"></span>${statusLabel}${stale}
          </div>
        </div>
        <div style="display:flex; align-items:center; gap:10px;">
          <span class="offer-price">${formatPrice(offer.price, currency, lang)}</span>
          <a class="offer-link" href="${esc(offer.url)}" target="_blank" rel="noopener noreferrer">${esc(vendorLabel(offer.vendor))}</a>
        </div>
      </div>`;
    })
    .join("");

  const sku = skuOf(product);
  const slot = slotForCategory(product.category);

  const initials = (product.brand ?? product.name).slice(0,2).toUpperCase();
  const placeholder = `<div style="width:72px; height:72px; border-radius:12px; border:1px dashed #cbd5e1; background: linear-gradient(135deg, #ecfdf5, #f0fdfa); display:grid; place-items:center; font-weight:800; color:var(--blue-dark); margin-bottom:12px;">${esc(initials)}</div>`;

  panel.innerHTML = `
    <button class="overlay-close" type="button">${t(lang, "close")} ✕</button>
    ${placeholder}
    <div class="overlay-title">${esc(displayName(product))}</div>
    <div class="overlay-brand">${esc(product.brand ?? "")}</div>
    ${sku ? `<div class="overlay-sku">SKU: ${esc(sku)}</div>` : ""}
    ${slot ? `<button class="btn-primary add-to-build" type="button">+ ${t(lang, "addToBuild")}</button>` : ""}
    ${allSpecRows ? `<table class="spec-table">${allSpecRows}</table>` : ""}
    ${hasReferenceSpecs ? `<p class="reference-note">${t(lang, product.pckombo ? "pckomboReferenceNote" : "referenceSpecsNote")}</p>` : ""}
    <h3 style="font-size:0.8rem; text-transform:uppercase; letter-spacing:0.06em; color:var(--text-dim); margin-bottom:10px;">
      ${t(lang, "offersHeading")}
    </h3>
    ${offerRows}`;

  backdrop.appendChild(panel);
  document.body.appendChild(backdrop);
  document.body.style.overflow = "hidden";

  const addBtn = panel.querySelector(".add-to-build");
  if (addBtn && slot) {
    addBtn.addEventListener("click", () => {
      const build = getStoredBuild();
      build[slot.id] = product.id;
      setStoredBuild(build);
      closeDetail();
      navigate(buildHash(build));
    });
  }

  const cleanup = () => {
    document.body.style.overflow = "";
    backdrop.remove();
    document.removeEventListener("keydown", onKeydown);
    dismiss = null;
  };

  const onKeydown = (e: KeyboardEvent) => {
    if (e.key === "Escape") onClose();
  };

  backdrop.addEventListener("click", (e) => {
    if (e.target === backdrop) onClose();
  });
  panel.querySelector(".overlay-close")!.addEventListener("click", () => onClose());
  document.addEventListener("keydown", onKeydown);
  dismiss = cleanup;
}