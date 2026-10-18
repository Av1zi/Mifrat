import { loadHistory } from "./api";
import type { PriceHistoryFile } from "./types";

/**
 * Price-drop signals, derived only from data/site/history/<category>.json.
 * A product gets a signal only when its recorded history is long enough to
 * mean something; nothing here is estimated or invented.
 */
export interface PriceSignal {
  /** Today's lowest price across vendors. */
  current: number;
  /** Median of that vendor's price over the window. */
  typical: number;
  /** Percent below `typical` (0 when not below). */
  dropPct: number;
  /** Today's price is the lowest of the window and was higher at some point. */
  lowest: boolean;
  /** Days with a price for that vendor inside the window. */
  days: number;
}

export const SIGNAL_WINDOW_DAYS = 30;
/** Fewer recorded days than this is a blip, not a trend. */
const MIN_DAYS = 7;
/** Smaller moves are noise. */
export const MIN_DROP_PCT = 5;
const MIN_LOW_GAP = 0.02;
/** A vendor missing from a snapshot keeps its last price for this many days. */
const GAP_FILL_DAYS = 7;

/** One vendor's prices over the window, short gaps carried forward, null where unknown. */
function filledSeries(prices: Array<number | null>, from: number, end: number): Array<number | null> {
  const out: Array<number | null> = new Array<number | null>(end - from).fill(null);
  let last: number | null = null;
  let gap = 0;
  // Start a little before the window so a gap at its edge can be filled.
  for (let i = Math.max(0, from - GAP_FILL_DAYS); i < end; i++) {
    const price = prices[i];
    if (typeof price === "number" && price > 0) {
      last = price;
      gap = 0;
    } else if (last !== null && ++gap > GAP_FILL_DAYS) {
      last = null;
    }
    if (i >= from) out[i - from] = last;
  }
  return out;
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = sorted.length >> 1;
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/**
 * The signal follows the vendor that holds today's lowest price and looks at
 * that vendor's own series. A cross-vendor "lowest per day" would read a
 * cheaper store appearing in the data as a price drop, which it is not.
 */
function signalFor(file: PriceHistoryFile, series: Record<string, Array<number | null>>): PriceSignal | null {
  const end = file.dates.length;
  const lastDate = Date.parse(file.dates[end - 1] ?? "");
  if (!Number.isFinite(lastDate)) return null;
  let from = end - 1;
  while (from > 0 && (lastDate - Date.parse(file.dates[from - 1])) / 86_400_000 < SIGNAL_WINDOW_DAYS) from--;

  const vendors = Object.values(series)
    .filter((prices) => Array.isArray(prices))
    .map((prices) => filledSeries(prices, from, end));
  const today = vendors.map((v) => v[v.length - 1]);
  const current = Math.min(...today.filter((p): p is number => p !== null));
  if (!Number.isFinite(current)) return null;

  const own = vendors[today.indexOf(current)].filter((p): p is number => p !== null);
  if (own.length < MIN_DAYS) return null;
  // Lowest of every vendor on every day of the window, not just of its own.
  const windowLow = Math.min(...vendors.flat().filter((p): p is number => p !== null));

  const typical = median(own);
  const high = Math.max(...own);
  const dropPct = Math.max(0, Math.round(((typical - current) / typical) * 100));
  const lowest = current <= windowLow && (high - current) / high >= MIN_LOW_GAP;
  if (dropPct < MIN_DROP_PCT && !lowest) return null;
  return { current, typical: Math.round(typical), dropPct, lowest, days: own.length };
}

/** Every product of the file that currently carries a signal. */
export function computeSignals(file: PriceHistoryFile): Map<string, PriceSignal> {
  const out = new Map<string, PriceSignal>();
  if (!Array.isArray(file.dates) || file.dates.length < MIN_DAYS) return out;
  for (const [id, entry] of Object.entries(file)) {
    if (id === "dates" || id === "timestamps" || Array.isArray(entry) || !entry?.v) continue;
    const signal = signalFor(file, entry.v);
    if (signal) out.set(id, signal);
  }
  return out;
}

const cache = new Map<string, Promise<Map<string, PriceSignal>>>();

/** Signals per product id for a category; empty when there is no history file. */
export function loadSignals(category: string): Promise<Map<string, PriceSignal>> {
  let promise = cache.get(category);
  if (!promise) {
    promise = loadHistory(category).then((file) => (file ? computeSignals(file) : new Map()));
    cache.set(category, promise);
  }
  return promise;
}
