import { loadHistory } from "../../api";
import { formatPrice } from "../../format";
import { t, vendorLabel } from "../../i18n";
import type { Currency, Lang } from "../../types";
import { html, mount } from "../../ui/html";
import { esc } from "../../utils";

const SERIES = 8;

/** Redraws when the card's width changes; module-level so a route re-entry disconnects the old one. */
let resizeObserver: ResizeObserver | null = null;

/** Series class (colour comes from the --chart-n tokens in chart.css). */
const seriesClass = (index: number): string => `ph-c${(index % SERIES) + 1}`;

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
  if (dates.length < 2) return;
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
  const shortDate = (iso: string): string => {
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
    const visDates = dates.slice(start, end);

    const shown = visible();
    let lo = Infinity;
    let hi = -Infinity;
    for (const v of shown) {
      for (const p of series[v].slice(start, end)) {
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

    // Match the viewBox to the card's pixel width so 1 SVG unit stays ~1 CSS
    // pixel (a stretched fixed viewBox scales the axis labels with it).
    const measured = host.clientWidth > 0 ? host.clientWidth : Math.max(320, (host.parentElement?.clientWidth ?? 940) - 44);
    const W = Math.max(320, Math.min(1400, Math.round(measured)));
    const H = Math.max(200, Math.min(340, Math.round(W * 0.32)));
    const L = 88;
    const R = 18;
    const T = 12;
    const B = 30;
    const n = visDates.length;
    const x = (i: number): number => (n === 1 ? (L + W - R) / 2 : L + (W - L - R) * (i / (n - 1)));
    const y = (v: number): number => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);

    const ticks = 4;
    let grid = "";
    for (let g = 0; g <= ticks; g++) {
      const value = lo + ((hi - lo) * g) / ticks;
      const gy = y(value);
      grid += `<line x1="${L}" y1="${gy}" x2="${W - R}" y2="${gy}" class="ph-grid"/>`;
      grid += `<text x="${L - 8}" y="${gy + 4}" text-anchor="end" class="ph-tick">${formatPrice(Math.round(value), currency, lang)}</text>`;
    }
    const xLabels = [0, Math.floor((n - 1) / 2), n - 1]
      .filter((v, i, a) => a.indexOf(v) === i)
      .map((i) => `<text x="${x(i)}" y="${H - 8}" text-anchor="middle" class="ph-tick">${shortDate(visDates[i])}</text>`)
      .join("");

    // Step lines: a price holds until the next change.
    const paths = shown
      .map((vendor) => {
        const points = series[vendor].slice(start, end);
        let d = "";
        let penDown = false;
        points.forEach((p, i) => {
          if (p === null || p === undefined) {
            penDown = false;
            return;
          }
          const cx = x(i).toFixed(1);
          const cy = y(p).toFixed(1);
          d += penDown ? ` H ${cx} V ${cy}` : `M ${cx} ${cy}`;
          penDown = true;
        });
        return d ? `<path d="${d}" class="ph-line ${seriesClass(vendors.indexOf(vendor))}"><title>${esc(vendorLabel(vendor))}</title></path>` : "";
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

    // Preserve focus across redraws (the range select keeps keyboard context).
    const activeId = restoreFocusId ?? (host.contains(document.activeElement) ? (document.activeElement as HTMLElement).id || "" : "");
    host.hidden = false;
    mount(
      host,
      html`<header class="card__head"><h2 class="card__title">${t(lang, "priceHistory")}</h2>${rangeControl}</header>
        <div class="ph-legend">${vendors.map((vendor) => {
          const off = hidden.has(vendor);
          return html`<button type="button" class="ph-legend__item${off ? " is-off" : ""}" data-vendor="${vendor}" aria-pressed="${off ? "false" : "true"}" title="${t(lang, "toggleSeries")}"><span class="ph-swatch ${seriesClass(vendors.indexOf(vendor))}"></span>${vendorLabel(vendor)}</button>`;
        })}</div>
        <div class="ph-wrap">
          <svg class="ph-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${t(lang, "priceHistory")}" tabindex="0">
          </svg>
          <div class="ph-tip" hidden></div>
        </div>`
    );
    // The SVG body holds trusted, already-escaped chart markup built above.
    const svg = host.querySelector<SVGSVGElement>(".ph-chart")!;
    svg.innerHTML = `${grid}${paths}<line class="ph-cross" y1="${T}" y2="${H - B}" visibility="hidden"/>${xLabels}`;
    if (activeId) host.querySelector<HTMLElement>(`#${activeId}`)?.focus({ preventScroll: true });
    lastDrawnWidth = W;

    const wrap = host.querySelector<HTMLElement>(".ph-wrap")!;
    const tip = wrap.querySelector<HTMLElement>(".ph-tip")!;
    const cross = svg.querySelector<SVGLineElement>(".ph-cross")!;
    const visibleSeries = shown.map((v) => series[v].slice(start, end));

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
      const d = new Date(timestamps[start + index] ?? visDates[index]);
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
      tip.hidden = true;
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
          ({ vendor, price }) => html`<div class="ph-tip__row${price === cheapest ? " is-best" : ""}"><span class="ph-swatch ${seriesClass(vendors.indexOf(vendor))}"></span><span class="ph-tip__vendor">${vendorLabel(vendor)}</span><span class="ph-tip__price">${formatPrice(price as number, currency, lang)}</span></div>`
        )}`
      );
      tip.hidden = false;
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
    svg.addEventListener("mousemove", (e) => {
      focusIdx = nearest(e.clientX);
      showAt(focusIdx, e.clientX, e.clientY);
    });
    svg.addEventListener("mouseleave", hide);
    // Touch + keyboard: focus the chart and arrow through points.
    svg.addEventListener(
      "touchstart",
      (e) => {
        const touch = e.touches[0];
        if (!touch) return;
        focusIdx = nearest(touch.clientX);
        showAt(focusIdx, touch.clientX, touch.clientY);
      },
      { passive: true }
    );
    svg.addEventListener("keydown", (e) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
      e.preventDefault();
      if (e.key === "ArrowLeft") focusIdx = Math.max(0, focusIdx - 1);
      else if (e.key === "ArrowRight") focusIdx = Math.min(n - 1, focusIdx + 1);
      else focusIdx = e.key === "Home" ? 0 : n - 1;
      showAt(focusIdx);
    });
    svg.addEventListener("blur", hide);

    host.querySelector(".ph-range")?.addEventListener("change", (e) => {
      const days = Number((e.target as HTMLSelectElement).value);
      dayWindow = Number.isFinite(days) && days > 0 ? Math.min(days, dates.length) : dates.length;
      draw("ph-range-select");
    });
  };

  // Redraw when the card's width changes (window resize, sidebar collapse),
  // guarded by width so draws never loop.
  resizeObserver?.disconnect();
  if (typeof ResizeObserver !== "undefined" && host.parentElement) {
    let pending = false;
    resizeObserver = new ResizeObserver(() => {
      if (pending || Math.abs((host.clientWidth || 0) - lastDrawnWidth) < 24) return;
      pending = true;
      requestAnimationFrame(() => {
        pending = false;
        if (Math.abs((host.clientWidth || 0) - lastDrawnWidth) < 24) return;
        draw(document.activeElement?.id);
      });
    });
    resizeObserver.observe(host.parentElement);
  }

  draw();
}
