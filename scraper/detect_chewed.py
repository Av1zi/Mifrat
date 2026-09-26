"""Detect mattes that ate INTO the product (interior holes/bites/fragments).

isnet-general-use sometimes removes product interior it mistakes for
background — brushed-metal CPU heatspreaders, white IHS areas, box-art
graphics (Sep 2026: user found Ryzen 8000/9000 + Threadripper PRO renders
with bites out of the IHS, and a Ryzen-7 box reduced to fragments).
Alpha-share QA cannot see this: the renders are big and mostly opaque.

Signals (all webp-intrinsic, no source needed):
  big_hole    enclosed-hole components bigger than 0.2% of the alpha bbox
              each, summed as a share of the bbox. The size floor matters:
              mesh panels, fan grilles and motherboard mounting holes show
              genuine see-through pinholes — small by construction — while a
              bite out of an IHS is percents-large. Deliberately NOT used:
              fill ratio (multi-item kit photos have legitimately low fill
              from the gap between sticks) and raw hole share (same pinhole
              problem).
  fragments   significant opaque components (each >0.1% of bbox) — backstop
              for box-art shredding. A healthy product is 1 body.

Thresholds are category-aware (solid products vs see-through-prone ones).

Usage:
  python -m scraper.detect_chewed --report tmp/chewed.txt
  python -m scraper.detect_chewed --quarantine   # delete webp+thumb, pin keep_jpg
  python -m scraper.detect_chewed --filter-list tmp/renders.txt  # CI: drop
      flagged paths from a process_images --list-out file before commit
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

try:
    import numpy as np
    from scipy import ndimage
    _HAVE_SCI = True
except ImportError:  # pragma: no cover
    _HAVE_SCI = False

IMAGES_DIR = Path("data/images")
KEEP_JPG_FILE = IMAGES_DIR / "keep_jpg.txt"
THUMB_SUBDIR = "thumbs"
CATALOG_FILE = Path("data/catalog.json")

OPAQUE_AT = 128          # alpha >= this counts as product
MIN_FRAG_SHARE = 0.001   # opaque component this big counts as a fragment
BIG_HOLE_MIN = 0.002     # enclosed holes below this bbox share are pinholes
                         # (mesh/grilles/mounting holes), not bites

# Solid products: any real bite is chewing (a CPU IHS, an SSD PCB, a DIMM
# stick and a motherboard have no legit percents-large see-through areas).
STRICT_CATS = {"cpu", "memory", "storage", "motherboard"}
STRICT_BIG_HOLE = 0.01
# See-through-prone products (mesh cases, fans, fin stacks, PSU grilles)
# and unmapped SKUs: only carnage-level damage is actionable automatically.
LENIENT_BIG_HOLE = 0.12
CARNAGE_FRAGS = 15       # backstop for every category


def analyze(webp: Path) -> dict | None:
    """Metrics for one render, or None when unreadable."""
    try:
        with Image.open(webp) as im:
            im.load()
            rgba = im.convert("RGBA")
    except Exception:
        return None
    alpha = rgba.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        return {"hole": 0.0, "big_hole": 0.0, "fill": 0.0, "frags": 0,
                "empty": True, "size": rgba.size}
    w, h = rgba.size
    x0, y0, x1, y1 = bbox
    bw, bh = x1 - x0, y1 - y0
    area = max(1, bw * bh)
    opaque = np.asarray(alpha, dtype=np.uint8)[y0:y1, x0:x1] >= OPAQUE_AT
    fill = float(opaque.mean())
    s = np.ones((3, 3), dtype=int)  # 8-connectivity both times
    lab_o, n_o = ndimage.label(opaque, structure=s)
    frags = 0
    if n_o:
        sizes = np.bincount(lab_o.ravel())[1:]
        frags = int((sizes >= MIN_FRAG_SHARE * area).sum())
    lab_t, n_t = ndimage.label(~opaque, structure=s)
    hole_px = 0
    big_px = 0
    if n_t:
        edge_labels = set(np.unique(np.concatenate([
            lab_t[0, :], lab_t[-1, :], lab_t[:, 0], lab_t[:, -1]]))) - {0}
        for lbl in range(1, n_t + 1):
            if lbl not in edge_labels:
                size = int((lab_t == lbl).sum())
                hole_px += size
                if size >= BIG_HOLE_MIN * area:
                    big_px += size
    return {"hole": hole_px / area, "big_hole": big_px / area,
            "fill": fill, "frags": frags,
            "empty": False, "size": (w, h)}


def load_category_map() -> dict[tuple[str, str], str]:
    """(vendor, sku) -> category from the catalog offers.

    Lets the flag rule be strict for solid products (CPUs, DIMMs, SSDs,
    boards) and lenient for see-through-prone ones (mesh cases, fans).
    Missing catalog (or an unmapped SKU) means lenient — never quarantine
    on a guess.
    """
    mapping: dict[tuple[str, str], str] = {}
    try:
        catalog = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return mapping
    for product in catalog.get("products", []):
        for offer in product.get("offers", []) or []:
            sku = str(offer.get("vendor_sku") or "")
            if not sku:
                continue
            vendor = str(offer.get("vendor_id") or "")
            mapping[(vendor, sku)] = product.get("category", "")
            mapping[(vendor.lower(), sku)] = product.get("category", "")
    return mapping


def render_category(webp: Path, mapping: dict[tuple[str, str], str]) -> str:
    rel = webp.relative_to(IMAGES_DIR).parts
    vendor = rel[0] if rel else ""
    stem = webp.stem
    keys = [(vendor, stem)]
    if vendor == "onepc":
        keys.append(("1pc", stem))
    elif vendor == "1pc":
        keys.append(("onepc", stem))
    for key in keys:
        if key in mapping:
            return mapping[key]
    # Subdirectory covers (ivory per-SKU folders): offers carry the full
    # subpath as the SKU (e.g. ivory "SNV3S/1000G"), so join folder + stem.
    if len(rel) > 2:
        subsku = "/".join(rel[1:-1] + (stem,))
        if (vendor, subsku) in mapping:
            return mapping[(vendor, subsku)]
    for (_vendor, sku), category in mapping.items():
        if sku == stem:
            return category
    return ""


def is_chewed(m: dict, category: str = "") -> bool:
    if m.get("empty"):
        return True
    if m["frags"] >= CARNAGE_FRAGS:
        return True
    limit = STRICT_BIG_HOLE if category in STRICT_CATS else LENIENT_BIG_HOLE
    return m["big_hole"] > limit


def iter_renders(vendors: list[str] | None = None):
    if not IMAGES_DIR.is_dir():
        return
    for vendor_dir in sorted(p for p in IMAGES_DIR.iterdir() if p.is_dir()):
        if vendors and vendor_dir.name not in vendors:
            continue
        for path in sorted(vendor_dir.rglob("*.webp")):
            if THUMB_SUBDIR in path.relative_to(vendor_dir).parts:
                continue
            yield path


def load_keep() -> set[str]:
    keep: set[str] = set()
    try:
        if KEEP_JPG_FILE.is_file():
            for line in KEEP_JPG_FILE.read_text(encoding="utf-8").splitlines():
                entry = line.strip()
                if not entry or entry.startswith("#"):
                    continue
                stem = entry[:-4] if entry.lower().endswith(".jpg") else entry
                keep.add(stem)
                keep.add(stem.rsplit("/", 1)[-1])
    except OSError:
        pass
    return keep


def main(argv: list[str] | None = None) -> int:
    if not _HAVE_SCI:
        print("[detect-chewed] needs numpy+scipy "
              "(pip install -r requirements-images.txt pulls scipy)")
        return 1
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vendor", action="append", dest="vendors", default=None)
    ap.add_argument("--report", default=None, help="write flagged paths here")
    ap.add_argument("--quarantine", action="store_true",
                    help="delete flagged render+thumb and pin keep_jpg.txt")
    ap.add_argument("--quarantine-list", default=None, metavar="FILE",
                    help="quarantine exactly the render paths listed in FILE "
                    "(one per line, e.g. user-reported bad covers) instead "
                    "of the auto-detected set")
    ap.add_argument("--filter-list", default=None,
                    help="drop flagged paths from a --list-out file (CI)")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)

    flagged: list[tuple[Path, dict]] = []
    seen = 0
    catmap = load_category_map()
    for webp in iter_renders(args.vendors):
        seen += 1
        m = analyze(webp)
        if m is None:
            continue
        if is_chewed(m, render_category(webp, catmap)):
            flagged.append((webp, m))
        if args.limit and seen >= args.limit:
            break
    print(f"[detect-chewed] {len(flagged)} chewed of {seen} renders "
          f"(strict big_hole>{STRICT_BIG_HOLE} for {sorted(STRICT_CATS)}, "
          f"lenient big_hole>{LENIENT_BIG_HOLE}/frags>={CARNAGE_FRAGS} else)")
    for webp, m in sorted(flagged, key=lambda r: -r[1]["big_hole"])[:30]:
        print(f"  big_hole={m['big_hole']:.3f} hole={m['hole']:.3f} "
              f"fill={m['fill']:.3f} frags={m['frags']} {webp.as_posix()}")

    if args.report:
        out = Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("".join(f"{w.as_posix()}\n" for w, _ in flagged),
                       encoding="utf-8")
        print(f"[detect-chewed] wrote {len(flagged)} paths to {out}")

    if args.filter_list:
        lst = Path(args.filter_list)
        if lst.is_file():
            bad = {w.as_posix().replace("/", "\\")
                   for w, _ in flagged} | {w.as_posix() for w, _ in flagged}
            lines = [ln for ln in lst.read_text(encoding="utf-8").splitlines()
                     if ln.strip() and ln.strip() not in bad]
            removed = len(lst.read_text(encoding='utf-8').splitlines()) - len(lines)
            lst.write_text(("\n".join(lines) + "\n") if lines else "",
                           encoding="utf-8")
            print(f"[detect-chewed] dropped {removed} chewed paths "
                  f"from {lst}")

    targets: list[tuple[Path, dict]] = flagged
    if args.quarantine_list:
        qfile = Path(args.quarantine_list)
        targets = []
        if qfile.is_file():
            for line in qfile.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # review-list lines may carry a "[category] " prefix
                if line.startswith("[") and "] " in line:
                    line = line.split("] ", 1)[1]
                p = Path(line)
                if not p.is_absolute():
                    p = Path.cwd() / p
                m = analyze(p)
                targets.append((p, m or {"hole": 0.0, "big_hole": 0.0,
                                         "fill": 0.0, "frags": 0,
                                         "empty": False, "size": (0, 0)}))
        print(f"[detect-chewed] quarantining {len(targets)} listed renders")

    if (args.quarantine or args.quarantine_list) and targets:
        keep_lines = []
        try:
            existing = KEEP_JPG_FILE.read_text(encoding="utf-8").splitlines() \
                if KEEP_JPG_FILE.is_file() else []
        except OSError:
            existing = []
        have = {ln.strip() for ln in existing}
        for webp, m in targets:
            try:
                webp.unlink(missing_ok=True)
                # Thumb lives beside the cover for top-level renders and
                # under <sku>/thumbs/ for per-SKU subdirectory covers
                # (same layout scraper/process_images.self_thumb_path uses).
                thumb = webp.parent / THUMB_SUBDIR / f"{webp.stem}.webp"
                thumb.unlink(missing_ok=True)
            except OSError as exc:
                print(f"  [skip] could not delete {webp}: {exc}")
                continue
            try:
                rel = webp.relative_to(IMAGES_DIR)
            except ValueError:
                rel = None
            if rel is not None and len(rel.parts) > 2:
                entry = f"{rel.parts[0]}/{rel.parts[1]}/{webp.stem}"
            else:
                vendor = webp.parent.name
                entry = f"{vendor}/{webp.stem}"
            if entry not in have:
                keep_lines.append(entry)
                have.add(entry)
        if keep_lines:
            with KEEP_JPG_FILE.open("a", encoding="utf-8") as f:
                f.write("\n# 2026-09-27: chewed-product quarantine "
                        "(detect_chewed: interior bites/fragments).\n")
                for entry in keep_lines:
                    f.write(f"{entry}\n")
            print(f"[detect-chewed] quarantined {len(targets)} renders, "
                  f"pinned {len(keep_lines)} keep_jpg entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
