import { loadCategory } from "../api";
import { formatPrice } from "../format";
import { categoryLabel, CATEGORY_ORDER, searchResultsCount, t } from "../i18n";
import { icon } from "../icons";
import { bestOffer, effectivePrice } from "../offers";
import { searchIndex } from "../search";
import { categoriesHash, categoryHash, productHash, searchHash } from "../state";
import { setPageTitle } from "../titles";
import type { Currency, IndexRow, Lang, Product } from "../types";
import { emptyBox, fillQuickCats, quickCats } from "../ui/emptyBox";
import { html, mount, type Html } from "../ui/html";
import { pageHero } from "../ui/pageHero";
import { saveButton, syncPickControls } from "../ui/pick";
import { emptyValue } from "../ui/empty";
import { errorState, loadingState } from "../ui/state";
import { bindThumbs, initialsOf, thumb } from "../ui/thumb";
import { vendorTag } from "../ui/vendor";
import { displayName } from "../utils";

/** Results shown on the page; the per-category links reach the rest. */
const SHOWN = 48;

/**
 * "Did you mean": shorter versions of the query (dropping words from the end,
 * then from the start) that do have results. Only real queries, never guesses.
 */
async function suggestions(lang: Lang, query: string): Promise<string[]> {
  const words = query.trim().split(/\s+/).filter(Boolean);
  const candidates: string[] = [];
  for (let n = words.length - 1; n >= 1; n--) candidates.push(words.slice(0, n).join(" "));
  for (let n = 1; n < words.length; n++) candidates.push(words.slice(n).join(" "));
  const out: string[] = [];
  for (const candidate of [...new Set(candidates)]) {
    if (candidate.length < 2) continue;
    if ((await searchIndex(lang, candidate, 1)).length > 0) out.push(candidate);
    if (out.length === 4) break;
  }
  return out;
}

function resultRow(row: IndexRow, product: Product | undefined, lang: Lang, currency: Currency): Html {
  const [id, category, minPrice, brand, name] = row;
  const href = productHash(category, id);
  const label = product ? displayName(product) : name ?? id;
  const price = product ? effectivePrice(product) : minPrice && minPrice > 0 ? minPrice : null;
  const offer = product ? bestOffer(product) : null;
  return html`<article class="sr-row">
    <a class="sr-row__thumb" href="${href}" tabindex="-1" aria-hidden="true">${thumb(product?.thumb ?? product?.image, initialsOf(brand, label), "md")}</a>
    <div class="sr-row__main">
      <span class="sr-row__cat">${categoryLabel(category, lang)}</span>
      <a class="sr-row__name" href="${href}" dir="auto">${label}</a>
      ${brand ? html`<span class="sr-row__brand">${brand}</span>` : ""}
    </div>
    <div class="sr-row__buy">
      <b>${price !== null ? formatPrice(price, currency, lang) : emptyValue(lang)}</b>
      ${offer ? vendorTag(offer.vendor) : ""}
    </div>
    <div class="sr-row__tools">${product ? saveButton(product, lang) : ""}<a class="btn btn--primary btn--sm" href="${href}">${t(lang, "allPrices")}</a></div>
  </article>`;
}

/** #/search?q=: every catalog match, grouped counts per category, or the designed empty state. */
export async function renderSearch(container: HTMLElement, lang: Lang, currency: Currency, query: string): Promise<void> {
  const q = query.trim();
  setPageTitle(lang, q ? `${t(lang, "searchTitle")}: ${q}` : t(lang, "searchTitle"));
  const hero = (count: number | null): Html =>
    pageHero({
      lang,
      crumbs: [{ label: t(lang, "searchCrumb") }],
      title: t(lang, "searchTitle"),
      sub: q && count !== null ? html`${searchResultsCount(lang, count)} „<bdi>${q}</bdi>”` : undefined,
    });
  mount(container, html`${hero(null)}${loadingState(lang)}`);

  let rows: IndexRow[];
  try {
    rows = q.length >= 2 ? await searchIndex(lang, q) : [];
  } catch (err) {
    mount(container, html`${hero(null)}${errorState(lang, err)}`);
    return;
  }

  if (rows.length === 0) {
    const ideas = q ? await suggestions(lang, q) : [];
    mount(
      container,
      html`${hero(0)}
      <div class="search-empty">
        ${emptyBox({
          icon: "search",
          title: q ? html`${t(lang, "noMatchFor")} „<bdi>${q}</bdi>”` : t(lang, "searchEmptyPrompt"),
          body: t(lang, "searchEmptyBody"),
          extra:
            ideas.length > 0
              ? html`<div class="suggest"><span class="suggest__label">${t(lang, "didYouMean")}</span><div class="pills">${ideas.map(
                  (idea) => html`<a class="pill" href="${searchHash(idea)}" dir="auto">${idea}</a>`
                )}</div></div>`
              : undefined,
          actions: html`<a class="btn btn--primary" href="${categoriesHash()}">${t(lang, "homeBrowseCta")}</a>
            <button type="button" class="btn btn--ghost" data-role="clear-search">${t(lang, "clearSearch")}</button>`,
        })}
        ${quickCats(lang, t(lang, "browseByCategory"))}
      </div>`
    );
    fillQuickCats(container, lang);
    container.querySelector('[data-role="clear-search"]')?.addEventListener("click", () => {
      const input = document.querySelector<HTMLInputElement>(".site-header [data-search-input]");
      if (input) {
        input.value = "";
        input.focus();
      }
    });
    return;
  }

  // Full product rows for what is shown (photos, live best store).
  const shown = rows.slice(0, SHOWN);
  const products = new Map<string, Product>();
  await Promise.all(
    [...new Set(shown.map((r) => r[1]))].map(async (category) => {
      const list = await loadCategory(category).catch(() => [] as Product[]);
      const wanted = new Set(shown.filter((r) => r[1] === category).map((r) => r[0]));
      for (const p of list) if (wanted.has(p.id)) products.set(p.id, p);
    })
  );
  if (!container.isConnected) return;

  const order = CATEGORY_ORDER as readonly string[];
  const rank = (id: string): number => (order.indexOf(id) === -1 ? order.length : order.indexOf(id));
  const perCategory = new Map<string, number>();
  for (const r of rows) perCategory.set(r[1], (perCategory.get(r[1]) ?? 0) + 1);
  const cats = [...perCategory].sort((a, b) => b[1] - a[1] || rank(a[0]) - rank(b[0]));

  mount(
    container,
    html`${hero(rows.length)}
    <nav class="sr-cats" aria-label="${t(lang, "filterByCategory")}">
      <span class="sr-cats__label">${t(lang, "searchInCategoryLabel")}</span>
      <div class="pills">${cats.map(
        ([id, n]) => html`<a class="pill" href="${categoryHash(id, { q })}">${categoryLabel(id, lang)}<span class="pill__n">${n}</span></a>`
      )}</div>
    </nav>
    <div class="sr-list">${shown.map((r) => resultRow(r, products.get(r[0]), lang, currency))}</div>
    ${rows.length > SHOWN ? html`<p class="sr-more">${icon("info", 16)}${t(lang, "searchMoreHint")}</p>` : ""}`
  );
  bindThumbs(container);
  syncPickControls();
}
