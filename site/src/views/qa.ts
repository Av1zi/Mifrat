import { loadQa } from "../api";
import { formatPrice } from "../format";
import { attributeLabel, categoryLabel, resultsCount, t, vendorLabel } from "../i18n";
import { productHash, homeHash, categoryHash } from "../state";
import { setPageTitle } from "../titles";
import type { Currency, Lang } from "../types";
import { errorPanel, esc } from "../utils";

/** Public review list: every product with duplicate same-vendor listings. */
export async function renderQa(
  container: HTMLElement,
  lang: Lang,
  currency: Currency
): Promise<void> {
  setPageTitle(lang, t(lang, "qaTitle"));
  container.innerHTML = `<div class="empty-state">${t(lang, "loading")}</div>`;

  let qa;
  try {
    qa = await loadQa();
  } catch (err) {
    container.innerHTML = errorPanel(
      t(lang, "loadError"),
      t(lang, "retry"),
      err
    );
    return;
  }

  const cases = qa.cases ?? [];
  if (cases.length === 0) {
    container.innerHTML = `
      <div class="crumbs"><a href="${homeHash()}">← ${t(lang, "backToCategories")}</a></div>
      <div class="title-band"><h1>${esc(t(lang, "qaHeading"))}</h1></div>
      <div class="empty-state">${esc(t(lang, "qaEmpty"))}</div>`;
    return;
  }

  /** Render a spec-conflict value (kept/dropped) as short text. */
  const specValueText = (value: unknown): string => {
    if (value === null || value === undefined || value === "") return "—";
    if (Array.isArray(value)) return value.map((item) => String(item)).join(", ");
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  };

  const rows = cases
    .map((c) => {
      const offers = c.offers
        .map(
          (o) => `
          <li><span class="qa-sku">${esc(o.vendor_sku ?? o.listing_key)}</span>
          <span class="dim">${esc(o.title ?? "")}</span>
          <span class="qa-price">${o.price === null || o.price === undefined ? "-" : esc(formatPrice(o.price, currency, lang))}</span></li>`
        )
        .join("");
      const kindLabel = esc(
        t(
          lang,
          c.kind === "naming_conflict"
            ? "qaKindNaming"
            : c.kind === "spec_conflict"
              ? "qaKindSpec"
              : "qaKindDuplicate"
        )
      );
      const vendorBit = c.vendor ? ` · ${esc(vendorLabel(c.vendor))}` : "";
      const titlesBit =
        c.kind === "naming_conflict" && c.titles && c.titles.length > 0
          ? `<p class="qa-titles">${c.titles.map((x) => esc(x)).join("<br>")}</p>`
          : "";
      // Spec conflict (scraper/specs/merge.py): two sources disagreed on one
      // schema field. Shows the field plus the value kept and the one dropped.
      const specBit =
        c.kind === "spec_conflict"
          ? `<p class="qa-spec">${
              c.field
                ? `<span class="qa-field">${esc(attributeLabel(c.field, lang))}</span> · `
                : ""
            }${
              c.detail
                ? esc(c.detail)
                : `${esc(t(lang, "qaSpecKept"))}: ${esc(specValueText(c.kept))} · ${esc(
                    t(lang, "qaSpecDropped")
                  )}: ${esc(specValueText(c.dropped))}`
            }</p>`
          : "";
      return `
      <article class="qa-case">
        <h2><a href="${productHash(c.category, c.product_id)}">${esc(c.product_id)}</a></h2>
        <p class="qa-meta"><span class="qa-kind">${kindLabel}</span>${esc(categoryLabel(c.category, lang))}${vendorBit} · <a href="${categoryHash(c.category)}">${esc(categoryLabel(c.category, lang))}</a></p>
        ${titlesBit}
        ${specBit}
        ${offers ? `<ul class="qa-offers">${offers}</ul>` : ""}
      </article>`;
    })
    .join("");

  container.innerHTML = `
    <div class="crumbs"><a href="${homeHash()}">← ${t(lang, "backToCategories")}</a></div>
    <div class="title-band"><h1>${esc(t(lang, "qaHeading"))}</h1><p>${esc(resultsCount(lang, cases.length))}</p></div>
    <div class="qa-list">${rows}</div>`;
}
