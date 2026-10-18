import { loadCategory } from "../api";
import { t } from "../i18n";
import { MIN_DROP_PCT, loadSignals, type PriceSignal } from "../signals";
import { partRef } from "../storage";
import type { CategoryMeta, Currency, Lang, Product } from "../types";
import { html, mount } from "../ui/html";
import { partCard } from "../ui/partCard";
import { syncPickControls } from "../ui/pick";
import { positivePrice } from "../ui/price";
import { bindThumbs } from "../ui/thumb";
import { displayName } from "../utils";

const STRIP_SIZE = 6;
/** Candidates examined before the in-stock / price-agrees checks narrow them. */
const CANDIDATES = 40;
/** The catalog price may differ from the history's last day by this much (rounding, a fresh scrape). */
const PRICE_AGREES = 0.05;

interface Candidate {
  category: string;
  id: string;
  signal: PriceSignal;
}

/**
 * Fills the home page's "Biggest price drops" section from the history
 * files. Only products with a real recorded drop qualify, and the section
 * stays hidden when none does: nothing here is a placeholder.
 */
export async function fillDropsStrip(
  host: HTMLElement,
  categories: CategoryMeta[],
  lang: Lang,
  currency: Currency
): Promise<void> {
  const perCategory = await Promise.all(
    categories.map(async (cat) => {
      const signals = await loadSignals(cat.id).catch(() => new Map<string, PriceSignal>());
      return [...signals].map(([id, signal]): Candidate => ({ category: cat.id, id, signal }));
    })
  );
  const ranked = perCategory
    .flat()
    .filter((c) => c.signal.dropPct >= MIN_DROP_PCT)
    .sort((a, b) => b.signal.dropPct - a.signal.dropPct || b.signal.days - a.signal.days)
    .slice(0, CANDIDATES);
  if (ranked.length === 0) return;

  const catalogs = new Map<string, Map<string, Product>>();
  await Promise.all(
    [...new Set(ranked.map((c) => c.category))].map(async (id) => {
      const products = await loadCategory(id).catch(() => [] as Product[]);
      catalogs.set(id, new Map(products.map((p) => [p.id, p])));
    })
  );

  const picks: Array<{ candidate: Candidate; product: Product }> = [];
  for (const candidate of ranked) {
    const product = catalogs.get(candidate.category)?.get(candidate.id);
    const price = positivePrice(product?.min_price);
    if (!product || price === null || !product.in_stock) continue;
    if (Math.abs(price - candidate.signal.current) / candidate.signal.current > PRICE_AGREES) continue;
    picks.push({ candidate, product });
    if (picks.length === STRIP_SIZE) break;
  }
  if (picks.length === 0 || !host.isConnected) return;

  mount(
    host,
    html`<header class="section__head">
        <div>
          <h2>${t(lang, "dropsTitle")}</h2>
          <p class="text-dim">${t(lang, "dropsSub")}</p>
        </div>
      </header>
      <div class="part-grid part-grid--strip">${picks.map(({ candidate, product }) =>
        partCard(partRef(product, displayName(product)), product, candidate.signal, lang, currency)
      )}</div>`
  );
  host.hidden = false;
  bindThumbs(host);
  syncPickControls();
}
