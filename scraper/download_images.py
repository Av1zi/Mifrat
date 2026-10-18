"""
Downloads cover images for products scraped by detail_pages.py spiders.

Run AFTER a detail spider finishes, pointed at that vendor's output
jsonl. Deliberately a plain script rather than Scrapy's ImagesPipeline
— at ~5 new items/day this is simpler to reason about and keeps the
resize/compress step in one place shared across all 4 vendors.

Usage:
    python -m scraper.download_images data/raw/detail/tms.jsonl tms
    python -m scraper.download_images --from-catalog [--limit 200]
    python -m scraper.download_images --prune [--apply]      # dry run default
    python -m scraper.download_images --refetch-alpha [--dry-run] [--vendor v]
    python -m scraper.download_images --convert-local        # jpg -> webp

Saves to data/images/<vendor>/<vendor_sku>.webp: long edge at most 640px,
WebP quality 76 (~12-15KB). Sources with an alpha channel (Ivory/1PC webp,
Yahav/TMS png) are composited onto WHITE — never `.convert("RGB")`, which
discards the alpha and leaves whatever garbage RGB sat under the
transparent pixels (black backdrops, stray patches; Oct 2026 audit).

List-page thumbnails (128px) are NOT stored: site/scripts/copy-data.mjs
derives them from the covers at build time.

The archive only holds what the site can show: the catalog-selected cover
of every product plus its runner-up (see keep_set / --prune).
"""
import json
import sys
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image

try:
    from scraper.image_urls import (
        best_of,
        candidate_urls,
        is_probably_not_a_photo,
        url_shape_score,
    )
except ImportError:
    from image_urls import (  # type: ignore[no-redef]
        best_of,
        candidate_urls,
        is_probably_not_a_photo,
        url_shape_score,
    )

# Oct 2026: JPEG q82 / 800px -> WebP q76 / 640px. A q75 WebP re-encode is
# ~47% smaller at equal size; the 640 cap takes TMS's / Yahav's 800px files
# down a further ~25%. The PDP shows covers at <= 480 CSS px.
MAX_DIMENSION = 640
WEBP_QUALITY = 76
WEBP_METHOD = 6
COVER_EXT = ".webp"
LEGACY_EXT = ".jpg"
# Over-size budget (median cover is ~18KB, p99 ~50KB). encode_cover steps
# the quality down for the rare busy photo that would exceed it, and
# scripts/check_image_files.py enforces it.
COVER_MAX_BYTES = 100_000
REQUEST_TIMEOUT = 15

# Source URL extensions that can carry an alpha channel. JPEG never does,
# so a JPEG-sourced cover was never damaged and is not refetched.
ALPHA_CAPABLE_EXTS = (".webp", ".png", ".gif")

# Ledger for the --upgrade pass: which URL each cover was last fetched from.
# Its job is to make an upgrade a ONE-TIME event per file — Ivory's originals
# really are 500px, so without this every run would re-download all 756 of
# them for no gain (see _upgrade_low_res).
UPGRADE_LEDGER = Path("data/images/upgrade_ledger.json")

# A URL must look at least this much like a vendor original before an
# under-600px cover is refetched from it. 7.0 is cleared by TMS's
# /image/catalog/products/... originals (13) and Ivory's /files/catalog/org/
# (7.5), and is NOT cleared by 1PC's ~500px bucket (3.5) — where the
# "original" is 496px and re-downloading would be a downgrade.
ORIGINAL_SHAPE_FLOOR = 7.0


# ---------------------------------------------------------------------------
# Per-host User-Agent overrides (YahavPC, 2026-10-14)
#
# Every vendor in this pipeline is crawled by Scrapy with a browser UA
# (settings.py USER_AGENT) — that is the project-wide default and the reason
# the listing and detail spiders talk to these sites at all. This downloader
# is the one place that identifies itself instead as MifratBot, which is the
# right default for a plain CDN fetch.
#
# YahavPC's nginx denies its own photos to that name. Measured on
# /img/p/11270/g1.png: "Mozilla/5.0 (compatible; MifratBot/1.0)" -> 403,
# "curl/8.0.1" -> 403, no UA at all -> 200, Chrome 126 -> 200, and adding a
# Referer from the product page does not change any of it. The same 403 hits
# the product HTML and /api/BuildInit, which the spiders fetch fine because
# they send a browser UA.
#
# That is a static UA denylist matching on "bot"/"curl", not a challenge: the
# identical file is served without negotiation to anything else, and one of
# those UAs is already what this project uses for the vendor's HTML and API.
# So the override aligns the photo fetch with the request that already works,
# scoped to this host. It is deliberately NOT a retry loop, a proxy, a cookie
# jar or a challenge solver — the KSP/Plonter "WAF answered = stop signal"
# rule is untouched, and a real challenge here would still end the scrape.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
DEFAULT_UA = "Mozilla/5.0 (compatible; MifratBot/1.0)"
UA_OVERRIDES = {"yahavpc.co.il": BROWSER_UA}


def _user_agent_for(url: str) -> str:
    """MifratBot, unless this host is known to deny that name."""
    try:
        host = (urlparse(str(url)).hostname or "").lower()
    except Exception:
        return DEFAULT_UA
    for domain, ua in UA_OVERRIDES.items():
        if host == domain or host.endswith("." + domain):
            return ua
    return DEFAULT_UA


def _has_basename(url: str) -> bool:
    """Same guard as the spiders' _og_image and the normalizer's
    _has_image_basename: a bare ".../full/" directory URL is not an image
    (Plonter emits these for imageless products). Keep the three in sync."""
    try:
        if not url:
            return False
        return bool(urlparse(str(url)).path.rsplit("/", 1)[-1])
    except Exception:
        return False


def _has_alpha(img: Image.Image) -> bool:
    """True when the decoded image carries transparency (RGBA/LA/PA, or a
    palette/greyscale/RGB image with a tRNS transparency entry)."""
    return img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info


def flatten_on_white(img: Image.Image) -> Image.Image:
    """RGB copy of `img`, transparency composited onto white (#fff).

    Opaque images are only converted to RGB (unchanged pixels). For images
    with alpha, the alpha channel is used as the paste mask, so the RGB values
    stored under fully transparent pixels — often black or leftover junk —
    never reach the output. This is the Oct 2026 fix for the Ivory/Yahav/1PC
    black-background covers; never call `.convert("RGB")` on a decoded vendor
    image directly.
    """
    if _has_alpha(img):
        rgba = img.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, (255, 255, 255))
        canvas.paste(rgba, mask=rgba.getchannel("A"))
        return canvas
    return img.convert("RGB")


def encode_cover(img: Image.Image, dest_path: Path) -> None:
    """Flatten on white, shrink to MAX_DIMENSION, write the WebP cover."""
    flat = flatten_on_white(img)
    flat.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    for quality in (WEBP_QUALITY, 68, 60, 52):
        buf = BytesIO()
        flat.save(buf, "WEBP", quality=quality, method=WEBP_METHOD)
        if buf.tell() <= COVER_MAX_BYTES:
            break
    dest_path.write_bytes(buf.getvalue())


def _legacy_sibling(dest_path: Path) -> Path:
    """The pre-WebP `.jpg` twin of a cover path. Built by name, not with
    with_suffix(): SKUs such as "ABC.1" would lose their ".1"."""
    return dest_path.with_name(dest_path.name[: -len(COVER_EXT)] + LEGACY_EXT)


def download_and_save(image_url: str, dest_path: Path) -> bool:
    """Returns True on success. Never raises — a failed image download
    should not block the rest of the batch; log and move on.

    Sets LAST_HTTP_STATUS (None on non-HTTP failures) so batch loops can
    implement block detection (see _backfill_from_catalog).
    """
    global LAST_HTTP_STATUS, LAST_HAD_ALPHA
    LAST_HTTP_STATUS = None
    LAST_HAD_ALPHA = False
    try:
        resp = requests.get(image_url, timeout=REQUEST_TIMEOUT, headers={
            "User-Agent": _user_agent_for(image_url)
        })
        resp.raise_for_status()
        with Image.open(BytesIO(resp.content)) as img:
            LAST_HAD_ALPHA = _has_alpha(img)
            encode_cover(img, dest_path)
        legacy = _legacy_sibling(dest_path)
        if legacy.is_file():
            legacy.unlink()  # superseded by the WebP cover
        return True
    except Exception as exc:
        try:
            LAST_HTTP_STATUS = exc.response.status_code  # type: ignore[attr-defined]
        except Exception:
            pass
        print(f"  FAILED {image_url} -> {dest_path}: {exc}")
        return False


# HTTP status of the most recent download_and_save call (None when the
# failure wasn't HTTP, or the last call succeeded).
LAST_HTTP_STATUS: int | None = None
# True when the most recent successful download carried an alpha channel.
LAST_HAD_ALPHA: bool = False


def process_jsonl(jsonl_path: str, vendor: str) -> None:
    input_path = Path(jsonl_path)
    if not input_path.exists():
        print(f"No such file: {input_path}")
        sys.exit(1)

    succeeded, failed, skipped, not_wanted = [], [], [], []
    plan = load_image_plan()
    with input_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            sku = item.get("vendor_sku")
            image_url = item.get("image_url")
            if not sku:
                failed.append("<unknown sku>")
                continue
            if not image_url or not _has_basename(image_url):
                # No photo on the vendor side (Plonter emits a bare
                # directory URL for these). Quiet skip — NOT a failure:
                # specs are still marked done and the listing thumbnail
                # covers the product photo.
                skipped.append(sku)
                continue

            dest = _dest_for(vendor, sku)
            if dest.exists():
                # Already downloaded (e.g. a re-run after a partial failure).
                succeeded.append(sku)
                continue
            key = (vendor, dest_stem(sku))
            if plan is not None and key not in plan.wanted:
                # Not the cover the catalog wants: pruned on purpose
                # (--prune), delisted, or a detail row whose SKU no offer
                # carries any more (1PC's pre-Oct-13 ids, Yahav's numeric
                # ids). The detail jsonl is cumulative, so without this gate
                # every pruned or orphaned file would be re-downloaded on the
                # next daily run. A brand-new product becomes wanted once the
                # normalizer has seen it (next day's run).
                not_wanted.append(sku)
                continue

            if download_candidates(_row_candidate_urls(item), dest):
                succeeded.append(sku)
            else:
                failed.append(sku)

    print(f"\n{vendor}: {len(succeeded)} images ok, {len(failed)} failed, "
          f"{len(skipped)} skipped (no vendor photo), "
          f"{len(not_wanted)} not the catalog's wanted cover (skipped)")
    if failed:
        print(f"Failed SKUs: {failed}")
        print("No image file was saved for these — they are retried")
        print("automatically on the next run (files already on disk are")
        print("skipped, so only the missing ones are re-attempted).")


def _vendor_folder(vendor_id: str) -> str:
    """Same normalization as site_data._image_vendor_key: 1pc -> onepc."""
    return "onepc" if vendor_id in ("1pc", "onepc") else (vendor_id or "")


def _long_edge(path: Path) -> int | None:
    """Long edge of an on-disk cover, or None when unreadable.

    Cheap: Pillow's lazy open reads the header only, so walking a few
    thousand files costs well under a second.
    """
    try:
        with Image.open(path) as img:
            width, height = img.size
            return max(width, height)
    except Exception:
        return None


def _row_candidate_urls(item: dict) -> list[str]:
    """Best-first candidate URLs for one detail row.

    Prefers the spider's `image_urls` (og:image + gallery, Sep 2026) and falls
    back to the single `image_url` older rows carry. Every URL expands through
    image_urls.candidate_urls(), so a cached 1000x1000 render brings its
    unsuffixed original along and the original is what gets fetched.
    """
    urls: list[str] = []
    for raw in [*(item.get("image_urls") or []), item.get("image_url")]:
        if not raw or not _has_basename(str(raw)):
            continue
        expanded = candidate_urls(str(raw))
        if not expanded:
            # candidate_urls() returns nothing for site furniture (logos,
            # flags, banners). Never treat the raw URL as a fallback then —
            # a logo is worse than the initials placeholder.
            if is_probably_not_a_photo(str(raw)):
                continue
            expanded = [str(raw)]
        for url in expanded:
            if url not in urls:
                urls.append(url)
    return sorted(urls, key=url_shape_score, reverse=True)


def download_candidates(urls: list[str], dest_path: Path) -> bool:
    """Download the first candidate URL that works, best-first.

    One photo is reachable at several URLs; the biggest is tried first, and a
    URL that 403s or 404s must not cost the product its photo, so the rest
    follow in order. Returns True as soon as one lands on disk.
    """
    tried = 0
    for url in urls:
        tried += 1
        if download_and_save(url, dest_path):
            if tried > 1:
                print(f"  fell back to {url} for {dest_path.name}")
            return True
    return False


def dest_stem(sku: str) -> str:
    """Filename stem for a vendor SKU (site_data._safe_image_stem)."""
    try:
        from scraper.site_data import _safe_image_stem
    except ImportError:
        from site_data import _safe_image_stem  # type: ignore[no-redef]
    return _safe_image_stem(sku)


def _dest_for(vendor_folder: str, sku: str) -> Path:
    """On-disk destination for a downloaded cover. The filename goes
    through site_data._safe_image_stem (strips invisible Cf/Cc chars that
    would otherwise produce uncommittable/unfetchable files) — both sides
    must agree, so never build this path from the raw SKU directly.
    """
    return Path(f"data/images/{vendor_folder}/{dest_stem(sku)}{COVER_EXT}")


def _backfill_from_catalog(limit: int = 200, vendors: list[str] | None = None,
                         sleep_secs: float = 1.0) -> None:
    """Download cover images for catalog PRODUCTS that currently
    have no local photo (one image per product — the minimal set that
    closes the visible gap). Covers listing-only products (no detail row,
    so no og:image) — exactly the gap that forced the old remote-URL
    fallback.

    A product "has a photo" by the same rule site_data._resolve_image
    uses (an offer whose image file exists on disk); photoless products
    get their product.image_url's offer (else their first usable offer).
    Products whose offers carry no usable image URL at all (~86) can never
    have photos and are skipped — they render as initials thumbs.

    Politeness: sequential, MifratBot UA (see download_and_save), 15s
    timeout, `sleep_secs` pause between downloads, skips files already on
    disk, capped at `limit` new downloads per run. Never raises — image
    gaps must never block the pipeline; missing photos render as initials
    placeholders.

    TMS binding (see AGENTS.md): TMS blocks datacenter IPs and rate-limits
    aggressively, so consecutive 403/429s are a stop signal, not a retry
    cue — abort the run after 2 in a row to protect the daily listing
    scrape, which matters far more than photos.
    """
    try:
        from scraper.site_data import _local_image_path
    except ImportError:
        from site_data import _local_image_path  # type: ignore[no-redef]

    catalog_path = Path("data/catalog.json")
    if not catalog_path.exists():
        print(f"No such file: {catalog_path} — run normalize first")
        sys.exit(1)

    with catalog_path.open(encoding="utf-8") as f:
        catalog = json.load(f)

    def _usable_offer(offer: dict) -> bool:
        sku = str(offer.get("vendor_sku") or "").strip()
        return bool(sku) and bool(offer.get("image_url")) and _has_basename(
            str(offer.get("image_url"))
        )

    def _has_photo(product: dict) -> bool:
        for offer in product.get("offers", []) or []:
            if not _usable_offer(offer):
                continue
            if _local_image_path(
                offer.get("vendor_id"), str(offer.get("vendor_sku") or "")
            ):
                return True
        return False

    # One target per photoless product: prefer the offer behind the
    # product's current image_url (keeps catalog ↔ site choice stable),
    # else the first usable offer.
    pending: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    skipped_no_url = 0
    for product in catalog.get("products", []):
        if _has_photo(product):
            continue
        offers = [o for o in product.get("offers", []) or [] if _usable_offer(o)]
        if not offers:
            skipped_no_url += 1
            continue
        current = product.get("image_url")
        chosen = next(
            (o for o in offers if o.get("image_url") == current), offers[0]
        )
        vendor = str(chosen.get("vendor_id") or "")
        folder = _vendor_folder(vendor)
        if vendors and folder not in vendors and vendor not in vendors:
            continue
        sku = str(chosen.get("vendor_sku") or "").strip()
        dest = _dest_for(folder, sku)
        key = (folder, dest.name)
        if key in seen:
            continue
        seen.add(key)
        if dest.exists():
            continue
        pending.append((folder, sku, str(chosen.get("image_url"))))

    print(f"[backfill] {len(pending)} products need an image "
          f"({skipped_no_url} have no usable vendor photo at all)")
    if not pending:
        return

    import time

    batch = pending[:limit]
    succeeded, failed = 0, 0
    blocked_streak = 0
    for folder, sku, url in batch:
        dest = _dest_for(folder, sku)
        if dest.exists():
            continue
        if download_and_save(url, dest):
            succeeded += 1
            blocked_streak = 0
        else:
            failed += 1
            if LAST_HTTP_STATUS in (403, 429):
                blocked_streak += 1
                if blocked_streak >= 2:
                    print(
                        f"[backfill] STOP: 2 consecutive {LAST_HTTP_STATUS}s — "
                        f"treating as a block signal (photos must never "
                        f"endanger the listing scrape). "
                        f"{len(pending) - succeeded - failed} remaining."
                    )
                    break
            else:
                blocked_streak = 0
        time.sleep(sleep_secs)

    print(
        f"[backfill] downloaded {succeeded}/{len(batch)} "
        f"({len(pending) - succeeded - failed} remaining for future runs)"
    )
    if failed:
        print(f"[backfill] {failed} failed — retried automatically next run")


def _upgrade_low_res(limit: int = 0, vendors: list[str] | None = None,
                     sleep_secs: float = 1.0, dry_run: bool = False,
                     max_edge: int = 0) -> None:
    """Re-download covers that are low-resolution copies of a better URL.

    The audited case (Sep 2026): 657 TMS covers on disk are 228px listing
    tiles while the same product page serves a 1500x1500 original. The catalog
    has stored the original since the merge step — but the FILE on disk came
    from an earlier --from-catalog run, and every later download skipped it
    ("file exists" was treated as "done"). The merge step overwrites the
    listing tile with the detail page's original, so the stored URL alone
    cannot reveal which files are stale; the file's own size can.

    Rule: a cover whose long edge is under UPGRADE_EDGE (600px) is re-fetched
    once from the best URL we can name for it — the stored offer URL, or the
    unsuffixed original derived from it — provided that URL looks like a real
    vendor original (shape >= ORIGINAL_SHAPE_FLOOR, which excludes 1PC's
    ~500px bucket, where the "original" is 496px and the stored _510 render is
    actually the larger file).

    Politeness matches the rest of this module: sequential, MifratBot UA, one
    request per `sleep_secs`, hard stop after 2 consecutive 403/429s — photos
    must never endanger the listing scrape.
    """
    from scraper.image_score import TILE_EDGE, UPGRADE_EDGE

    catalog_path = Path("data/catalog.json")
    if not catalog_path.is_file():
        print(f"No such file: {catalog_path} — run normalize first")
        sys.exit(1)
    with catalog_path.open(encoding="utf-8") as f:
        catalog = json.load(f)

    ledger = _load_upgrade_ledger()
    pending: list[tuple[str, str, str, int]] = []
    seen: set[str] = set()
    # Two SKUs can name the same photo (vendor re-uses a render across SKUs);
    # fetching it twice would be pure waste, so a target URL is queued once.
    seen_targets: set[str] = set()
    already_upgraded = 0
    for product in catalog.get("products", []):
        for offer in product.get("offers", []) or []:
            url = str(offer.get("image_url") or "")
            sku = str(offer.get("vendor_sku") or "").strip()
            if not url or not sku or not _has_basename(url):
                continue
            folder = _vendor_folder(str(offer.get("vendor_id") or ""))
            if vendors and folder not in vendors:
                continue
            dest = _dest_for(folder, sku)
            if not dest.is_file():
                continue  # a missing photo is --from-catalog's job, not ours
            ledger_key = f"{folder}/{dest.name}"
            if ledger_key in seen:
                continue
            seen.add(ledger_key)
            edge = _long_edge(dest)
            if edge is None or edge >= (max_edge or UPGRADE_EDGE):
                continue
            target = best_of(candidate_urls(url)) or url
            if edge >= TILE_EDGE and target == url:
                # In the 300-600px band with nothing better to name: the stored
                # URL is what produced this file (Ivory/Plonter originals), so
                # a re-download would be a no-op. Only tile-territory files
                # (<300px, where the stored URL is usually the detail page's
                # uncompressed original) are refetched from the same URL.
                continue
            if url_shape_score(target) < ORIGINAL_SHAPE_FLOOR:
                # Nothing better than what we already hold (1PC's ~500px
                # bucket): re-downloading would replace a 510px file with a
                # 496px one.
                continue
            if (ledger.get(ledger_key) or {}).get("url") == target:
                already_upgraded += 1
                continue
            if target in seen_targets:
                continue
            seen_targets.add(target)
            pending.append((folder, sku, target, edge))

    print(f"[upgrade] {len(pending)} covers are low-resolution copies of a "
          f"better URL ({already_upgraded} were already refetched once and "
          f"left alone)")
    if dry_run or not pending:
        for folder, sku, url, edge in pending[:40]:
            print(f"  {folder:8s} {sku[:34]:34s} {edge:4d}px -> {url[:88]}")
        if len(pending) > 40:
            print(f"  … {len(pending) - 40} more")
        return

    import time

    batch = pending[:limit] if limit else pending
    upgraded, failed = 0, 0
    blocked_streak = 0
    for folder, sku, url, edge in batch:
        dest = _dest_for(folder, sku)
        ok = download_and_save(url, dest)
        # Recorded whether or not bytes changed: the point is "this file has
        # already been tried against this URL", so a genuinely-500px original
        # (Ivory) is not fetched again tomorrow and the day after.
        ledger[f"{folder}/{dest.name}"] = {"url": url, "edge": _long_edge(dest)}
        if ok:
            upgraded += 1
            blocked_streak = 0
        else:
            failed += 1
            if LAST_HTTP_STATUS in (403, 429):
                blocked_streak += 1
                if blocked_streak >= 2:
                    print(
                        f"[upgrade] STOP: 2 consecutive {LAST_HTTP_STATUS}s — "
                        f"treating as a block signal. {len(batch) - upgraded - failed} "
                        f"remaining for a future run."
                    )
                    _save_upgrade_ledger(ledger)
                    break
            else:
                blocked_streak = 0
        if upgraded and upgraded % 50 == 0:
            _save_upgrade_ledger(ledger)
        time.sleep(sleep_secs)

    _save_upgrade_ledger(ledger)
    print(f"[upgrade] re-downloaded {upgraded}/{len(batch)} at full size "
          f"({len(pending) - upgraded - failed} remaining for future runs)")
    if failed:
        print(f"[upgrade] {failed} failed — retried automatically next run")


def _load_upgrade_ledger() -> dict:
    """{<vendor>/<file>: {"url": last fetched URL, "edge": long edge}}.

    Missing or broken ledger is a warning, never a failure: the worst case is
    that one run re-fetches a few hundred files that are already fine.
    """
    try:
        if UPGRADE_LEDGER.is_file():
            with UPGRADE_LEDGER.open(encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as exc:
        print(f"[upgrade] ignoring {UPGRADE_LEDGER}: {exc}")
    return {}


def _save_upgrade_ledger(ledger: dict) -> None:
    try:
        UPGRADE_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with UPGRADE_LEDGER.open("w", encoding="utf-8") as f:
            json.dump(ledger, f, ensure_ascii=False, indent=0, sort_keys=True)
    except OSError as exc:
        print(f"[upgrade] could not write {UPGRADE_LEDGER}: {exc}")


# ---------------------------------------------------------------------------
# Image plan: which files the site can actually show (Oct 2026 prune)
# ---------------------------------------------------------------------------

class ImagePlan:
    """What the catalog needs from data/images/.

    Keys are (vendor_folder, stem) — the stem is the on-disk path under the
    vendor folder without extension (legacy ivory per-SKU subdirs included).

    known   every (vendor, sku) any product offers a cover candidate for
    wanted  the cover the site WANTS per product: first candidate in
            site_data._ordered_image_candidates, whether or not it is on disk
    keep    files to retain: the cover the site resolves today (the same call
            site_data makes), the wanted cover when on disk, and ONE runner-up
            per product (best-scored other candidate on disk) so the chooser
            or the dark-backdrop fallback can flip without a re-download
    """

    def __init__(self) -> None:
        self.known: set[tuple[str, str]] = set()
        self.wanted: set[tuple[str, str]] = set()
        self.keep: set[tuple[str, str]] = set()
        self.selected: set[tuple[str, str]] = set()
        self.runner_ups: set[tuple[str, str]] = set()
        self.urls: dict[tuple[str, str], str] = {}


def _cover_file(key: tuple[str, str]) -> Path:
    try:
        from scraper.site_data import IMAGES_DIR
    except ImportError:
        from site_data import IMAGES_DIR  # type: ignore[no-redef]
    return IMAGES_DIR / key[0] / f"{key[1]}{COVER_EXT}"


def build_image_plan(catalog: dict) -> ImagePlan:
    try:
        from scraper import site_data
        from scraper.image_score import score_candidate
    except ImportError:
        import site_data  # type: ignore[no-redef]
        from image_score import score_candidate  # type: ignore[no-redef]
    from urllib.parse import unquote

    plan = ImagePlan()
    for product in catalog.get("products", []):
        ordered: list[tuple[tuple[str, str], str, str]] = []
        seen: set[tuple[str, str]] = set()
        for vendor, sku, url in site_data._ordered_image_candidates(product):
            key = (site_data._image_vendor_key(vendor), site_data._safe_image_stem(sku))
            if key in seen:
                continue
            seen.add(key)
            ordered.append((key, vendor, url))
            plan.urls.setdefault(key, url)
        if not ordered:
            continue
        plan.known.update(k for k, _v, _u in ordered)
        plan.wanted.add(ordered[0][0])

        image, _thumb = site_data._resolve_image(product, product.get("offers", []))
        chosen: set[tuple[str, str]] = set()
        if image:
            rel = unquote(image[len("/images/"):])
            folder, _, tail = rel.partition("/")
            chosen.add((folder, tail[: -len(COVER_EXT)]))
        if _cover_file(ordered[0][0]).is_file():
            chosen.add(ordered[0][0])
        plan.selected |= chosen

        best, best_score = None, float("-inf")
        for key, vendor, url in ordered:
            if key in chosen or not _cover_file(key).is_file():
                continue
            score = score_candidate(
                {"url": url, "vendor": vendor, "in_stock": False},
                category=str(product.get("category") or ""),
            )
            if score > best_score:
                best, best_score = key, score
        if best is not None:
            plan.runner_ups.add(best)
        plan.keep |= chosen
    plan.keep |= plan.runner_ups
    site_data._DROPPED_REMOTES.clear()
    return plan


def load_image_plan() -> ImagePlan | None:
    """Plan from data/catalog.json, or None (callers then do not gate) when
    the catalog is absent/unreadable — a missing plan must never stop a
    download."""
    catalog_path = Path("data/catalog.json")
    if not catalog_path.is_file():
        return None
    try:
        with catalog_path.open(encoding="utf-8") as f:
            catalog = json.load(f)
        if len(catalog.get("products", [])) < 500:
            return None  # a truncated catalog would gate everything out
        return build_image_plan(catalog)
    except Exception as exc:
        print(f"[plan] ignoring catalog: {exc}")
        return None


def _iter_image_files(base: Path):
    for vendor_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        for path in sorted(vendor_dir.rglob("*")):
            if path.is_file():
                yield vendor_dir.name, path


def _prune(apply: bool = False) -> None:
    """Delete every file in data/images/ the catalog cannot show.

    Keeps `plan.keep` (selected cover + runner-up per product). Everything
    else goes: orphan covers (all of Plonter's, vendors' unchosen duplicates),
    legacy .jpg files and the committed thumbs/ trees. Dry run by default.
    Deleted covers are re-downloaded on demand (`--from-catalog`), and the
    daily detail job only fetches a SKU when it is the catalog's cover.
    """
    base = Path("data/images")
    if not base.is_dir():
        print(f"No such directory: {base}")
        sys.exit(1)
    plan = load_image_plan()
    if plan is None or not plan.keep:
        print("[prune] no usable catalog/plan — refusing to delete anything")
        sys.exit(1)

    keep_stats: dict[str, list[int]] = {}
    drop_stats: dict[str, list[int]] = {}
    to_delete: list[Path] = []
    kept_files: set[Path] = set()
    for vendor, path in _iter_image_files(base):
        rel = path.relative_to(base / vendor)
        keep = False
        if path.suffix.lower() == COVER_EXT and "thumbs" not in rel.parts:
            stem = rel.as_posix()[: -len(COVER_EXT)]
            keep = (vendor, stem) in plan.keep
        size = path.stat().st_size
        bucket = keep_stats if keep else drop_stats
        row = bucket.setdefault(vendor, [0, 0])
        row[0] += 1
        row[1] += size
        if keep:
            kept_files.add(path)
        else:
            to_delete.append(path)

    missing = [k for k in plan.keep if not _cover_file(k).is_file()]
    print(f"[prune] catalog wants {len(plan.wanted)} covers; plan keeps "
          f"{len(plan.keep)} ({len(plan.runner_ups)} runner-ups)")
    for label, stats in (("keep", keep_stats), ("delete", drop_stats)):
        total_n = sum(v[0] for v in stats.values())
        total_b = sum(v[1] for v in stats.values())
        print(f"  {label:6s} {total_n:6d} files {total_b / 1e6:8.1f} MB   "
              + "  ".join(f"{v}:{n}/{b / 1e6:.0f}MB" for v, (n, b) in sorted(stats.items())))
    if missing:
        print(f"  note: {len(missing)} planned files are not on disk")
    plonter_kept = sorted(k for k in plan.keep if k[0] == "plonter")
    if plonter_kept:
        print(f"  note: {len(plonter_kept)} plonter covers are the ONLY photo of a "
              f"product and are kept: {plonter_kept[:5]}")

    if not apply:
        print("[prune] dry run — nothing deleted (add --apply)")
        return

    for path in to_delete:
        path.unlink()
    for vendor_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        for d in sorted((p for p in vendor_dir.rglob("*") if p.is_dir()),
                        key=lambda q: len(q.parts), reverse=True):
            try:
                d.rmdir()  # only succeeds when empty
            except OSError:
                pass
        try:
            vendor_dir.rmdir()
        except OSError:
            pass
    ledger = _load_upgrade_ledger()
    alive = {f"{p.relative_to(base).as_posix()}" for p in kept_files}
    pruned_ledger = {k: v for k, v in ledger.items() if k in alive}
    if len(pruned_ledger) != len(ledger):
        _save_upgrade_ledger(pruned_ledger)
    print(f"[prune] deleted {len(to_delete)} files; ledger {len(ledger)} -> {len(pruned_ledger)}")


def _convert_one(path_str: str) -> tuple[str, str]:
    path = Path(path_str)
    dest = path.with_name(path.name[: -len(LEGACY_EXT)] + COVER_EXT)
    try:
        if not dest.is_file():
            with Image.open(path) as img:
                encode_cover(img, dest)
        path.unlink()
        return path_str, "ok"
    except Exception as exc:
        return path_str, f"FAILED: {exc}"


def _convert_local(workers: int = 0) -> None:
    """Re-encode legacy .jpg covers (not thumbs/) as 640px WebP, no network."""
    from concurrent.futures import ProcessPoolExecutor
    import os

    base = Path("data/images")
    files = [str(p) for _v, p in _iter_image_files(base)
             if p.suffix.lower() == LEGACY_EXT and "thumbs" not in p.relative_to(base).parts]
    print(f"[convert] {len(files)} legacy .jpg covers")
    done, failed = 0, 0
    with ProcessPoolExecutor(max_workers=workers or max(1, (os.cpu_count() or 2) - 1)) as pool:
        for i, (name, status) in enumerate(pool.map(_convert_one, files, chunksize=32), 1):
            if status == "ok":
                done += 1
            else:
                failed += 1
                print(f"  {name}: {status}")
            if i % 2000 == 0:
                print(f"  ... {i}/{len(files)}")
    ledger = _load_upgrade_ledger()
    migrated = {(k[: -len(LEGACY_EXT)] + COVER_EXT if k.endswith(LEGACY_EXT) else k): v
                for k, v in ledger.items()}
    if migrated != ledger:
        _save_upgrade_ledger(migrated)
    print(f"[convert] {done} converted, {failed} failed; ledger keys migrated")


def _url_may_have_alpha(url: str) -> bool:
    try:
        return urlparse(url).path.lower().endswith(ALPHA_CAPABLE_EXTS)
    except Exception:
        return False


def _refetch_alpha(limit: int = 0, vendors: list[str] | None = None,
                   sleep_secs: float = 1.0, dry_run: bool = False) -> None:
    """Re-download kept covers whose SOURCE format can carry transparency.

    The JPEG/WebP on disk cannot tell us whether its source had an alpha
    channel (the old converter threw it away), so the decision is made from
    the source format instead: Ivory/1PC webp and Yahav/TMS png are
    re-fetched, JPEG sources never were damaged. Only the files the plan
    keeps are fetched (the rest are about to be pruned). The catalog's
    stored URL is the source of truth; a fetch that finds no alpha simply
    rewrites an identical cover at the new size/format.

    Politeness as everywhere in this module: sequential, one request per
    `sleep_secs`, hard stop after 2 consecutive 403/429s. TMS is excluded
    unless named with --vendor tms (home-IP rules in AGENTS.md: 1 run/day,
    >= 3s between requests) — leave its covers noted instead.
    """
    plan = load_image_plan()
    if plan is None:
        print("No usable data/catalog.json — run normalize first")
        sys.exit(1)
    allowed = set(vendors) if vendors else {"ivory", "yahav", "onepc"}
    if "tms" in allowed:
        sleep_secs = max(sleep_secs, 3.0)
    ledger = _load_upgrade_ledger()
    pending: list[tuple[str, str, str]] = []
    skipped_tms = skipped_done = skipped_jpeg = 0
    for key in sorted(plan.keep):
        folder, stem = key
        url = plan.urls.get(key, "")
        if not url or not _cover_file(key).is_file():
            continue
        target = best_of(candidate_urls(url)) or url
        if not _url_may_have_alpha(target):
            skipped_jpeg += 1
            continue
        if folder not in allowed:
            if folder == "tms":
                skipped_tms += 1
            continue
        ledger_key = f"{folder}/{stem}{COVER_EXT}"
        if (ledger.get(ledger_key) or {}).get("alpha_checked") == target:
            skipped_done += 1
            continue
        pending.append((folder, stem, target))
    print(f"[alpha] {len(pending)} kept covers have an alpha-capable source "
          f"({skipped_jpeg} JPEG sources untouched, {skipped_done} already "
          f"checked, {skipped_tms} tms png left for the home-IP run)")
    if dry_run or not pending:
        by_vendor: dict[str, int] = {}
        for folder, _stem, _url in pending:
            by_vendor[folder] = by_vendor.get(folder, 0) + 1
        print("  by vendor:", by_vendor)
        for folder, stem, url in pending[:15]:
            print(f"  {folder:7s} {stem[:30]:30s} {url[:80]}")
        return

    import time

    batch = pending[:limit] if limit else pending
    had_alpha = fetched = failed = 0
    blocked_streak = 0
    for folder, stem, url in batch:
        dest = _cover_file((folder, stem))
        ok = download_and_save(url, dest)
        if ok:
            fetched += 1
            blocked_streak = 0
            had_alpha += 1 if LAST_HAD_ALPHA else 0
            ledger[f"{folder}/{stem}{COVER_EXT}"] = {
                "url": url, "edge": _long_edge(dest), "alpha_checked": url,
            }
        else:
            failed += 1
            if LAST_HTTP_STATUS in (403, 429):
                blocked_streak += 1
                if blocked_streak >= 2:
                    print(f"[alpha] STOP: 2 consecutive {LAST_HTTP_STATUS}s — block "
                          f"signal. {len(batch) - fetched - failed} remaining.")
                    break
            else:
                blocked_streak = 0
        if fetched and fetched % 50 == 0:
            _save_upgrade_ledger(ledger)
        time.sleep(sleep_secs)
    _save_upgrade_ledger(ledger)
    print(f"[alpha] re-fetched {fetched}/{len(batch)} ({had_alpha} really had "
          f"transparency), {failed} failed — failures keep their old cover and "
          f"are retried next run")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Download product cover images")
    parser.add_argument("jsonl_path", nargs="?", help="detail jsonl to process")
    parser.add_argument("vendor", nargs="?", help="vendor folder under data/images/")
    parser.add_argument(
        "--from-catalog",
        action="store_true",
        help="backfill covers from data/catalog.json offers "
        "(covers listing-only products with no detail row)",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="delete every file under data/images/ that is not a "
        "catalog-selected cover or its runner-up (plus legacy .jpg and "
        "thumbs/). DRY RUN unless --apply is given.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="with --prune: actually delete (default is a dry run)",
    )
    parser.add_argument(
        "--convert-local",
        action="store_true",
        help="one-time, no network: re-encode every legacy .jpg cover as a "
        "640px WebP and delete the .jpg",
    )
    parser.add_argument(
        "--refetch-alpha",
        action="store_true",
        help="re-download kept covers whose SOURCE format can carry "
        "transparency (webp/png) so the alpha is composited on white. "
        "Skips tms unless --vendor tms is given. Honors --dry-run/--limit/"
        "--sleep.",
    )
    parser.add_argument(
        "--upgrade",
        action="store_true",
        help="re-download covers that are low-resolution copies of a URL we "
        "can improve (e.g. a 228px TMS listing tile whose product page "
        "serves a 1500px original). Reads data/catalog.json; run normalize "
        "first.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="with --upgrade / --refetch-alpha: print the plan and "
        "download nothing",
    )
    parser.add_argument(
        "--upgrade-max-edge",
        type=int,
        default=0,
        help="with --upgrade: replace covers under this long edge "
        "(default: image_score.UPGRADE_EDGE, 600)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="max downloads per run for --from-catalog / --upgrade "
        "(politeness cap, default 200)",
    )
    parser.add_argument(
        "--vendor",
        dest="only_vendor",
        action="append",
        default=None,
        help="only backfill this vendor folder (e.g. --vendor tms); "
        "repeatable. Default: all vendors.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=1.0,
        help="seconds to pause between downloads (default 1.0)",
    )
    args = parser.parse_args()

    if args.upgrade:
        _upgrade_low_res(limit=args.limit, vendors=args.only_vendor,
                         sleep_secs=args.sleep, dry_run=args.dry_run,
                         max_edge=args.upgrade_max_edge)
    elif args.prune:
        _prune(apply=args.apply)
    elif args.convert_local:
        _convert_local()
    elif args.refetch_alpha:
        _refetch_alpha(limit=args.limit, vendors=args.only_vendor,
                       sleep_secs=args.sleep, dry_run=args.dry_run)
    elif args.from_catalog:
        _backfill_from_catalog(limit=args.limit, vendors=args.only_vendor,
                               sleep_secs=args.sleep)
    elif args.jsonl_path and args.vendor:
        process_jsonl(args.jsonl_path, args.vendor)
    else:
        parser.print_usage()
        print("Usage: python -m scraper.download_images <jsonl_path> <vendor>")
        print("   or: python -m scraper.download_images --from-catalog [--limit 200]")
        print("   or: python -m scraper.download_images --prune [--apply]")
        print("   or: python -m scraper.download_images --refetch-alpha [--dry-run] [--vendor ivory]")
        print("   or: python -m scraper.download_images --upgrade [--dry-run] [--limit N]")
        sys.exit(1)
