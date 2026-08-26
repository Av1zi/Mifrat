import { formatPrice } from "../format";
import { attributeLabel, t, vendorLabel } from "../i18n";
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

  panel.innerHTML = `
    <button class="overlay-close" type="button">${t(lang, "close")} ✕</button>
    <div class="overlay-title">${esc(displayName(product))}</div>
    <div class="overlay-brand">${esc(product.brand ?? "")}</div>
    ${sku ? `<div class="overlay-sku">SKU: ${esc(sku)}</div>` : ""}
    ${specRows ? `<table class="spec-table">${specRows}</table>` : ""}
    <h3 style="font-size:0.8rem; text-transform:uppercase; letter-spacing:0.06em; color:var(--ink-dim); margin-bottom:10px;">
      ${t(lang, "offersHeading")}
    </h3>
    ${offerRows}`;

  backdrop.appendChild(panel);
  document.body.appendChild(backdrop);
  document.body.style.overflow = "hidden";

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