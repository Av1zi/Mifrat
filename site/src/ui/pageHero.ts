import { t } from "../i18n";
import { homeHash } from "../state";
import type { Lang } from "../types";
import { html, type Html } from "./html";

export interface Crumb {
  label: string;
  /** Omitted on the current page (the last crumb). */
  href?: string;
}

interface HeroOptions {
  lang: Lang;
  /** Trail after "Home"; the last entry is the current page. */
  crumbs?: Crumb[];
  title: string | Html;
  /** Product names are Latin: let the browser pick their direction. */
  titleDir?: "auto";
  sub?: string | Html;
  /** Extra row under the title (spec chips, SKU). */
  meta?: Html;
  /** In-page tabs docked to the band's bottom edge. */
  tabs?: Array<{ label: string; href: string; active?: boolean }>;
  /** End-side content beside the title (actions). */
  aside?: Html;
}

/**
 * The ink band every inner page opens with: breadcrumbs, title, optional
 * subtitle / meta row / anchor tabs. Spans the full width (.bleed).
 */
export function pageHero(options: HeroOptions): Html {
  const { lang, crumbs = [], title, titleDir, sub, meta, tabs, aside } = options;
  const trail: Crumb[] = [{ label: t(lang, "homeCrumb"), href: homeHash() }, ...crumbs];
  return html`<section class="bleed page-hero${tabs ? " page-hero--tabs" : ""}">
    <div class="bleed__inner page-hero__inner">
      <nav class="crumbs" aria-label="${t(lang, "breadcrumbs")}">
        ${trail.map((c, i) =>
          html`${i > 0 ? html`<span class="crumbs__sep" aria-hidden="true">/</span>` : ""}${
            c.href
              ? html`<a href="${c.href}">${c.label}</a>`
              : html`<span aria-current="page">${c.label}</span>`
          }`
        )}
      </nav>
      <div class="page-hero__row">
        <div class="page-hero__text">
          <h1${titleDir ? html` dir="${titleDir}"` : ""}>${title}</h1>
          ${sub ? html`<p class="page-hero__sub">${sub}</p>` : ""}
        </div>
        ${aside ? html`<div class="page-hero__aside">${aside}</div>` : ""}
      </div>
      ${meta ?? ""}
      ${tabs
        ? html`<nav class="page-tabs" aria-label="${t(lang, "sectionsNav")}">${tabs.map(
            (tab) => html`<a class="page-tab${tab.active ? " is-active" : ""}" href="${tab.href}" data-tab-target="${tab.href}">${tab.label}</a>`
          )}</nav>`
        : ""}
    </div>
  </section>`;
}

/**
 * In-page anchor tabs: hash routing owns location.hash, so clicks scroll
 * instead of navigating, and the active tab follows the scroll position.
 */
export function bindPageTabs(root: ParentNode): void {
  const tabs = Array.from(root.querySelectorAll<HTMLAnchorElement>(".page-tab[data-tab-target]"));
  if (tabs.length === 0) return;
  const targets = tabs.map((tab) => {
    const id = (tab.dataset.tabTarget ?? "").replace(/^#/, "");
    return id ? document.getElementById(id) : null;
  });
  const activate = (index: number): void => tabs.forEach((tab, i) => tab.classList.toggle("is-active", i === index));
  tabs.forEach((tab, i) => {
    tab.addEventListener("click", (e) => {
      e.preventDefault();
      const target = targets[i];
      if (target) target.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
      else window.scrollTo({ top: 0, behavior: "smooth" });
      activate(i);
    });
  });
  const onScroll = (): void => {
    if (!tabs[0].isConnected) {
      window.removeEventListener("scroll", onScroll);
      return;
    }
    const line = 140;
    let current = 0;
    targets.forEach((el, i) => {
      if (el && el.getBoundingClientRect().top <= line) current = i;
    });
    activate(current);
  };
  window.addEventListener("scroll", onScroll, { passive: true });
}
