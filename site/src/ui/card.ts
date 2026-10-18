import { html, raw, type Html } from "./html";

interface CardOptions {
  title?: string;
  /** End-edge header content, e.g. a select or a count. */
  actions?: Html;
  className?: string;
  id?: string;
  tag?: "section" | "div" | "article" | "aside";
}

export function card(body: Html, options: CardOptions = {}): Html {
  const { title, actions, className = "", id, tag = "section" } = options;
  const head =
    title || actions
      ? html`<header class="card__head">${title ? html`<h2 class="card__title">${title}</h2>` : ""}${actions ?? ""}</header>`
      : "";
  const idAttr = id ? html` id="${id}"` : "";
  return html`${raw(`<${tag}`)} class="card ${className}"${idAttr}>${head}${body}${raw(`</${tag}>`)}`;
}
