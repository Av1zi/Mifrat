/**
 * Inline SVG icon set. All icons are Lucide (ISC licensed,
 * https://lucide.dev) in its 24px grid style, except `graphics` which is
 * drawn in the same stroke style because Lucide ships no GPU glyph.
 * No emoji, no icon fonts, no external requests.
 */

import { raw, type Html } from "./ui/html";

export type IconName =
  | "wrench"
  | "chip"
  | "search"
  | "chevron"
  | "sun"
  | "moon"
  | "copy"
  | "plus"
  | "trash"
  | "bolt"
  | "close"
  | "globe"
  | "coin"
  | "check"
  | "memory"
  | "droplet"
  | "grid"
  | "board"
  | "drive"
  | "graphics"
  | "power"
  | "tower"
  | "fan"
  | "case-fan"
  | "radiator"
  | "heatsink"
  | "cooling-other"
  | "accessories"
  | "file-text"
  | "sliders"
  | "back"
  | "forward"
  | "rows"
  | "table"
  | "alert"
  | "circle-x"
  | "circle-check"
  | "external"
  | "shield"
  | "heart"
  | "compare"
  | "trend-down"
  | "cart"
  | "link"
  | "pencil"
  | "info"
  | "save"
  | "clock"
  | "chevron-left"
  | "chevron-right"
  | "store";

const PATHS: Record<IconName, string> = {
  wrench:
    '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />',
  chip:
    '<rect width="16" height="16" x="4" y="4" rx="2" /><rect width="6" height="6" x="9" y="9" rx="1" /><path d="M15 2v2" /><path d="M15 20v2" /><path d="M2 15h2" /><path d="M2 9h2" /><path d="M20 15h2" /><path d="M20 9h2" /><path d="M9 2v2" /><path d="M9 20v2" />',
  search:
    '<circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" />',
  chevron:
    '<path d="m6 9 6 6 6-6" />',
  sun:
    '<circle cx="12" cy="12" r="4" /><path d="M12 2v2" /><path d="M12 20v2" /><path d="m4.93 4.93 1.41 1.41" /><path d="m17.66 17.66 1.41 1.41" /><path d="M2 12h2" /><path d="M20 12h2" /><path d="m6.34 17.66-1.41 1.41" /><path d="m19.07 4.93-1.41 1.41" />',
  moon:
    '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />',
  copy:
    '<rect width="14" height="14" x="8" y="8" rx="2" ry="2" /><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" />',
  plus:
    '<path d="M5 12h14" /><path d="M12 5v14" />',
  trash:
    '<path d="M3 6h18" /><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" /><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" /><line x1="10" x2="10" y1="11" y2="17" /><line x1="14" x2="14" y1="11" y2="17" />',
  bolt:
    '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z" />',
  close:
    '<path d="M18 6 6 18" /><path d="m6 6 12 12" />',
  globe:
    '<circle cx="12" cy="12" r="10" /><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20" /><path d="M2 12h20" />',
  coin:
    '<circle cx="8" cy="8" r="6" /><path d="M18.09 10.37A6 6 0 1 1 10.34 18" /><path d="M7 6h1v4" /><path d="m16.71 13.88.7.71-2.82 2.82" />',
  check:
    '<path d="M20 6 9 17l-5-5" />',
  memory:
    '<path d="M6 19v-3" /><path d="M10 19v-3" /><path d="M14 19v-3" /><path d="M18 19v-3" /><path d="M8 11V9" /><path d="M16 11V9" /><path d="M12 11V9" /><path d="M2 15h20" /><path d="M2 7a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v1.1a2 2 0 0 0 0 3.837V17a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-5.1a2 2 0 0 0 0-3.837Z" />',
  droplet:
    '<path d="M12 22a7 7 0 0 0 7-7c0-2-1-3.9-3-5.5s-3.5-4-4-6.5c-.5 2.5-2 4.9-4 6.5C6 11.1 5 13 5 15a7 7 0 0 0 7 7Z" />',
  accessories:
    '<rect x="3" y="7" width="18" height="13" rx="1.5" /><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12h18" />',
  grid:
    '<rect width="7" height="7" x="3" y="3" rx="1" /><rect width="7" height="7" x="14" y="3" rx="1" /><rect width="7" height="7" x="14" y="14" rx="1" /><rect width="7" height="7" x="3" y="14" rx="1" />',
  board:
    '<rect x="3" y="3" width="18" height="18" rx="1.5" /><path d="M7 7h4v4H7zM13 13h4v4h-4zM11 9h3M9 11v4" />',
  drive:
    '<rect x="3" y="5" width="18" height="14" rx="2" /><path d="M7 9h10M7 13h6" /><circle cx="17" cy="14" r="1" />',
  graphics:
    '<rect x="2.5" y="5" width="19" height="11" rx="1.5" /><circle cx="9.5" cy="10.5" r="2.6" /><circle cx="15.5" cy="10.5" r="2.6" /><path d="M6 16v3.5h12V16" />',
  power:
    '<rect x="2.5" y="5" width="19" height="14" rx="1.5" /><circle cx="9" cy="12" r="3.4" /><path d="M9 8.6v6.8" /><path d="M15.5 9.5h3.5M15.5 12h3.5M15.5 14.5h3.5" />',
  tower:
    '<rect x="6" y="2" width="12" height="20" rx="1.5" /><path d="M9 5h6v5H9zM9 14h2M13 14h2M9 18h2M13 18h2" />',
  fan:
    '<circle cx="12" cy="12" r="2.5" /><path d="M12 9c-1-4 2-6 4-5s1 4-2 6M15 12c4-1 6 2 5 4s-4 1-6-2M12 15c1 4-2 6-4 5s-1-4 2-6M9 12c-4 1-6-2-5-4s4-1 6 2" />',
  "case-fan":
    '<rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="12" cy="12" r="2.2" /><path d="M12 9.8c-1-4 2-6 4-5s1 4-2 6M14.2 12c4-1 6 2 5 4s-4 1-6-2M12 14.2c1 4-2 6-4 5s-1-4 2-6M9.8 12c-4 1-6-2-5-4s4-1 6 2" />',
  radiator:
    '<rect x="3" y="4" width="18" height="6" rx="1" /><path d="M6.5 4v6M10 4v6M13.5 4v6M17 4v6" /><circle cx="12" cy="16.5" r="3" /><path d="M6.5 10v3.5a3 3 0 0 0 2.7 3M17.5 10v3.5a3 3 0 0 1-2.7 3" />',
  heatsink:
    '<path d="M7 3v13M10.5 3v13M14 3v13M17.5 3v13" /><path d="M4.5 16h15v1.5a2.5 2.5 0 0 1-2.5 2.5H7a2.5 2.5 0 0 1-2.5-2.5z" />',
  "cooling-other":
    '<path d="M12 2v20" /><path d="m3.5 7 17 10" /><path d="m20.5 7-17 10" /><path d="M9.5 4 12 6.5 14.5 4" /><path d="M9.5 20 12 17.5 14.5 20" />',
  "file-text":
    '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6M8 13h8M8 17h6" />',
  sliders:
    '<path d="M21 4H14M10 4H3M21 12H12M8 12H3M21 20H16M12 20H3M14 2v4M8 10v4M16 18v4" />',
  back:
    '<path d="m12 19-7-7 7-7" /><path d="M19 12H5" />',
  forward:
    '<path d="M5 12h14" /><path d="m12 5 7 7-7 7" />',
  rows:
    '<rect width="7" height="7" x="3" y="3" rx="1" /><rect width="7" height="7" x="3" y="14" rx="1" /><path d="M14 4h7M14 9h7M14 15h7M14 20h7" />',
  table:
    '<path d="M9 3H5a2 2 0 0 0-2 2v4m6-6h10a2 2 0 0 1 2 2v4M9 3v18m0 0h10a2 2 0 0 0 2-2V9M9 21H5a2 2 0 0 1-2-2V9m0 0h18" />',
  alert:
    '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3" /><path d="M12 9v4M12 17h.01" />',
  "circle-x":
    '<circle cx="12" cy="12" r="10" /><path d="m15 9-6 6M9 9l6 6" />',
  "circle-check":
    '<circle cx="12" cy="12" r="10" /><path d="m9 12 2 2 4-4" />',
  external:
    '<path d="M15 3h6v6M10 14 21 3" /><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />',
  shield:
    '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z" /><path d="m9 12 2 2 4-4" />',
  heart:
    '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z" />',
  compare:
    '<rect width="18" height="18" x="3" y="3" rx="2" /><path d="M9 3v18M15 3v18" />',
  "trend-down":
    '<path d="m22 17-8.5-8.5-5 5L2 7" /><path d="M16 17h6v-6" />',
  cart:
    '<circle cx="8" cy="21" r="1" /><circle cx="19" cy="21" r="1" /><path d="M2.05 2.05h2l2.66 12.42a2 2 0 0 0 2 1.58h9.78a2 2 0 0 0 1.95-1.57l1.65-7.43H5.12" />',
  link:
    '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" /><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />',
  pencil:
    '<path d="M21.17 6.81a1 1 0 0 0-3.99-3.99L3.84 16.17a2 2 0 0 0-.5.83l-1.32 4.35a.5.5 0 0 0 .62.62l4.35-1.32a2 2 0 0 0 .83-.5z" /><path d="m15 5 4 4" />',
  info:
    '<circle cx="12" cy="12" r="10" /><path d="M12 16v-4M12 8h.01" />',
  save:
    '<path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z" /><path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7" /><path d="M7 3v4a1 1 0 0 0 1 1h7" />',
  clock:
    '<circle cx="12" cy="12" r="10" /><path d="M12 6v6l4 2" />',
  "chevron-left":
    '<path d="m15 18-6-6 6-6" />',
  "chevron-right":
    '<path d="m9 18 6-6-6-6" />',
  store:
    '<path d="m2 7 4.41-4.41A2 2 0 0 1 7.83 2h8.34a2 2 0 0 1 1.42.59L22 7" /><path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8" /><path d="M15 22v-4a2 2 0 0 0-2-2h-2a2 2 0 0 0-2 2v4" /><path d="M2 7h20" /><path d="M22 7v3a2 2 0 0 1-2 2a2.7 2.7 0 0 1-1.59-.63.7.7 0 0 0-.82 0A2.7 2.7 0 0 1 16 12a2.7 2.7 0 0 1-1.59-.63.7.7 0 0 0-.82 0A2.7 2.7 0 0 1 12 12a2.7 2.7 0 0 1-1.59-.63.7.7 0 0 0-.82 0A2.7 2.7 0 0 1 8 12a2.7 2.7 0 0 1-1.59-.63.7.7 0 0 0-.82 0A2.7 2.7 0 0 1 4 12a2 2 0 0 1-2-2V7" />',
};

/**
 * The one icon map for catalog categories (mega menu, home grid, category
 * cards). Each category gets a distinct mark so the grid reads at a glance.
 */
export const CATEGORY_ICONS: Record<string, IconName> = {
  cpu: "chip",
  motherboard: "board",
  memory: "memory",
  storage: "drive",
  gpu: "graphics",
  psu: "power",
  case: "tower",
  cooler_air: "heatsink",
  aio: "radiator",
  cooling_other: "cooling-other",
  case_fan: "case-fan",
  fan: "fan",
  fan_controller: "fan",
  cooler_accessory: "wrench",
  thermal_paste: "droplet",
  thermal: "droplet",
  rgb_lighting: "bolt",
  rgb: "bolt",
  accessories: "accessories",
  other: "grid",
};

export function icon(name: IconName, size = 16): Html {
  return raw(`<svg class="ic ic-${name}" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${PATHS[name]}</svg>`);
}
