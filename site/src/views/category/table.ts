import { slotForCategory } from "../../build";
import { attributeLabel, showingText, t, vendorLabel, vendorsCount } from "../../i18n";
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
import { PAGE_SIZE, type CategoryActions, type CategoryCtx } from "./data";
import { vendorDots, vendorKey } from "../../ui/vendor";
import { addPickedPart } from "./picker";

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
    variant: "primary",
    size: "sm",
    data: { quickadd: p.id },
    ariaLabel: `${t(lang, "quickAdd")}: ${displayName(p)}`,
  });
}

/** Heart on every row (not while picking a build part). */
function toolsMarkup(ctx: CategoryCtx, p: Product): Html {
  if (ctx.pickSlot) return html``;
  return saveButton(p, ctx.lang);
}

/** Bare compare checkbox for the table's first column. */
function compareCell(ctx: CategoryCtx, p: Product): Html {
  if (ctx.pickSlot) return html``;
  return compareCheck(p, ctx.lang, true);
}

function titleMarkup(p: Product, lang: Lang, href: string): Html {
  const allStale = p.offers.length > 0 && p.offers.every((o) => o.stale);
  return html`<a class="row__title" href="${href}" dir="auto">${displayName(p)}</a>${allStale ? html` <span class="stale-tag">${t(lang, "staleData")}</span>` : ""}`;
}

/** Stores that list the part, cheapest first, one entry per store. */
function vendorsOf(p: Product): string[] {
  const seen = new Map<string, string>();
  for (const o of sortOffers(p.offers)) if (!seen.has(vendorKey(o.vendor))) seen.set(vendorKey(o.vendor), o.vendor);
  return [...seen.values()];
}

function priceBlock(ctx: CategoryCtx, p: Product, size: "md" | "lg"): Html {
  const { lang, currency } = ctx;
  const offer = bestOffer(p);
  return html`<span class="row__price">
    ${priceCell(p.min_price, currency, lang, size)}
    ${offer && positivePrice(p.min_price) !== null ? html`<span class="row__from">${t(lang, "atVendor")} ${vendorLabel(offer.vendor)}</span>` : ""}
    ${p.in_stock ? "" : html`<span class="row__out">${t(lang, "outOfStock")}</span>`}
    ${signalBadges(ctx.signals.get(p.id), lang)}
  </span>`;
}

function cardRow(ctx: CategoryCtx, p: Product): Html {
  const { lang } = ctx;
  const href = productHash(ctx.category, p.id);
  const name = displayName(p);
  const chips = ctx.columns.map((f) => chipText(p, f, lang)).filter(Boolean);
  return html`<article class="row${p.in_stock ? "" : " is-out"}" data-id="${p.id}" data-href="${href}">
    <a class="row__thumb" href="${href}" tabindex="-1" aria-hidden="true">${thumb(p.thumb ?? p.image, initialsOf(p.brand, p.name), "md")}</a>
    <div class="row__main">
      <div>${titleMarkup(p, lang, href)}</div>
      ${p.brand ? html`<span class="row__brand">${p.brand}</span>` : ""}
      ${chips.length > 0 ? html`<ul class="chip-list row__chips">${chips.map((c) => html`<li>${chip(c)}</li>`)}</ul>` : ""}
    </div>
    <div class="row__buy">
      ${priceBlock(ctx, p, "lg")}
      ${storesMarkup(ctx, p)}
    </div>
    <div class="row__action" aria-label="${name}">${actionMarkup(ctx, p)}<div class="row__tools">${ctx.pickSlot ? "" : compareCheck(p, lang)}${toolsMarkup(ctx, p)}</div></div>
  </article>`;
}

function sortHeader(ctx: CategoryCtx, label: string, asc: SortKey, desc: SortKey, className = ""): Html {
  const active = ctx.params.sort === asc ? "ascending" : ctx.params.sort === desc ? "descending" : "none";
  const next = ctx.params.sort === asc ? desc : asc;
  const arrow = active === "ascending" ? "▴" : active === "descending" ? "▾" : "";
  return html`<th scope="col" class="${className}" aria-sort="${active}"><button type="button" class="th-sort${active !== "none" ? " is-active" : ""}" data-sort="${next}" title="${t(ctx.lang, "sortLabel")}">${label}<span aria-hidden="true">${arrow}</span></button></th>`;
}

function tableRow(ctx: CategoryCtx, p: Product): Html {
  const { lang } = ctx;
  const href = productHash(ctx.category, p.id);
  return html`<tr class="list-row${p.in_stock ? "" : " is-out"}" data-id="${p.id}" data-href="${href}">
    ${ctx.pickSlot ? "" : html`<td class="col-cmp">${compareCell(ctx, p)}</td>`}
    <td class="col-name"><div class="col-name__in"><a class="col-name__thumb" href="${href}" tabindex="-1" aria-hidden="true">${thumb(p.thumb ?? p.image, initialsOf(p.brand, p.name), "sm")}</a><span class="col-name__text">${titleMarkup(p, lang, href)}${p.brand ? html`<span class="row__brand">${p.brand}</span>` : ""}</span></div></td>
    ${ctx.columns.map((f) => html`<td class="col-spec">${specCell(specValue(p, f), lang)}</td>`)}
    <td class="col-stores">${vendorDots(vendorsOf(p))}</td>
    <td class="col-price">${priceBlock(ctx, p, "md")}</td>
    <td class="col-action"><div class="col-action__in">${actionMarkup(ctx, p)}${toolsMarkup(ctx, p)}</div></td>
  </tr>`;
}

function tableMarkup(ctx: CategoryCtx, rows: Product[]): Html {
  const { lang } = ctx;
  return html`<div class="table-wrap"><table class="table list-table">
    <thead><tr>
      ${ctx.pickSlot ? "" : html`<th scope="col" class="col-cmp"><span class="visually-hidden">${t(lang, "compareAction")}</span></th>`}
      ${sortHeader(ctx, t(lang, "nameHeading"), "name", "name_desc")}
      ${ctx.columns.map((f) => html`<th scope="col" class="col-spec" title="${attributeLabel(f, lang, ctx.category)}">${attributeLabel(f, lang, ctx.category)}</th>`)}
      ${sortHeader(ctx, t(lang, "storesHeading"), "vendors_desc", "vendors_desc")}
      ${sortHeader(ctx, t(lang, "priceHeading"), "price_asc", "price_desc", "col-price")}
      <th scope="col"><span class="visually-hidden">${t(lang, "buyHeaderLabel")}</span></th>
    </tr></thead>
    <tbody>${rows.map((p) => tableRow(ctx, p))}</tbody>
  </table></div>`;
}

/** Draws the current page of the filtered list in the active view. */
export function renderList(ctx: CategoryCtx, listEl: HTMLElement, filtered: Product[], tableAllowed: boolean): void {
  const start = ctx.page * PAGE_SIZE;
  const visible = filtered.slice(start, start + PAGE_SIZE);
  listEl.classList.remove("list--table");
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

/** "Showing 1–24 of 234" plus numbered pages (first, last, and the neighbours of the current one). */
export function pagerMarkup(ctx: CategoryCtx, total: number): Html {
  const { lang } = ctx;
  if (total === 0) return html``;
  const pages = Math.ceil(total / PAGE_SIZE);
  const from = ctx.page * PAGE_SIZE + 1;
  const to = Math.min(total, from + PAGE_SIZE - 1);
  const locale = lang === "he" ? "he-IL" : "en-US";
  const summary = html`<span class="pager__info">${showingText(lang, from.toLocaleString(locale), to.toLocaleString(locale), total.toLocaleString(locale))}</span>`;
  if (pages <= 1) return summary;
  const list = [...new Set([0, pages - 1, ctx.page - 1, ctx.page, ctx.page + 1])]
    .filter((n) => n >= 0 && n < pages)
    .sort((a, b) => a - b);
  const items: Html[] = [];
  list.forEach((n, i) => {
    if (i > 0 && n - list[i - 1] > 1) items.push(html`<span class="pager__gap" aria-hidden="true">…</span>`);
    const current = n === ctx.page;
    items.push(html`<button type="button" class="pager__btn${current ? " is-current" : ""}" data-page="${n}"${current ? html` aria-current="page"` : ""}>${(n + 1).toLocaleString(locale)}</button>`);
  });
  const rtl = lang === "he";
  return html`${summary}<div class="pager__pages">
    <button type="button" class="pager__btn" data-page="${ctx.page - 1}"${ctx.page === 0 ? html` disabled` : ""} aria-label="${t(lang, "prevPage")}">${icon(rtl ? "chevron-right" : "chevron-left", 16)}</button>
    ${items}
    <button type="button" class="pager__btn" data-page="${ctx.page + 1}"${ctx.page >= pages - 1 ? html` disabled` : ""} aria-label="${t(lang, "nextPage")}">${icon(rtl ? "chevron-left" : "chevron-right", 16)}</button>
  </div>`;
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
