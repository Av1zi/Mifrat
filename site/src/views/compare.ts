import { loadCategory, loadIndex } from "../api";
import { COMPARE_MAX, getCompare, removeCompare } from "../compare";
import { attributeLabel, categoryLabel, specGroupLabel, t, vendorLabel, vendorsCount } from "../i18n";
import { icon } from "../icons";
import { bestOffer } from "../offers";
import { displaySpecFields, formatSpecValue, specValue } from "../specs";
import { categoriesHash, categoryHash, compareHash, productHash, replaceRoute } from "../state";
import { setPageTitle } from "../titles";
import type { Currency, Lang, Product } from "../types";
import { button } from "../ui/button";
import { chip } from "../ui/chip";
import { html, mount, type Html } from "../ui/html";
import { positivePrice, priceCell } from "../ui/price";
import { specCell } from "../ui/spec";
import { emptyState, errorState, loadingState } from "../ui/state";
import { bindThumbs, initialsOf, thumb } from "../ui/thumb";
import { displayName } from "../utils";

interface SpecRow {
  field: string;
  group: string;
  differs: boolean;
}

/** Spec rows with at least one known value; `differs` when two parts show different known values. */
function specRows(items: Product[], category: string, lang: Lang): SpecRow[] {
  const rows: SpecRow[] = [];
  for (const field of displaySpecFields(category)) {
    const texts = items.map((p) => formatSpecValue(specValue(p, field.name), lang));
    const known = texts.filter((text) => text !== "");
    if (known.length === 0) continue;
    rows.push({ field: field.name, group: field.group, differs: new Set(known).size > 1 });
  }
  return rows;
}

function headCell(p: Product, category: string, lang: Lang): Html {
  const name = displayName(p);
  return html`<th scope="col" class="compare-table__item">
    <a class="compare-table__thumb" href="${productHash(category, p.id)}" tabindex="-1" aria-hidden="true">${thumb(p.thumb ?? p.image, initialsOf(p.brand, p.name), "md")}</a>
    <a class="compare-table__name" href="${productHash(category, p.id)}">${name}</a>
    ${p.brand ? html`<span class="row__brand">${p.brand}</span>` : ""}
    ${button({ label: `${t(lang, "compareRemoveItem")}: ${name}`, icon: icon("close", 14), size: "sm", iconOnly: true, className: "compare-table__x", data: { remove: p.id } })}
  </th>`;
}

function overviewRows(items: Product[], lang: Lang, currency: Currency): Html {
  const prices = items.map((p) => positivePrice(p.min_price));
  const known = prices.filter((price): price is number => price !== null);
  const lowest = known.length > 1 && new Set(known).size > 1 ? Math.min(...known) : null;
  const differs = (values: unknown[]): string => (new Set(values).size > 1 ? "is-diff" : "");
  return html`
    <tr class="${differs(prices)}"><th scope="row">${t(lang, "priceHeading")}</th>${items.map((p, i) => html`<td>${priceCell(p.min_price, currency, lang, "lg")}${prices[i] !== null && prices[i] === lowest ? html` ${chip(t(lang, "cheapest"), { tone: "brand" })}` : ""}</td>`)}</tr>
    <tr><th scope="row">${t(lang, "merchantHeading")}</th>${items.map((p) => {
      const offer = bestOffer(p);
      return html`<td>${offer ? html`<b>${vendorLabel(offer.vendor)}</b> · ` : ""}${vendorsCount(lang, p.vendor_count)}</td>`;
    })}</tr>
    <tr class="${differs(items.map((p) => p.in_stock))}"><th scope="row">${t(lang, "availability")}</th>${items.map((p) => html`<td><span class="stock"><span class="status-dot ${p.in_stock ? "status-dot--ok" : "status-dot--err"}" aria-hidden="true"></span>${p.in_stock ? t(lang, "inStock") : t(lang, "outOfStock")}</span></td>`)}</tr>`;
}

function tableMarkup(items: Product[], category: string, lang: Lang, currency: Currency, onlyDiffs: boolean): Html {
  const rows = specRows(items, category, lang);
  const shown = onlyDiffs ? rows.filter((row) => row.differs) : rows;
  const groups = [...new Set(shown.map((row) => row.group))];
  const span = items.length + 1;
  return html`<div class="table-wrap compare-wrap"><table class="table compare-table">
    <thead><tr><th scope="col" class="compare-table__corner"><span class="visually-hidden">${t(lang, "compareSpecs")}</span></th>${items.map((p) => headCell(p, category, lang))}</tr></thead>
    <tbody>
      <tr class="compare-table__group"><th scope="colgroup" colspan="${span}">${t(lang, "compareGeneral")}</th></tr>
      ${overviewRows(items, lang, currency)}
      ${shown.length === 0 ? html`<tr><td colspan="${span}" class="text-dim">${t(lang, "compareSame")}</td></tr>` : ""}
      ${groups.map(
        (group) => html`<tr class="compare-table__group"><th scope="colgroup" colspan="${span}">${specGroupLabel(group, lang)}</th></tr>
        ${shown
          .filter((row) => row.group === group)
          .map(
            (row) => html`<tr class="${row.differs ? "is-diff" : ""}"><th scope="row">${attributeLabel(row.field, lang, category)}</th>${items.map((p) => html`<td>${specCell(specValue(p, row.field), lang)}</td>`)}</tr>`
          )}`
      )}
    </tbody>
  </table></div>`;
}

/**
 * #/compare?ids=a,b,c,d. Ids come from the URL (shareable); with none, the
 * stored compare list is used and written back into the address bar. Parts
 * of other categories than the first are dropped, never mixed.
 */
export async function renderCompare(container: HTMLElement, lang: Lang, currency: Currency, urlIds: string[]): Promise<void> {
  setPageTitle(lang, t(lang, "compareTitle"), t(lang, "metaCompareDesc"));
  mount(container, loadingState(lang));

  const empty = (): Html =>
    html`<header class="page-head"><h1>${t(lang, "compareTitle")}</h1></header>
      ${emptyState(t(lang, "compareEmpty"), button({ label: t(lang, "savedBrowse"), icon: icon("forward", 14), variant: "primary", href: categoriesHash() }))}`;

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
    mount(container, errorState(lang, err));
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
      html`<div data-compare-root>
        <nav class="crumbs">
          <a href="${categoryHash(category)}">${icon("back", 14)}${categoryLabel(category, lang)}</a>
        </nav>
        <header class="page-head">
          <h1>${t(lang, "compareTitle")}</h1>
          <p>${categoryLabel(category, lang)} · ${t(lang, "compareDiffNote")}</p>
        </header>
        ${missing ? html`<p class="notice" role="status">${t(lang, "compareMissing")}</p>` : ""}
        <label class="check compare-only"><input type="checkbox" data-role="only-diffs"${onlyDiffs ? html` checked` : ""}><span>${t(lang, "compareOnlyDiffs")}</span></label>
        ${tableMarkup(items, category, lang, currency, onlyDiffs)}
      </div>`
    );
    bindThumbs(container);

    // The root is rebuilt on every draw, so its listeners go with it.
    const root = container.querySelector<HTMLElement>("[data-compare-root]")!;
    root.addEventListener("click", (e) => {
      const removeEl = (e.target as HTMLElement).closest<HTMLElement>("[data-remove]");
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
