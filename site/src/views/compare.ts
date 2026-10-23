import { loadCategory, loadIndex } from "../api";
import { COMPARE_MAX, getCompare, removeCompare } from "../compare";
import { formatPrice } from "../format";
import { attributeLabel, categoryLabel, specGroupLabel, t, vendorsCount } from "../i18n";
import { icon } from "../icons";
import { bestOffer } from "../offers";
import { displaySpecFields, formatSpecValue, specValue } from "../specs";
import { categoriesHash, categoryHash, compareHash, productHash, replaceRoute, savedHash } from "../state";
import { setPageTitle } from "../titles";
import type { Currency, Lang, Product } from "../types";
import { button } from "../ui/button";
import { emptyValue } from "../ui/empty";
import { html, mount, type Html } from "../ui/html";
import { pageHero } from "../ui/pageHero";
import { positivePrice, priceCell } from "../ui/price";
import { specCell } from "../ui/spec";
import { emptyBox } from "../ui/emptyBox";
import { errorState, loadingState } from "../ui/state";
import { bindThumbs, initialsOf, thumb } from "../ui/thumb";
import { vendorTag } from "../ui/vendor";
import { displayName } from "../utils";

interface SpecRow {
  field: string;
  group: string;
  differs: boolean;
  /** Index of the clearly best value (numeric fields with a known direction), else -1. */
  best: number;
}

/** Numeric fields where more is better / less is better; everything else is just compared. */
const HIGHER_BETTER = /(_count|_gb|_tb|_mb|_mhz|_ghz|_mbps|_slots|_connectors|_ports|_tbw)$|^wattage_w$/;
const LOWER_BETTER = /^(tdp_w|cas_latency|noise_db|noise_dba|recommended_psu_w|power_w)$/;

function bestIndex(items: Product[], field: string): number {
  const higher = HIGHER_BETTER.test(field);
  const lower = LOWER_BETTER.test(field);
  if (!higher && !lower) return -1;
  const values = items.map((p) => specValue(p, field));
  const nums = values.map((v) => (typeof v === "number" && Number.isFinite(v) ? v : null));
  const known = nums.filter((n): n is number => n !== null);
  if (known.length < 2 || new Set(known).size < 2) return -1;
  const target = higher ? Math.max(...known) : Math.min(...known);
  // A tie for first place has no single winner.
  return known.filter((n) => n === target).length === 1 ? nums.indexOf(target) : -1;
}

/** Spec rows with at least one known value; `differs` when two parts show different known values. */
function specRows(items: Product[], category: string, lang: Lang): SpecRow[] {
  const rows: SpecRow[] = [];
  for (const field of displaySpecFields(category)) {
    const texts = items.map((p) => formatSpecValue(specValue(p, field.name), lang));
    const known = texts.filter((text) => text !== "");
    if (known.length === 0) continue;
    rows.push({ field: field.name, group: field.group, differs: new Set(known).size > 1, best: bestIndex(items, field.name) });
  }
  return rows;
}

function headCell(p: Product, category: string, lang: Lang, currency: Currency): Html {
  const name = displayName(p);
  const href = productHash(category, p.id);
  const offer = bestOffer(p);
  return html`<th scope="col" class="cmp-head">
    ${button({ label: `${t(lang, "compareRemoveItem")}: ${name}`, icon: icon("close", 14), size: "sm", iconOnly: true, className: "cmp-head__x", data: { remove: p.id } })}
    <a class="cmp-head__img" href="${href}" tabindex="-1" aria-hidden="true">${thumb(p.image ?? p.thumb, initialsOf(p.brand, p.name), "lg")}</a>
    <a class="cmp-head__name" href="${href}" dir="auto">${name}</a>
    <span class="cmp-head__price">${priceCell(p.min_price, currency, lang)}${offer ? vendorTag(offer.vendor) : ""}</span>
    <a class="btn btn--primary btn--sm btn--block" href="${href}">${t(lang, "allPrices")}</a>
  </th>`;
}

function addCell(category: string, lang: Lang): Html {
  return html`<th scope="col" class="cmp-head cmp-head--add">
    <a class="cmp-add" href="${categoryHash(category)}" aria-label="${t(lang, "compareAddProduct")}">${icon("plus", 22)}</a>
    <span class="cmp-add__label">${t(lang, "compareAddProduct")}</span>
    <span class="cmp-add__hint">${t(lang, "compareUpTo")}</span>
  </th>`;
}

function overviewRows(items: Product[], lang: Lang, currency: Currency, pad: Html): Html {
  const prices = items.map((p) => positivePrice(p.min_price));
  const known = prices.filter((price): price is number => price !== null);
  const lowest = known.length > 1 && new Set(known).size > 1 ? Math.min(...known) : null;
  const differs = (values: unknown[]): string => (new Set(values).size > 1 ? "is-diff" : "");
  const range = (p: Product): Html => {
    const all = p.offers.map((o) => positivePrice(o.price)).filter((n): n is number => n !== null);
    if (all.length === 0) return emptyValue(lang);
    const lo = Math.min(...all);
    const hi = Math.max(...all);
    return html`<bdi dir="ltr">${lo === hi ? formatPrice(lo, currency, lang) : `${formatPrice(lo, currency, lang)} – ${formatPrice(hi, currency, lang)}`}</bdi>`;
  };
  return html`
    <tr class="${differs(prices)}"><th scope="row">${t(lang, "cheapest")}</th>${items.map((p, i) => html`<td class="${prices[i] !== null && prices[i] === lowest ? "is-best" : ""}">${priceCell(p.min_price, currency, lang)}</td>`)}${pad}</tr>
    <tr><th scope="row">${t(lang, "priceRangeLabel")}</th>${items.map((p) => html`<td>${range(p)}</td>`)}${pad}</tr>
    <tr class="${differs(items.map((p) => p.vendor_count))}"><th scope="row">${t(lang, "storesHeading")}</th>${items.map((p) => html`<td>${vendorsCount(lang, p.vendor_count)}</td>`)}${pad}</tr>
    <tr class="${differs(items.map((p) => p.in_stock))}"><th scope="row">${t(lang, "availability")}</th>${items.map((p) => html`<td><span class="stock"><span class="status-dot ${p.in_stock ? "status-dot--ok" : "status-dot--err"}" aria-hidden="true"></span>${p.in_stock ? t(lang, "inStock") : t(lang, "outOfStock")}</span></td>`)}${pad}</tr>`;
}

function tableMarkup(items: Product[], category: string, lang: Lang, currency: Currency, onlyDiffs: boolean): Html {
  const rows = specRows(items, category, lang);
  const shown = onlyDiffs ? rows.filter((row) => row.differs) : rows;
  const groups = [...new Set(shown.map((row) => row.group))];
  const canAdd = items.length < COMPARE_MAX;
  const span = items.length + 1 + (canAdd ? 1 : 0);
  const pad = canAdd ? html`<td class="cmp-pad" aria-hidden="true"></td>` : html``;
  return html`<div class="card card--flush cmp-card"><div class="table-wrap"><table class="table compare-table" style="--cmp-cols: ${items.length + (canAdd ? 1 : 0)}">
    <thead><tr><th scope="col" class="compare-table__corner">${t(lang, "productLabel")}</th>${items.map((p) => headCell(p, category, lang, currency))}${canAdd ? addCell(category, lang) : ""}</tr></thead>
    <tbody>
      <tr class="compare-table__group"><th scope="colgroup" colspan="${span}">${t(lang, "priceHeading")}</th></tr>
      ${overviewRows(items, lang, currency, pad)}
      ${shown.length === 0 ? html`<tr><td colspan="${span}" class="text-dim">${t(lang, "compareSame")}</td></tr>` : ""}
      ${groups.map(
        (group) => html`<tr class="compare-table__group"><th scope="colgroup" colspan="${span}">${specGroupLabel(group, lang)}</th></tr>
        ${shown
          .filter((row) => row.group === group)
          .map(
            (row) => html`<tr class="${row.differs ? "is-diff" : ""}"><th scope="row">${attributeLabel(row.field, lang, category)}</th>${items.map((p, i) => html`<td class="${i === row.best ? "is-best" : ""}">${specCell(specValue(p, row.field), lang)}</td>`)}${pad}</tr>`
          )}`
      )}
    </tbody>
  </table></div></div>`;
}

/**
 * #/compare?ids=a,b,c,d. Ids come from the URL (shareable); with none, the
 * stored compare list is used and written back into the address bar. Parts
 * of other categories than the first are dropped, never mixed.
 */
export async function renderCompare(container: HTMLElement, lang: Lang, currency: Currency, urlIds: string[]): Promise<void> {
  setPageTitle(lang, t(lang, "compareTitle"), t(lang, "metaCompareDesc"));
  const hero = (category?: string): Html =>
    pageHero({
      lang,
      crumbs: category
        ? [{ label: categoryLabel(category, lang), href: categoryHash(category) }, { label: t(lang, "compareTitle") }]
        : [{ label: t(lang, "compareTitle") }],
      title: t(lang, "compareTitle"),
      sub: t(lang, "compareHeroSub"),
    });
  mount(container, html`${hero()}${loadingState(lang)}`);

  const empty = (): Html =>
    html`${hero()}
      ${emptyBox({
        icon: "compare",
        title: t(lang, "compareEmptyTitle"),
        body: t(lang, "compareEmptyBody"),
        steps: [
          { title: t(lang, "compareStep1"), body: t(lang, "compareStep1Body") },
          { title: t(lang, "compareStep2"), body: t(lang, "compareStep2Body") },
          { title: t(lang, "compareStep3"), body: t(lang, "compareStep3Body") },
        ],
        actions: html`<a class="btn btn--primary" href="${categoriesHash()}">${t(lang, "compareEmptyCta")}</a>
          <a class="btn btn--ghost" href="${savedHash()}">${icon("heart", 16)}${t(lang, "compareFromSaved")}</a>`,
      })}`;

  const ids = (urlIds.length > 0 ? urlIds : getCompare().items.map((p) => p.id)).slice(0, COMPARE_MAX);
  if (ids.length === 0) {
    mount(container, empty());
    return;
  }

  let products: Product[];
  let category: string;
  let missing = false;
  try {
    const index = await loadIndex();
    const categoryOf = new Map(index.map((row) => [row[0], row[1]]));
    const first = ids.map((id) => categoryOf.get(id)).find((c): c is string => c !== undefined);
    if (!first) {
      mount(container, empty());
      return;
    }
    category = first;
    const sameCategory = ids.filter((id) => categoryOf.get(id) === category);
    missing = sameCategory.length !== ids.length;
    const all = await loadCategory(category);
    const byId = new Map(all.map((p) => [p.id, p]));
    products = sameCategory.map((id) => byId.get(id)).filter((p): p is Product => p !== undefined);
    missing = missing || products.length !== sameCategory.length;
  } catch (err) {
    mount(container, html`${hero()}${errorState(lang, err)}`);
    return;
  }
  if (products.length === 0) {
    mount(container, empty());
    return;
  }
  if (urlIds.length === 0) replaceRoute(compareHash(products.map((p) => p.id)));

  let items = products;
  let onlyDiffs = false;

  const draw = (): void => {
    if (items.length === 0) {
      mount(container, empty());
      return;
    }
    mount(
      container,
      html`<div class="contents" data-compare-root>
        ${hero(category)}
        ${missing ? html`<p class="notice notice--warn" role="status">${icon("alert", 16)}<span>${t(lang, "compareMissing")}</span></p>` : ""}
        <div class="cmp-bar">
          <b class="cmp-bar__count">${items.length} ${categoryLabel(category, lang)}</b>
          <label class="check"><input type="checkbox" data-role="only-diffs"${onlyDiffs ? html` checked` : ""}><span>${t(lang, "compareOnlyDiffs")}</span></label>
          <span class="cmp-bar__legend"><span class="cmp-bar__swatch" aria-hidden="true"></span>${t(lang, "compareBestLegend")}</span>
          ${button({ label: t(lang, "copyCompareLink"), icon: icon("link", 15), size: "sm", data: { role: "copy-compare" }, className: "cmp-bar__copy" })}
        </div>
        ${tableMarkup(items, category, lang, currency, onlyDiffs)}
      </div>`
    );
    bindThumbs(container);

    // The root is rebuilt on every draw, so its listeners go with it.
    const root = container.querySelector<HTMLElement>("[data-compare-root]")!;
    root.addEventListener("click", (e) => {
      const target = e.target as HTMLElement;
      const copy = target.closest<HTMLButtonElement>('[data-role="copy-compare"]');
      if (copy) {
        const url = `${location.origin}${location.pathname}${compareHash(items.map((p) => p.id))}`;
        void navigator.clipboard?.writeText(url).then(() => {
          copy.classList.add("is-done");
          copy.querySelector("span")!.textContent = t(lang, "linkCopied");
        });
        return;
      }
      const removeEl = target.closest<HTMLElement>("[data-remove]");
      if (!removeEl) return;
      const id = removeEl.dataset.remove ?? "";
      items = items.filter((p) => p.id !== id);
      removeCompare(id);
      replaceRoute(items.length > 0 ? compareHash(items.map((p) => p.id)) : "#/compare");
      draw();
    });
    root.addEventListener("change", (e) => {
      const input = (e.target as HTMLElement).closest<HTMLInputElement>('[data-role="only-diffs"]');
      if (!input) return;
      onlyDiffs = input.checked;
      draw();
      container.querySelector<HTMLInputElement>('[data-role="only-diffs"]')?.focus();
    });
  };
  draw();
}
