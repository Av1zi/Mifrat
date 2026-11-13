/**
 * Motherboard form factors, shared by the case filters and the board/case
 * compatibility check. Vendors spell them a dozen ways ("Micro ATX", "mATX",
 * "Micro-ATX、Mini-ITX", "E-ATX (310mm Width)"), so everything goes through
 * `boardSize` first.
 */

export type BoardSize =
  | "XL-ATX"
  | "E-ATX"
  | "SSI-EEB"
  | "SSI-CEB"
  | "ATX"
  | "Micro-ATX"
  | "Mini-DTX"
  | "Mini-ITX"
  | "Thin Mini-ITX";

/** Largest first: the order the filter rail lists them in. */
export const BOARD_ORDER: BoardSize[] = [
  "XL-ATX",
  "E-ATX",
  "SSI-EEB",
  "SSI-CEB",
  "ATX",
  "Micro-ATX",
  "Mini-DTX",
  "Mini-ITX",
  "Thin Mini-ITX",
];

/** PCPartPicker's spelling of each size ("EATX", "Micro ATX"). */
export const BOARD_LABEL: Record<BoardSize, string> = {
  "XL-ATX": "XL ATX",
  "E-ATX": "EATX",
  "SSI-EEB": "SSI EEB",
  "SSI-CEB": "SSI CEB",
  ATX: "ATX",
  "Micro-ATX": "Micro ATX",
  "Mini-DTX": "Mini DTX",
  "Mini-ITX": "Mini ITX",
  "Thin Mini-ITX": "Thin Mini ITX",
};

/** One spelling -> its size, or null when the text names no board size. */
export function boardSize(text: unknown): BoardSize | null {
  if (text === null || text === undefined) return null;
  const v = String(text).toUpperCase().replace(/[^A-Z0-9]/g, "");
  if (!v) return null;
  if (v.includes("SSIEEB")) return "SSI-EEB";
  if (v.includes("SSICEB")) return "SSI-CEB";
  if (v.includes("THINMINIITX")) return "Thin Mini-ITX";
  if (v.includes("MINIDTX")) return "Mini-DTX";
  if (v.includes("MINIITX") || v === "ITX") return "Mini-ITX";
  if (v.includes("MICROATX") || v === "MATX" || v === "UATX") return "Micro-ATX";
  if (v.includes("XLATX")) return "XL-ATX";
  if (v.includes("EATX") || v.includes("EXTENDEDATX")) return "E-ATX";
  if (v.includes("ATX")) return "ATX";
  return null;
}

/**
 * The board sizes a case lists, one entry per size. List cells that arrive
 * unsplit ("ATX / Micro-ATX / Mini-ITX", "Micro-ATX、Mini-ITX") are split here.
 */
export function listedBoardSizes(value: unknown): BoardSize[] {
  if (!Array.isArray(value)) return [];
  const found = new Set<BoardSize>();
  for (const cell of value) {
    for (const part of String(cell).split(/[/、,|+]|\s{2,}|:/)) {
      const size = boardSize(part);
      if (size) found.add(size);
    }
  }
  return BOARD_ORDER.filter((size) => found.has(size));
}

/**
 * Smaller ATX-family boards share the larger ones' mounting holes, so a case
 * that takes an ATX board also takes Micro-ATX and Mini-ITX even when the
 * listing only names "ATX". Mini-DTX and Thin Mini-ITX are never implied.
 */
const IMPLIES: Partial<Record<BoardSize, BoardSize[]>> = {
  "XL-ATX": ["ATX", "Micro-ATX", "Mini-ITX"],
  "E-ATX": ["ATX", "Micro-ATX", "Mini-ITX"],
  "SSI-EEB": ["ATX", "Micro-ATX", "Mini-ITX"],
  "SSI-CEB": ["ATX", "Micro-ATX", "Mini-ITX"],
  ATX: ["Micro-ATX", "Mini-ITX"],
  "Micro-ATX": ["Mini-ITX"],
};

/** Every board size a case takes: the listed ones plus the ones they imply. */
export function supportedBoardSizes(value: unknown): BoardSize[] {
  const listed = listedBoardSizes(value);
  const all = new Set<BoardSize>(listed);
  for (const size of listed) for (const smaller of IMPLIES[size] ?? []) all.add(smaller);
  return BOARD_ORDER.filter((size) => all.has(size));
}

type CaseFamily = "ATX" | "MicroATX" | "Mini ITX";

function familyOf(size: BoardSize): CaseFamily {
  if (size === "Micro-ATX") return "MicroATX";
  if (size === "Mini-ITX" || size === "Mini-DTX" || size === "Thin Mini-ITX") return "Mini ITX";
  return "ATX";
}

/**
 * The case's board family, from the largest board it lists; else from a size
 * the case type or product name spells out ("Compact MicroATX", "NX200M Micro").
 */
function caseFamily(mbFormFactors: unknown, type: string, name: string): CaseFamily | null {
  const listed = listedBoardSizes(mbFormFactors);
  if (listed.length > 0) return familyOf(listed[0]);
  const fromType = boardSize(type);
  if (fromType) return familyOf(fromType);
  if (/\bm-?atx\b|\bmicro\b/i.test(name)) return "MicroATX";
  if (/\b(?:mini[\s-]?)?itx\b/i.test(name)) return "Mini ITX";
  return null;
}

/**
 * PCPartPicker's case type ("ATX Mid Tower", "MicroATX Mini Tower", "Mini ITX
 * Desktop", "Rackmount 4U"): board family + body style. Null when either half
 * is unknown; the case still shows under the motherboard form-factor filter.
 */
export function caseType(type: unknown, mbFormFactors: unknown, name = ""): string | null {
  const raw = typeof type === "string" ? type : "";
  const rack = raw.match(/\b([1-5])U\b/i);
  if (rack) return `Rackmount ${rack[1]}U`;
  if (/HTPC/i.test(raw)) return "HTPC";
  const body = /full|ultra/i.test(raw)
    ? "Full Tower"
    : /mid/i.test(raw)
      ? "Mid Tower"
      : /mini\s*tower|small|compact/i.test(raw)
        ? "Mini Tower"
        : /sff|desktop/i.test(raw)
          ? "Desktop"
          : /tower/i.test(raw)
            ? "Tower"
            : null;
  if (!body) return null;
  const family = caseFamily(mbFormFactors, raw, name);
  if (!family) return null;
  // PCPartPicker has one tower class for ITX: "Mini ITX Tower".
  if (family === "Mini ITX" && body !== "Desktop") return "Mini ITX Tower";
  return `${family} ${body === "Tower" ? "Mid Tower" : body}`;
}
