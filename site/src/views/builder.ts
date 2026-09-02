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

  function thumbPlaceholder(slot: BuildSlot, product?: Product): string {
    if (!product) {
      const initials = slot.id.slice(0, 3).toUpperCase();
      return `<div class="thumb" aria-hidden="true"><span>${esc(initials)}</span></div>`;
    }
    if (product.image) {
      return `<div class="thumb has-part" aria-hidden="true"><img src="${esc(product.image)}" alt="${esc(displayName(product))}" style="width:100%;height:100%;object-fit:contain;border-radius:8px;"></div>`;
    }
    const label = (product.brand ?? product.name).slice(0, 2).toUpperCase() || "•";
    return `<div class="thumb has-part" aria-hidden="true"><span>${esc(label)}</span></div>`;
  }

  function rowHtml(slot: BuildSlot): string {
    const entry = parts.get(slot.id);

    if (!entry) {
      return `
        <div class="buildRow is-empty">
          <div class="bhCell">
            <div class="buildSlotLabel">${esc(slot.label[lang])}<small>${esc(slot.id)}</small></div>
          </div>
          <div class="bhCell">${thumbPlaceholder(slot)}</div>
          <div class="bhCell">
            <a class="btn-choose" href="${chooseUrl(slot)}">+ ${esc(slot.choose[lang])}</a>
          </div>
          <div class="bhCell bsPrice">—</div>
          <div class="bhCell bsWhere"><span style="color:var(--text-dim)">—</span></div>
          <div class="bhCell bsStock"><span style="color:var(--text-dim)">—</span></div>
          <div class="bhCell"></div>
        </div>
      `;
    }

    const product = entry.product;
    const offer = bestOffer(product);
    const price = effectivePrice(product);

    const whereHtml = offer
      ? `<span class="bsWhere">${esc(vendorLabel(offer.vendor))}</span>`
      : `<span style="color:var(--text-dim)">—</span>`;

    const buyHtml = offer
      ? `
          <a
            class="offer-link"
            href="${esc(offer.url)}"
            target="_blank"
            rel="noopener noreferrer"
          >
            ${lang === "he" ? "קנייה" : "Buy"}
          </a>
        `
      : `<span style="color:var(--text-dim)">—</span>`;

    return `
      <div class="buildRow">
        <div class="bhCell">
          <div class="buildSlotLabel">${esc(slot.label[lang])}</div>
        </div>
        <div class="bhCell">${thumbPlaceholder(slot, product)}</div>
        <div class="bhCell">
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
        <div class="bhCell bsPrice">
          ${price === null ? "—" : esc(formatPrice(price, currency, lang))}
        </div>
        <div class="bhCell">${whereHtml}</div>
        <div class="bhCell bsStock">
          <span class="status-dot ${product.in_stock ? "in" : "out"}"></span>
          ${product.in_stock ? t(lang, "inStock") : t(lang, "outOfStock")}
        </div>
        <div class="bhCell">${buyHtml}</div>
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

    const compatClass = !hasParts ? "idle" : issues.length > 0 ? "bad" : "ok";
    const compatText = !hasParts
      ? t(lang, "compatibilityIdle")
      : issues.length > 0
        ? issues.join(" · ")
        : t(lang, "compatibilityOk");
    const compatIcon = !hasParts ? "○" : issues.length > 0 ? "⚠" : "✓";

    const rows = BUILD_SLOTS.map((slot) => rowHtml(slot)).join("");

    container.innerHTML = `
      <div class="wrapperPageTitle">
        <h1 class="pageTitle">${t(lang, "builderTitle")}</h1>
        <p class="pageTitle-sub">${t(lang, "tagline")}</p>
        <nav class="tabsGroup" aria-label="builder tabs">
          <a class="active" href="${buildHash(build)}">${lang === "he" ? "סקירה" : "Overview"}</a>
          <a href="#prices">${lang === "he" ? "מחירים לפי חנות" : "Prices by merchant"}</a>
        </nav>
      </div>

      <div class="actionBoxGroup">
        <div class="permalink">
          <button class="btn-small" id="builder-copy-link" type="button" title="Copy link">⎘</button>
          <input
            class="share-input"
            id="builder-share-link"
            type="text"
            readonly
            dir="ltr"
            value="${esc(shareUrl)}"
          />
        </div>
        <div class="markup" aria-hidden="true">
          <span title="PCPP">◈</span>
          <span title="Reddit">⬢</span>
          <span title="HTML">&lt;/&gt;</span>
          <span title="Text">≡</span>
        </div>
        <div class="options">
          <button type="button" id="builder-start-new">↺ ${lang === "he" ? "התחלה חדשה" : "Start new"}</button>
          <span style="font-size:0.75rem; color:var(--text-dim); align-self:center;">${parts.size} / ${BUILD_SLOTS.length}</span>
        </div>
      </div>

      <div class="partlistMetrics">
        <div class="compatBanner ${compatClass}">${esc(compatIcon)} ${esc(compatText)}</div>
        ${
          estWatts > 0
            ? `<div class="wattBlock">⚡ <span>${t(lang, "estimatedWattage")}</span> <b>${estWatts}W</b></div>`
            : `<div class="wattBlock" style="opacity:0.6">⚡ ${t(lang, "estimatedWattage")} 0W</div>`
        }
      </div>

      <div class="buildTableWrap">
        <div class="buildHead">
          <div class="bhCell">${t(lang, "componentHeading")}</div>
          <div class="bhCell"></div>
          <div class="bhCell">${t(lang, "selectionHeading")}</div>
          <div class="bhCell">${t(lang, "priceHeading")}</div>
          <div class="bhCell">${lang === "he" ? "חנות" : "Store"}</div>
          <div class="bhCell">${t(lang, "availability")}</div>
          <div class="bhCell"></div>
        </div>
        ${rows}
      </div>

      <div class="build-total">
        <span>${t(lang, "totalLabel")}</span>
        <strong>${esc(formatPrice(total, currency, lang))}</strong>
      </div>

      <div class="compatNote">
        <b>${lang === "he" ? "הערת תאימות:" : "Compatibility note:"}</b>
        ${lang === "he"
          ? "בדיקת התאימות מבוססת על נתונים ידועים בלבד. אישורים פיזיים כמו מרווח לקירור לא נבדקים אוטומטית."
          : "Some physical constraints (RAM clearance, cooler height, GPU length) are not automatically checked — verify case fit manually."}
      </div>

      <p style="margin-top:14px; font-size:0.76rem; color:var(--text-dim);">
        * ${t(lang, "disclaimer")}
      </p>
    `;

    const copyButton =
      container.querySelector<HTMLButtonElement>("#builder-copy-link");

    const shareInput =
      container.querySelector<HTMLInputElement>("#builder-share-link");

    if (copyButton && shareInput) {
      copyButton.addEventListener("click", () => {
        shareInput.select();

        const done = () => {
          const prev = copyButton.textContent;
          copyButton.textContent = t(lang, "copied");

          window.setTimeout(() => {
            copyButton.textContent = prev;
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

    const startNew = container.querySelector<HTMLButtonElement>("#builder-start-new");
    if (startNew) {
      startNew.addEventListener("click", () => {
        if (parts.size === 0) return;
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
