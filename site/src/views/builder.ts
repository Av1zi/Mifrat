import { loadCategory } from "../api";
import { BUILD_SLOTS, checkCompatibility, estimateWattage, type BuildSlot } from "../build";
import { formatPrice } from "../format";
import { t, vendorLabel } from "../i18n";
import { buildHash, getStoredBuild, replaceRoute, setStoredBuild } from "../state";
import type { Currency, Lang, Offer, Product } from "../types";
import { displayName, esc } from "../utils";
import { closeDetail } from "./detail";

const slotCache = new Map<string, Promise<Product[]>>();

function loadSlotProducts(slot: BuildSlot): Promise<Product[]> {
  let promise = slotCache.get(slot.id);
  if (!promise) {
    promise = Promise.all(
      slot.categories.map((c) => loadCategory(c).catch(() => [] as Product[]))
    ).then((lists) => lists.flat());
    slotCache.set(slot.id, promise);
  }
  return promise;
}

function bestOffer(p: Product): Offer | null {
  const inStock = p.offers.filter((o) => o.in_stock && o.price !== null);
  const pool = inStock.length ? inStock : p.offers;
  if (!pool.length) return null;
  return pool.reduce((best, o) => (o.price !== null && (best.price === null || o.price < best.price) ? o : best), pool[0]);
}

export async function renderBuilder(
  container: HTMLElement,
  lang: Lang,
  currency: Currency,
  shared: Record<string, string> | null
): Promise<void> {
  closeDetail();
  const validSlots = new Set(BUILD_SLOTS.map((s) => s.id));
  let buildIds: Record<string, string> = Object.fromEntries(
    Object.entries(shared ?? getStoredBuild()).filter(([k, v]) => validSlots.has(k) && typeof v === "string" && v)
  );
  let parts: Record<string, Product> = {};

  container.innerHTML = `<div class="empty-state">${t(lang, "loading")}</div>`;

  const slotById = (id: string): BuildSlot => BUILD_SLOTS.find((s) => s.id === id)!;

  function buyHtml(p: Product): string {
    const offer = bestOffer(p);
    if (!offer) return "";
    return `<a class="offer-link" href="${esc(offer.url)}" target="_blank" rel="noopener noreferrer">${esc(vendorLabel(offer.vendor))}</a>`;
  }

  function rowHtml(slot: BuildSlot): string {
    const p = parts[slot.id];
    const selection = p
      ? `<div class="bs-part">
           <div class="bs-part-name">${esc(displayName(p))}</div>
           <div class="bs-part-brand">${esc(p.brand ?? "")}</div>
         </div>
         <button class="bs-remove" type="button" data-remove="${slot.id}" title="${t(lang, "removePart")}">✕</button>`
      : `<button class="btn-choose" type="button" data-pick="${slot.id}">+ ${esc(slot.choose[lang])}</button>`;
    return `
      <div class="build-row">
        <div class="bh-cell bs-slot">${esc(slot.label[lang])}</div>
        <div class="bh-cell bs-selection">${selection}</div>
        <div class="bh-cell bs-price">${p ? formatPrice(p.min_price, currency, lang) : ""}</div>
        <div class="bh-cell bs-stock">${p ? `<span class="status-dot ${p.in_stock ? "in" : "out"}"></span>${p.in_stock ? t(lang, "inStock") : t(lang, "outOfStock")}` : ""}</div>
        <div class="bh-cell bs-buy">${p ? buyHtml(p) : ""}</div>
      </div>`;
  }

  function render(): void {
    const estWatts = estimateWattage(parts);
    const issues = checkCompatibility(parts, estWatts, lang);
    const hasParts = Object.keys(parts).length > 0;
    const total = Object.values(parts).reduce((sum, p) => sum + (p.min_price ?? 0), 0);
    const shareUrl = location.origin + location.pathname + buildHash(buildIds);

    container.innerHTML = `
      <div class="hero build-hero"><h1>${t(lang, "builderTitle")}</h1></div>
      <div class="build-share">
        <input class="share-input" id="share-link" type="text" readonly dir="ltr" value="${esc(shareUrl)}" />
        <button class="btn-primary" id="copy-link" type="button">${t(lang, "copyLink")}</button>
      </div>
      <div class="compat-row">
        ${
          hasParts
            ? issues.length
              ? `<div class="compat-banner bad">⚠ ${esc(issues.join(" · "))}</div>`
              : `<div class="compat-banner ok">✓ ${t(lang, "compatibilityOk")}</div>`
            : `<div class="compat-banner idle">${t(lang, "compatibilityIdle")}</div>`
        }
        ${estWatts > 0 ? `<div class="watt-badge">⚡ ${t(lang, "estimatedWattage")} ${estWatts}W</div>` : ""}
      </div>
      <div class="build-table">
        <div class="build-head">
          <div class="bh-cell">${t(lang, "componentHeading")}</div>
          <div class="bh-cell">${t(lang, "selectionHeading")}</div>
          <div class="bh-cell">${t(lang, "priceHeading")}</div>
          <div class="bh-cell">${t(lang, "availability")}</div>
          <div class="bh-cell"></div>
        </div>
        ${BUILD_SLOTS.map(rowHtml).join("")}
      </div>
      <div class="build-total">${t(lang, "totalLabel")} <strong>${formatPrice(total, currency, lang)}</strong></div>`;

    container.querySelectorAll("[data-pick]").forEach((el) => {
      el.addEventListener("click", () => {
        const slot = slotById((el as HTMLElement).dataset.pick!);
        openPicker(lang, currency, slot, (id) => {
          buildIds[slot.id] = id;
          void refresh();
        });
      });
    });
    container.querySelectorAll("[data-remove]").forEach((el) => {
      el.addEventListener("click", () => {
        delete buildIds[(el as HTMLElement).dataset.remove!];
        void refresh();
      });
    });
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

  async function refresh(): Promise<void> {
    setStoredBuild(buildIds);
    replaceRoute(buildHash(buildIds));
    const next: Record<string, Product> = {};
    await Promise.all(
      BUILD_SLOTS.map(async (slot) => {
        const id = buildIds[slot.id];
        if (!id) return;
        const list = await loadSlotProducts(slot);
        const found = list.find((p) => p.id === id);
        if (found) next[slot.id] = found;
        else delete buildIds[slot.id];
      })
    );
    parts = next;
    render();
  }

  await refresh();
}

function openPicker(lang: Lang, currency: Currency, slot: BuildSlot, onPick: (id: string) => void): void {
  const backdrop = document.createElement("div");
  backdrop.className = "overlay-backdrop";
  const panel = document.createElement("div");
  panel.className = "overlay-panel";
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-modal", "true");
  panel.innerHTML = `
    <button class="overlay-close" type="button">${t(lang, "close")} ✕</button>
    <div class="overlay-title">${esc(slot.choose[lang])}</div>
    <input class="search-input picker-search" type="search" placeholder="${esc(t(lang, "searchPlaceholder"))}" />
    <div class="picker-list"><div class="empty-state">${t(lang, "loading")}</div></div>`;
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
  panel.querySelector(".overlay-close")!.addEventListener("click", close);

  let all: Product[] = [];
  const listEl = panel.querySelector(".picker-list")!;

  const draw = (q: string) => {
    const query = q.trim().toLowerCase();
    const items = query
      ? all.filter((p) => `${p.name} ${p.brand ?? ""}`.toLowerCase().includes(query))
      : all;
    listEl.innerHTML = items.length
      ? items
          .slice(0, 200)
          .map(
            (p) => `
              <button class="picker-item" type="button" data-id="${esc(p.id)}">
                <span class="picker-name">${esc(displayName(p))}</span>
                <span class="picker-price">${formatPrice(p.min_price, currency, lang)}</span>
              </button>`
          )
          .join("")
      : `<div class="empty-state">${t(lang, "noResults")}</div>`;
    listEl.querySelectorAll(".picker-item").forEach((el) => {
      el.addEventListener("click", () => {
        onPick((el as HTMLElement).dataset.id!);
        close();
      });
    });
  };

  panel.querySelector(".picker-search")!.addEventListener("input", (e) => {
    draw((e.target as HTMLInputElement).value);
  });

  void loadSlotProducts(slot).then((products) => {
    all = products.slice().sort((a, b) => (a.min_price ?? Infinity) - (b.min_price ?? Infinity));
    draw("");
  });
}