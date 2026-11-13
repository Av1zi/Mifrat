import { loadHistory } from "../../api";
import { formatPrice } from "../../format";
import { t, vendorLabel } from "../../i18n";
import type { Currency, Lang } from "../../types";
import { html, mount, type Html } from "../../ui/html";
import { esc } from "../../utils";
import { vendorKey } from "../../ui/vendor";


/** Redraws when the card's width changes; module-level so a route re-entry disconnects the old one. */
let resizeObserver: ResizeObserver | null = null;

/** Series class: each store keeps its own colour (--v-<vendor> tokens in chart.css). */
const seriesClass = (vendor: string): string => `ph-v-${vendorKey(vendor)}`;

let measureCtx: CanvasRenderingContext2D | null | undefined;
/** Widest of `texts` in `font`, so the price axis takes only the room its labels need. */
function textWidth(texts: string[], font: string): number {
  if (measureCtx === undefined) {
    try {
      measureCtx = document.createElement("canvas").getContext?.("2d") ?? null;
    } catch {
      measureCtx = null;
    }
  }
  // No canvas (an old engine, a test DOM): ~7px a character at 11-12px.
  if (!measureCtx) return texts.reduce((w, s) => Math.max(w, s.length * 7), 0);
  measureCtx.font = font;
  return texts.reduce((w, s) => Math.max(w, measureCtx!.measureText(s).width), 0);
}

/** The host's content-box width and font, tolerating a DOM without layout APIs. */
function plotBox(host: HTMLElement): { width: number; font: string } {
  const style = typeof getComputedStyle === "function" ? getComputedStyle(host) : null;
  const pad = style ? (parseFloat(style.paddingLeft) || 0) + (parseFloat(style.paddingRight) || 0) : 0;
  return { width: (host.clientWidth || 0) - pad, font: style?.fontFamily || "system-ui, sans-serif" };
}

const coarsePointer = (): boolean => typeof matchMedia === "function" && matchMedia("(pointer: coarse)").matches;

export async function renderPriceHistory(
  host: HTMLElement,
  lang: Lang,
  currency: Currency,
  category: string,
  productId: string
): Promise<void> {
  let file;
  try {
    file = await loadHistory(category);
  } catch {
    return;
  }
  if (!file) return;
  const entry = file[productId];
  if (!entry || Array.isArray(entry)) return;

  const dates = Array.isArray(file.dates) ? file.dates : [];
  if (dates.length < 1) return;
  const timestamps = Array.isArray(file.timestamps) ? file.timestamps : [];
  const series = entry.v;
  const vendors = Object.keys(series).filter(
    (v) => Array.isArray(series[v]) && series[v].some((p) => p !== null && p !== undefined)
  );
  if (vendors.length === 0) return;

  let dayWindow = dates.length;
  // Legend toggles hide a line per vendor; the axis rescales to the visible series.
  const hidden = new Set<string>();
  const visible = (): string[] => vendors.filter((v) => !hidden.has(v));

  const locale = lang === "he" ? "he-IL" : "en-GB";
  const shortDate = (value: unknown): string => {
    const iso = typeof value === "string" ? value : "";
    const d = new Date(iso);
    if (!Number.isNaN(d.getTime())) {
      return new Intl.DateTimeFormat(locale, { day: "numeric", month: "short" }).format(d);
    }
    const parts = iso.split("-");
    return parts.length === 3 ? `${parts[2]}.${parts[1]}` : iso;
  };

  let lastDrawnWidth = 0;
  const draw = (restoreFocusId?: string): void => {
    const end = dates.length;
    const start = Math.max(0, end - dayWindow);
    const shown = visible();
    // Days before any shown store has a price would be blank space on the
    // left: the plot starts at the first priced day (the stats keep the window).
    let from = start;
    while (from < end - 1 && !shown.some((v) => series[v][from] !== null && series[v][from] !== undefined)) from++;
    const visDates = dates.slice(from, end);

    let lo = Infinity;
    let hi = -Infinity;
    for (const v of shown) {
      for (const p of series[v].slice(from, end)) {
        if (p === null || p === undefined) continue;
        if (p < lo) lo = p;
        if (p > hi) hi = p;
      }
    }
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) return;
    if (lo === hi) {
      lo = Math.max(0, lo - 1);
      hi += 1;
    }
    // Breathing room around spikes so ordinary moves stay readable.
    const pad = Math.max((hi - lo) * 0.22, 5);
    lo = Math.max(0, lo - pad);
    hi += pad;

    // Match the viewBox to the chart's real pixel width (the card's content
    // box) so 1 SVG unit stays 1 CSS pixel: a viewBox wider than the space
    // it gets shrinks every label and line with it. Measured after unhiding,
    // since a hidden card has no width.
    host.hidden = false;
    const box = plotBox(host);
    const W = Math.max(240, Math.min(1400, Math.round(box.width > 0 ? box.width : 320)));
    // Narrow charts get taller (a 0.32 ratio is a strip on a phone) and a
    // readout above the plot instead of a tooltip over it; so do touch screens,
    // where a floating tooltip sits under the finger.
    const compact = W < 560;
    const docked = compact || coarsePointer();
    const H = compact ? Math.max(220, Math.min(300, Math.round(W * 0.75))) : Math.max(200, Math.min(340, Math.round(W * 0.32)));
    const ticks = 4;
    const tickValues = Array.from({ length: ticks + 1 }, (_, g) => lo + ((hi - lo) * g) / ticks);
    const tickLabels = tickValues.map((value) => formatPrice(Math.round(value), currency, lang));
    // The price axis is as wide as its widest label, not a fixed 88px.
    const L = Math.ceil(textWidth(tickLabels, `${compact ? 12 : 11}px ${box.font}`)) + 12;
    const R = compact ? 6 : 18;
    const T = 12;
    const B = 30;
    const n = visDates.length;
    const x = (i: number): number => (n === 1 ? (L + W - R) / 2 : L + (W - L - R) * (i / (n - 1)));
    const y = (v: number): number => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);

    let grid = "";
    tickValues.forEach((value, g) => {
      const gy = y(value);
      grid += `<line x1="${L}" y1="${gy}" x2="${W - R}" y2="${gy}" class="ph-grid"/>`;
      grid += `<text x="${L - 6}" y="${gy + 4}" text-anchor="end" class="ph-tick">${esc(tickLabels[g])}</text>`;
    });
    // Edge dates align to the plot's edges so they never hang outside it.
    const xIdx = [0, Math.floor((n - 1) / 2), n - 1].filter((v, i, a) => a.indexOf(v) === i);
    const xLabels = xIdx
      .map((i) => {
        const anchor = n === 1 ? "middle" : i === 0 ? "start" : i === n - 1 ? "end" : "middle";
        return `<text x="${x(i)}" y="${H - 8}" text-anchor="${anchor}" class="ph-tick">${esc(shortDate(visDates[i]))}</text>`;
      })
      .join("");

    // Step lines: a price holds until the next change. A lone point (one day
    // of data, a store that just appeared, a day isolated by gaps) has no
    // line to draw - a bare moveto renders nothing - so it gets a dot.
    let dots = "";
    const paths = shown
      .map((vendor) => {
        const points = series[vendor].slice(from, end);
        let d = "";
        let penDown = false;
        const present: number[] = [];
        points.forEach((p, i) => {
          if (p === null || p === undefined) {
            penDown = false;
            return;
          }
          present.push(i);
          const cx = x(i).toFixed(1);
          const cy = y(p).toFixed(1);
          d += penDown ? ` H ${cx} V ${cy}` : `M ${cx} ${cy}`;
          penDown = true;
        });
        // Dot every isolated point, plus the ends of a very short series
        // (<=3 visible points) so a day or two of data is still visible.
        const dotIdx = new Set<number>();
        for (const i of present) {
          const before = i > 0 ? points[i - 1] : null;
          const after = i < points.length - 1 ? points[i + 1] : null;
          if ((before === null || before === undefined) && (after === null || after === undefined)) dotIdx.add(i);
        }
        if (present.length > 0 && present.length <= 3) {
          dotIdx.add(present[0] as number);
          dotIdx.add(present[present.length - 1] as number);
        }
        for (const i of dotIdx) {
          const p = points[i] as number;
          dots += `<circle cx="${x(i).toFixed(1)}" cy="${y(p).toFixed(1)}" r="5" class="ph-dot ${seriesClass(vendor)}"><title>${esc(vendorLabel(vendor))}</title></circle>`;
        }
        return d ? `<path d="${d}" class="ph-line ${seriesClass(vendor)}"><title>${esc(vendorLabel(vendor))}</title></path>` : "";
      })
      .join("");

    const rangeDefs = [7, 14, 30, 120].filter((days, i, arr) => days < dates.length || i === arr.length - 1);
    const singleAll = rangeDefs.length === 1 && rangeDefs[0] >= dates.length;
    const rangeControl = singleAll
      ? html`<span class="text-dim">${t(lang, "historyAll")}</span>`
      : html`<label class="visually-hidden" for="ph-range-select">${t(lang, "priceHistory")}</label>
        <select class="select ph-range" id="ph-range-select">${rangeDefs.map((days) => {
          const full = days >= dates.length;
          const label = full ? t(lang, "historyAll") : `${days} ${t(lang, "historyDays")}`;
          return html`<option value="${days}"${dayWindow === (full ? dates.length : days) ? html` selected` : ""}>${label}</option>`;
        })}</select>`;

    // Low / high over the visible window, and the week's move of today's cheapest store.
    const stats = (): Html => {
      let low: { price: number; vendor: string; at: number } | null = null;
      let high: { price: number; vendor: string; at: number } | null = null;
      for (const v of shown) {
        for (let i = start; i < end; i++) {
          const p = series[v][i];
          if (p === null || p === undefined) continue;
          if (!low || p < low.price || (p === low.price && i > low.at)) low = { price: p, vendor: v, at: i };
          if (!high || p > high.price) high = { price: p, vendor: v, at: i };
        }
      }
      const today = shown
        .map((v) => ({ v, p: series[v][end - 1] }))
        .filter((r): r is { v: string; p: number } => r.p !== null && r.p !== undefined)
        .sort((a, b) => a.p - b.p)[0];
      let change: number | null = null;
      if (today) {
        const from = Math.max(0, end - 8);
        const past = series[today.v].slice(from, end - 1).find((p) => p !== null && p !== undefined);
        if (past !== undefined && past !== null) change = today.p - past;
      }
      const when = (at: number): string => (at === end - 1 ? t(lang, "todayLabel") : shortDate(dates[at]));
      const span = dayWindow >= dates.length ? t(lang, "historyAll") : `${dayWindow} ${t(lang, "historyDays")}`;
      return html`<div class="ph-stats">
        ${low ? html`<div class="ph-stat"><span>${t(lang, "historyLow")} · ${span}</span><b>${formatPrice(low.price, currency, lang)} <small>${vendorLabel(low.vendor)}, ${when(low.at)}</small></b></div>` : ""}
        ${high ? html`<div class="ph-stat"><span>${t(lang, "historyHigh")} · ${span}</span><b>${formatPrice(high.price, currency, lang)} <small>${vendorLabel(high.vendor)}, ${when(high.at)}</small></b></div>` : ""}
        ${today && change !== null
          ? html`<div class="ph-stat"><span>${t(lang, "historyChange7")}</span><b class="${change < 0 ? "is-down" : change > 0 ? "is-up" : ""}">${change === 0
              ? t(lang, "noChange")
              : html`<bdi dir="ltr">${change < 0 ? "−" : "+"}${formatPrice(Math.abs(change), currency, lang)}</bdi>`} <small>${vendorLabel(today.v)}</small></b></div>`
          : ""}
      </div>`;
    };

    // Preserve focus across redraws (the range select keeps keyboard context).
    const activeId = restoreFocusId ?? (host.contains(document.activeElement) ? (document.activeElement as HTMLElement).id || "" : "");
    mount(
      host,
      html`<header class="card__head"><h2 class="card__title">${t(lang, "priceHistory")}</h2>${rangeControl}</header>
        ${stats()}
        <div class="ph-legend">${vendors.map((vendor) => {
          const off = hidden.has(vendor);
          return html`<button type="button" class="ph-legend__item${off ? " is-off" : ""}" data-vendor="${vendor}" aria-pressed="${off ? "false" : "true"}" title="${t(lang, "toggleSeries")}"><span class="ph-swatch ${seriesClass(vendor)}"></span>${vendorLabel(vendor)}</button>`;
        })}</div>
        <div class="ph-wrap${compact ? " is-compact" : ""}${docked ? " is-docked" : ""}" style="--ph-stores: ${shown.length}">
          <div class="ph-tip" data-hint="${t(lang, "historyScrubHint")}" data-empty${docked ? "" : html` hidden`}></div>
          <svg class="ph-chart" viewBox="0 0 ${W} ${H}" direction="ltr" role="img" aria-label="${t(lang, "priceHistory")}" tabindex="0">
          </svg>
        </div>`
    );
    // The SVG body holds trusted, already-escaped chart markup built above.
    const svg = host.querySelector<SVGSVGElement>(".ph-chart")!;
    svg.innerHTML = `${grid}${paths}${dots}<line class="ph-cross" y1="${T}" y2="${H - B}" visibility="hidden"/>${xLabels}`;
    if (activeId) host.querySelector<HTMLElement>(`#${activeId}`)?.focus({ preventScroll: true });
    lastDrawnWidth = W;

    const wrap = host.querySelector<HTMLElement>(".ph-wrap")!;
    const tip = wrap.querySelector<HTMLElement>(".ph-tip")!;
    const cross = svg.querySelector<SVGLineElement>(".ph-cross")!;
    const visibleSeries = shown.map((v) => series[v].slice(from, end));

    host.querySelectorAll<HTMLButtonElement>(".ph-legend__item").forEach((btn) => {
      btn.addEventListener("click", () => {
        const vendor = btn.dataset.vendor ?? "";
        if (hidden.has(vendor)) hidden.delete(vendor);
        else hidden.add(vendor);
        // Never leave the chart empty: the last visible line stays on.
        if (visible().length === 0) hidden.delete(vendor);
        draw();
      });
    });

    const fmtDay = (index: number): string => {
      const d = new Date(timestamps[from + index] ?? visDates[index]);
      return Number.isNaN(d.getTime())
        ? shortDate(visDates[index])
        : new Intl.DateTimeFormat(locale, { day: "numeric", month: "numeric", year: "numeric" }).format(d);
    };
    const nearest = (clientX: number): number => {
      const rect = svg.getBoundingClientRect();
      const px = ((clientX - rect.left) / rect.width) * W;
      let best = 0;
      let bestDist = Infinity;
      for (let i = 0; i < n; i++) {
        const dist = Math.abs(x(i) - px);
        if (dist < bestDist) {
          bestDist = dist;
          best = i;
        }
      }
      return best;
    };
    const hide = (): void => {
      // Docked, the strip stays in place showing its hint, so nothing below it moves.
      if (docked) {
        tip.replaceChildren();
        tip.dataset.empty = "";
      } else tip.hidden = true;
      cross.setAttribute("visibility", "hidden");
    };
    const showAt = (best: number, anchorX?: number, anchorY?: number): void => {
      const rows = shown
        .map((vendor, vi) => ({ vendor, price: visibleSeries[vi][best] as number | null }))
        .filter((r) => r.price !== null && r.price !== undefined);
      if (rows.length === 0) {
        hide();
        return;
      }
      const cheapest = Math.min(...rows.map((r) => r.price as number));
      cross.setAttribute("visibility", "visible");
      cross.setAttribute("x1", x(best).toFixed(1));
      cross.setAttribute("x2", x(best).toFixed(1));
      mount(
        tip,
        html`<div class="ph-tip__date">${fmtDay(best)}</div>${rows.map(
          ({ vendor, price }) => html`<div class="ph-tip__row${price === cheapest ? " is-best" : ""}"><span class="ph-swatch ${seriesClass(vendor)}"></span><span class="ph-tip__vendor">${vendorLabel(vendor)}</span><span class="ph-tip__price">${formatPrice(price as number, currency, lang)}</span></div>`
        )}`
      );
      tip.hidden = false;
      delete tip.dataset.empty;
      // Docked (phones, touch): the readout is a strip above the plot, so it
      // never covers the lines and is never under the finger.
      if (docked) {
        tip.style.left = "";
        tip.style.top = "";
        return;
      }
      const wrapRect = wrap.getBoundingClientRect();
      let lx = anchorX !== undefined ? anchorX - wrapRect.left + 14 : (x(best) / W) * wrapRect.width;
      let ly = anchorY !== undefined ? anchorY - wrapRect.top - 10 : 20;
      tip.style.visibility = "hidden";
      tip.style.left = "0px";
      const tw = tip.offsetWidth;
      const th = tip.offsetHeight;
      if (lx + tw + 8 > wrapRect.width) {
        lx = anchorX !== undefined ? anchorX - wrapRect.left - tw - 14 : lx - tw - 28;
      }
      ly = Math.max(4, Math.min(ly, wrapRect.height - th - 4));
      tip.style.left = `${lx}px`;
      tip.style.top = `${ly}px`;
      tip.style.visibility = "";
    };

    let focusIdx = n - 1;
    const point = (clientX: number, clientY: number): void => {
      focusIdx = nearest(clientX);
      showAt(focusIdx, clientX, clientY);
    };
    // Mouse and pen: hover reads the day under the pointer.
    svg.addEventListener("pointermove", (e) => {
      if (e.pointerType !== "touch") point(e.clientX, e.clientY);
    });
    svg.addEventListener("pointerleave", (e) => {
      if (e.pointerType === "mouse") hide();
    });
    // Touch: a finger on the chart scrubs it. Touch events, not pointer
    // events: browsers stop sending pointermove for a touch they might turn
    // into a scroll, so the reading froze on the first tap. Once the finger
    // has moved more sideways than up/down it owns the gesture (the page
    // does not scroll); a mostly vertical swipe stays a page scroll.
    let touchStart: { x: number; y: number } | null = null;
    let scrubbing = false;
    svg.addEventListener(
      "touchstart",
      (e) => {
        const touch = e.touches[0];
        if (!touch || e.touches.length > 1) return;
        touchStart = { x: touch.clientX, y: touch.clientY };
        scrubbing = false;
        point(touch.clientX, touch.clientY);
      },
      { passive: true }
    );
    svg.addEventListener(
      "touchmove",
      (e) => {
        const touch = e.touches[0];
        if (!touch || !touchStart) return;
        if (!scrubbing) {
          const dx = Math.abs(touch.clientX - touchStart.x);
          const dy = Math.abs(touch.clientY - touchStart.y);
          if (dy > dx && dy > 8) {
            touchStart = null;
            return;
          }
          scrubbing = dx > 4;
        }
        if (scrubbing && e.cancelable) e.preventDefault();
        point(touch.clientX, touch.clientY);
      },
      { passive: false }
    );
    const endTouch = (): void => {
      touchStart = null;
      scrubbing = false;
      // The last reading stays up on a phone; the docked strip has room for it.
      if (!docked) hide();
    };
    svg.addEventListener("touchend", endTouch);
    svg.addEventListener("touchcancel", endTouch);
    svg.addEventListener("keydown", (e) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
      e.preventDefault();
      if (e.key === "ArrowLeft") focusIdx = Math.max(0, focusIdx - 1);
      else if (e.key === "ArrowRight") focusIdx = Math.min(n - 1, focusIdx + 1);
      else focusIdx = e.key === "Home" ? 0 : n - 1;
      showAt(focusIdx);
    });
    svg.addEventListener("blur", () => {
      if (!scrubbing && !docked) hide();
    });

    host.querySelector(".ph-range")?.addEventListener("change", (e) => {
      const days = Number((e.target as HTMLSelectElement).value);
      dayWindow = Number.isFinite(days) && days > 0 ? Math.min(days, dates.length) : dates.length;
      draw("ph-range-select");
    });
  };

  // Redraw when the chart's width changes (rotation, window resize), guarded
  // by width so draws never loop. It compares like with like: lastDrawnWidth
  // is the plot width (content box), so this must be too. Comparing the
  // card's outer width against it re-drew the chart on every height change
  // in the column, mid-gesture, which dropped the reading under the finger.
  resizeObserver?.disconnect();
  if (typeof ResizeObserver !== "undefined") {
    const plotWidth = (): number => plotBox(host).width;
    let pending = false;
    resizeObserver = new ResizeObserver(() => {
      if (pending || Math.abs(plotWidth() - lastDrawnWidth) < 24) return;
      pending = true;
      requestAnimationFrame(() => {
        pending = false;
        if (Math.abs(plotWidth() - lastDrawnWidth) < 24) return;
        draw(document.activeElement?.id);
      });
    });
    resizeObserver.observe(host);
  }

  draw();
}
