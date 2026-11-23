import type { QaCase } from "./types";

/** Keep reviewed history in the payload, but show only unresolved QA work. */
export function openQaCases(cases: readonly QaCase[]): QaCase[] {
  return cases.filter((case_) => !case_.dismissed && !case_.fixed);
}
