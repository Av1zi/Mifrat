import { esc } from "../utils";

/**
 * A fragment that is already safe to put into innerHTML. `html` returns one;
 * everything else interpolated into an `html` template is escaped.
 */
export class Html {
  constructor(readonly value: string) {}
  toString(): string {
    return this.value;
  }
}

type Hole = Html | string | number | boolean | null | undefined | Hole[];

function part(hole: Hole): string {
  if (hole === null || hole === undefined || typeof hole === "boolean") return "";
  if (hole instanceof Html) return hole.value;
  if (Array.isArray(hole)) return hole.map(part).join("");
  return esc(hole);
}

/**
 * Tagged template for markup. Strings and numbers are escaped, nested `html`
 * fragments and arrays of them pass through, `false`/`null`/`undefined`
 * render nothing (so `${cond && html`...`}` works).
 */
export function html(strings: TemplateStringsArray, ...holes: Hole[]): Html {
  let out = strings[0];
  for (let i = 0; i < holes.length; i++) out += part(holes[i]) + strings[i + 1];
  return new Html(out);
}

/** Marks a string as trusted markup (static SVG, pre-escaped fragments). */
export function raw(markup: string): Html {
  return new Html(markup);
}

export function mount(el: Element, fragment: Html): void {
  el.innerHTML = fragment.value;
}

/** `data-*` attribute list from a record (values escaped). */
export function dataAttrs(data: Record<string, string> | undefined): Html {
  if (!data) return new Html("");
  return new Html(
    Object.entries(data)
      .map(([key, value]) => ` data-${key}="${esc(value)}"`)
      .join("")
  );
}
