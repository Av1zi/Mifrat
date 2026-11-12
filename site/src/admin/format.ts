// Formatting for the admin console: Israel wall-clock times (the owner's
// clock; the data is UTC), relative ages, counts.

const TZ = "Asia/Jerusalem";

const timeFmt = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false });
const dayFmt = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, weekday: "short", day: "numeric", month: "short" });
const shortDayFmt = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, day: "numeric", month: "numeric" });
const dateKeyFmt = new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" });

export function ilTime(iso: string): string {
  return timeFmt.format(new Date(iso));
}

export function ilDay(iso: string): string {
  return dayFmt.format(new Date(iso));
}

export function ilShortDay(iso: string | Date): string {
  return shortDayFmt.format(typeof iso === "string" ? new Date(iso) : iso);
}

/** Israel calendar date (YYYY-MM-DD) of an instant. */
export function ilDateKey(at: string | Date): string {
  return dateKeyFmt.format(typeof at === "string" ? new Date(at) : at);
}

export function ilDateTime(iso: string): string {
  return `${ilDay(iso)}, ${ilTime(iso)}`;
}

export function ago(iso: string, now: Date): string {
  const minutes = Math.round((now.getTime() - new Date(iso).getTime()) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 36) return `${hours}h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

export function n(value: number | null | undefined): string {
  return value == null ? "–" : value.toLocaleString("en-US");
}

export function ils(value: number | null | undefined): string {
  return value == null ? "–" : `₪${value.toLocaleString("en-US")}`;
}

export function pct(delta: number, base: number): string {
  if (!base) return "";
  const p = (100 * delta) / base;
  return `${p > 0 ? "+" : ""}${p.toFixed(p > -10 && p < 10 ? 1 : 0)}%`;
}
