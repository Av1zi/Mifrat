import { t } from "../../i18n";
import { icon } from "../../icons";
import { createListLink, listUrl } from "../../lists";
import { findSavedBuild, saveBuild } from "../../savedBuilds";
import { buildHash, buildItemCount } from "../../state";
import { button } from "../../ui/button";
import { html, type Html } from "../../ui/html";
import { exportLines, type BuilderCtx } from "./parts";

/**
 * The short link generates itself (debounced POST, deduped server-side): the
 * input shows the short URL once known and falls back to the long URL while
 * pending or offline. A link is a permanent snapshot, so a changed build
 * gets a new one.
 */
function ensureShortLink(ctx: BuilderCtx, key: string): void {
  const { share, container, lang } = ctx;
  if (buildItemCount(ctx.build) === 0 || share.shortUrlFor?.key === key || share.pendingKey === key) return;
  share.pendingKey = key;
  const status = container.querySelector('[data-role="short-status"]');
  if (status) status.textContent = t(lang, "shorteningLabel");
  window.clearTimeout(share.timer);
  share.timer = window.setTimeout(() => {
    const clear = (): void => {
      share.pendingKey = null;
      if (status) status.textContent = "";
    };
    // The build moved on while waiting: the next render reschedules.
    if (JSON.stringify(ctx.build) !== key) {
      clear();
      return;
    }
    createListLink(ctx.build).then(
      (id) => {
        clear();
        if (JSON.stringify(ctx.build) !== key) return;
        const url = listUrl(id);
        share.shortUrlFor = { key, url };
        const input = container.querySelector<HTMLInputElement>('[data-role="share-link"]');
        if (input) input.value = url;
      },
      // API unreachable (offline, `vite dev` without the Worker): the long
      // URL already in the input still shares fine.
      clear
    );
  }, 900);
}

export function shareCard(ctx: BuilderCtx): Html {
  const { lang, build, share } = ctx;
  const longUrl = `${location.origin}${location.pathname}${buildHash(build)}`;
  const key = JSON.stringify(build);
  const shown = share.shortUrlFor && share.shortUrlFor.key === key ? share.shortUrlFor.url : longUrl;
  const empty = buildItemCount(build) === 0;
  const saved = !empty && findSavedBuild(build) !== undefined;
  return html`<div class="build-share">
      <label class="search-field build-share__link">
        ${icon("link", 16)}
        <input class="ltr" data-role="share-link" type="text" readonly value="${shown}" aria-label="${t(lang, "shareLinkAria")}">
      </label>
      ${button({ label: t(lang, "copyLink"), icon: icon("copy", 16), variant: "primary", data: { role: "copy-link" }, disabled: empty })}
      ${button({ label: saved ? t(lang, "buildSaved") : t(lang, "saveBuild"), icon: icon(saved ? "check" : "save", 16), data: { role: "save-build" }, disabled: empty || saved, className: saved ? "is-done" : "" })}
      ${button({ label: t(lang, "startNew"), icon: icon("plus", 16), data: { role: "start-new" }, disabled: empty })}
      <details class="export-menu">
        <summary class="btn btn--ghost" title="${t(lang, "exportTitle")}">${icon("file-text", 16)}<span>${t(lang, "exportTitle")}</span>${icon("chevron", 13)}</summary>
        <div class="export-menu__list">
          ${button({ label: t(lang, "copyMarkdown"), icon: icon("grid", 15), size: "sm", data: { role: "export-md" } })}
          ${button({ label: t(lang, "copyText"), icon: icon("file-text", 15), size: "sm", data: { role: "export-text" } })}
        </div>
      </details>
    </div>
    <p class="fineprint build-share__status" data-role="short-status" role="status" aria-live="polite"></p>`;
}

async function copyText(text: string, btn: HTMLButtonElement, doneLabel: string): Promise<void> {
  const original = btn.innerHTML;
  const done = (): void => {
    btn.classList.add("is-done");
    btn.innerHTML = html`${icon("check", 15)}<span>${doneLabel}</span>`.value;
    window.setTimeout(() => {
      btn.classList.remove("is-done");
      btn.innerHTML = original;
    }, 1400);
  };
  try {
    await navigator.clipboard.writeText(text);
    done();
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    try {
      document.execCommand("copy");
      done();
    } catch {
      // Nothing more to try; the button simply does not flip to "copied".
    }
    area.remove();
  }
}

/** Wires copy/export buttons of a freshly rendered share card. */
export function bindShare(ctx: BuilderCtx): void {
  const root = ctx.container;
  const { lang } = ctx;
  const on = (role: string, run: (btn: HTMLButtonElement) => void): void => {
    const btn = root.querySelector<HTMLButtonElement>(`[data-role="${role}"]`);
    btn?.addEventListener("click", () => run(btn));
  };
  const input = root.querySelector<HTMLInputElement>('[data-role="share-link"]');
  input?.addEventListener("click", () => input.select());
  on("copy-link", (btn) => void copyText(input?.value ?? "", btn, t(lang, "linkCopied")));
  on("export-md", (btn) => void copyText(exportLines(ctx, "markdown"), btn, t(lang, "markupTableCopied")));
  on("export-text", (btn) => void copyText(exportLines(ctx, "text"), btn, t(lang, "markupTextCopied")));
  on("save-build", (btn) => {
    if (buildItemCount(ctx.build) === 0) return;
    saveBuild(ctx.build);
    btn.disabled = true;
    btn.classList.add("is-done");
    btn.innerHTML = html`${icon("check", 16)}<span>${t(lang, "buildSaved")}</span>`.value;
  });
  // The input always shows the short link: start (debounced) creation for this render's build.
  ensureShortLink(ctx, JSON.stringify(ctx.build));
}
