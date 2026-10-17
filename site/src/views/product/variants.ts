import { attributeLabel, t } from "../../i18n";
import { formatSpecValue, specValue, VARIANT_IDENTITY_KEYS, VARIANT_KEY_PRIORITY } from "../../specs";
import { productHash } from "../../state";
import type { Lang, Product } from "../../types";
import { html, type Html } from "../../ui/html";
import { NOISE_KEYS, rawText } from "./text";

interface VariantGroup {
  key: string;
  values: Array<{ value: string; productId: string; active: boolean }>;
}

// Unit separator: cannot occur inside scraped text, so joined signatures
// cannot collide the way " " or "|" could.
const SEP = "\u0001";

function computeVariantGroups(product: Product, sameBrand: Product[]): VariantGroup[] {
  if (sameBrand.length < 2) return [];
  // Identity gate: no variant pills without identity. A missing model, or a
  // missing category identity key (chipset/socket on boards, chipset on
  // GPUs), would let same-brand different-line products pose as variants.
  if (!product.model) return [];
  const identityKeys = VARIANT_IDENTITY_KEYS[product.category] ?? [];
  for (const k of identityKeys) if (!rawText(specValue(product, k))) return [];

  const groups: VariantGroup[] = [];
  for (const key of VARIANT_KEY_PRIORITY) {
    const current = rawText(specValue(product, key));
    if (!current) continue;
    // Signature = brand + model + identity + everything EXCEPT the candidate
    // key: variants must be identical in every other dimension.
    const sigOf = (p: Product): string =>
      [
        p.brand ?? "",
        p.model ?? "",
        ...identityKeys.map((k) => rawText(specValue(p, k))),
        ...VARIANT_KEY_PRIORITY.filter((k) => k !== key).map((k) => rawText(specValue(p, k))),
      ].join(SEP);
    const mySig = sigOf(product);
    const distinct = new Map<string, Product[]>();
    for (const p of sameBrand) {
      if (sigOf(p) !== mySig) continue;
      const v = rawText(specValue(p, key));
      if (!v) continue;
      distinct.set(v, [...(distinct.get(v) ?? []), p]);
    }
    if (distinct.size < 2 || distinct.size > 8) continue;

    // A colour pill must never span chipsets.
    if (key === "color") {
      const chips = new Set<string>();
      for (const owners of distinct.values()) {
        for (const p of owners) {
          const chip = rawText(specValue(p, "chipset"));
          if (chip) chips.add(chip);
        }
      }
      if (chips.size > 1) continue;
    }

    const values = Array.from(distinct.entries()).map(([value, owners]) => {
      // Prefer the owner sharing the most attribute values with the current product.
      let best = owners[0];
      let bestScore = -1;
      for (const cand of owners) {
        let score = 0;
        for (const k of [...VARIANT_KEY_PRIORITY, ...identityKeys]) {
          if (NOISE_KEYS.has(k)) continue;
          if (rawText(specValue(cand, k)) === rawText(specValue(product, k))) score++;
        }
        if (score > bestScore) {
          bestScore = score;
          best = cand;
        }
      }
      return { value, productId: best.id, active: value === current };
    });
    // Value-only order keeps the active pill in place while navigating variants.
    values.sort((a, b) => a.value.localeCompare(b.value, "en", { numeric: true }));
    groups.push({ key, values });
    if (groups.length >= 4) break;
  }
  return groups;
}

export function variantsMarkup(product: Product, products: Product[], lang: Lang): Html {
  const sameBrand = product.brand ? products.filter((p) => p.brand === product.brand) : [];
  const groups = computeVariantGroups(product, sameBrand);
  if (groups.length === 0) return html``;
  return html`<div class="variants">
    <h3 class="variants__title">${t(lang, "variantsHeading")}</h3>
    ${groups.map(
      (g) => html`<div class="variants__group">
        <p>${attributeLabel(g.key, lang)}: <b>${formatSpecValue(specValue(product, g.key), lang)}</b></p>
        <div class="pills">
          ${g.values.map((v) =>
            v.active
              ? html`<span class="pill is-active" aria-current="true">${v.value}</span>`
              : html`<a class="pill" href="${productHash(product.category, v.productId)}">${v.value}</a>`
          )}
        </div>
      </div>`
    )}
  </div>`;
}
