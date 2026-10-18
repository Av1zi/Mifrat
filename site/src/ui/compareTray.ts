import { COMPARE_MAX, getCompare } from "../compare";
import { compareCount, t } from "../i18n";
import { icon } from "../icons";
import { compareHash, parseRoute } from "../state";
import type { Lang } from "../types";
import { button } from "./button";
import { html, mount } from "./html";
import { bindThumbs, initialsOf, thumb } from "./thumb";

const NOTICE_MS = 4000;
let noticeTimer: number | undefined;
let notice = "";

/** Short message in the tray ("up to 4 parts"); also read out through its live region. */
export function showTrayNotice(message: string): void {
  notice = message;
  window.clearTimeout(noticeTimer);
  noticeTimer = window.setTimeout(() => {
    notice = "";
    syncCompareTray();
  }, NOTICE_MS);
  syncCompareTray();
}

/**
 * The sticky compare tray lives in the shell (`#compare-tray`, recreated on
 * every shell render). Hidden while empty and on the compare page itself.
 */
export function syncCompareTray(): void {
  const tray = document.getElementById("compare-tray");
  if (!tray) return;
  const lang: Lang = document.documentElement.lang === "en" ? "en" : "he";
  const { items } = getCompare();
  const hidden = items.length === 0 || parseRoute().view === "compare";
  tray.hidden = hidden;
  document.body.classList.toggle("has-tray", !hidden);
  if (hidden) return;

  const ready = items.length >= 2;
  mount(
    tray,
    html`<div class="compare-tray__inner">
      <p class="compare-tray__count"><b>${t(lang, "compareTitle")}</b> <span>${compareCount(lang, items.length, COMPARE_MAX)}</span></p>
      <ul class="compare-tray__items" aria-label="${t(lang, "compareTrayLabel")}">
        ${items.map(
          (p) => html`<li class="compare-tray__item" title="${p.name}">
            ${thumb(p.thumb, initialsOf(p.brand, p.name), "sm", "")}
            <span class="compare-tray__name">${p.name}</span>
            ${button({ label: `${t(lang, "compareRemove")}: ${p.name}`, icon: icon("close", 14), size: "sm", iconOnly: true, className: "compare-tray__x", data: { "tray-remove": p.id } })}
          </li>`
        )}
      </ul>
      <p class="compare-tray__notice" role="status">${notice}</p>
      <div class="compare-tray__actions">
        ${button({ label: t(lang, "compareClear"), size: "sm", data: { "tray-clear": "1" } })}
        ${ready
          ? button({ label: t(lang, "compareNow"), icon: icon("compare", 16), variant: "primary", size: "sm", href: compareHash(items.map((p) => p.id)) })
          : button({ label: t(lang, "compareNeedMore"), variant: "primary", size: "sm", disabled: true })}
      </div>
    </div>`
  );
  bindThumbs(tray);
}
