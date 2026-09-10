import type { Lang } from "./types";

/**
 * Single place for tab titles. Every route sets its own title so each
 * page has a distinct and meaningful browser tab.
 */
export function setPageTitle(lang: Lang, page: string): void {
  const brand = lang === "he" ? "מפרט" : "Mifrat";
  document.title = page ? `${page} | ${brand}` : brand;
}
