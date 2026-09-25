"""
specs/export_site.py — generate the frontend's spec metadata from the schema.

One definition, four consumers (plan §3): the same `schema.py` tables produce

1. `site/src/specSchema.generated.ts` — per-category ordered field lists with
   type/label/filterable/group metadata, consumed by
   - site/src/specs.ts (display order + filter allowlist),
   - site/src/i18n.ts (attribute labels),
   - site/src/views/product.ts (the PDP spec sheet, "Unknown" for nulls),
   - site/src/types.ts (the ProductSpecs value type);
2. the JSON schema (`python -c "from scraper.specs import schema; ..."`);
3. the golden-test field lists;
4. this generator itself, which `scripts/check_spec_sync.py` re-runs in CI and
   fails on any diff — so the frontend can never drift from the extractor.

Usage (repo root):
    python -m scraper.specs.export_site            # write the file
    python -m scraper.specs.export_site --check    # exit 1 if it would change
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import schema

ROOT = Path(__file__).resolve().parent.parent.parent
OUT_PATH = ROOT / "site" / "src" / "specSchema.generated.ts"

HEADER = """/**
 * GENERATED FILE — DO NOT EDIT.
 *
 * Source of truth: scraper/specs/schema.py (see scraper/specs/README.md).
 * Regenerate with:  python -m scraper.specs.export_site
 * CI check:         python scraper/scripts/check_spec_sync.py (or --check above)
 */

export interface SpecFieldMeta {
  /** Schema field name (units live in the name: `_ghz`, `_mm`, `_w`, ...). */
  name: string;
  type: "int" | "float" | "bool" | "str" | "enum" | "list_str" | "dict_int";
  unit: string | null;
  enum: string[];
  filterable: boolean;
  group: string;
  /** Short display label (Hebrew / English). */
  he: string;
  en: string;
}

/** Schema version — bump in schema.py; golden fixtures record it too. */
export const SCHEMA_VERSION = %(version)d;

/** Ordered spec fields per category (the PDP renders exactly this order). */
export const SPEC_FIELDS: Record<string, SpecFieldMeta[]> = %(fields)s;

/** Category -> filterable field names (the filter rail's allowlist). */
export const FILTERABLE_FIELDS: Record<string, string[]> = %(filterable)s;

/** Field -> label, merged into i18n ATTRIBUTE_LABELS. */
export const SPEC_LABELS: Record<string, { he: string; en: string }> = %(labels)s;
"""


def _ts_string(value: str | None) -> str:
    if value is None:
        return "null"
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _field_literal(field: schema.FieldSpec) -> str:
    enum = ", ".join(_ts_string(item) for item in field.enum)
    return (
        "{ name: " + _ts_string(field.name)
        + ", type: " + _ts_string(field.type)
        + ", unit: " + _ts_string(field.unit)
        + ", enum: [" + enum + "]"
        + f", filterable: {'true' if field.filterable else 'false'}"
        + ", group: " + _ts_string(field.group)
        + ", he: " + _ts_string(field.label_he)
        + ", en: " + _ts_string(field.label_en)
        + " }"
    )


def render() -> str:
    categories = list(schema.SCHEMA)
    block_lines: list[str] = ["{"]
    for category in categories:
        fields = schema.fields_for(category)
        block_lines.append(f"  {_ts_string(category)}: [")
        for field in fields:
            block_lines.append(f"    {_field_literal(field)},")
        block_lines.append("  ],")
    block_lines.append("}")

    filterable_lines: list[str] = ["{"]
    for category in categories:
        names = ", ".join(_ts_string(name) for name in schema.filterable_fields(category))
        filterable_lines.append(f"  {_ts_string(category)}: [{names}],")
    filterable_lines.append("}")

    labels: dict[str, tuple[str, str]] = {}
    for category in categories:
        for field in schema.fields_for(category):
            labels.setdefault(field.name, (field.label_he, field.label_en))
    label_lines: list[str] = ["{"]
    for name in sorted(labels):
        he, en = labels[name]
        label_lines.append(f'  {_ts_string(name)}: {{ he: {_ts_string(he)}, en: {_ts_string(en)} }},')
    label_lines.append("}")

    return HEADER % {
        "version": schema.SCHEMA_VERSION,
        "fields": "\n".join(block_lines),
        "filterable": "\n".join(filterable_lines),
        "labels": "\n".join(label_lines),
    }


def main() -> int:
    check = "--check" in sys.argv[1:]
    rendered = render()
    current = OUT_PATH.read_text(encoding="utf-8") if OUT_PATH.exists() else ""
    if current == rendered:
        print(f"[spec-export] {OUT_PATH.relative_to(ROOT)} is up to date")
        return 0
    if check:
        print(f"[spec-export] FAIL: {OUT_PATH.relative_to(ROOT)} is stale — "
              "run: python -m scraper.specs.export_site")
        return 1
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(rendered, encoding="utf-8")
    print(f"[spec-export] wrote {OUT_PATH.relative_to(ROOT)} "
          f"({len(rendered):,} bytes, {len(schema.SCHEMA)} categories)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
