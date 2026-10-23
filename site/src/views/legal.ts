import type { Lang } from "../types";
import { card } from "../ui/card";
import { html, mount, raw } from "../ui/html";
import { pageHero } from "../ui/pageHero";

/** Shared frame for the privacy, terms and cookie pages. `body` is trusted static markup. */
export function renderLegalPage(
  container: HTMLElement,
  lang: Lang,
  title: string,
  subtitle: string,
  body: string
): void {
  mount(
    container,
    html`${pageHero({ lang, crumbs: [{ label: title }], title, sub: subtitle })}
      <div class="narrow">${card(html`${raw(body)}`, { className: "prose", tag: "article" })}</div>`
  );
}
