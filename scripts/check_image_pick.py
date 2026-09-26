"""Offline regression for the photo pipeline (Sep 2026).

Covers, with no network and no dependency on the real image corpus:

- scraped URL vocabulary: which shapes are originals, which are resized
  derivatives, which are site furniture (scraper/image_urls.py)
- candidate capture from real detail-page markup (the gallery selectors in
  scraper/spiders/detail_pages.py, pinned against the markup verified live)
- scoring + best-photo picking + incumbent stability (scraper/image_score.py)
- the refetch rule that fixes the audited 228px-tile covers
  (scraper/download_images.py)
- the transparent-render pass: matte metrics, alpha crop, keep_jpg escape
  hatch, mtime idempotency (scraper/process_images.py)
- site-side resolution: transparent .webp preferred over .jpg, candidate
  fallback, no image ever blanked (scraper/site_data.py)
- chewed-product detection: bites out of the product, box-art shredding,
  and the category-aware flag rule (scraper/detect_chewed.py)

Run: python scripts/check_image_pick.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from scraper import image_score, image_urls  # noqa: E402
from scraper.download_images import _row_candidate_urls, _upgrade_low_res  # noqa: E402
from scraper.process_images import (  # noqa: E402
    _crop_to_product,
    _needs_render,
    _removed_share,
    load_keep_jpg,
)

TMS_ORIGINAL = "https://tms.co.il/image/catalog/products/ST28000NM003K/D9kz8CXkiv.jpg"
TMS_1000 = "https://tms.co.il/image/cache/catalog/products/ST28000NM003K/D9kz8CXkiv-1000x1000.jpg"
TMS_TILE = "https://tms.co.il/image/cache/catalog/products/ST28000NM003K/D9kz8CXkiv-228x228.jpg"
ONEPC_510 = "https://1pc.co.il/images/thumbs/0063041_antec-p20ce-case_510.jpeg"
ONEPC_FULL = "https://1pc.co.il/images/thumbs/0063041_antec-p20ce-case.jpeg"
PLONTER_FULL = "https://www.plonter.co.il/graphics/product_images/full/MG10SCA20TE.jpg"
IVORY_ORG = "https://www.ivory.co.il/files/catalog/org/1770291675f75Lv.webp"
LOGO = "https://1pc.co.il/images/thumbs/0076482_logo.e8a255e0.png"
MENU = "https://tms.co.il/catalog/view/theme/default/image/site/menu-sale.jpg"
FLAG = "https://1pc.co.il/images/flags/il.png"


class Checks:
    def __init__(self) -> None:
        self.count = 0
        self.failures: list[str] = []

    def ok(self, condition: bool, label: str, detail: str = "") -> None:
        self.count += 1
        if not condition:
            self.failures.append(f"{label}{(' — ' + detail) if detail else ''}")

    def eq(self, actual, expected, label: str) -> None:
        self.ok(actual == expected, label, f"got {actual!r}, want {expected!r}")

    def lt(self, a, b, label: str) -> None:
        self.ok(a < b, label, f"{a!r} is not < {b!r}")

    def gt(self, a, b, label: str) -> None:
        self.ok(a > b, label, f"{a!r} is not > {b!r}")


def check_url_vocabulary(c: Checks) -> None:
    """Derivation: the same photo's original must be nameable from a render."""
    c.eq(image_urls.strip_size_suffix(TMS_1000), TMS_ORIGINAL,
         "TMS cached render derives its unsuffixed original")
    c.eq(image_urls.strip_size_suffix(TMS_TILE), TMS_ORIGINAL,
         "TMS 228px tile derives the same original")
    c.eq(image_urls.strip_size_suffix(ONEPC_510), ONEPC_FULL,
         "1PC _510 render derives the unsuffixed file the page links")
    c.eq(image_urls.strip_size_suffix(TMS_ORIGINAL), None,
         "an original URL has nothing to strip")
    c.eq(image_urls.strip_size_suffix(IVORY_ORG), None,
         "Ivory's org URLs are already originals")
    c.eq(image_urls.strip_size_suffix(""), None, "empty URL derives nothing")

    c.eq(image_urls.candidate_urls(TMS_TILE), [TMS_ORIGINAL, TMS_TILE],
         "candidates put the original first and keep the tile as fallback")
    c.eq(image_urls.candidate_urls(LOGO), [], "furniture yields no candidates")
    c.eq(image_urls.candidate_urls(MENU), [], "menu art yields no candidates")

    c.ok(image_urls.is_probably_not_a_photo(LOGO), "logo rejected as furniture")
    c.ok(image_urls.is_probably_not_a_photo(FLAG), "flag icon rejected")
    c.ok(image_urls.is_probably_not_a_photo(MENU), "menu banner rejected")
    c.ok(image_urls.is_probably_not_a_photo("https://x/img.svg"), "svg rejected")
    c.ok(not image_urls.is_probably_not_a_photo(TMS_ORIGINAL),
         "a real TMS original is not furniture")
    c.ok(not image_urls.is_probably_not_a_photo(IVORY_ORG),
         "a real Ivory original is not furniture")

    c.eq(image_urls.photo_key(TMS_TILE), image_urls.photo_key(TMS_ORIGINAL),
         "tile and original are the same photo")
    c.eq(image_urls.photo_key(ONEPC_510), image_urls.photo_key(ONEPC_FULL),
         "1PC render and original are the same photo")
    c.ok(image_urls.photo_key(TMS_ORIGINAL) != image_urls.photo_key(PLONTER_FULL),
         "different vendors' photos are different photos")

    c.gt(image_urls.url_shape_score(TMS_ORIGINAL), image_urls.url_shape_score(TMS_1000),
         "original outranks its own cached render")
    c.gt(image_urls.url_shape_score(TMS_1000), image_urls.url_shape_score(TMS_TILE),
         "cached render outranks the 228px tile")
    c.lt(image_urls.url_shape_score(LOGO), 0, "furniture scores below zero")
    c.eq(image_urls.best_of([TMS_TILE, TMS_ORIGINAL]), TMS_ORIGINAL,
         "best_of picks the original regardless of input order")
    c.eq(image_urls.best_of([]), None, "best_of of nothing is None")


def check_gallery_capture(c: Checks) -> None:
    """The spider's candidate capture, against the markup verified live."""
    from scrapy.http import HtmlResponse, Request
    from scraper.spiders.detail_pages import MAX_GALLERY_CANDIDATES, _gallery_images

    def response(html: str, url: str) -> HtmlResponse:
        return HtmlResponse(url=url, body=html.encode("utf-8"), encoding="utf-8",
                            request=Request(url))

    tms_html = f"""
    <html><head>
      <meta property="og:image" content="{TMS_ORIGINAL}" />
      <meta name="twitter:image" content="{TMS_ORIGINAL}">
    </head><body>
      <a href="{TMS_ORIGINAL}"><img id="product-main-image" src="{TMS_1000}"></a>
      <img src="https://tms.co.il/image/cache/catalog/products/ST28000NM003K/dPAVaGecpf-222x222.jpg">
      <img src="/catalog/view/theme/default/image/site/menu-sale.jpg">
      <img src="/catalog/view/theme/default/image/facebook.png">
    </body></html>
    """
    tms = _gallery_images(response(tms_html, "https://tms.co.il/p/1"))
    c.eq(tms[0], TMS_ORIGINAL, "TMS og:image leads the candidate list")
    c.ok(TMS_TILE not in tms,
         "TMS 228px tile is never a candidate when the original is known")
    c.ok(all("menu-sale" not in u and "facebook" not in u for u in tms),
         "TMS site furniture never reaches the candidate list")
    c.ok(len(tms) <= MAX_GALLERY_CANDIDATES, "TMS candidates are capped")

    onepc_html = f"""
    <html><head><meta property="og:image" content="{ONEPC_510}"></head><body>
      <a data-full-image-url="{ONEPC_FULL}" href="{ONEPC_FULL}">x</a>
      <img src="https://1pc.co.il/images/thumbs/0076482_logo.e8a255e0.png">
    </body></html>
    """
    onepc = _gallery_images(response(onepc_html, "https://1pc.co.il/p/1"))
    c.eq(onepc[0], ONEPC_FULL, "1PC prefers the unsuffixed full-size anchor")
    c.ok(LOGO not in onepc, "1PC logo is not a candidate")

    ivory_html = f"""
    <html><head><meta property="og:image" content="{IVORY_ORG}"></head><body>
      <img class="product__mainImg" data-original-picture="files/catalog/org/1770291675f75Lv.webp"
           src="files/catalog/org/1770291675f75Lv.webp">
      <img src="https://www.ivory.co.il/files/misc/1679917728s28Sg.svg">
    </body></html>
    """
    ivory = _gallery_images(response(ivory_html, "https://www.ivory.co.il/catalog.php?id=1"))
    c.eq(ivory, [IVORY_ORG], "Ivory's repeated main image yields one candidate")


def check_scoring(c: Checks) -> None:
    table = {"case": ["tms", "plonter", "onepc", "ivory"]}

    tms_detail = image_score.score_candidate(
        {"url": TMS_ORIGINAL, "kind": "detail", "vendor": "tms", "in_stock": True},
        category="case", table=table)
    tms_tile = image_score.score_candidate(
        {"url": TMS_TILE, "kind": "listing", "vendor": "tms", "in_stock": True},
        category="case", table=table)
    onepc_detail = image_score.score_candidate(
        {"url": ONEPC_FULL, "kind": "detail", "vendor": "1pc", "in_stock": True},
        category="case", table=table)
    ivory_detail = image_score.score_candidate(
        {"url": IVORY_ORG, "kind": "detail", "vendor": "ivory", "in_stock": True},
        category="case", table=table)
    furniture = image_score.score_candidate(
        {"url": LOGO, "kind": "detail", "vendor": "1pc", "in_stock": True},
        category="case", table=table)
    local_tile = image_score.score_candidate(
        {"url": TMS_ORIGINAL, "kind": "detail", "vendor": "tms", "in_stock": True,
         "local_edge": 228, "local_bytes": 9000},
        category="case", table=table)

    c.gt(tms_detail, tms_tile, "TMS original beats the listing tile")
    c.gt(tms_detail, onepc_detail, "category priority puts tms above 1pc")
    c.gt(onepc_detail, ivory_detail, "category priority puts 1pc above ivory")
    c.lt(furniture, 0, "furniture is unpickable")
    c.lt(local_tile, tms_detail,
         "a 228px local file is penalised against a full-size one")
    c.eq(image_score.priority_table().get("case"), ["tms", "plonter", "onepc", "ivory"],
         "committed priority table is loaded for 'case'")

    # Cross-vendor, same kind: the committed table decides (that is its job),
    # even when the lower-priority vendor's URL shape is nicer.
    picked = image_score.pick_image(
        [{"url": TMS_TILE, "vendor": "tms", "in_stock": True},
         {"url": ONEPC_FULL, "vendor": "1pc", "in_stock": True}],
        category="case", table=table)
    c.eq(picked["url"], TMS_TILE,
         "at equal kind the higher-priority vendor wins despite a worse URL shape")

    # Cross-vendor, different kind: a detail-page photo beats a foreign
    # vendor's listing tile (listing tiles are 74-290px thumbnails).
    picked = image_score.pick_image(
        [{"url": TMS_TILE, "kind": "listing", "vendor": "tms", "in_stock": True},
         {"url": ONEPC_FULL, "kind": "detail", "vendor": "1pc", "in_stock": True}],
        category="case", table=table)
    c.eq(picked["url"], ONEPC_FULL,
         "a detail photo beats another vendor's listing tile")

    # One priority rank apart is a margin smaller than HYSTERESIS: the site
    # keeps showing what it already shows instead of reshuffling covers.
    incumbent = image_score.pick_image(
        [{"url": ONEPC_FULL, "kind": "detail", "vendor": "1pc", "in_stock": True},
         {"url": IVORY_ORG, "kind": "detail", "vendor": "ivory", "in_stock": True}],
        category="case", table=table, incumbent_url=IVORY_ORG)
    c.eq(incumbent["url"], IVORY_ORG,
         "a marginally-better challenger does not displace the incumbent")

    replaced = image_score.pick_image(
        [{"url": TMS_ORIGINAL, "kind": "detail", "vendor": "tms", "in_stock": True},
         {"url": TMS_TILE, "kind": "listing", "vendor": "tms", "in_stock": True}],
        category="case", table=table, incumbent_url=TMS_TILE)
    c.eq(replaced["url"], TMS_ORIGINAL,
         "a clearly better shot does displace the incumbent")
    c.eq(image_score.pick_image([], category="case"), None,
         "no candidates means no image")


def check_refetch_rules(c: Checks) -> None:
    c.ok(image_score.should_refetch(TMS_ORIGINAL),
         "a missing file is always worth downloading")
    c.ok(image_score.should_refetch(TMS_ORIGINAL, existing_edge=228, existing_bytes=9000),
         "a 228px tile is refetched from the 1500px original")
    c.ok(not image_score.should_refetch(TMS_ORIGINAL, existing_edge=800, existing_bytes=40000),
         "a full-size file is never re-downloaded")
    c.ok(not image_score.should_refetch(LOGO, existing_edge=228, existing_bytes=2000),
         "furniture is never downloaded")

    row = {"image_urls": [TMS_1000, ONEPC_510], "image_url": TMS_TILE}
    urls = _row_candidate_urls(row)
    c.eq(urls[0], TMS_ORIGINAL,
         "detail-row candidates lead with the derived original")
    c.ok(ONEPC_FULL in urls, "every candidate URL is expanded to its original")
    c.eq(_row_candidate_urls({"image_url": LOGO}), [],
         "a furniture-only row yields no download target")
    c.eq(_row_candidate_urls({"image_url": ""}), [],
         "a row without an image yields no target")


def check_transparent_render(c: Checks) -> None:
    rng = Image.new("RGB", (200, 200), "white")
    for x in range(60, 140):
        for y in range(60, 140):
            rng.putpixel((x, y), (30, 30, 30))
    matted = rng.convert("RGBA")
    for x in range(200):
        for y in range(200):
            if not (60 <= x < 140 and 60 <= y < 140):
                matted.putpixel((x, y), (0, 0, 0, 0))

    removed = _removed_share(matted)
    c.gt(removed, 0.6, "a cleared background counts as removed")
    c.lt(removed, 1.0, "the product itself stays opaque")

    cropped, did = _crop_to_product(matted)
    c.ok(did, "a padded frame is cropped to the product")
    c.lt(cropped.size[0], 200, "the crop is smaller than the frame")
    c.gt(cropped.size[0], 80, "the crop keeps the product plus padding")

    speck = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    speck.putpixel((100, 100), (255, 255, 255, 255))
    _out, did_speck = _crop_to_product(speck)
    c.ok(not did_speck, "a collapsed mask is not trusted as a crop box")

    opaque = Image.new("RGBA", (200, 200), (255, 255, 255, 255))
    c.eq(_removed_share(opaque), 0.0, "an untouched image reports nothing removed")

    with tempfile.TemporaryDirectory() as tmp:
        cover = Path(tmp) / "data" / "images" / "tms" / "SKU.jpg"
        cover.parent.mkdir(parents=True)
        cover.write_bytes(b"x")
        c.ok(_needs_render(cover, set()), "no render yet means it needs one")
        render = cover.with_suffix(".webp")
        render.write_bytes(b"y")
        c.ok(not _needs_render(cover, set()),
             "a fresh render is skipped (mtime idempotency)")
        c.ok(not _needs_render(cover, {"SKU"}), "keep_jpg.txt exempts a bare SKU")
        c.ok(not _needs_render(cover, {"tms/SKU.jpg"}),
             "keep_jpg.txt exempts vendor/SKU.jpg")
        c.ok(_needs_render(cover, set(), force=True), "--force ignores a fresh render")

    c.ok(isinstance(load_keep_jpg(), set), "the keep_jpg list parses")


def check_site_resolution(c: Checks) -> None:
    from scraper import site_data

    with tempfile.TemporaryDirectory() as tmp:
        images = Path(tmp) / "images"
        (images / "tms").mkdir(parents=True)
        (images / "tms" / "A.jpg").write_bytes(b"j")
        (images / "tms" / "A.webp").write_bytes(b"w")
        (images / "tms" / "B.jpg").write_bytes(b"j")
        (images / "plonter").mkdir(parents=True)
        (images / "plonter" / "C.jpg").write_bytes(b"j")

        original = site_data.IMAGES_DIR
        site_data.IMAGES_DIR = images
        try:
            image, thumb = site_data._local_image_path("tms", "A"), None
            c.eq(image, "/images/tms/A.webp",
                 "the transparent render is preferred over the .jpg")
            c.eq(site_data._local_image_path("tms", "B"), "/images/tms/B.jpg",
                 "a cover with no render falls back to the .jpg")
            c.eq(site_data._local_image_path("tms", "ZZZ"), None,
                 "an unknown SKU resolves to nothing")

            product = {
                "image_url": TMS_TILE,
                "offers": [
                    {"vendor_id": "tms", "vendor_sku": "ZZZ", "image_url": TMS_TILE},
                    {"vendor_id": "tms", "vendor_sku": "A", "image_url": TMS_TILE},
                ],
            }
            image, _thumb = site_data._resolve_image(product, product["offers"])
            c.eq(image, "/images/tms/A.webp",
                 "resolution falls through to the first offer with a local file")

            ordered = {
                "image_url": PLONTER_FULL,
                "offers": [
                    {"vendor_id": "tms", "vendor_sku": "A", "image_url": TMS_TILE},
                    {"vendor_id": "plonter", "vendor_sku": "C",
                     "image_url": PLONTER_FULL},
                ],
            }
            image, _thumb = site_data._resolve_image(ordered, ordered["offers"])
            c.eq(image, "/images/plonter/C.jpg",
                 "the stored cover's offer leads the resolution order")

            none = {
                "image_url": PLONTER_FULL,
                "offers": [{"vendor_id": "plonter", "vendor_sku": "MISSING",
                            "image_url": PLONTER_FULL}],
            }
            c.eq(site_data._resolve_image(none, none["offers"])[0], None,
                 "a product with no local file resolves to nothing, never a remote URL")
        finally:
            site_data.IMAGES_DIR = original


def check_chewed_detection(c: Checks) -> None:
    """Bites out of the product must flag; legit layouts must not.

    Synthetic RGBA renders, no corpus needed. Needs numpy+scipy (the same
    optional dependency detect_chewed itself requires) — skipped with a
    note where it is missing, mirroring the Tier-0 degrade pattern.
    """
    try:
        from scraper import detect_chewed
    except Exception as exc:
        c.ok(False, "detect_chewed imports", str(exc))
        return
    if not detect_chewed._HAVE_SCI:
        c.ok(True, "scipy missing — chewed checks skipped (CI runs them after "
                    "requirements-images.txt is installed)")
        return

    def render(opaque_boxes: list[tuple[int, int, int, int]],
               size: tuple[int, int] = (200, 200)) -> Image.Image:
        img = Image.new("RGBA", size, (0, 0, 0, 0))
        for x0, y0, x1, y1 in opaque_boxes:
            for x in range(x0, x1):
                for y in range(y0, y1):
                    img.putpixel((x, y), (200, 200, 200, 255))
        return img

    with tempfile.TemporaryDirectory() as tmp:
        solid = Path(tmp) / "solid.webp"
        render([(20, 20, 180, 180)]).save(solid, "WEBP")
        m = detect_chewed.analyze(solid)
        c.eq(m["big_hole"], 0.0, "a solid product has no big holes")
        c.ok(not detect_chewed.is_chewed(m, "cpu"), "a solid CPU is clean")

        bitten = Path(tmp) / "bitten.webp"
        img = render([(20, 20, 180, 180)])
        for x in range(60, 140):
            for y in range(60, 140):
                img.putpixel((x, y), (0, 0, 0, 0))  # IHS bite, fully enclosed
        img.save(bitten, "WEBP")
        mb = detect_chewed.analyze(bitten)
        c.gt(mb["big_hole"], 0.2, "an IHS-sized bite dominates the bbox")
        c.ok(detect_chewed.is_chewed(mb, "cpu"), "a bitten CPU flags (strict)")

        nibbled = Path(tmp) / "nibbled.webp"  # 3.5% hole: strict flags it,
        img = render([(20, 20, 180, 180)])    # lenient tolerates it (mesh?)
        for x in range(60, 90):
            for y in range(60, 90):
                img.putpixel((x, y), (0, 0, 0, 0))
        img.save(nibbled, "WEBP")
        mn = detect_chewed.analyze(nibbled)
        c.ok(detect_chewed.is_chewed(mn, "cpu"),
             "a 3.5% hole still flags on a solid CPU")
        c.ok(not detect_chewed.is_chewed(mn, "case"),
             "the same holes in a mesh-prone category stay lenient")

        kit = Path(tmp) / "kit.webp"  # two sticks, legit gap between them
        render([(20, 40, 80, 160), (120, 40, 180, 160)]).save(kit, "WEBP")
        mk = detect_chewed.analyze(kit)
        c.eq(mk["big_hole"], 0.0, "an exterior-connected kit gap is no hole")
        c.ok(not detect_chewed.is_chewed(mk, "memory"),
             "a two-stick kit photo is not chewing")

        mesh = Path(tmp) / "mesh.webp"  # pinholes below the size floor
        img = render([(20, 20, 180, 180)])
        for x in range(30, 170, 10):
            for y in range(30, 170, 10):
                img.putpixel((x, y), (0, 0, 0, 0))
        img.save(mesh, "WEBP")
        mm = detect_chewed.analyze(mesh)
        c.eq(mm["big_hole"], 0.0, "mesh pinholes stay under the size floor")

        shreds = Path(tmp) / "shreds.webp"  # box-art carnage: 20 shards
        boxes = [(10 + 9 * i, 10 + 7 * i, 16 + 9 * i, 16 + 7 * i)
                 for i in range(20)]
        render(boxes).save(shreds, "WEBP")
        ms = detect_chewed.analyze(shreds)
        c.ok(detect_chewed.is_chewed(ms, "case"),
             "shredded fragments flag even in a lenient category")

        empty = Path(tmp) / "empty.webp"
        Image.new("RGBA", (100, 100), (0, 0, 0, 0)).save(empty, "WEBP")
        me = detect_chewed.analyze(empty)
        c.ok(me["empty"], "a fully vaporized matte reports empty")
        c.ok(detect_chewed.is_chewed(me, "psu"), "an empty render always flags")


def check_priority_file(c: Checks) -> None:
    path = ROOT / "data" / "matching" / "image_vendor_priority.json"
    c.ok(path.is_file(), "the committed priority table exists")
    data = json.loads(path.read_text(encoding="utf-8"))
    priority = data.get("priority") or {}
    c.gt(len(priority), 0, "the priority table lists categories")
    c.ok(all(isinstance(v, list) and v for v in priority.values()),
         "every priority entry is a non-empty list")
    try:
        from scraper.specs.schema import CATEGORIES  # type: ignore[attr-defined]
    except Exception:
        return
    missing = [category for category in CATEGORIES if category not in priority]
    # Categories with no offers can be absent; a missing entry only falls back
    # to the built-in default, so this is a drift *warning* worth pinning.
    c.eq(missing, [], "every schema category has a priority entry")


def main() -> int:
    checks = Checks()
    for group in (check_url_vocabulary, check_gallery_capture, check_scoring,
                  check_refetch_rules, check_transparent_render,
                  check_site_resolution, check_chewed_detection,
                  check_priority_file):
        group(checks)

    if checks.failures:
        print(f"[image-pick] FAIL — {len(checks.failures)} of {checks.count} "
              f"assertions failed")
        for failure in checks.failures:
            print(f"  - {failure}")
        return 1
    print(f"[image-pick] pass — {checks.count} assertions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
