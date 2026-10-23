import { t } from "../../i18n";
import { fetchListBuild, isValidListId } from "../../lists";
import { getStoredBuild, removeFromBuild, setStoredBuild, type BuildMap } from "../../state";
import type { Currency, Lang } from "../../types";
import { button } from "../../ui/button";
import { card } from "../../ui/card";
import { html, mount, type Html } from "../../ui/html";
import { emptyState, loadingState } from "../../ui/state";
import { bindThumbs } from "../../ui/thumb";
import { bindPageTabs, pageHero } from "../../ui/pageHero";
import { cleanBuild, persist, refreshParts, type BuilderCtx } from "./parts";
import { bindShare, shareCard } from "./share";
import { slotsMarkup } from "./slots";
import { checksMarkup, splitMarkup, statusMarkup, summarize } from "./summary";

function hero(lang: Lang): Html {
  return pageHero({
    lang,
    crumbs: [{ label: t(lang, "builderNav") }],
    title: t(lang, "builderTitle"),
    sub: t(lang, "builderSub"),
    tabs: [
      { label: t(lang, "tabOverview"), href: "#build-top", active: true },
      { label: t(lang, "splitTitle"), href: "#split" },
      { label: t(lang, "compatChecksTitle"), href: "#compat" },
    ],
  });
}

function render(ctx: BuilderCtx): void {
  const { lang } = ctx;
  const summary = summarize(ctx);
  mount(
    ctx.container,
    html`
    ${hero(lang)}
    <div class="builder" id="build-top">
      <section class="card card--flush build-bar">
        ${shareCard(ctx)}
        ${statusMarkup(ctx, summary)}
      </section>
      ${slotsMarkup(ctx)}
      <div class="builder__cards">
        ${splitMarkup(ctx)}
        ${checksMarkup(ctx, summary)}
      </div>
      <p class="fineprint">${t(lang, "disclaimer")}</p>
    </div>`
  );
  bindThumbs(ctx.container);
  bindShare(ctx);
  bindPageTabs(ctx.container);
  ctx.container.querySelector<HTMLAnchorElement>('[data-jump="compat"]')?.addEventListener("click", (e) => {
    e.preventDefault();
    document.getElementById("compat")?.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  const itemCount = Object.values(ctx.build).reduce((n, ids) => n + ids.length, 0);
  ctx.container.querySelector('[data-role="start-new"]')?.addEventListener("click", () => {
    if (itemCount === 0) return;
    for (const key of Object.keys(ctx.build)) delete ctx.build[key];
    persist(ctx);
    void refreshParts(ctx).then(() => render(ctx));
  });

  ctx.container.querySelectorAll<HTMLElement>('[data-action="remove"]').forEach((el) => {
    el.addEventListener("click", () => {
      const { slot, id } = el.dataset;
      if (!slot || !id) return;
      removeFromBuild(ctx.build, slot, id);
      persist(ctx);
      void refreshParts(ctx).then(() => render(ctx));
    });
  });
}

export async function renderBuilder(
  container: HTMLElement,
  lang: Lang,
  currency: Currency,
  shared: BuildMap | null,
  listId: string | null
): Promise<void> {
  const build = cleanBuild(shared ?? getStoredBuild());
  if (shared) setStoredBuild(build);

  const ctx: BuilderCtx = {
    container,
    lang,
    currency,
    build,
    parts: new Map(),
    // After opening a /list/<id> link, the first edit leaves the /list path
    // so reloads stop refetching the snapshot.
    activeListId: listId,
    share: { shortUrlFor: null, pendingKey: null, timer: undefined },
  };

  mount(container, html`${hero(lang)}${loadingState(lang)}`);
  await refreshParts(ctx);
  render(ctx);
}

/**
 * Opens a short /list/<id> link: resolves the stored build (live lookup
 * against today's catalog, unknown ids pruned like any stale link), then
 * hands off to the regular builder. Unknown or malformed ids get an in-app
 * panel instead of a dead page.
 */
export async function renderListRoute(
  container: HTMLElement,
  lang: Lang,
  currency: Currency,
  listId: string
): Promise<void> {
  const unknown = (): void =>
    mount(
      container,
      card(emptyState(t(lang, "unknownList"), button({ label: t(lang, "backToBuilder"), href: "#/build" })), { className: "narrow" })
    );
  if (!isValidListId(listId)) {
    unknown();
    return;
  }
  mount(container, loadingState(lang));
  let shared: BuildMap;
  try {
    shared = await fetchListBuild(listId);
  } catch {
    unknown();
    return;
  }
  await renderBuilder(container, lang, currency, shared, listId);
}
