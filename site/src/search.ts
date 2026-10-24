import { loadCategory, loadIndex } from "./api";
import { categoryLabel, t } from "./i18n";
import { navigate, productHash, searchHash } from "./state";
import type { Currency, IndexRow, Lang, Product } from "./types";
import { displayName, normSearch, searchScore, searchTokens } from "./utils";
import { html, mount, type Html } from "./ui/html";
import { initialsOf, thumb } from "./ui/thumb";
import { priceCell } from "./ui/price";

/**
 * Site search over index.json (~500KB, one cached fetch) instead of every
 * category file. Matching covers name/brand/category/id; the displayed hits
 * are then lazy-enriched with their full products (photos) by fetching only
 * their categories. One implementation serves the header box and the home
 * hero box.
 */

interface IndexHit {
  row: IndexRow;
  haystack: string;
  nameHay: string;
  brandHay: string;
  categoryHay: string;
}

interface SearchBox {
  root: HTMLElement;
  input: HTMLInputElement;
  results: HTMLElement;
  lang: Lang;
  currency: Currency;
  seq: number;
}

let indexHits: { lang: Lang; hits: IndexHit[] } | null = null;
const boxes = new Set<SearchBox>();

async function ensureIndex(lang: Lang): Promise<IndexHit[]> {
  if (indexHits && indexHits.lang === lang) return indexHits.hits;
  const rows = await loadIndex();
  const hits = rows.map((row) => ({
    row,
    haystack: normSearch(
      `${row[4] ?? ""} ${row[3] ?? ""} ${row[0]} ${row[1]} ${categoryLabel(row[1], lang)}`
    ),
    nameHay: normSearch(String(row[4] ?? row[0] ?? "")),
    brandHay: normSearch(String(row[3] ?? "")),
    categoryHay: normSearch(categoryLabel(row[1], lang)),
  }));
  indexHits = { lang, hits };
  return hits;
}

function hitMarkup(
  category: string,
  id: string,
  name: string,
  brand: string | null,
  imageSrc: string | null | undefined,
  price: number | null,
  box: SearchBox
): Html {
  return html`<a class="search-hit" role="option" aria-selected="false" href="${productHash(category, id)}">
    ${thumb(imageSrc, initialsOf(brand, name), "sm")}
    <span class="search-hit__name">${name}<span class="search-hit__cat">${categoryLabel(category, box.lang)}</span></span>
    ${priceCell(price, box.currency, box.lang)}
  </a>`;
}

function interimHit(row: IndexRow, box: SearchBox): Html {
  return hitMarkup(row[1], row[0], row[4] ?? row[0], row[3], null, row[2], box);
}

function fullHit(product: Product, box: SearchBox): Html {
  return hitMarkup(
    product.category,
    product.id,
    displayName(product),
    product.brand,
    product.thumb ?? product.image,
    product.min_price,
    box
  );
}

function setOpen(box: SearchBox, open: boolean): void {
  box.results.hidden = !open;
  box.input.setAttribute("aria-expanded", open ? "true" : "false");
}

/**
 * Index rows matching `query`, best first. Ranked before slicing so an exact
 * name match is not lost below products that merely contain the words.
 */
export async function searchIndex(lang: Lang, query: string, limit = Infinity): Promise<IndexRow[]> {
  const index = await ensureIndex(lang);
  const tokens = searchTokens(query);
  if (tokens.length === 0) return [];
  return index
    .map((entry) => ({
      entry,
      score: searchScore(tokens, {
        haystack: entry.haystack,
        name: entry.nameHay,
        brand: entry.brandHay,
        category: entry.categoryHay,
      }),
    }))
    .filter((candidate) => candidate.score >= 0)
    .sort(
      (a, b) =>
        b.score - a.score ||
        a.entry.nameHay.length - b.entry.nameHay.length ||
        a.entry.nameHay.localeCompare(b.entry.nameHay)
    )
    .slice(0, limit)
    .map((candidate) => candidate.entry.row);
}

/** "See all results" row at the foot of the dropdown. */
function allResultsLink(box: SearchBox, query: string, found: boolean): Html {
  return html`<a class="search-all" href="${searchHash(query)}">${found ? t(box.lang, "searchAllResults") : t(box.lang, "searchOpenPage")}<span dir="auto">„${query}”</span></a>`;
}

async function run(box: SearchBox, query: string, seq: number): Promise<void> {
  if (query.length < 2) {
    box.results.innerHTML = "";
    setOpen(box, false);
    return;
  }
  setOpen(box, true);
  mount(box.results, html`<div class="search-status" role="status">${t(box.lang, "loading")}</div>`);
  try {
    const rows = await searchIndex(box.lang, query, 8);
    if (seq !== box.seq) return;
    const hits = rows.map((row) => ({ row }));
    if (hits.length === 0) {
      mount(box.results, html`<div class="search-status" role="status">${t(box.lang, "noResults")}</div>${allResultsLink(box, query, false)}`);
      return;
    }
    mount(box.results, html`${hits.map((h) => interimHit(h.row, box))}${allResultsLink(box, query, true)}`);

    const byCategory = new Map<string, IndexRow[]>();
    for (const h of hits) {
      const list = byCategory.get(h.row[1]) ?? [];
      list.push(h.row);
      byCategory.set(h.row[1], list);
    }
    const found = new Map<string, Product>();
    await Promise.all(
      [...byCategory].map(async ([category, rows]) => {
        try {
          const products = await loadCategory(category);
          for (const row of rows) {
            const p = products.find((x) => x.id === row[0]);
            if (p) found.set(row[0], p);
          }
        } catch {
          // Keep the interim rows when one category fails.
        }
      })
    );
    if (seq !== box.seq) return;
    mount(
      box.results,
      html`${hits.map((h) => {
        const p = found.get(h.row[0]);
        return p ? fullHit(p, box) : interimHit(h.row, box);
      })}${allResultsLink(box, query, true)}`
    );
  } catch {
    if (seq !== box.seq) return;
    mount(box.results, html`<div class="search-status" role="status">${t(box.lang, "loadError")}</div>`);
  }
}

/**
 * Wires a search box. `root` holds `input[data-search-input]` and
 * `[data-search-results]`. Safe to call again after the DOM is replaced.
 */
export function bindSearch(root: HTMLElement, lang: Lang, currency: Currency): void {
  const input = root.querySelector<HTMLInputElement>("[data-search-input]");
  const results = root.querySelector<HTMLElement>("[data-search-results]");
  if (!input || !results) return;
  const box: SearchBox = { root, input, results, lang, currency, seq: 0 };
  boxes.add(box);

  let timer: number | undefined;
  input.addEventListener("input", () => {
    window.clearTimeout(timer);
    const query = input.value.trim();
    input.setAttribute("aria-expanded", query.length >= 2 ? "true" : "false");
    timer = window.setTimeout(() => {
      box.seq += 1;
      void run(box, query, box.seq);
    }, 220);
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      setOpen(box, false);
      return;
    }
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp" && e.key !== "Enter") return;
    const hits = Array.from(results.querySelectorAll<HTMLElement>(".search-hit"));
    let idx = hits.findIndex((h) => h.classList.contains("is-active"));
    if (e.key === "Enter") {
      // A highlighted hit opens; otherwise Enter goes to the full results page.
      e.preventDefault();
      if (idx >= 0) hits[idx].click();
      else if (input.value.trim().length > 0) {
        setOpen(box, false);
        navigate(searchHash(input.value.trim()));
      }
      return;
    }
    if (hits.length === 0) return;
    e.preventDefault();
    if (e.key === "ArrowDown") idx = idx < hits.length - 1 ? idx + 1 : 0;
    else idx = idx > 0 ? idx - 1 : hits.length - 1;
    hits.forEach((h, i) => {
      h.classList.toggle("is-active", i === idx);
      h.setAttribute("aria-selected", i === idx ? "true" : "false");
      if (i === idx) h.scrollIntoView({ block: "nearest" });
    });
  });
}

/** Closes every open results list (route change, outside click). */
export function closeSearchResults(except?: EventTarget | null): void {
  for (const box of boxes) {
    if (!box.root.isConnected) {
      boxes.delete(box);
      continue;
    }
    if (except instanceof Node && box.root.contains(except)) continue;
    setOpen(box, false);
  }
}
