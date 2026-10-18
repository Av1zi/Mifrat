import { signalDown, t } from "../i18n";
import { MIN_DROP_PCT, type PriceSignal } from "../signals";
import type { Lang } from "../types";
import { chip } from "./chip";
import { html, type Html } from "./html";

/** "Down N%" and "Lowest in 30 days" chips for a product that has a signal. */
export function signalBadges(signal: PriceSignal | undefined, lang: Lang): Html {
  if (!signal) return html``;
  const title = t(lang, "signalTypicalTitle");
  return html`<span class="signals">${signal.dropPct >= MIN_DROP_PCT ? chip(signalDown(lang, signal.dropPct), { tone: "ok", title }) : ""}${signal.lowest ? chip(t(lang, "signalLowest"), { tone: "brand", title }) : ""}</span>`;
}
