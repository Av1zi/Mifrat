import { vendorLabel } from "../i18n";
import { html, type Html } from "./html";

const KNOWN = new Set(["tms", "onepc", "ivory", "yahav", "plonter"]);

/** CSS key for a vendor's colour tokens (--v-<key>); "1pc" is an alias. */
export function vendorKey(vendor: string): string {
  const id = vendor.toLowerCase() === "1pc" ? "onepc" : vendor.toLowerCase();
  return KNOWN.has(id) ? id : "other";
}

const MONOGRAMS: Record<string, string> = { tms: "TMS", onepc: "1PC", ivory: "IV", yahav: "YH", plonter: "PL" };

export function vendorDot(vendor: string): Html {
  return html`<span class="vdot vdot--${vendorKey(vendor)}" aria-hidden="true"></span>`;
}

/** Coloured dot + vendor name. */
export function vendorTag(vendor: string): Html {
  return html`<span class="vtag">${vendorDot(vendor)}<span>${vendorLabel(vendor)}</span></span>`;
}

/** Square monogram badge for offer tables. */
export function vendorMono(vendor: string): Html {
  const key = vendorKey(vendor);
  return html`<span class="vmono vmono--${key}" aria-hidden="true">${MONOGRAMS[key] ?? vendorLabel(vendor).slice(0, 3).toUpperCase()}</span>`;
}

/** One dot per vendor that sells the part (list rows). */
export function vendorDots(vendors: string[]): Html {
  return html`<span class="vdots" title="${vendors.map(vendorLabel).join(", ")}">${vendors.map(vendorDot)}<span class="vdots__n">${vendors.length}</span></span>`;
}
