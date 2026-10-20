import { slotForCategory } from "../../build";
import { attributeLabel, t, vendorLabel, vendorsCount } from "../../i18n";
import { icon } from "../../icons";
import { bestOffer, sortOffers } from "../../offers";
import { addToBuild, getStoredBuild, navigate, productHash, setStoredBuild } from "../../state";
import type { Lang, Product, SortKey } from "../../types";
import { displayName, safeUrl } from "../../utils";
import { button } from "../../ui/button";
import { compareCheck, saveButton, syncPickControls } from "../../ui/pick";
import { signalBadges } from "../../ui/signal";
import { chip } from "../../ui/chip";
import { emptyState } from "../../ui/state";
import { html, mount, type Html } from "../../ui/html";
import { priceCell, positivePrice } from "../../ui/price";
import { specCell } from "../../ui/spec";
import { bindThumbs, initialsOf, thumb } from "../../ui/thumb";
import { specValue } from "../../specs";
import { chipText } from "./columns";
import type { CategoryActions, CategoryCtx } from "./data";
import { addPickedPart } from "./picker";

function stockMarkup(p: Product, lang: Lang): Html {
  return html`<span class="stock"><span class="status-dot ${p.in_stock ? "status-dot--ok" : "status-dot--err"}" aria-hidden="true"></span>${p.in_stock ? t(lang, "inStock") : t(lang, "outOfStock")}</span>`;
}

/** "N stores" with a popover listing every offer, cheapest first. */
function storesMarkup(ctx: CategoryCtx, p: Product, popover = true): Html {
  const { lang, currency } = ctx;
  if (!popover || p.offers.length <= 1) return html`<span class="row__stores">${vendorsCount(lang, p.vendor_count)}</span>`;
  return html`<details class="stores">
    <summary>${vendorsCount(lang, p.vendor_count)}</summary>
    <ul class="stores__pop">
      ${sortOffers(p.offers).map((o) => {
        const url = safeUrl(o.url);
        const name = vendorLabel(o.vendor);
        return html`<li class="${o.in_stock ? "" : "is-out"}">
          ${url ? html`<a href="${url}" target="_blank" rel="noopener noreferrer">${name}${icon("external", 12)}</a>` : html`<span>${name}</span>`}
          ${priceCell(o.price, currency, lang)}
        </li>`;
      })}
    </ul>
  </details>`;
}

function actionMarkup(ctx: CategoryCtx, p: Product): Html {
  const { lang } = ctx;
  if (ctx.pickSlot) {
    return button({ label: t(lang, "addToBuild"), variant: "primary", size: "sm", data: { pickadd: p.id } });
  }
  if (!slotForCategory(p.category)) return html``;
  return button({
    label: t(lang, "quickAdd"),
    icon: icon("plus", 14),
    variant: "subtle",
    size: "sm",
    data: { quickadd: p.id },
    ariaLabel: `${t(lang, "quickAdd")}: ${displayName(p)}`,
  });
}

/** Compare checkbox + heart on every row in both views (not while picking a build part). */
function toolsMarkup(ctx: CategoryCtx, p: Product): Html {
  if (ctx.pickSlot) return html``;
  const { lang } = ctx;
  return html`<div class="row__tools">${compareCheck(p, lang)}${saveButton(p, lang)}</div>`;
}

function titleMarkup(p: Product, lang: Lang, href: string): Html {
  const allStale = p.offers.length > 0 && p.offers.every((o) => o.stale);
  return html`<a class="row__title" href="${href}">${displayName(p)}</a>${allStale ? html` <span class="stale-tag">${t(lang, "staleData")}</span>` : ""}`;
}

function cardRow(ctx: CategoryCtx, p: Product): Html {
  const { lang, currency } = ctx;
  const href = productHash(ctx.category, p.id);
  const name = displayName(p);
  const offer = bestOffer(p);
  const chips = ctx.columns.map((f) => chipText(p, f, lang)).filter(Boolean);
  return html`<article class="row" data-id="${p.id}" data-href="${href}">
    <a class="row__thumb" href="${href}" tabindex="-1" aria-hidden="true">${thumb(p.thumb ?? p.image, initialsOf(p.brand, p.name), "md")}</a>
    <div class="row__main">
      <div>${titleMarkup(p, lang, href)}</div>
      ${p.brand ? html`<span class="row__brand">${p.brand}</span>` : ""}
      ${chips.length > 0 ? html`<ul class="chip-list row__chips">${chips.map((c) => html`<li>${chip(c)}</li>`)}</ul>` : ""}
    </div>
    <div class="row__buy">
      ${priceCell(p.min_price, currency, lang, "lg")}
      ${signalBadges(ctx.signals.get(p.id), lang)}
      ${offer && positivePrice(p.min_price) !== null ? html`<span class="row__from">${t(lang, "atVendor")} ${vendorLabel(offer.vendor)}</span>` : ""}
      ${storesMarkup(ctx, p)}
      ${stockMarkup(p, lang)}
    </div>
    <div class="row__action" aria-label="${name}">${actionMarkup(ctx, p)}${toolsMarkup(ctx, p)}</div>
  </article>`;
}

function sortHeader(ctx: CategoryCtx, label: string, asc: SortKey, desc: SortKey): Html {
  const active = ctx.params.sort === asc ? "ascending" : ctx.params.sort === desc ? "descending" : "none";
  const next = ctx.params.sort === asc ? desc : asc;
  const arrow = active === "ascending" ? "↑" : active === "descending" ? "↓" : "↕";
  return html`<th scope="col" aria-sort="${active}"><button type="button" class="th-sort" data-sort="${next}" title="${t(ctx.lang, "sortLabel")}">${label}<span aria-hidden="true">${arrow}</span></button></th>`;
}

function tableRow(ctx: CategoryCtx, p: Product): Html {
  const { lang, currency } = ctx;
  const href = productHash(ctx.category, p.id);
  return html`<tr class="list-row" data-id="${p.id}" data-href="${href}">
    <td class="col-thumb"><a href="${href}" tabindex="-1" aria-hidden="true">${thumb(p.thumb ?? p.image, initialsOf(p.brand, p.name), "sm")}</a></td>
    <td class="col-name">${titleMarkup(p, lang, href)}${p.brand ? html`<span class="row__brand">${p.brand}</span>` : ""}</td>
    ${ctx.columns.map((f) => html`<td>${specCell(specValue(p, f), lang)}</td>`)}
    <td>${stockMarkup(p, lang)}</td>
    <td class="col-price">${priceCell(p.min_price, currency, lang)}${signalBadges(ctx.signals.get(p.id), lang)}${storesMarkup(ctx, p, false)}</td>
    <td class="col-action">${actionMarkup(ctx, p)}${toolsMarkup(ctx, p)}</td>
  </tr>`;
}

function tableMarkup(ctx: CategoryCtx, rows: Product[]): Html {
  const { lang } = ctx;
  return html`<div class="table-wrap"><table class="table list-table">
    <thead><tr>
      <th scope="col"><span class="visually-hidden">${t(lang, "photoLabel")}</span></th>
      ${sortHeader(ctx, t(lang, "sortName"), "name", "name_desc")}
      ${ctx.columns.map((f) => html`<th scope="col" title="${attributeLabel(f, lang, ctx.category)}">${attributeLabel(f, lang, ctx.category)}</th>`)}
      <th scope="col">${t(lang, "availability")}</th>
      ${sortHeader(ctx, t(lang, "priceHeading"), "price_asc", "price_desc")}
      <th scope="col"><span class="visually-hidden">${t(lang, "buyHeaderLabel")}</span></th>
    </tr></thead>
    <tbody>${rows.map((p) => tableRow(ctx, p))}</tbody>
  </table></div>`;
}

/** Draws the visible slice of the filtered list in the active view. */
export function renderList(ctx: CategoryCtx, listEl: HTMLElement, filtered: Product[], tableAllowed: boolean): void {
  const visible = filtered.slice(0, ctx.visible);
  if (visible.length === 0) {
    mount(listEl, emptyState(t(ctx.lang, "noResults")));
    return;
  }
  const asTable = ctx.view === "table" && tableAllowed;
  listEl.classList.toggle("list--table", asTable);
  mount(listEl, asTable ? tableMarkup(ctx, visible) : html`${visible.map((p) => cardRow(ctx, p))}`);
  bindThumbs(listEl);
  syncPickControls();
}

/** Delegated interactions for the list host (set once; its content is replaced). */
export function bindList(ctx: CategoryCtx, listEl: HTMLElement, actions: CategoryActions): void {
  listEl.addEventListener("click", (e) => {
    const target = e.target as HTMLElement;

    const sortEl = target.closest<HTMLElement>("[data-sort]");
    if (sortEl) {
      ctx.params.sort = sortEl.dataset.sort as SortKey;
      ctx.sortTouched = true;
      ctx.container.querySelector<HTMLSelectElement>('[data-role="sort"]')!.value = ctx.params.sort;
      actions.update();
      return;
    }

    const pickEl = target.closest<HTMLElement>("[data-pickadd]");
    if (pickEl) {
      const product = ctx.byId.get(pickEl.dataset.pickadd!);
      if (product) addPickedPart(ctx, product);
      return;
    }

    const quickEl = target.closest<HTMLButtonElement>("[data-quickadd]");
    if (quickEl) {
      if (quickEl.disabled) return;
      const product = ctx.byId.get(quickEl.dataset.quickadd!);
      const slot = product ? slotForCategory(product.category) : null;
      if (!product || !slot) return;
      const build = getStoredBuild();
      addToBuild(build, slot.id, product.id);
      setStoredBuild(build);
      const original = quickEl.innerHTML;
      quickEl.disabled = true;
      quickEl.classList.add("is-done");
      quickEl.innerHTML = html`${icon("check", 14)}<span>${t(ctx.lang, "addedLabel")}</span>`.value;
      const status = ctx.container.querySelector('[data-role="status"]');
      if (status) status.textContent = `${displayName(product)} — ${t(ctx.lang, "quickAddStatus")}`;
      window.setTimeout(() => {
        quickEl.disabled = false;
        quickEl.classList.remove("is-done");
        quickEl.innerHTML = original;
      }, 1300);
      return;
    }

    // Whole-row click navigates; links, buttons and the stores popover keep their own behaviour.
    if (target.closest("a, button, summary, details, input, label")) return;
    const row = target.closest<HTMLElement>("[data-href]");
    if (row?.dataset.href) navigate(row.dataset.href);
  });

  // One open stores popover at a time.
  listEl.addEventListener(
    "toggle",
    (e) => {
      const opened = e.target as HTMLDetailsElement;
      if (!opened.open) return;
      listEl.querySelectorAll<HTMLDetailsElement>("details.stores[open]").forEach((d) => {
        if (d !== opened) d.open = false;
      });
    },
    true
  );
}
