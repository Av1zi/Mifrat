/**
 * Minimal inline SVG icon set (stroke = currentColor, flat, no emoji).
 * Keeps the header/nav/builder chrome looking like PCPP's icon + label
 * nav items without pulling in an icon font or image assets.
 */

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
  | "coin";

const PATHS: Record<IconName, string> = {
  wrench:
    '<path d="M14.5 6.5a3.5 3.5 0 0 0-4.6-3.3L4 9.1a1.8 1.8 0 1 0 2.5 2.5l5.9-5.9a3.5 3.5 0 0 0 2.1.8z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><circle cx="3.6" cy="12.4" r="1.4" fill="none" stroke="currentColor" stroke-width="1.6"/>',
  chip:
    '<rect x="4.5" y="4.5" width="7" height="7" rx="1" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M6.5 1.8v2M9.5 1.8v2M6.5 12.2v2M9.5 12.2v2M1.8 6.5h2M1.8 9.5h2M12.2 6.5h2M12.2 9.5h2" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
  search:
    '<circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M10.5 10.5 15 15" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
  chevron:
    '<path d="M3.5 6 8 10.5 12.5 6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
  sun:
    '<circle cx="8" cy="8" r="3" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M8 1.5v1.8M8 12.7v1.8M1.5 8h1.8M12.7 8h1.8M3.4 3.4l1.3 1.3M11.3 11.3l1.3 1.3M12.6 3.4l-1.3 1.3M4.7 11.3 3.4 12.6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
  moon:
    '<path d="M13.5 9.5A5.5 5.5 0 0 1 6.5 2.5a5.5 5.5 0 1 0 7 7z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>',
  copy:
    '<rect x="5.5" y="5.5" width="8" height="8" rx="1.2" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M10.5 3.5v-1h-7v9h1" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
  plus:
    '<path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
  trash:
    '<path d="M2.5 4h11M6.5 4V2.8a.5.5 0 0 1 .5-.5h2a.5.5 0 0 1 .5.5V4M4 4l.7 9.2a1 1 0 0 0 1 .8h4.6a1 1 0 0 0 1-.8L12 4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M6.5 6.5v5M9.5 6.5v5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>',
  bolt:
    '<path d="M9 1.5 3.5 9H7l-1 5.5L11.5 7H8l1-5.5z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>',
  close:
    '<path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
  globe:
    '<circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M2 8h12M8 2c-3.5 3.5-3.5 8.5 0 12 3.5-3.5 3.5-8.5 0-12z" fill="none" stroke="currentColor" stroke-width="1.3"/>',
  coin:
    '<circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8 5v6M6 6.5h3.2a1.3 1.3 0 0 1 0 2.6H6.8a1.3 1.3 0 0 0 0 2.6H10" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>',
};

export function icon(name: IconName, size = 15): string {
  return `<svg class="ic ic-${name}" width="${size}" height="${size}" viewBox="0 0 16 16" aria-hidden="true" focusable="false">${PATHS[name]}</svg>`;
}
