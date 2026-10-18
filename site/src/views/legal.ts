import { t } from "../i18n";
import { icon } from "../icons";
import { homeHash } from "../state";
import type { Lang } from "../types";
import { card } from "../ui/card";
import { html, mount, raw } from "../ui/html";

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
    html`<div class="narrow">
      <nav class="crumbs"><a href="${homeHash()}">${icon("back", 14)}${t(lang, "backToHome")}</a></nav>
      <header class="page-head"><h1>${title}</h1><p>${subtitle}</p></header>
      ${card(html`${raw(body)}`, { className: "prose", tag: "article" })}
    </div>`
  );
}
