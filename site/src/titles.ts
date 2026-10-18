import { t } from "./i18n";
import type { Lang } from "./types";

const OG_LOCALE: Record<Lang, string> = { he: "he_IL", en: "en_US" };

function setMeta(selector: string, attr: "name" | "property", key: string, content: string): void {
  let el = document.head.querySelector<HTMLMetaElement>(selector);
  if (!el) {
    el = document.createElement("meta");
    el.setAttribute(attr, key);
    document.head.append(el);
  }
  el.setAttribute("content", content);
}

/**
 * Single place for tab titles and page metadata. Every route sets its own
 * title and (optionally) description, and the Open Graph / Twitter tags
 * follow, so each page is distinct in the tab, in history and in link
 * previews. The description falls back to the site-wide one.
 */
export function setPageTitle(lang: Lang, page: string, description?: string): void {
  const brand = lang === "he" ? "מפרט" : "Mifrat";
  const title = page ? `${page} | ${brand}` : brand;
  const desc = description ?? t(lang, "metaDescription");
  document.title = title;
  setMeta('meta[name="description"]', "name", "description", desc);
  setMeta('meta[property="og:title"]', "property", "og:title", title);
  setMeta('meta[property="og:description"]', "property", "og:description", desc);
  setMeta('meta[property="og:locale"]', "property", "og:locale", OG_LOCALE[lang]);
  setMeta('meta[name="twitter:title"]', "name", "twitter:title", title);
  setMeta('meta[name="twitter:description"]', "name", "twitter:description", desc);
}
