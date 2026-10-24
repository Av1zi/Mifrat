import { loadMeta } from "../api";
import { categoryLabel, t } from "../i18n";
import { CATEGORY_ICONS, icon, type IconName } from "../icons";
import { categoryHash } from "../state";
import type { Lang } from "../types";
import { safeImageUrl } from "../utils";
import { html, mount, type Html } from "./html";

interface EmptyStep {
  title: string;
  body: string;
  /** Number badge by default; an icon when given. */
  glyph?: IconName;
}

interface EmptyBoxOptions {
  icon: IconName;
  title: string | Html;
  body?: string | Html;
  steps?: EmptyStep[];
  /** Anything between the text and the actions (suggestion chips, a link). */
  extra?: Html;
  actions?: Html;
  /** Heading level: h1 on pages without a hero, h2 below one. */
  level?: 1 | 2;
  tone?: "brand" | "warn";
}

/** Dashed "nothing here yet" panel: round icon, title, text, optional how-to steps and actions. */
export function emptyBox(options: EmptyBoxOptions): Html {
  const { title, body, steps, extra, actions, level = 2, tone = "brand" } = options;
  const heading = level === 1 ? html`<h1 class="empty-box__title">${title}</h1>` : html`<h2 class="empty-box__title">${title}</h2>`;
  return html`<div class="empty-box">
    <span class="state-ic${tone === "warn" ? " state-ic--warn" : ""}" aria-hidden="true">${icon(options.icon, 32)}</span>
    ${heading}
    ${body ? html`<p class="empty-box__body">${body}</p>` : ""}
    ${steps && steps.length > 0
      ? html`<ol class="steps steps--${steps.length}">${steps.map(
          (step, i) => html`<li class="step"><b aria-hidden="true">${step.glyph ? icon(step.glyph, 15) : String(i + 1)}</b><span><strong>${step.title}</strong>${step.body}</span></li>`
        )}</ol>`
      : ""}
    ${extra ?? ""}
    ${actions ? html`<div class="empty-box__actions">${actions}</div>` : ""}
  </div>`;
}

/** The eight main categories, used where a dead end needs somewhere to go. */
const QUICK_CATS = ["cpu", "gpu", "motherboard", "memory", "storage", "psu", "case", "cpu_cooler"];

/** Section of category tiles with cover photos; counts and photos fill in from meta.json. */
export function quickCats(lang: Lang, heading: string, link?: Html): Html {
  return html`<section class="quick-cats">
    <header class="sec-head"><div><h2 class="quick-cats__title">${heading}</h2></div>${link ?? ""}</header>
    <div class="qgrid">${QUICK_CATS.map(
      (id) => html`<a class="qtile" href="${categoryHash(id)}"><span class="qtile__img" data-qcat="${id}">${icon(CATEGORY_ICONS[id] ?? "grid", 24)}</span><span class="qtile__text">${categoryLabel(id, lang)}<small data-qcount="${id}"></small></span></a>`
    )}</div>
  </section>`;
}

export function fillQuickCats(root: ParentNode, lang: Lang): void {
  void loadMeta()
    .then((meta) => {
      const byId = new Map(meta.categories.map((c) => [c.id, c]));
      root.querySelectorAll<HTMLElement>("[data-qcat]").forEach((slot) => {
        const src = safeImageUrl(byId.get(slot.dataset.qcat ?? "")?.cover);
        if (!src) return;
        mount(slot, html`<img src="${src}" alt="" loading="lazy" decoding="async">`);
        slot.querySelector("img")?.addEventListener("error", () => slot.replaceChildren(), { once: true });
      });
      root.querySelectorAll<HTMLElement>("[data-qcount]").forEach((el) => {
        const n = byId.get(el.dataset.qcount ?? "")?.count;
        if (n) el.textContent = `${n.toLocaleString(lang === "he" ? "he-IL" : "en-US")} ${t(lang, "homeTileProducts")}`;
      });
    })
    .catch(() => {});
}
