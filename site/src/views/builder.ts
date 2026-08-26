import { loadCategory } from "../api";
import {
  BUILD_SLOTS,
  checkCompatibility,
  estimateWattage,
  type BuildSlot,
} from "../build";
import { formatPrice } from "../format";
import { t, vendorLabel } from "../i18n";
import {
  buildHash,
  categoryHash,
  getStoredBuild,
  replaceRoute,
  setStoredBuild,
} from "../state";
import type { Currency, Lang, Offer, Product } from "../types";
import { displayName, esc } from "../utils";
import { closeDetail } from "./detail";

export async function renderBuilder(
  container: HTMLElement,
  lang: Lang,
  currency: Currency,
  shared: Record<string, string> | null
): Promise<void> {
  closeDetail();

  const validSlots = new Set(BUILD_SLOTS.map((slot) => slot.id));

  const build: Record<string, string> = {};
  const source = shared ?? getStoredBuild();

  for (const [slotId, productId] of Object.entries(source)) {
    if (validSlots.has(slotId) && productId) {
      build[slotId] = productId;
    }
  }

  if (shared) {
    setStoredBuild(build);
  }

  const parts = new Map<
    string,
    {
      product: Product;
      slot: BuildSlot;
    }
  >();

  container.innerHTML = `<div class="empty-state">${t(lang, "loading")}</div>`;

  async function refreshParts(): Promise<void> {
    const next = new Map<
      string,
      {
        product: Product;
        slot: BuildSlot;
      }
    >();

    const invalidSlots: string[] = [];

    await Promise.all(
      BUILD_SLOTS.map(async (slot) => {
        const productId = build[slot.id];
        if (!productId) return;

        for (const category of slot.categories) {
          try {
            const products = await loadCategory(category);
            const found = products.find((p) => p.id === productId);

            if (found) {
              next.set(slot.id, {
                product: found,
                slot,
              });

              return;
            }
          } catch {
            // Try next category.
          }
        }

        invalidSlots.push(slot.id);
      })
    );

    if (invalidSlots.length > 0) {
      for (const slotId of invalidSlots) {
        delete build[slotId];
      }

      persist();
    }

    parts.clear();

    for (const [slotId, entry] of next.entries()) {
      parts.set(slotId, entry);
    }
  }

  function persist(): void {
    setStoredBuild(build);
    replaceRoute(buildHash(build));
  }

  function bestOffer(product: Product): Offer | null {
    const offers = product.offers ?? [];

    const priced = offers.filter((offer) => typeof offer.price === "number");
    if (priced.length === 0) return null;

    const inStock = priced.filter((offer) => offer.in_stock);
    const pool = inStock.length > 0 ? inStock : priced;

    return (
      pool.slice().sort((a, b) => (a.price ?? 0) - (b.price ?? 0))[0] ?? null
    );
  }

  function effectivePrice(product: Product): number | null {
    return bestOffer(product)?.price ?? product.min_price;
  }

  function chooseUrl(slot: BuildSlot): string {
    return categoryHash(slot.categories[0], {
      pick: slot.id,
    });
  }

  function rowHtml(slot: BuildSlot): string {
    const entry = parts.get(slot.id);

    if (!entry) {
      return `
        <div class="build-row">
          <div class="bh-cell bs-slot">${esc(slot.label[lang])}</div>

          <div class="bh-cell bs-selection">
            <a class="btn-choose" href="${chooseUrl(slot)}">
              ${esc(slot.choose[lang])}
            </a>
          </div>

          <div class="bh-cell bs-price">—</div>
          <div class="bh-cell bs-stock"></div>
          <div class="bh-cell bs-buy"></div>
        </div>
      `;
    }

    const product = entry.product;
    const offer = bestOffer(product);
    const price = effectivePrice(product);

    const buyHtml = offer
      ? `
          <a
            class="offer-link"
            href="${esc(offer.url)}"
            target="_blank"
            rel="noopener noreferrer"
          >
            ${esc(vendorLabel(offer.vendor))}
          </a>
        `
      : `<span>—</span>`;

    return `
      <div class="build-row">
        <div class="bh-cell bs-slot">${esc(slot.label[lang])}</div>

        <div class="bh-cell bs-selection">
          <div class="bs-part">
            <div class="bs-part-name">${esc(displayName(product))}</div>
            ${
              product.brand
                ? `<div class="bs-part-brand">${esc(product.brand)}</div>`
                : ""
            }
          </div>

          <div class="bs-actions">
            <a class="btn-small" href="${chooseUrl(slot)}">
              ${lang === "he" ? "החלפה" : "Change"}
            </a>

            <button
              class="bs-remove"
              type="button"
              data-action="remove"
              data-slot="${esc(slot.id)}"
              aria-label="${esc(t(lang, "removePart"))}"
            >
              ✕
            </button>
          </div>
        </div>

        <div class="bh-cell bs-price">
          ${price === null ? "—" : esc(formatPrice(price, currency, lang))}
        </div>

        <div class="bh-cell bs-stock">
          <span class="status-dot ${product.in_stock ? "in" : "out"}"></span>
          ${product.in_stock ? t(lang, "inStock") : t(lang, "outOfStock")}
        </div>

        <div class="bh-cell bs-buy">${buyHtml}</div>
      </div>
    `;
  }

  function render(): void {
    const records: Record<string, Product> = {};

    for (const [slotId, entry] of parts.entries()) {
      records[slotId] = entry.product;
    }

    const estWatts = estimateWattage(records);
    const issues = checkCompatibility(records, estWatts, lang);
    const hasParts = parts.size > 0;

    const total = Array.from(parts.values()).reduce((sum, entry) => {
      return sum + (effectivePrice(entry.product) ?? 0);
    }, 0);

    const shareUrl = `${location.origin}${location.pathname}${buildHash(build)}`;

    const compatibility = !hasParts
      ? `<div class="compat-banner idle">${t(lang, "compatibilityIdle")}</div>`
      : issues.length > 0
        ? `<div class="compat-banner bad">⚠ ${esc(issues.join(" · "))}</div>`
        : `<div class="compat-banner ok">✓ ${t(lang, "compatibilityOk")}</div>`;

    const wattage =
      estWatts > 0
        ? `
            <div class="watt-badge">
              ⚡ ${t(lang, "estimatedWattage")} ${estWatts}W
            </div>
          `
        : "";

    const rows = BUILD_SLOTS.map((slot) => rowHtml(slot)).join("");

    container.innerHTML = `
      <div class="hero build-hero">
        <h1>${t(lang, "builderTitle")}</h1>
      </div>

      <div class="build-share">
        <input
          class="share-input"
          id="builder-share-link"
          type="text"
          readonly
          dir="ltr"
          value="${esc(shareUrl)}"
        />

        <button
          class="btn-primary"
          id="builder-copy-link"
          type="button"
        >
          ${t(lang, "copyLink")}
        </button>
      </div>

      <div class="compat-row">
        ${compatibility}
        ${wattage}
      </div>

      <div class="build-table">
        <div class="build-head">
          <div class="bh-cell">${t(lang, "componentHeading")}</div>
          <div class="bh-cell">${t(lang, "selectionHeading")}</div>
          <div class="bh-cell">${t(lang, "priceHeading")}</div>
          <div class="bh-cell">${t(lang, "availability")}</div>
          <div class="bh-cell"></div>
        </div>

        ${rows}
      </div>

      <div class="build-total">
        <span>${t(lang, "totalLabel")}</span>
        <strong>${esc(formatPrice(total, currency, lang))}</strong>
      </div>
    `;

    const copyButton =
      container.querySelector<HTMLButtonElement>("#builder-copy-link");

    const shareInput =
      container.querySelector<HTMLInputElement>("#builder-share-link");

    if (copyButton && shareInput) {
      copyButton.addEventListener("click", () => {
        shareInput.select();

        const done = () => {
          copyButton.textContent = t(lang, "copied");

          window.setTimeout(() => {
            copyButton.textContent = t(lang, "copyLink");
          }, 1200);
        };

        if (
          navigator.clipboard &&
          typeof navigator.clipboard.writeText === "function"
        ) {
          navigator.clipboard
            .writeText(shareInput.value)
            .then(done)
            .catch(done);
        } else {
          done();
        }
      });
    }

    container
      .querySelectorAll<HTMLElement>("[data-action='remove']")
      .forEach((button) => {
        button.addEventListener("click", () => {
          const slotId = button.dataset.slot;
          if (!slotId) return;

          delete build[slotId];

          persist();

          void refreshParts().then(() => {
            render();
          });
        });
      });
  }

  await refreshParts();
  render();
}