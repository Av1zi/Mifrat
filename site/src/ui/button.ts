import { dataAttrs, html, type Html } from "./html";

interface ButtonOptions {
  label: string | Html;
  icon?: Html;
  variant?: "primary" | "ghost" | "subtle";
  size?: "sm" | "md";
  /** Renders an anchor instead of a button. */
  href?: string;
  external?: boolean;
  id?: string;
  title?: string;
  ariaLabel?: string;
  data?: Record<string, string>;
  disabled?: boolean;
  className?: string;
  /** Icon-only button: the label becomes the accessible name. */
  iconOnly?: boolean;
  /** Toggle buttons: renders aria-pressed (button only). */
  pressed?: boolean;
}

export function button(options: ButtonOptions): Html {
  const {
    label,
    icon,
    variant = "ghost",
    size = "md",
    href,
    external,
    id,
    title,
    ariaLabel,
    data,
    disabled,
    className = "",
    iconOnly,
    pressed,
  } = options;
  const cls = `btn btn--${variant} btn--${size}${iconOnly ? " btn--icon" : ""} ${className}`;
  const inner = iconOnly
    ? html`${icon ?? ""}<span class="visually-hidden">${label}</span>`
    : html`${icon ?? ""}<span>${label}</span>`;
  const idAttr = id ? html` id="${id}"` : "";
  const titleAttr = title ? html` title="${title}"` : "";
  const ariaAttr = ariaLabel ? html` aria-label="${ariaLabel}"` : "";
  if (href !== undefined) {
    const rel = external ? html` target="_blank" rel="noopener noreferrer"` : "";
    return html`<a class="${cls}" href="${href}"${rel}${idAttr}${titleAttr}${ariaAttr}${dataAttrs(data)}>${inner}</a>`;
  }
  const pressedAttr = pressed === undefined ? "" : html` aria-pressed="${pressed ? "true" : "false"}"`;
  return html`<button type="button" class="${cls}"${idAttr}${pressedAttr}${titleAttr}${ariaAttr}${dataAttrs(data)}${disabled ? html` disabled` : ""}>${inner}</button>`;
}
