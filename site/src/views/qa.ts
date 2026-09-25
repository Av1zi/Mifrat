import { loadQa, loadSpecReport } from "../api";
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
  let specReport;
  try {
    [qa, specReport] = await Promise.all([loadQa(), loadSpecReport()]);
  } catch (err) {
    container.innerHTML = errorPanel(
      t(lang, "loadError"),
      t(lang, "retry"),
      err
    );
    return;
  }

  const cases = qa.cases ?? [];
  const reportPanel = specReport
    ? `
      <section class="qa-case">
        <h2>${esc(lang === "he" ? "כיסוי מפרטים" : "Spec coverage")}</h2>
        <p class="qa-spec">
          ${esc(lang === "he" ? "מוצרים" : "Products")}: ${specReport.products}
          · ${esc(lang === "he" ? "פערי ליבה" : "Core gaps")}: ${specReport.counts.core_gaps ?? 0}
          · ${esc(lang === "he" ? "לא ידוע" : "Unknown fields")}: ${specReport.counts.unknown ?? 0}
          · ${esc(lang === "he" ? "הסקות בטוחות" : "Safe inferences")}: ${specReport.derived ?? 0}
        </p>
        <p class="qa-spec">
          ${esc(lang === "he"
            ? "ערכים חסרים נשארים לא ידועים בכוונה כאשר אין מקור אמין."
            : "Unknown values remain unknown intentionally when no reliable source exists.")}
        </p>
      </section>`
    : "";
  if (cases.length === 0) {
    container.innerHTML = `
      <div class="crumbs"><a href="${homeHash()}">← ${t(lang, "backToCategories")}</a></div>
      <div class="title-band"><h1>${esc(t(lang, "qaHeading"))}</h1></div>
      ${reportPanel}
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
              : c.kind === "core_gap"
                ? "qaKindCore"
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
      // Core-compat gap (scraper/specs/report.py): the product cannot answer
      // "will it fit" for the listed fields. Rendered as field chips.
      const coreBit =
        c.kind === "core_gap" && c.fields && c.fields.length > 0
          ? `<p class="qa-spec"><span class="qa-field">${esc(
              t(lang, "qaMissingFields")
            )}</span> ${c.fields
              .map(
                (f) =>
                  `<span class="qa-field">${esc(attributeLabel(f, lang))}</span>`
              )
              .join(" ")}</p>`
          : "";
      return `
      <article class="qa-case">
        <h2><a href="${productHash(c.category, c.product_id)}">${esc(c.product_id)}</a></h2>
        <p class="qa-meta"><span class="qa-kind">${kindLabel}</span>${esc(categoryLabel(c.category, lang))}${vendorBit} · <a href="${categoryHash(c.category)}">${esc(categoryLabel(c.category, lang))}</a></p>
        ${titlesBit}
        ${specBit}
        ${coreBit}
        ${offers ? `<ul class="qa-offers">${offers}</ul>` : ""}
      </article>`;
    })
    .join("");

  container.innerHTML = `
    <div class="crumbs"><a href="${homeHash()}">← ${t(lang, "backToCategories")}</a></div>
    <div class="title-band"><h1>${esc(t(lang, "qaHeading"))}</h1><p>${esc(resultsCount(lang, cases.length))}</p></div>
    ${reportPanel}
    <div class="qa-list">${rows}</div>`;
}
