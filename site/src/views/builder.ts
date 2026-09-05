import { loadCategory } from "../api";
import {
  BUILD_SLOTS,
  checkCompatibility,
  estimateWattage,
  type BuildSlot,
} from "../build";
import { formatPrice } from "../format";
import { categoryLabel, t, vendorLabel } from "../i18n";
import { icon } from "../icons";
import {
  buildHash,
  buildItemCount,
  categoryHash,
  getStoredBuild,
  MULTI_SLOTS,
  productHash,
  removeFromBuild,
  replaceRoute,
  setStoredBuild,
  type BuildMap,
} from "../state";
import type { Currency, Lang, Offer, Product } from "../types";
import { displayName, esc } from "../utils";

// Categories that aren't builder slots get a trailing link row,
// like PCPP's Expansion / Peripherals / Accessories rows.
const EXTRA_CATS = [
  "case_fan",
  "cooling_other",
  "cooler_accessory",
  "fan_controller",
  "thermal_paste",
  "rgb_lighting",
  "other",
];

export async function renderBuilder(
  container: HTMLElement,
  lang: Lang,
  currency: Currency,
  shared: BuildMap | null
): Promise<void> {
  const validSlots = new Set(BUILD_SLOTS.map((slot) => slot.id));

  const build: BuildMap = {};
  const source = shared ?? getStoredBuild();

  for (const [slotId, productIds] of Object.entries(source)) {
    if (!validSlots.has(slotId)) continue;
    const ids = productIds.filter(Boolean);
    if (ids.length > 0) {
      // Single slots keep one entry even if the URL carries more.
      build[slotId] = MULTI_SLOTS.has(slotId) ? [...new Set(ids)] : [ids[0]];
    }
  }

  if (shared) {
    setStoredBuild(build);
  }

  // Resolved products per slot, in build order.
  const parts = new Map<string, Product[]>();

  container.innerHTML = `<div class="empty-state">${t(lang, "loading")}</div>`;

  async function refreshParts(): Promise<void> {
    const next = new Map<string, Product[]>();
    const pruned: BuildMap = {};

    await Promise.all(
      BUILD_SLOTS.map(async (slot) => {
        const found: Product[] = [];
        for (const productId of build[slot.id] ?? []) {
          for (const category of slot.categories) {
            try {
              const products = await loadCategory(category);
              const match = products.find((p) => p.id === productId);
              if (match) {
                found.push(match);
                break;
              }
            } catch {
              // Try next category.
            }
          }
        }
        if (found.length > 0) {
          next.set(slot.id, found);
          pruned[slot.id] = found.map((p) => p.id);
        }
      })
    );

    // Drop ids that no longer resolve (stale links, removed listings).
    for (const key of Object.keys(build)) delete build[key];
    for (const [key, ids] of Object.entries(pruned)) build[key] = ids;
    persist();

    parts.clear();
    for (const [slotId, list] of next.entries()) {
      parts.set(slotId, list);
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

  function thumbHtml(slot: BuildSlot, product?: Product): string {
    if (!product) {
      const initials = slot.id.slice(0, 3).toUpperCase();
      return `<div class="thumb" aria-hidden="true"><span>${esc(initials)}</span></div>`;
    }
    const href = productHash(product.category, product.id);
    if (product.image) {
      return `<a class="thumb has-part" href="${href}" tabindex="-1"><img src="${esc(product.image)}" alt="" loading="lazy"></a>`;
    }
    const label = (product.brand ?? product.name).slice(0, 2).toUpperCase() || "-";
    return `<a class="thumb has-part" href="${href}" tabindex="-1"><span>${esc(label)}</span></a>`;
  }

  function filledRow(
    slot: BuildSlot,
    product: Product,
    showSlotLabel: boolean
  ): string {
    const offer = bestOffer(product);
    const price = effectivePrice(product);
    const href = productHash(product.category, product.id);
    const priceHtml =
      price === null || !offer
        ? `<span class="dim">-</span>`
        : `<a class="price-link" href="${esc(offer.url)}" target="_blank" rel="noopener noreferrer">${esc(formatPrice(price, currency, lang))}</a>`;

    return `
      <div class="buildRow">
        <div class="bhCell">${
          showSlotLabel
            ? `<a class="slot-link" href="${categoryHash(slot.categories[0])}">${esc(slot.label[lang])}</a>`
            : ""
        }</div>
        <div class="bhCell">${thumbHtml(slot, product)}</div>
        <div class="bhCell">
          <a class="bs-part-name" href="${href}">${esc(displayName(product))}</a>
          ${product.brand ? `<div class="bs-part-brand">${esc(product.brand)}</div>` : ""}
        </div>
        <div class="bhCell bsBase">${price === null ? "-" : esc(formatPrice(price, currency, lang))}</div>
        <div class="bhCell bsShip"><span class="dim">-</span></div>
        <div class="bhCell bsStock">
          <span class="status-dot ${product.in_stock ? "in" : "out"}"></span>
          ${product.in_stock ? t(lang, "inStock") : t(lang, "outOfStock")}
        </div>
        <div class="bhCell bsPrice">${priceHtml}</div>
        <div class="bhCell bsWhere">${offer ? esc(vendorLabel(offer.vendor)) : `<span class="dim">-</span>`}</div>
        <div class="bhCell">${offer ? `<a class="offer-link" href="${esc(offer.url)}" target="_blank" rel="noopener noreferrer">${t(lang, "buyLabel")}</a>` : `<span class="dim">-</span>`}</div>
        <div class="bhCell bsRemove">
          <button class="icon-btn" type="button" data-action="remove" data-slot="${esc(slot.id)}" data-id="${esc(product.id)}" aria-label="${esc(t(lang, "removePart"))}" title="${esc(t(lang, "removePart"))}">
            ${icon("trash", 15)}
          </button>
        </div>
      </div>
    `;
  }

  function emptyRow(slot: BuildSlot): string {
    return `
      <div class="buildRow is-empty">
        <div class="bhCell"><a class="slot-link" href="${categoryHash(slot.categories[0])}">${esc(slot.label[lang])}</a></div>
        <div class="bhCell">${thumbHtml(slot)}</div>
        <div class="bhCell bsChoose" style="grid-column: 3 / -1;">
          <a class="btn-choose" href="${chooseUrl(slot)}">${icon("plus", 13)}<span>${esc(slot.choose[lang])}</span></a>
        </div>
      </div>
    `;
  }

  function addAdditionalRow(slot: BuildSlot): string {
    const label =
      lang === "he" ? `הוספת ${esc(slot.label[lang])} נוסף` : `Add Additional ${esc(slot.label[lang])}`;
    return `
      <div class="buildRow buildRow--add">
        <div class="bhCell"></div>
        <div class="bhCell"></div>
        <div class="bhCell bsChoose" style="grid-column: 3 / -1;">
          <a class="btn-choose btn-choose--ghost" href="${chooseUrl(slot)}">${icon("plus", 13)}<span>${label}</span></a>
        </div>
      </div>
    `;
  }

  function markupLines(mode: "markdown" | "text"): string {
    const origin = location.origin + location.pathname;
    const lines: string[] = [];
    if (mode === "markdown") {
      lines.push("Type|Item|Price", ":----|:----|:----");
    }
    for (const slot of BUILD_SLOTS) {
      for (const product of parts.get(slot.id) ?? []) {
        const offer = bestOffer(product);
        const price = effectivePrice(product);
        const priceStr = price === null ? "-" : formatPrice(price, currency, lang);
        const url = origin + productHash(product.category, product.id);
        if (mode === "markdown") {
          const where = offer ? ` @ ${vendorLabel(offer.vendor)}` : "";
          lines.push(`**${slot.label.en}** | [${displayName(product)}](${url}) | ${priceStr}${where}`);
        } else {
          lines.push(`${slot.label.en}: ${displayName(product)} - ${priceStr}`);
        }
      }
    }
    let total = 0;
    for (const list of parts.values()) {
      for (const product of list) total += effectivePrice(product) ?? 0;
    }
    if (mode === "markdown") {
      lines.push(` | **Total** | **${formatPrice(total, currency, lang)}**`);
    } else {
      lines.push(`${t(lang, "totalLabel")} ${formatPrice(total, currency, lang)}`);
    }
    return lines.join("\n");
  }

  async function copyText(text: string, btn: HTMLButtonElement): Promise<void> {
    const original = btn.innerHTML;
    const done = (ok: boolean) => {
      btn.innerHTML = ok
        ? `${icon("copy", 13)}<span>${esc(t(lang, "markupCopied"))}</span>`
        : original;
      window.setTimeout(() => {
        btn.innerHTML = original;
      }, 1400);
    };
    try {
      await navigator.clipboard.writeText(text);
      done(true);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
        done(true);
      } catch {
        done(false);
      }
      ta.remove();
    }
  }

  function render(): void {
    // First pick per slot drives wattage + compatibility banners.
    const records: Record<string, Product> = {};
    for (const [slotId, list] of parts.entries()) {
      if (list[0]) records[slotId] = list[0];
    }

    const estWatts = estimateWattage(records);
    const issues = checkCompatibility(records, estWatts, lang);
    const itemCount = buildItemCount(build);
    const hasParts = itemCount > 0;

    let total = 0;
    for (const list of parts.values()) {
      for (const product of list) total += effectivePrice(product) ?? 0;
    }

    const shareUrl = `${location.origin}${location.pathname}${buildHash(build)}`;

    const compatClass = !hasParts ? "idle" : issues.length > 0 ? "bad" : "ok";
    const compatText = !hasParts
      ? t(lang, "compatibilityIdle")
      : issues.length > 0
        ? issues.join(" - ")
        : t(lang, "compatibilityOk");

    const rows = BUILD_SLOTS.map((slot) => {
      const list = parts.get(slot.id) ?? [];
      if (list.length === 0) return emptyRow(slot);
      const itemRows = list
        .map((product, i) => filledRow(slot, product, i === 0))
        .join("");
      const extra = MULTI_SLOTS.has(slot.id) ? addAdditionalRow(slot) : "";
      return itemRows + extra;
    }).join("");

    const extraRow = `
      <div class="buildRow buildRow--links">
        <div class="bhCell"><span class="slot-link slot-link--static">${t(lang, "expansionOther")}</span></div>
        <div class="bhCell bsChoose" style="grid-column: 2 / -1;">
          ${EXTRA_CATS.map((c) => `<a href="${categoryHash(c)}">${esc(categoryLabel(c, lang))}</a>`).join("<span class='link-sep'>, </span>")}
        </div>
      </div>`;

    container.innerHTML = `
      <div class="title-band">
        <h1>${t(lang, "builderTitle")}</h1>
      </div>

      <div class="actionBoxGroup">
        <div class="permalink">
          <button class="btn-small btn-icon" id="builder-copy-link" type="button" title="${esc(t(lang, "copyLink"))}">${icon("copy", 13)}</button>
          <input
            class="share-input"
            id="builder-share-link"
            type="text"
            readonly
            dir="ltr"
            value="${esc(shareUrl)}"
          />
        </div>
        <div class="markup">
          <span class="markup-label">Markup:</span>
          <button type="button" id="markup-md" title="${esc(t(lang, "copyMarkdown"))}">PCPP</button>
          <button type="button" id="markup-text" title="${esc(t(lang, "copyText"))}">TXT</button>
        </div>
        <div class="options">
          <span class="parts-count">${itemCount} / ${BUILD_SLOTS.length} ${t(lang, "partsCount")}</span>
          <button type="button" id="builder-start-new">${icon("plus", 13)}<span>${t(lang, "startNew")}</span></button>
        </div>
      </div>

      <div class="partlistMetrics">
        <div class="compatBanner ${compatClass}"><span class="compat-dot" aria-hidden="true"></span><span>${esc(compatText)}</span></div>
        <div class="wattBlock">${icon("bolt", 14)}<span>${t(lang, "estimatedWattage")}</span><b>${estWatts}W</b></div>
      </div>

      <div class="buildTableWrap">
        <div class="buildHead">
          <div class="bhCell">${t(lang, "componentHeading")}</div>
          <div class="bhCell"></div>
          <div class="bhCell">${t(lang, "selectionHeading")}</div>
          <div class="bhCell">${t(lang, "baseHeading")}</div>
          <div class="bhCell">${t(lang, "shippingHeading")}</div>
          <div class="bhCell">${t(lang, "availability")}</div>
          <div class="bhCell">${t(lang, "priceHeading")}</div>
          <div class="bhCell">${t(lang, "merchantHeading")}</div>
          <div class="bhCell"></div>
          <div class="bhCell"></div>
        </div>
        ${rows}
        ${extraRow}
        <div class="buildRow buildTotalRow">
          <div class="bhCell buildTotalLabel" style="grid-column: 1 / 7;">${t(lang, "totalLabel")}</div>
          <div class="bhCell bsPrice">${esc(formatPrice(total, currency, lang))}</div>
          <div class="bhCell" style="grid-column: 8 / -1;"></div>
        </div>
      </div>

      <p class="pdp-disclaimer">* ${t(lang, "disclaimer")}</p>

      <div class="compatNote">
        <b>${lang === "he" ? "הערת תאימות:" : "Compatibility note:"}</b>
        ${lang === "he"
          ? "בדיקת התאימות מבוססת על נתונים ידועים בלבד. אישורים פיזיים כמו מרווח לקירור לא נבדקים אוטומטית."
          : "Some physical constraints (RAM clearance, cooler height, GPU length) are not automatically checked. Verify case fit manually."}
      </div>
    `;

    const copyButton =
      container.querySelector<HTMLButtonElement>("#builder-copy-link");
    const shareInput =
      container.querySelector<HTMLInputElement>("#builder-share-link");

    if (copyButton && shareInput) {
      copyButton.addEventListener("click", () => {
        void copyText(shareInput.value, copyButton);
      });
    }

    const mdBtn = container.querySelector<HTMLButtonElement>("#markup-md");
    if (mdBtn) {
      mdBtn.addEventListener("click", () => {
        void copyText(markupLines("markdown"), mdBtn);
      });
    }
    const txtBtn = container.querySelector<HTMLButtonElement>("#markup-text");
    if (txtBtn) {
      txtBtn.addEventListener("click", () => {
        void copyText(markupLines("text"), txtBtn);
      });
    }

    const startNew = container.querySelector<HTMLButtonElement>("#builder-start-new");
    if (startNew) {
      startNew.addEventListener("click", () => {
        if (itemCount === 0) return;
        for (const k of Object.keys(build)) delete build[k];
        persist();
        void refreshParts().then(render);
      });
    }

    container
      .querySelectorAll<HTMLElement>("[data-action='remove']")
      .forEach((button) => {
        button.addEventListener("click", () => {
          const slotId = button.dataset.slot;
          const productId = button.dataset.id;
          if (!slotId || !productId) return;

          removeFromBuild(build, slotId, productId);

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
