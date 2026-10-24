import { loadQa, loadSpecReport } from "../api";
import { formatPrice } from "../format";
import { attributeLabel, categoryLabel, resultsCount, t, vendorLabel } from "../i18n";
import { categoryHash, productHash } from "../state";
import { setPageTitle } from "../titles";
import type { Currency, Lang, QaCase, SpecReport } from "../types";
import { card } from "../ui/card";
import { chip } from "../ui/chip";
import { emptyValue } from "../ui/empty";
import { pageHero } from "../ui/pageHero";
import { html, mount, type Html } from "../ui/html";
import { emptyState, errorState, loadingState } from "../ui/state";

/** Public review list: duplicate listings, naming/spec conflicts and core-spec gaps. */
export async function renderQa(
  container: HTMLElement,
  lang: Lang,
  currency: Currency
): Promise<void> {
  setPageTitle(lang, t(lang, "qaTitle"));
  mount(container, loadingState(lang));

  let cases: QaCase[];
  let specReport: SpecReport | null;
  try {
    const [qa, report] = await Promise.all([loadQa(), loadSpecReport()]);
    cases = qa.cases ?? [];
    specReport = report;
  } catch (err) {
    mount(container, errorState(lang, err));
    return;
  }

  const he = lang === "he";
  const reportPanel = specReport
    ? card(
        html`<p class="qa-note">
            ${he ? "מוצרים" : "Products"}: ${specReport.products}
            · ${he ? "פערי ליבה" : "Core gaps"}: ${specReport.counts.core_gaps ?? 0}
            · ${he ? "לא ידוע" : "Unknown fields"}: ${specReport.counts.unknown ?? 0}
            · ${he ? "הסקות בטוחות" : "Safe inferences"}: ${specReport.derived ?? 0}
          </p>
          <p class="qa-note">${he ? "ערכים חסרים נשארים לא ידועים בכוונה כאשר אין מקור אמין." : "Unknown values remain unknown intentionally when no reliable source exists."}</p>`,
        { title: he ? "כיסוי מפרטים" : "Spec coverage", className: "qa-case" }
      )
    : "";

  const specValueText = (value: unknown): Html => {
    if (value === null || value === undefined || value === "") return emptyValue(lang);
    if (Array.isArray(value)) return html`${value.map(String).join(", ")}`;
    if (typeof value === "object") return html`${JSON.stringify(value)}`;
    return html`${String(value)}`;
  };

  const kindKey = (kind: QaCase["kind"]) =>
    kind === "naming_conflict"
      ? "qaKindNaming"
      : kind === "spec_conflict"
        ? "qaKindSpec"
        : kind === "core_gap"
          ? "qaKindCore"
          : "qaKindDuplicate";

  const rows = cases.map((c) =>
    card(
      html`<h2><a href="${productHash(c.category, c.product_id)}">${c.product_id}</a></h2>
        <p class="qa-meta">
          ${chip(t(lang, kindKey(c.kind)), { tone: c.kind === "core_gap" ? "warn" : "brand" })}
          <a href="${categoryHash(c.category)}">${categoryLabel(c.category, lang)}</a>${c.vendor ? ` · ${vendorLabel(c.vendor)}` : ""}
        </p>
        ${c.kind === "naming_conflict" && c.titles && c.titles.length > 0 ? html`<p class="qa-note">${c.titles.map((x) => html`${x}<br>`)}</p>` : ""}
        ${c.kind === "spec_conflict"
          ? html`<p class="qa-note">${c.field ? html`${chip(attributeLabel(c.field, lang))} ` : ""}${c.detail ? c.detail : html`${t(lang, "qaSpecKept")}: ${specValueText(c.kept)} · ${t(lang, "qaSpecDropped")}: ${specValueText(c.dropped)}`}</p>`
          : ""}
        ${c.kind === "core_gap" && c.fields && c.fields.length > 0
          ? html`<p class="qa-note">${t(lang, "qaMissingFields")} ${c.fields.map((f) => html`${chip(attributeLabel(f, lang))} `)}</p>`
          : ""}
        ${c.offers.length > 0
          ? html`<ul class="qa-offers">${c.offers.map(
              (o) => html`<li><code>${o.vendor_sku ?? o.listing_key}</code><span class="text-dim">${o.title ?? ""}</span>${o.price === null || o.price === undefined ? emptyValue(lang) : html`<b class="num">${formatPrice(o.price, currency, lang)}</b>`}</li>`
            )}</ul>`
          : ""}`,
      { className: "qa-case", tag: "article" }
    )
  );

  mount(
    container,
    html`${pageHero({ lang, crumbs: [{ label: t(lang, "qaTitle") }], title: t(lang, "qaHeading"), sub: cases.length > 0 ? resultsCount(lang, cases.length) : undefined })}
      <div class="qa-list">
        ${reportPanel}
        ${cases.length === 0 ? emptyState(t(lang, "qaEmpty")) : rows}
      </div>`
  );
}
