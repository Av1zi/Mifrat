import { readItem, writeItem } from "./storage";
import type { Currency, Lang } from "./types";

const FX_CACHE_KEY = "mifrat:fx:ils-usd";
const FX_ENDPOINT = "https://api.frankfurter.dev/v1/latest?base=ILS&symbols=USD";

interface FxCache {
  date: string; // YYYY-MM-DD, local cache day — refetch once per day at most
  rate: number; // 1 ILS = `rate` USD
}

let fxRate: number | null = null;

function todayStr(): string {
  return new Date().toISOString().slice(0, 10);
}

function isRate(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

/**
 * Fetches the ILS->USD rate at most once per day, cached in localStorage.
 * Best-effort only: if this fails (offline, API down), the app just stays
 * on ILS-only display — currency conversion is a convenience, never a
 * dependency for the site to function.
 */
export async function ensureFxRate(): Promise<void> {
  if (fxRate !== null) return;

  try {
    const cachedRaw = readItem(FX_CACHE_KEY);
    if (cachedRaw) {
      const cached = JSON.parse(cachedRaw) as Partial<FxCache> | null;
      if (cached?.date === todayStr() && isRate(cached.rate)) {
        fxRate = cached.rate;
        return;
      }
    }
  } catch {
    // Corrupt cache entry — ignore and refetch below.
  }

  try {
    const res = await fetch(FX_ENDPOINT);
    if (!res.ok) return;
    const data = await res.json();
    const rate: unknown = data?.rates?.USD;
    if (isRate(rate)) {
      fxRate = rate;
      writeItem(FX_CACHE_KEY, JSON.stringify({ date: todayStr(), rate }));
    }
  } catch {
    // Offline or blocked — silently skip, ILS display still works fine.
  }
}

export function formatPrice(priceIls: number | null, currency: Currency, lang: Lang): string {
  if (priceIls === null) return lang === "he" ? "מחיר לא זמין" : "Price unavailable";

  const locale = lang === "he" ? "he-IL" : "en-US";

  if (currency === "USD" && fxRate !== null) {
    const usd = priceIls * fxRate;
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 0,
    }).format(usd);
  }

  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: "ILS",
    maximumFractionDigits: 0,
  }).format(priceIls);
}
