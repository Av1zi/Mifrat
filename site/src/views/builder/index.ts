import { t } from "../../i18n";
import { fetchListBuild, isValidListId } from "../../lists";
import { icon } from "../../icons";
import { getStoredBuild, removeFromBuild, savedHash, setStoredBuild, type BuildMap } from "../../state";
import { setPageTitle } from "../../titles";
import type { Currency, Lang } from "../../types";
import { html, mount, type Html } from "../../ui/html";
import { loadingState } from "../../ui/state";
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
  const unknown = (): void => {
    setPageTitle(lang, t(lang, "brokenTitle"));
    // The link exactly as opened, so the visitor can see whether it was cut short.
    const opened = `${location.host}${location.pathname}`;
    mount(
      container,
      html`<section class="card broken">
        <div class="broken__main">
          <span class="state-ic state-ic--warn" aria-hidden="true">${icon("unlink", 32)}</span>
          <h1>${t(lang, "brokenTitle")}</h1>
          <p>${t(lang, "brokenBody")}</p>
          <span class="code-chip" title="${t(lang, "brokenOpened")}">${opened}</span>
          <div class="empty-box__actions">
            <a class="btn btn--primary" href="${savedHash()}">${icon("heart", 16)}${t(lang, "brokenToSaved")}</a>
            <a class="btn btn--ghost" href="#/build">${icon("wrench", 16)}${t(lang, "builderNav")}</a>
          </div>
        </div>
        <div class="broken__help">
          <strong>${t(lang, "brokenHelpTitle")}</strong>
          <ul>
            <li>${t(lang, "brokenHelp1")}</li>
            <li>${t(lang, "brokenHelp2")}</li>
            <li>${t(lang, "brokenHelp3")}</li>
          </ul>
        </div>
      </section>`
    );
  };
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
