import { COMPARE_MAX, getCompare, onCompareChange, removeCompare, clearCompare, toggleCompare } from "../compare";
import { t } from "../i18n";
import { icon } from "../icons";
import { getSaved, isSaved, onSavedChange, toggleSaved } from "../saved";
import { getSavedBuilds } from "../savedBuilds";
import { partRef, type PartRef } from "../storage";
import type { Lang, Product } from "../types";
import { displayName } from "../utils";
import { button } from "./button";
import { showTrayNotice, syncCompareTray } from "./compareTray";
import { html, type Html } from "./html";

/**
 * Compare and save controls. Markup carries only the product id; the part's
 * name/thumb snapshot is registered here when the control is rendered, and
 * one delegated listener (bindPickControls) handles every control on the
 * page, so views never wire clicks themselves.
 */
const parts = new Map<string, PartRef>();

function register(p: Product): PartRef {
  const ref = partRef(p, displayName(p));
  parts.set(p.id, ref);
  return ref;
}

const pageLang = (): Lang => (document.documentElement.lang === "en" ? "en" : "he");

/** Heart toggle for a part we only hold a snapshot of (the saved list). */
export function saveButtonRef(ref: PartRef, lang: Lang, labelled = false): Html {
  parts.set(ref.id, ref);
  return button({
    label: labelled ? t(lang, "savedAdd") : `${t(lang, "savedAdd")}: ${ref.name}`,
    icon: icon("heart", labelled ? 16 : 17),
    variant: "ghost",
    size: labelled ? "md" : "sm",
    iconOnly: !labelled,
    className: "save-btn",
    pressed: isSaved(ref.id),
    data: { save: ref.id },
  });
}

/** Heart toggle: icon-only on rows, labelled on the product page. */
export function saveButton(p: Product, lang: Lang, labelled = false): Html {
  return saveButtonRef(register(p), lang, labelled);
}

/** "Compare" checkbox for list rows; `bare` drops the visible label (table column). */
export function compareCheck(p: Product, lang: Lang, bare = false): Html {
  register(p);
  if (bare) {
    return html`<label class="cmp-check" title="${t(lang, "compareAction")}"><input type="checkbox" data-compare="${p.id}" aria-label="${t(lang, "compareAction")}: ${displayName(p)}"></label>`;
  }
  return html`<label class="check compare-check"><input type="checkbox" data-compare="${p.id}"><span>${t(lang, "compareAction")}</span></label>`;
}

/** Labelled toggle for the product page (its text follows the state, see syncPickControls). */
export function compareButton(p: Product, lang: Lang): Html {
  register(p);
  return button({
    label: t(lang, "compareAdd"),
    icon: icon("compare", 16),
    pressed: false,
    className: "compare-btn",
    data: { compare: p.id, "label-on": t(lang, "compareRemove"), "label-off": t(lang, "compareAdd") },
  });
}

/** Brings every control in the document in line with the stored lists. */
export function syncPickControls(): void {
  const list = getCompare();
  const ids = new Set(list.items.map((p) => p.id));
  const full = list.items.length >= COMPARE_MAX;
  const lang = pageLang();

  document.querySelectorAll<HTMLElement>("[data-compare]").forEach((el) => {
    const id = el.dataset.compare ?? "";
    const on = ids.has(id);
    if (el instanceof HTMLInputElement) {
      el.checked = on;
      el.disabled = full && !on;
      el.title = el.disabled ? t(lang, "compareFull") : "";
      return;
    }
    el.setAttribute("aria-pressed", on ? "true" : "false");
    const label = el.querySelector("span");
    const next = on ? el.dataset.labelOn : el.dataset.labelOff;
    if (label && next) label.textContent = next;
  });

  const saved = new Set(getSaved().map((p) => p.id));
  document.querySelectorAll<HTMLElement>("[data-save]").forEach((el) => {
    el.setAttribute("aria-pressed", saved.has(el.dataset.save ?? "") ? "true" : "false");
  });

  // The header heart counts everything on the Saved page: parts and parts lists.
  const savedTotal = saved.size + getSavedBuilds().length;
  document.querySelectorAll<HTMLElement>("[data-saved-count]").forEach((el) => {
    const n = savedTotal;
    el.textContent = String(n);
    el.hidden = n === 0;
  });
  syncCompareTray();
}

let bound = false;

/** Registered once: handles every compare/save control and the tray's own buttons. */
export function bindPickControls(): void {
  if (bound) return;
  bound = true;

  document.addEventListener("change", (e) => {
    const input = (e.target as HTMLElement).closest<HTMLInputElement>("input[data-compare]");
    if (input) applyCompare(input.dataset.compare ?? "");
  });

  document.addEventListener("click", (e) => {
    const target = e.target as HTMLElement;

    const compare = target.closest<HTMLElement>("button[data-compare]");
    if (compare) {
      applyCompare(compare.dataset.compare ?? "");
      return;
    }

    const save = target.closest<HTMLElement>("[data-save]");
    if (save) {
      const ref = parts.get(save.dataset.save ?? "");
      if (ref) toggleSaved(ref);
      return;
    }

    const trayRemove = target.closest<HTMLElement>("[data-tray-remove]");
    if (trayRemove) {
      removeCompare(trayRemove.dataset.trayRemove ?? "");
      return;
    }
    if (target.closest("[data-tray-clear]")) clearCompare();
  });

  onCompareChange(syncPickControls);
  onSavedChange(syncPickControls);
}

function applyCompare(id: string): void {
  const ref = parts.get(id);
  if (!ref) return;
  const lang = pageLang();
  const result = toggleCompare(ref);
  if (result === "full") showTrayNotice(t(lang, "compareFull"));
  else if (result === "switched") showTrayNotice(t(lang, "compareSwitched"));
  syncPickControls();
}
