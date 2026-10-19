import { attributeLabel, specGroupLabel, t } from "../../i18n";
import { displaySpecFields, formatSpecValue, specValue } from "../../specs";
import type { Lang, Product } from "../../types";
import { card } from "../../ui/card";
import { html, type Html } from "../../ui/html";
import { specCell } from "../../ui/spec";

/**
 * Spec sheet as accordions grouped by the schema's own groups. A field no
 * product in the category fills is dropped entirely (a column of "Not listed"
 * for a fact no vendor ever prints is noise); every remaining field is shown
 * in its group, gaps carrying the shared "Not listed" look. A group with no
 * known value starts closed and says so in its summary.
 *
 * `categoryProducts` (the already-loaded category page data) is what makes
 * the cross-category "is this field ever filled?" test possible without an
 * extra request; without it only this product's own fields are considered.
 */
export function specsCard(product: Product, lang: Lang, categoryProducts?: Product[]): Html {
  const universe = categoryProducts && categoryProducts.length > 0 ? categoryProducts : [product];
  const groups = new Map<string, ReturnType<typeof displaySpecFields>>();
  for (const field of displaySpecFields(product.category)) {
    const anyKnown = universe.some(
      (p) => formatSpecValue(specValue(p, field.name), lang) !== ""
    );
    if (!anyKnown) continue;
    groups.set(field.group, [...(groups.get(field.group) ?? []), field]);
  }

  const sections = [...groups].map(([group, fields]) => {
    const known = fields.filter((f) => formatSpecValue(specValue(product, f.name), lang) !== "").length;
    return html`<details class="acc"${known > 0 ? html` open` : ""}>
      <summary>${specGroupLabel(group, lang)}<span class="acc__meta">${known} / ${fields.length}</span></summary>
      <dl class="acc__body spec-list">
        ${fields.map(
          (f) => html`<div class="spec-row"><dt>${attributeLabel(f.name, lang, product.category)}</dt><dd>${specCell(specValue(product, f.name), lang)}</dd></div>`
        )}
      </dl>
    </details>`;
  });

  return card(html`${sections}`, { title: t(lang, "specsHeading"), className: "specs" });
}
