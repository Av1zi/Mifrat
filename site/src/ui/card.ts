import { html, raw, type Html } from "./html";

interface CardOptions {
  title?: string;
  /** Muted line beside the title (counts, "updated today"). */
  sub?: string | Html;
  /** End-edge header content, e.g. a select or a count. */
  actions?: Html;
  className?: string;
  id?: string;
  tag?: "section" | "div" | "article" | "aside";
  /** Edge-to-edge body (tables): no padding, the head gets a rule. */
  flush?: boolean;
}

export function card(body: Html, options: CardOptions = {}): Html {
  const { title, sub, actions, className = "", id, tag = "section", flush } = options;
  const head =
    title || actions || sub
      ? html`<header class="card__head">${title ? html`<h2 class="card__title">${title}</h2>` : ""}${sub ? html`<span class="card__sub">${sub}</span>` : ""}${actions ?? ""}</header>`
      : "";
  const idAttr = id ? html` id="${id}"` : "";
  return html`${raw(`<${tag}`)} class="card${flush ? " card--flush" : ""} ${className}"${idAttr}>${head}${body}${raw(`</${tag}>`)}`;
}
