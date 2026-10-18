import { impliedFilterValues, isProductCompatibleWithBuild, optionMatchesTokens } from "../../build";
import { formatPrice } from "../../format";
import { attributeLabel, t, vendorLabel } from "../../i18n";
import { isNumericSpec, specFieldMap } from "../../specs";
import { categoryHash, replaceRoute } from "../../state";
import { chip } from "../../ui/chip";
import { button } from "../../ui/button";
import { html, type Html } from "../../ui/html";
import {
  listFieldsFor,
  specOptionValues,
  type CategoryActions,
  type CategoryCtx,
  type OptionCounts,
  type Range,
} from "./data";

const OPTIONS_SHOWN = 6;

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
      const label = html`${attributeLabel(key, lang)}: ${key === "vendor" ? vendorLabel(value) : value}`;
      chips.push(
        locked
          ? chip(label, { tone: "brand", locked: true, title: t(lang, "compatLocked") })
          : chip(label, { tone: "brand", removable: true, data: { key, value } })
      );
    }
  }
  for (const [key, range] of Object.entries(params.ranges)) {
    if (range.min === null && range.max === null) continue;
    const text =
      range.min !== null && range.max !== null
        ? `${range.min} – ${range.max}`
        : range.min !== null
          ? `${t(lang, "min")}: ${range.min}`
          : `${t(lang, "max")}: ${range.max}`;
    chips.push(chip(html`${attributeLabel(key, lang)}: ${text}`, { tone: "brand", removable: true, data: { "range-key": key } }));
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
  const listFields = listFieldsFor(ctx.category);
  for (const p of ctx.products) {
    if (!isProductCompatibleWithBuild(p, ctx.targetSlotId, ctx.build.first)) continue;
    for (const key of ctx.filterable.keys()) {
      let set = good.get(key);
      if (!set) {
        set = new Set();
        good.set(key, set);
      }
      if (key === "vendor") for (const offer of p.offers) set.add(offer.vendor);
      else for (const value of specOptionValues(p, key, listFields.has(key))) set.add(value);
    }
  }
  return good;
}

function optionMarkup(ctx: CategoryCtx, good: Map<string, Set<string>>, key: string, value: string, count: number): Html {
  const dead = good.size > 0 && !(good.get(key)?.has(value) ?? false);
  const state = dead ? (ctx.compatOn ? " is-off" : " is-soft-off") : "";
  const checked = (ctx.params.filters[key] ?? []).includes(value);
  return html`<label class="check${state}"><input type="checkbox" data-attr="${key}" value="${value}"${checked ? html` checked` : ""}${dead && ctx.compatOn ? html` disabled` : ""}>${key === "vendor" ? vendorLabel(value) : value}<span class="check__count">${count}</span></label>`;
}

function group(label: string, body: Html, open: boolean, selected = 0): Html {
  return html`<details class="acc"${open ? html` open` : ""}>
    <summary>${label}${selected > 0 ? html`<span class="acc__meta">${selected}</span>` : ""}</summary>
    <div class="acc__body">${body}</div>
  </details>`;
}

function rangeMarkup(ctx: CategoryCtx, key: string, range: Range): Html {
  const span = range.max - range.min;
  const step = key === "price" ? Math.max(1, Math.floor(span / 100)) : key.includes("ghz") || key.includes("clock") ? 0.1 : 1;
  const lo = ctx.params.ranges[key]?.min ?? range.min;
  const hi = ctx.params.ranges[key]?.max ?? range.max;
  const label = key === "price" ? t(ctx.lang, "priceRange") : attributeLabel(key, ctx.lang);
  const minAria = key === "price" ? t(ctx.lang, "priceMinAria") : `${label} ${t(ctx.lang, "min")}`;
  const maxAria = key === "price" ? t(ctx.lang, "priceMaxAria") : `${label} ${t(ctx.lang, "max")}`;
  const edge = (n: number): string => (key === "price" ? formatPrice(n, ctx.currency, ctx.lang) : String(n));
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
  const shown = values.slice(0, OPTIONS_SHOWN);
  const extra = values.slice(OPTIONS_SHOWN);
  const label = key === "vendor" ? t(ctx.lang, "merchantsTitle") : attributeLabel(key, ctx.lang);
  const body = html`${shown.map(([v, n]) => optionMarkup(ctx, good, key, v, n))}
    ${extra.length > 0
      ? html`<div data-extra hidden>${extra.map(([v, n]) => optionMarkup(ctx, good, key, v, n))}</div>
        <button type="button" class="link-btn" data-more data-label-more="${t(ctx.lang, "showMore")} (${extra.length})" data-label-less="${t(ctx.lang, "showLess")}">${t(ctx.lang, "showMore")} (${extra.length})</button>`
      : ""}`;
  return group(label, body, open, (ctx.params.filters[key] ?? []).length);
}

/** Rail body: merchants, price, numeric ranges, then checkbox groups in schema order. */
export function filtersMarkup(ctx: CategoryCtx): Html {
  const good = compatibleOptions(ctx);
  const fields = specFieldMap(ctx.category);
  const sections: Html[] = [];
  let first = true;
  const open = (): boolean => {
    const was = first;
    first = false;
    return was;
  };

  const vendors = ctx.filterable.get("vendor");
  if (vendors) sections.push(checkGroup(ctx, good, "vendor", vendors, open()));

  const price = ctx.ranges.get("price");
  if (price) sections.push(group(t(ctx.lang, "priceRange"), rangeMarkup(ctx, "price", price), open(), ctx.params.ranges.price ? 1 : 0));

  for (const [key, range] of ctx.ranges) {
    if (key === "price" || range.min === range.max) continue;
    sections.push(group(attributeLabel(key, ctx.lang), rangeMarkup(ctx, key, range), false, ctx.params.ranges[key] ? 1 : 0));
  }

  for (const [key, values] of ctx.filterable) {
    if (key === "vendor" || isNumericSpec(fields.get(key))) continue;
    sections.push(checkGroup(ctx, good, key, values, false));
  }
  return html`${sections}`;
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
