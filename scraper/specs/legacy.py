"""
specs/legacy.py — the transitional `attributes` view (one cycle only).

The frontend's filters, table columns, variant pills and the compatibility
engine still read `attributes` (site/src/specs.ts FILTER_ALLOWLIST,
views/category.ts, build.ts), and matching.py reads it for canonical product
naming. Rather than keep two parallel spec systems, `attributes` is now
DERIVED from the merged `specs`:

- every schema field emits its own name plus every alias it declares
  (`core_count` + `cores`, `total_gb` + `capacity_gb`/`capacity`/`kit`, ...),
  so existing consumers keep finding the keys they were written against;
- booleans emit "Yes"/"No" strings, matching the pre-overhaul canonical form
  the filter rail labeled;
- a small table below fixes the handful of keys whose legacy *shape* was a
  formatted string ("750W", "2x16GB", "80 PLUS Gold", "PCIe Gen 4.0").

Why this is safe: values round-trip. Feeding this view back through
`vendor_struct.ingest_computed_attributes()` reproduces the same schema values
(canonicalizers map "Tray" -> tray, "80 PLUS Gold" -> 80+ Gold), which is what
lets the per-listing and product-level passes agree.

Removal: once the frontend is re-keyed to `specs` (plan Phase 4), delete this
module and the `attributes` field together.
"""

from __future__ import annotations

import re

from . import schema
from .derive import derived_extras

_YES = "Yes"
_NO = "No"


def _join(value) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return ", ".join(f"{count}x {name}" for name, count in value.items())
    return str(value)


def _fmt_capacity_gb(value) -> str:
    gb = int(value)
    return f"{gb // 1000}TB" if gb >= 1000 and gb % 1000 == 0 else f"{gb}GB"


def _fmt_tdp(value) -> str:
    return f"{int(value)}W"


def _wifi_standard(specs: dict) -> str | None:
    """Old shape was uppercase 'WIFI6E'; the schema stores 'Wi-Fi 6E'."""
    text = specs.get("wireless")
    if not isinstance(text, str):
        return None
    match = re.search(r"wi-?fi\s?([67])\s?(e)?", text, re.I)
    if match:
        return f"WIFI{match.group(1)}{(match.group(2) or '').upper()}"
    return None


def _rack_max(rack: dict) -> int | None:
    sizes = []
    for key in rack:
        match = re.search(r"(\d{2,3})", str(key))
        if match:
            sizes.append(int(match.group(1)))
    return max(sizes) if sizes else None


def _legacy_shapes(category: str | None, specs: dict) -> dict:
    """Legacy keys whose historic value was a formatted string."""
    out: dict = {}

    if specs.get("tdp_w") is not None:
        out["tdp"] = _fmt_tdp(specs["tdp_w"])
    if specs.get("total_gb") is not None:
        out["memory"] = f"{int(specs['total_gb'])}GB"
        out["capacity"] = f"{int(specs['total_gb'])}GB"
        if specs.get("module_count") and specs.get("module_size_gb"):
            kit = f"{int(specs['module_count'])}x{int(specs['module_size_gb'])}GB"
            out["kit"] = kit
            out["modules"] = kit
    if specs.get("capacity_gb") is not None:
        out["capacity"] = _fmt_capacity_gb(specs["capacity_gb"])
    if specs.get("memory_gb") is not None:
        out["memory"] = f"{int(specs['memory_gb'])}GB"
    if specs.get("l2_cache_mb") is not None:
        out["l2_cache"] = f"{int(specs['l2_cache_mb'])}MB"
    if specs.get("l3_cache_mb") is not None:
        out["l3_cache"] = f"{int(specs['l3_cache_mb'])}MB"
    if specs.get("pcie_gen") is not None:
        out["pcie_gen"] = f"PCIe Gen {int(specs['pcie_gen'])}.0"
    if specs.get("packaging"):
        out["packaging"] = "Tray" if specs["packaging"] in ("tray", "oem") else "Box"
    if specs.get("efficiency"):
        out["efficiency"] = "80 PLUS " + str(specs["efficiency"]).replace("80+ ", "")
    if specs.get("wattage_w") is not None:
        out["wattage"] = f"{int(specs['wattage_w'])}W"
    if specs.get("length_mm") is not None:
        out["length"] = f"{int(specs['length_mm'])} mm"
    if specs.get("noise_db") is not None:
        out["noise_level"] = f"{specs['noise_db']} dB"
    if specs.get("airflow_cfm") is not None:
        out["airflow"] = f"{specs['airflow_cfm']} CFM"
    if specs.get("first_word_latency_ns") is not None:
        out["first_word_latency"] = f"{specs['first_word_latency_ns']} ns"
    if specs.get("voltage_v") is not None:
        out["voltage"] = f"{specs['voltage_v']}V"
    if specs.get("rpm") is not None:
        out["spindle_speed"] = f"{int(specs['rpm'])} RPM"
    if specs.get("max_gpu_length_mm") is not None:
        out["maximum_video_card_length"] = f"{int(specs['max_gpu_length_mm'])}mm"
    if specs.get("volume_l") is not None:
        out["external_volume"] = f"{specs['volume_l']}L"
    if specs.get("m2_slots"):
        # Legacy key was the slot COUNT; the schema keeps the slot list
        # ("M.2 x3"), so read the count out of the first entry.
        first = specs["m2_slots"][0] if isinstance(specs["m2_slots"], list) else ""
        match = re.search(r"x\s*(\d+)", str(first))
        out["m2_slots"] = int(match.group(1)) if match else len(specs["m2_slots"])
    if specs.get("radiator_support"):
        rack = _rack_max(specs["radiator_support"])
        if rack:
            out["supported_radiator_mm"] = rack
    standard = _wifi_standard(specs)
    if standard:
        out["wifi_standard"] = standard
    if specs.get("wireless"):
        out["wifi"] = _YES if specs["wireless"] != "None" else _NO
    if specs.get("type") and category == "case":
        out["case_type"] = specs["type"]
    return out


def to_attributes(category: str | None, specs: dict,
                  passthrough: dict | None = None) -> dict:
    """Project a merged spec sheet into the legacy `attributes` blob.

    `passthrough` carries non-schema keys callers deliberately maintain
    (`bundle_only`, and any vendor key that never became a schema field).
    """
    fields = schema.field_map(category)
    attributes: dict = {}

    for name, value in specs.items():
        if value is None:
            continue
        field = fields.get(name)
        if field is None:
            continue
        rendered = value
        if field.type == "bool":
            rendered = _YES if value else _NO
        elif field.type in ("list_str", "dict_int"):
            rendered = _join(value)
        for key in (name, *field.aliases):
            attributes.setdefault(key, rendered)

    if specs.get("part_numbers"):
        attributes.setdefault("mpn", str(specs["part_numbers"][0]))

    attributes.update(_legacy_shapes(category, specs))
    attributes.update(derived_extras(category, specs))

    for key, value in (passthrough or {}).items():
        if schema.field_for_key(category, key) is None:
            attributes[key] = value
    return attributes
