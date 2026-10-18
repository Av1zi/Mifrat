import { icon } from "../icons";
import { dataAttrs, html, type Html } from "./html";

type Tone = "neutral" | "brand" | "ok" | "warn" | "err";

interface ChipOptions {
  tone?: Tone;
  href?: string;
  title?: string;
  /** Button chip with a trailing close icon (active-filter chips). */
  removable?: boolean;
  /** data-* attributes, button chips only. */
  data?: Record<string, string>;
  /** Non-interactive and dimmed (values owned by the compatibility filter). */
  locked?: boolean;
}

export function chip(label: string | Html, options: ChipOptions = {}): Html {
  const { tone = "neutral", href, title = "", removable, data, locked } = options;
  const cls = `chip chip--${tone}${locked ? " is-locked" : ""}`;
  if (href) return html`<a class="${cls}" href="${href}" title="${title}"><bdi>${label}</bdi></a>`;
  if (removable) {
    return html`<button type="button" class="${cls}" title="${title}"${dataAttrs(data)}><bdi>${label}</bdi>${icon("close", 12)}</button>`;
  }
  return html`<span class="${cls}" title="${title}"><bdi>${label}</bdi></span>`;
}
