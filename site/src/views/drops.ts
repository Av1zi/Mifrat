import { loadCategory, loadMeta } from "../api";
import { formatPrice } from "../format";
import { categoryLabel, CATEGORY_ORDER, dropsCount, savingText, t } from "../i18n";
import { icon } from "../icons";
import { bestOffer } from "../offers";
import { MIN_DROP_PCT, SIGNAL_WINDOW_DAYS, loadSignals, type PriceSignal } from "../signals";
import { dropsHash, productHash } from "../state";
import { partRef } from "../storage";
import { setPageTitle } from "../titles";
import type { CategoryMeta, Currency, Lang, Product } from "../types";
import { html, mount, type Html } from "../ui/html";
import { pageHero } from "../ui/pageHero";
import { saveButtonRef, syncPickControls } from "../ui/pick";
import { positivePrice } from "../ui/price";
import { emptyState, errorState, loadingState } from "../ui/state";
import { bindThumbs, initialsOf, thumb } from "../ui/thumb";
import { vendorTag } from "../ui/vendor";
import { displayName } from "../utils";

/** The catalog price may differ from the history's last day by this much (rounding, a fresh scrape). */
const PRICE_AGREES = 0.05;
/** Below this many cards the home marquee would visibly repeat itself: show a plain row instead. */
const MARQUEE_MIN = 6;

export interface DropPick {
  category: string;
  product: Product;
  signal: PriceSignal;
}

/**
 * Real recorded drops only: in stock, priced, the catalog price agreeing with
 * the history's last day, and at least MIN_DROP_PCT below the vendor's own
 * typical (median) price over the window. Nothing here is a placeholder.
 */
export async function findDrops(
  categories: CategoryMeta[],
  windowDays: number,
  limit: number
): Promise<DropPick[]> {
  const perCategory = await Promise.all(
    categories.map(async (cat) => {
      const signals = await loadSignals(cat.id, windowDays).catch(
        () => new Map<string, PriceSignal>()
      );
      return [...signals].map(([id, signal]) => ({ category: cat.id, id, signal }));
    })
  );
  const ranked = perCategory
    .flat()
    .filter((c) => c.signal.dropPct >= MIN_DROP_PCT)
    .sort((a, b) => b.signal.dropPct - a.signal.dropPct || b.signal.days - a.signal.days)
    // Some candidates fail the stock / price checks below: look a little further.
    .slice(0, Math.ceil(limit * 1.6));
  if (ranked.length === 0) return [];

  const catalogs = new Map<string, Map<string, Product>>();
  await Promise.all(
    [...new Set(ranked.map((c) => c.category))].map(async (id) => {
      const products = await loadCategory(id).catch(() => [] as Product[]);
      catalogs.set(id, new Map(products.map((p) => [p.id, p])));
    })
  );

  const picks: DropPick[] = [];
  for (const candidate of ranked) {
    const product = catalogs.get(candidate.category)?.get(candidate.id);
    const price = positivePrice(product?.min_price);
    if (!product || price === null || !product.in_stock) continue;
    if (Math.abs(price - candidate.signal.current) / candidate.signal.current > PRICE_AGREES)
      continue;
    picks.push({ category: candidate.category, product, signal: candidate.signal });
    if (picks.length === limit) break;
  }
  return picks;
}

/** Drop card: badge, photo, category, name, price against the usual price, cheapest store, savings. */
export function dropCard(pick: DropPick, lang: Lang, currency: Currency, decorative = false): Html {
  const { product, signal, category } = pick;
  const href = productHash(category, product.id);
  const name = displayName(product);
  const now = positivePrice(product.min_price) ?? signal.current;
  const offer = bestOffer(product);
  const tab = decorative ? html` tabindex="-1"` : "";
  return html`<article class="card dcard" ${decorative ? html` aria-hidden="true"` : ""}>
    <span class="dtag"><span dir="ltr">↓ ${signal.dropPct}%</span></span>
    ${decorative ? "" : html`<span class="dcard__save">${saveButtonRef(partRef(product, name), lang)}</span>`}
    <a class="dcard__img" href="${href}" ${tab} aria-hidden="true"
      >${thumb(product.image ?? product.thumb, initialsOf(product.brand, product.name), "lg")}</a
    >
    <div class="dcard__body">
      <span class="dcard__cat">${categoryLabel(category, lang)}</span>
      <a class="dcard__name" href="${href}" dir="auto" ${tab}>${name}</a>
      <div class="dcard__price">
        <b>${formatPrice(now, currency, lang)}</b>
        <s title="${t(lang, "signalTypicalTitle")}"
          >${formatPrice(signal.typical, currency, lang)}</s
        >
      </div>
      <div class="dcard__meta">
        ${offer ? vendorTag(offer.vendor) : html`<span></span>`}
        <span class="dcard__saving"
          >${savingText(lang, formatPrice(Math.max(0, signal.typical - now), currency, lang))}</span
        >
      </div>
      <a class="btn btn--primary btn--block dcard__cta" href="${href}" ${tab}
        >${t(lang, "allPrices")}${icon("forward", 15)}</a
      >
    </div>
  </article>`;
}

/**
 * Home page "Biggest price drops": two counter-scrolling marquee rows (a
 * plain scrollable row under reduced motion or with few drops). The section
 * stays hidden when there is no real drop to show.
 */
export async function fillDropsStrip(
  host: HTMLElement,
  categories: CategoryMeta[],
  lang: Lang,
  currency: Currency
): Promise<void> {
  const picks = await findDrops(categories, SIGNAL_WINDOW_DAYS, 16);
  if (picks.length === 0 || !host.isConnected) return;

  const head = html`<header class="sec-head">
    <div>
      <h2>${t(lang, "dropsTitle")}</h2>
      <p>${t(lang, "dropsHomeSub")}</p>
    </div>
    <a class="sec-head__link" href="${dropsHash()}">${t(lang, "allDrops")}${icon("forward", 14)}</a>
  </header>`;

  if (picks.length < MARQUEE_MIN) {
    mount(
      host,
      html`${head}
        <div class="drop-row">${picks.map((p) => dropCard(p, lang, currency))}</div>`
    );
  } else {
    const half = Math.ceil(picks.length / 2);
    const rows = [picks.slice(0, half), picks.slice(half)].filter((row) => row.length > 0);
    // Each track holds its cards twice; the copy is decorative and slides in as the first set leaves.
    mount(
      host,
      html`${head}
        <div class="mq">
          ${rows.map(
            (row, i) =>
              html`<div class="mq__row">
                <div
                  class="mq__track mq__track--${i % 2 === 0 ? "a" : "b"}"
                  style="--mq-dur: ${Math.max(36, row.length * 7)}s"
                >
                  ${row.map((p) => dropCard(p, lang, currency))}
                  ${row.map((p) => dropCard(p, lang, currency, true))}
                </div>
              </div>`
          )}
        </div>`
    );
  }
  host.hidden = false;
  bindThumbs(host);
  syncPickControls();
}

type DropSort = "pct" | "amount" | "price";

/** #/drops: every recorded drop, filterable by window and category. */
export async function renderDrops(
  container: HTMLElement,
  lang: Lang,
  currency: Currency
): Promise<void> {
  setPageTitle(lang, t(lang, "dropsNav"), t(lang, "dropsPageSub"));
  const hero = pageHero({
    lang,
    crumbs: [{ label: t(lang, "dropsNav") }],
    title: t(lang, "dropsNav"),
    sub: t(lang, "dropsPageSub"),
  });
  mount(container, html`${hero}${loadingState(lang)}`);

  let categories: CategoryMeta[];
  try {
    categories = (await loadMeta()).categories.filter((c) => c.count > 0);
  } catch (err) {
    mount(container, html`${hero}${errorState(lang, err)}`);
    return;
  }

  const byWindow = new Map<number, Promise<DropPick[]>>();
  const picksFor = (days: number): Promise<DropPick[]> => {
    let promise = byWindow.get(days);
    if (!promise) {
      promise = findDrops(categories, days, 72);
      byWindow.set(days, promise);
    }
    return promise;
  };

  let days = SIGNAL_WINDOW_DAYS;
  let cat = "all";
  let sort: DropSort = "pct";
  const order = CATEGORY_ORDER as readonly string[];
  const rank = (id: string): number =>
    order.indexOf(id) === -1 ? order.length : order.indexOf(id);

  const draw = async (): Promise<void> => {
    const picks = await picksFor(days);
    if (!container.isConnected) return;
    const cats = [...new Set(picks.map((p) => p.category))].sort((a, b) => rank(a) - rank(b));
    if (cat !== "all" && !cats.includes(cat)) cat = "all";
    const shown = picks
      .filter((p) => cat === "all" || p.category === cat)
      .sort((a, b) => {
        if (sort === "amount")
          return b.signal.typical - b.signal.current - (a.signal.typical - a.signal.current);
        if (sort === "price") return a.signal.current - b.signal.current;
        return b.signal.dropPct - a.signal.dropPct;
      });

    const segBtn = (n: number, label: string): Html =>
      html`<button
        type="button"
        class="seg__btn"
        data-days="${n}"
        aria-pressed="${days === n ? "true" : "false"}"
      >
        ${label}
      </button>`;
    mount(
      container,
      html`<div class="contents" data-drops-root>
        ${hero}
        <div class="drops-bar">
          <div class="seg" role="group" aria-label="${t(lang, "periodLabel")}">
            ${segBtn(7, t(lang, "days7"))}${segBtn(30, t(lang, "days30"))}
          </div>
          <div class="chip-row" role="group" aria-label="${t(lang, "filterByCategory")}">
            ${["all", ...cats].map(
              (id) =>
                html`<button
                  type="button"
                  class="pill"
                  data-cat="${id}"
                  aria-pressed="${cat === id ? "true" : "false"}"
                >
                  ${id === "all" ? t(lang, "allLabel") : categoryLabel(id, lang)}
                </button>`
            )}
          </div>
          <label class="drops-bar__sort"
            >${t(lang, "sortLabel")}
            <select class="select" data-role="sort">
              <option value="pct" ${sort === "pct" ? html` selected` : ""}>
                ${t(lang, "dropsSortPct")}
              </option>
              <option value="amount" ${sort === "amount" ? html` selected` : ""}>
                ${t(lang, "dropsSortAmount")}
              </option>
              <option value="price" ${sort === "price" ? html` selected` : ""}>
                ${t(lang, "sortPriceAsc")}
              </option>
            </select>
          </label>
        </div>
        <p class="drops-count" role="status">${dropsCount(lang, shown.length, days)}</p>
        ${
          shown.length > 0
            ? html`<div class="drop-grid">${shown.map((p) => dropCard(p, lang, currency))}</div>`
            : emptyState(t(lang, "dropsEmpty"))
        }
      </div>`
    );
    bindThumbs(container);
    syncPickControls();
    // The root is rebuilt on every draw, so its listeners go with it.
    bind(container.querySelector<HTMLElement>("[data-drops-root]")!);
  };

  const bind = (root: HTMLElement): void => {
    root.addEventListener("click", (e) => {
      const target = e.target as HTMLElement;
      const seg = target.closest<HTMLElement>("[data-days]");
      if (seg) {
        days = Number(seg.dataset.days) || SIGNAL_WINDOW_DAYS;
        void draw();
        return;
      }
      const chip = target.closest<HTMLElement>("[data-cat]");
      if (chip) {
        cat = chip.dataset.cat ?? "all";
        void draw().then(() =>
          container.querySelector<HTMLElement>(`[data-cat="${CSS.escape(cat)}"]`)?.focus()
        );
      }
    });
    root.addEventListener("change", (e) => {
      const select = (e.target as HTMLElement).closest<HTMLSelectElement>('[data-role="sort"]');
      if (!select) return;
      sort = select.value as DropSort;
      void draw().then(() =>
        container.querySelector<HTMLSelectElement>('[data-role="sort"]')?.focus()
      );
    });
  };

  await draw();
}
