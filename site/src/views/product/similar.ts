import { attributeLabel } from "../../i18n";
import { formatSpecValue, specPriority, specValue, VARIANT_IDENTITY_KEYS } from "../../specs";
import { productHash } from "../../state";
import type { Currency, Lang, Product } from "../../types";
import { html, type Html } from "../../ui/html";
import { priceCell } from "../../ui/price";
import { initialsOf, thumb } from "../../ui/thumb";
import { displayName } from "../../utils";
import { NOISE_KEYS, normEcho, rawText } from "./text";

function similarProducts(product: Product, all: Product[]): Product[] {
  // Score only curated spec keys; identity keys weigh triple so
  // same-chipset/socket/chip parts surface first.
  const priority = specPriority(product.category);
  const identity = new Set<string>(VARIANT_IDENTITY_KEYS[product.category] ?? []);
  const scored: Array<{ p: Product; score: number }> = [];
  for (const p of all) {
    if (p.id === product.id) continue;
    let score = 0;
    if (p.brand && product.brand && p.brand === product.brand) score += 5;
    for (const k of priority) {
      if (NOISE_KEYS.has(k)) continue;
      const value = rawText(specValue(product, k));
      if (value !== "" && rawText(specValue(p, k)) === value) score += identity.has(k) ? 3 : 1;
    }
    scored.push({ p, score });
  }
  const price = (p: Product): number => (p.min_price !== null && p.min_price > 0 ? p.min_price : Infinity);
  scored.sort((a, b) => b.score - a.score || price(a.p) - price(b.p));
  // Unrelated items must not fill every slot.
  return scored.filter((s) => s.score >= 6).slice(0, 8).map((s) => s.p);
}

export function similarMarkup(
  product: Product,
  products: Product[],
  lang: Lang,
  currency: Currency,
  echoOf: (s: string) => boolean
): Html | null {
  const similar = similarProducts(product, products);
  if (similar.length === 0) return null;

  // Twins can share a display name ("Gigabyte GeForce RTX 5060 TI 8GB" x5):
  // when names collide add a dim disambiguator, model tokens the title
  // lacks, otherwise the first differing spec values.
  const nameNorm = normEcho(displayName(product));
  const counts = new Map<string, number>();
  for (const p of similar) {
    const n = normEcho(displayName(p));
    counts.set(n, (counts.get(n) ?? 0) + 1);
  }
  const modelDisc = (p: Product): string => {
    const m = (p.model ?? "").trim();
    if (m === "" || echoOf(m)) return "";
    const titleTokens = new Set(displayName(p).toLowerCase().split(/[^a-z0-9א-ת+]+/i).filter(Boolean));
    const kept = m.split(/\s+/).filter((tok) => {
      const clean = tok.toLowerCase().replace(/[^a-z0-9א-ת+]/gi, "");
      if (clean === "" || titleTokens.has(clean) || /^\d+$/.test(clean)) return false;
      return !/^(nvidia|geforce|rtx?|gtx|rx|ti|super|series|edition)$/.test(clean);
    });
    const joined = kept.join(" ");
    return joined.length >= 3 ? joined : "";
  };
  const specDiffs = (p: Product, limit: number): string => {
    const out: string[] = [];
    for (const k of specPriority(p.category)) {
      if (NOISE_KEYS.has(k)) continue;
      const theirs = rawText(specValue(p, k));
      if (!theirs || theirs === rawText(specValue(product, k))) continue;
      out.push(`${attributeLabel(k, lang, p.category)} ${formatSpecValue(specValue(p, k), lang)}`);
      if (out.length >= limit) break;
    }
    return out.join(" · ");
  };

  const cards = similar.map((p) => {
    const name = displayName(p);
    const collides = (counts.get(normEcho(name)) ?? 0) > 1 || normEcho(name) === nameNorm;
    return { p, name, disc: collides ? modelDisc(p) || specDiffs(p, 2) : "" };
  });
  const discCounts = new Map<string, number>();
  for (const c of cards) if (c.disc) discCounts.set(c.disc, (discCounts.get(c.disc) ?? 0) + 1);
  for (const c of cards) {
    if (c.disc && (discCounts.get(c.disc) ?? 0) > 1) {
      const diff = specDiffs(c.p, 2);
      if (diff !== "" && diff !== c.disc) c.disc = diff;
    }
  }

  return html`<div class="similar">${cards.map(
    ({ p, name, disc }) => html`<a class="similar__card" href="${productHash(p.category, p.id)}">
      ${thumb(p.image, initialsOf(p.brand, p.name), "lg", name)}
      <span class="similar__name">${name}</span>
      ${disc ? html`<span class="similar__disc">${disc}</span>` : ""}
      ${priceCell(p.min_price, currency, lang)}
    </a>`
  )}</div>`;
}
