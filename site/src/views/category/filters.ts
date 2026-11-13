import { impliedFilterValues, isProductCompatibleWithBuild, optionMatchesTokens } from "../../build";
import { formatPrice } from "../../format";
import { attributeLabel, t, vendorLabel } from "../../i18n";
import { filterableSpecs, isNumericSpec, specFieldMap, specUnit } from "../../specs";
import { categoryHash, replaceRoute } from "../../state";
import { chip } from "../../ui/chip";
import { button } from "../../ui/button";
import { html, type Html } from "../../ui/html";
import { vendorDot } from "../../ui/vendor";
import {
  optionValues,
  type CategoryActions,
  type CategoryCtx,
  type OptionCounts,
  type Range,
} from "./data";
import { facetFor, optionDisplay, railKeys } from "./facets";

const OPTIONS_SHOWN = 6;

/** Group heading: the derived filter's own label, else the schema label. */
function keyLabel(ctx: CategoryCtx, key: string): string {
  if (key === "vendor") return t(ctx.lang, "merchantsTitle");
  if (key === "price") return t(ctx.lang, "priceRange");
  return facetFor(ctx.category, key)?.label[ctx.lang] ?? attributeLabel(key, ctx.lang, ctx.category);
}

/** Display text for one stored option value ("16" -> "16 GB", "Yes" -> "כן"). */
export function optionLabel(ctx: CategoryCtx, key: string, value: string): string {
  if (key === "vendor") return vendorLabel(value);
  const facet = facetFor(ctx.category, key);
  if (facet) return facet.optionLabel?.(value, ctx.lang) ?? value;
  const field = specFieldMap(ctx.category).get(key);
  if (field?.type === "bool") return value === "Yes" ? t(ctx.lang, "yesLabel") : value === "No" ? t(ctx.lang, "noLabel") : value;
  if (isNumericSpec(field)) {
    const unit = specUnit(key);
    return unit ? `${value} ${unit}` : value;
  }
  return optionDisplay(ctx.category, key, value, ctx.lang) ?? value;
}

/** Unit for a slider's edge labels ("mm", "W"), "" for counts. */
function rangeUnit(key: string): string {
  return key === "price" ? "" : specUnit(key);
}

export function activeFilterCount(ctx: CategoryCtx): number {
  return (
    Object.values(ctx.params.filters).reduce((n, values) => n + values.length, 0) +
    Object.keys(ctx.params.ranges).length +
    (ctx.params.stockOnly ? 1 : 0)
  );
}

/** Removable chips for every active value and range, plus "clear all". */
export function activeFilterChips(ctx: CategoryCtx): Html {
  const { lang, params } = ctx;
  const chips: Html[] = [];
  for (const [key, values] of Object.entries(params.filters)) {
    // Compat-applied values stay locked until the compat filter is turned off.
    const locked = ctx.compatOn && ctx.compatAutoKeys.has(key);
    for (const value of values) {
      const label = html`${keyLabel(ctx, key)}: ${optionLabel(ctx, key, value)}`;
      chips.push(
        locked
          ? chip(label, { tone: "brand", locked: true, title: t(lang, "compatLocked") })
          : chip(label, { tone: "brand", removable: true, data: { key, value } })
      );
    }
  }
  for (const [key, range] of Object.entries(params.ranges)) {
    if (range.min === null && range.max === null) continue;
    const unit = rangeUnit(key);
    const fmt = (n: number): string => (key === "price" ? formatPrice(n, ctx.currency, lang) : unit ? `${n} ${unit}` : String(n));
    const text =
      range.min !== null && range.max !== null
        ? `${fmt(range.min)} – ${fmt(range.max)}`
        : range.min !== null
          ? `${t(lang, "min")}: ${fmt(range.min)}`
          : `${t(lang, "max")}: ${fmt(range.max!)}`;
    chips.push(chip(html`${keyLabel(ctx, key)}: ${text}`, { tone: "brand", removable: true, data: { "range-key": key } }));
  }
  if (chips.length === 0) return html``;
  return html`${chips}${button({ label: t(lang, "clearFilters"), variant: "ghost", size: "sm", data: { role: "clear-all" } })}`;
}

/** Pre-selects the filter values the current build implies (AM5 board for an AM5 CPU, ...). */
export function applyImpliedFilters(ctx: CategoryCtx): void {
  if (!ctx.compatOn || !ctx.targetSlotId) return;
  const implied = impliedFilterValues(ctx.targetSlotId, ctx.build.first);
  let applied = false;
  for (const [key, tokens] of Object.entries(implied)) {
    if ((ctx.params.filters[key] ?? []).length > 0) continue;
    const matched = (ctx.filterable.get(key) ?? [])
      .map(([value]) => value)
      .filter((value) => optionMatchesTokens(value, tokens));
    if (matched.length > 0) {
      ctx.params.filters[key] = matched;
      ctx.compatAutoKeys.add(key);
      applied = true;
    }
  }
  if (applied) replaceRoute(categoryHash(ctx.category, { ...ctx.params, q: ctx.query }));
}

/** Option values at least one build-compatible product carries, per filter key. */
function compatibleOptions(ctx: CategoryCtx): Map<string, Set<string>> {
  const good = new Map<string, Set<string>>();
  if (ctx.build.items.length === 0 || !ctx.targetSlotId) return good;
  for (const p of ctx.products) {
    if (!isProductCompatibleWithBuild(p, ctx.targetSlotId, ctx.build.first)) continue;
    for (const key of ctx.filterable.keys()) {
      let set = good.get(key);
      if (!set) {
        set = new Set();
        good.set(key, set);
      }
      for (const value of optionValues(p, key, ctx.category)) set.add(value);
    }
  }
  return good;
}

function optionMarkup(ctx: CategoryCtx, good: Map<string, Set<string>>, key: string, value: string, count: number): Html {
  const dead = good.size > 0 && !(good.get(key)?.has(value) ?? false);
  const state = dead ? (ctx.compatOn ? " is-off" : " is-soft-off") : "";
  const checked = (ctx.params.filters[key] ?? []).includes(value);
  return html`<label class="check${state}"><input type="checkbox" data-attr="${key}" value="${value}"${checked ? html` checked` : ""}${dead && ctx.compatOn ? html` disabled` : ""}>${key === "vendor" ? html`${vendorDot(value)}${vendorLabel(value)}` : html`<bdi>${optionLabel(ctx, key, value)}</bdi>`}<span class="check__count">${count}</span></label>`;
}

function group(label: string, body: Html, open: boolean, selected = 0): Html {
  return html`<details class="acc"${open ? html` open` : ""}>
    <summary>${label}${selected > 0 ? html`<span class="acc__meta">${selected}</span>` : ""}</summary>
    <div class="acc__body">${body}</div>
  </details>`;
}

/** PCPartPicker's "All" row: checked while nothing in the group is, and clears the group. */
function allOption(ctx: CategoryCtx, key: string): Html {
  const none = (ctx.params.filters[key] ?? []).length === 0;
  return html`<label class="check check--all"><input type="checkbox" data-all="${key}"${none ? html` checked` : ""}>${t(ctx.lang, "allLabel")}</label>`;
}

function rangeMarkup(ctx: CategoryCtx, key: string, range: Range): Html {
  const span = range.max - range.min;
  const isFloat = specFieldMap(ctx.category).get(key)?.type === "float";
  const step = key === "price" ? Math.max(1, Math.floor(span / 100)) : isFloat ? 0.1 : 1;
  const lo = ctx.params.ranges[key]?.min ?? range.min;
  const hi = ctx.params.ranges[key]?.max ?? range.max;
  const label = keyLabel(ctx, key);
  const minAria = key === "price" ? t(ctx.lang, "priceMinAria") : `${label} ${t(ctx.lang, "min")}`;
  const maxAria = key === "price" ? t(ctx.lang, "priceMaxAria") : `${label} ${t(ctx.lang, "max")}`;
  const unit = rangeUnit(key);
  const edge = (n: number): string => (key === "price" ? formatPrice(n, ctx.currency, ctx.lang) : unit ? `${n} ${unit}` : String(n));
  return html`<div class="range-wrap" data-range="${key}">
    <div class="range-ends"><span>${edge(range.min)}</span><span>${edge(range.max)}</span></div>
    <div class="range">
      <div class="range__track"></div>
      <input type="range" data-role="min-slider" min="${range.min}" max="${range.max}" step="${step}" value="${lo}" aria-label="${minAria}">
      <input type="range" data-role="max-slider" min="${range.min}" max="${range.max}" step="${step}" value="${hi}" aria-label="${maxAria}">
    </div>
    <div class="range-inputs">
      <input class="input" type="number" data-role="min" min="${range.min}" max="${range.max}" step="${step}" value="${lo}" aria-label="${minAria}">
      <input class="input" type="number" data-role="max" min="${range.min}" max="${range.max}" step="${step}" value="${hi}" aria-label="${maxAria}">
    </div>
  </div>`;
}

function checkGroup(ctx: CategoryCtx, good: Map<string, Set<string>>, key: string, values: OptionCounts, open: boolean): Html {
  // A filter in use never hides its checked values behind "show more".
  const active = (ctx.params.filters[key] ?? []).length > 0;
  const limit = active ? values.length : OPTIONS_SHOWN;
  const shown = values.slice(0, limit);
  const extra = values.slice(limit);
  const body = html`${allOption(ctx, key)}${shown.map(([v, n]) => optionMarkup(ctx, good, key, v, n))}
    ${extra.length > 0
      ? html`<div data-extra hidden>${extra.map(([v, n]) => optionMarkup(ctx, good, key, v, n))}</div>
        <button type="button" class="link-btn" data-more data-label-more="${t(ctx.lang, "showMore")} (${extra.length})" data-label-less="${t(ctx.lang, "showLess")}">${t(ctx.lang, "showMore")} (${extra.length})</button>`
      : ""}`;
  return group(keyLabel(ctx, key), body, open || active, (ctx.params.filters[key] ?? []).length);
}

function rangeGroup(ctx: CategoryCtx, key: string, open: boolean): Html | null {
  const range = ctx.ranges.get(key);
  if (!range || range.min === range.max) return null;
  const active = ctx.params.ranges[key] !== undefined;
  return group(keyLabel(ctx, key), rangeMarkup(ctx, key, range), open || active, active ? 1 : 0);
}

/** Category filters open by default after the fixed head: the ones a buyer narrows by first. */
const OPEN_FIRST = 2;

/**
 * Rail body: stores, manufacturer and price always lead (in that order), then
 * every filter in the category's order (facets.ts), each drawn as checkboxes
 * or a slider by what its values allow. The head and the first category
 * filters open; the rest stay folded until clicked.
 */
export function filtersMarkup(ctx: CategoryCtx): Html {
  const good = compatibleOptions(ctx);
  const section = (key: string, open: boolean): Html | null => {
    const values = ctx.filterable.get(key);
    return values ? checkGroup(ctx, good, key, values, open) : rangeGroup(ctx, key, open);
  };
  const sections: Array<Html | null> = [section("vendor", true), section("manufacturer", true), rangeGroup(ctx, "price", true)];

  let opened = 0;
  for (const key of railKeys(ctx.category, filterableSpecs(ctx.category))) {
    if (key === "manufacturer") continue;
    const next = section(key, opened < OPEN_FIRST);
    if (!next) continue;
    sections.push(next);
    opened++;
  }
  return html`${sections}`;
}

/** "All" stays checked exactly while its group has nothing selected. */
function syncAllOptions(rail: Element, ctx: CategoryCtx): void {
  rail.querySelectorAll<HTMLInputElement>("input[data-all]").forEach((input) => {
    input.checked = (ctx.params.filters[input.dataset.all!] ?? []).length === 0;
  });
}

/** Keeps checkbox states in sync without rebuilding the rail (open groups stay open). */
export function refreshRailStates(ctx: CategoryCtx): void {
  const rail = ctx.container.querySelector("#filter-rail");
  if (!rail) return;
  const good = compatibleOptions(ctx);
  rail.querySelectorAll<HTMLInputElement>("input[data-attr]").forEach((input) => {
    const key = input.dataset.attr!;
    const dead = good.size > 0 && !(good.get(key)?.has(input.value) ?? false);
    const label = input.closest(".check");
    label?.classList.toggle("is-off", dead && ctx.compatOn);
    label?.classList.toggle("is-soft-off", dead && !ctx.compatOn);
    input.disabled = dead && ctx.compatOn;
    input.checked = (ctx.params.filters[key] ?? []).includes(input.value);
  });
  syncAllOptions(rail, ctx);
}

function bindRange(ctx: CategoryCtx, actions: CategoryActions, wrap: HTMLElement): void {
  const key = wrap.dataset.range!;
  const range = ctx.ranges.get(key)!;
  const span = range.max - range.min;
  const box = wrap.querySelector<HTMLElement>(".range")!;
  const q = (role: string): HTMLInputElement => wrap.querySelector<HTMLInputElement>(`[data-role="${role}"]`)!;
  const minSlider = q("min-slider");
  const maxSlider = q("max-slider");
  const minInput = q("min");
  const maxInput = q("max");

  const paint = (lo: number, hi: number): void => {
    if (span <= 0) return;
    const pct = (v: number): number => Math.max(0, Math.min(100, ((v - range.min) / span) * 100));
    box.style.setProperty("--lo", `${pct(lo)}%`);
    box.style.setProperty("--hi", `${pct(hi)}%`);
  };
  const ordered = (a: number, b: number): [number, number] => (a <= b ? [a, b] : [b, a]);
  const fromSliders = (): [number, number] => {
    const lo = Number(minSlider.value);
    const hi = Number(maxSlider.value);
    return ordered(Number.isNaN(lo) ? range.min : lo, Number.isNaN(hi) ? range.max : hi);
  };
  // A full-span selection clears the constraint instead of storing it.
  const commit = (lo: number, hi: number): void => {
    if (lo <= range.min && hi >= range.max) delete ctx.params.ranges[key];
    else ctx.params.ranges[key] = { min: lo, max: hi };
    actions.update();
  };
  const preview = (): void => {
    const [lo, hi] = fromSliders();
    minInput.value = String(lo);
    maxInput.value = String(hi);
    paint(lo, hi);
  };

  minSlider.addEventListener("input", preview);
  maxSlider.addEventListener("input", preview);
  minSlider.addEventListener("change", () => commit(...fromSliders()));
  maxSlider.addEventListener("change", () => commit(...fromSliders()));

  const fromBoxes = (): void => {
    const clamp = (raw: string, fallback: number): number => {
      const n = Number(raw);
      return raw.trim() === "" || Number.isNaN(n) ? fallback : Math.max(range.min, Math.min(range.max, n));
    };
    const [lo, hi] = ordered(clamp(minInput.value, range.min), clamp(maxInput.value, range.max));
    minSlider.value = minInput.value = String(lo);
    maxSlider.value = maxInput.value = String(hi);
    paint(lo, hi);
    commit(lo, hi);
  };
  minInput.addEventListener("change", fromBoxes);
  maxInput.addEventListener("change", fromBoxes);
  paint(...fromSliders());
}

/** Wires one freshly rendered rail body. */
export function bindFilters(ctx: CategoryCtx, actions: CategoryActions): void {
  const rail = ctx.container.querySelector<HTMLElement>("#filter-rail")!;

  rail.querySelectorAll<HTMLInputElement>("input[data-attr]").forEach((input) => {
    input.addEventListener("change", () => {
      const key = input.dataset.attr!;
      // Compat-owned values cannot be toggled while the compat filter is on.
      if (ctx.compatOn && ctx.compatAutoKeys.has(key)) {
        input.checked = (ctx.params.filters[key] ?? []).includes(input.value);
        return;
      }
      const set = new Set(ctx.params.filters[key] ?? []);
      if (input.checked) set.add(input.value);
      else set.delete(input.value);
      if (set.size > 0) ctx.params.filters[key] = [...set];
      else delete ctx.params.filters[key];
      // The user took over this key; compat no longer owns it.
      ctx.compatAutoKeys.delete(key);
      actions.update();
    });
  });

  rail.querySelectorAll<HTMLButtonElement>("[data-more]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const extra = btn.previousElementSibling as HTMLElement | null;
      if (!extra) return;
      const show = extra.hidden;
      extra.hidden = !show;
      btn.textContent = show ? btn.dataset.labelLess! : btn.dataset.labelMore!;
    });
  });

  rail.querySelectorAll<HTMLElement>("[data-range]").forEach((wrap) => bindRange(ctx, actions, wrap));

  // "All" clears its group; unticking it while nothing is chosen does nothing.
  rail.querySelectorAll<HTMLInputElement>("input[data-all]").forEach((input) => {
    input.addEventListener("change", () => {
      const key = input.dataset.all!;
      if (ctx.compatOn && ctx.compatAutoKeys.has(key)) {
        syncAllOptions(rail, ctx);
        return;
      }
      delete ctx.params.filters[key];
      ctx.compatAutoKeys.delete(key);
      actions.update();
    });
  });
}

/** Clearing is explicit intent to see everything: it also drops the compat filter. */
export function clearAllFilters(ctx: CategoryCtx, actions: CategoryActions): void {
  ctx.compatOn = false;
  ctx.params.filters = {};
  ctx.params.ranges = {};
  ctx.params.stockOnly = false;
  ctx.compatAutoKeys.clear();
  actions.rebuildRail();
  actions.update();
}

/** Delegated handlers for the active-chip strip (its markup is replaced on every update). */
export function bindActiveChips(ctx: CategoryCtx, actions: CategoryActions): void {
  const host = ctx.container.querySelector<HTMLElement>('[data-role="active-filters"]')!;
  host.addEventListener("click", (e) => {
    const el = (e.target as HTMLElement).closest<HTMLElement>("button");
    if (!el) return;
    if (el.dataset.role === "clear-all") {
      clearAllFilters(ctx, actions);
      return;
    }
    if (el.dataset.rangeKey) {
      delete ctx.params.ranges[el.dataset.rangeKey];
    } else if (el.dataset.key && el.dataset.value !== undefined) {
      const key = el.dataset.key;
      const rest = (ctx.params.filters[key] ?? []).filter((v) => v !== el.dataset.value);
      if (rest.length > 0) ctx.params.filters[key] = rest;
      else delete ctx.params.filters[key];
      ctx.compatAutoKeys.delete(key);
    } else {
      return;
    }
    actions.rebuildRail();
    actions.update();
  });
}
