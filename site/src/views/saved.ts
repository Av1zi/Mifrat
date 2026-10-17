import { loadCategory } from "../api";
import { t } from "../i18n";
import { icon } from "../icons";
import { getSaved, onSavedChange } from "../saved";
import { loadSignals } from "../signals";
import { categoriesHash, parseRoute } from "../state";
import { setPageTitle } from "../titles";
import type { Currency, Lang, Product } from "../types";
import { button } from "../ui/button";
import { html, mount } from "../ui/html";
import { partCard } from "../ui/partCard";
import { syncPickControls } from "../ui/pick";
import { emptyState, loadingState } from "../ui/state";
import { bindThumbs } from "../ui/thumb";

/** Bumped per render so a superseded instance (language switch) stops redrawing. */
let generation = 0;

/** Saved parts (localStorage only), with live prices and signals where the catalog still lists them. */
export async function renderSaved(container: HTMLElement, lang: Lang, currency: Currency): Promise<void> {
  setPageTitle(lang, t(lang, "savedTitle"), t(lang, "metaSavedDesc"));
  mount(container, loadingState(lang));
  const mine = ++generation;
  const alive = (): boolean => mine === generation && parseRoute().view === "saved";

  const draw = async (): Promise<void> => {
    const saved = getSaved();
    const categories = [...new Set(saved.map((p) => p.category))];
    const loaded = await Promise.all(
      categories.map(async (id) => {
        const [products, signals] = await Promise.all([loadCategory(id).catch(() => [] as Product[]), loadSignals(id).catch(() => new Map())]);
        return [id, { byId: new Map(products.map((p) => [p.id, p])), signals }] as const;
      })
    );
    if (!alive()) return;
    const data = new Map(loaded);

    mount(
      container,
      html`<div data-saved-root>
        <header class="page-head">
          <h1>${t(lang, "savedTitle")}</h1>
          <p>${t(lang, "savedHint")}</p>
        </header>
        ${saved.length === 0
          ? emptyState(t(lang, "savedEmpty"), button({ label: t(lang, "savedBrowse"), icon: icon("forward", 14), variant: "primary", href: categoriesHash() }))
          : html`<div class="part-grid">${saved.map((ref) => {
              const entry = data.get(ref.category);
              return partCard(ref, entry?.byId.get(ref.id), entry?.signals.get(ref.id), lang, currency);
            })}</div>`}
      </div>`
    );
    bindThumbs(container);
    syncPickControls();
  };

  await draw();

  // Removing a heart here redraws the list; a stale instance unsubscribes itself.
  const off = onSavedChange(() => {
    if (alive()) void draw();
    else off();
  });
}
