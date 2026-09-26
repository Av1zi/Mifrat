"""
Vendor image-URL vocabulary: what a URL shape says about the file behind it.

Why this exists (Sep 2026, "transparent photos + automatic best-photo picking"):

The audit (scripts/audit_images.py) found 657 TMS covers on disk at 228px
while the SAME product page serves a 1500x1500 original — because
download_images() skips any destination file that already exists, and the
listing tile (228px) had been written first by the --from-catalog backfill.
Nothing in the pipeline could tell "228px tile of photo X" from "original of
photo X", so nothing could prefer the better file.

Every vendor here serves the same photo at several URL shapes:

  TMS (OpenCart)   /image/catalog/products/<sku>/<hash>.jpg          original
                   /image/cache/catalog/products/<sku>/<hash>-1000x1000.jpg
                   /image/cache/.../<hash>-74x74.jpg                 tile
  1PC (CS-Cart)    /images/thumbs/<id>_<slug>.jpeg                   native
                   /images/thumbs/<id>_<slug>_510.jpeg                resized
  Plonter          /graphics/product_images/full/<SKU>.jpg           full
  Ivory            /files/catalog/org/<hash>.webp                    original

Two things follow, and both live here rather than in each caller:

1. Given any URL, `candidate_urls()` derives the same photo's originals
   (strip the resize suffix; drop the /cache/ segment), so a pipeline that
   already stores the small URL can upgrade without re-crawling the page.
2. Given two URLs, `photo_key()` says whether they are the same shot at
   different sizes — the check that turns "different URL" into "same photo,
   bigger file", which is what makes an in-place upgrade safe instead of a
   coin flip.

Same pattern as scraper/specs/labels.py owning the vendor label vocabulary:
one module owns the vendor-specific string knowledge, and everything else
asks it questions.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

# TMS/OpenCart cached resize: "-1000x1000.jpg", "-74x74.jpeg", "-222x222.jpg".
_CACHE_SIZE_RE = re.compile(r"-\d{2,4}x\d{2,4}(\.[A-Za-z0-9]+)$")

# 1PC/CS-Cart appended size: "_510.jpeg", "_290.webp". Only stripped when the
# number is a plausible render size and the rest of the basename survives —
# see _strip_size_suffix, which refuses to touch e.g. "12_5000" style SKUs.
_APPENDED_SIZE_RE = re.compile(r"_(\d{2,4})(\.[A-Za-z0-9]+)$")

# A cached segment that carries the original path after it.
_CACHE_SEGMENT_RE = re.compile(r"/image/cache/")

# Paths that are site furniture, never a product photo. Matched on the path
# only, case-insensitively; ".svg" is always furniture (no vendor shoots SVG).
_NON_PRODUCT_RE = re.compile(
    r"(?:[/_.-](?:logos?|flags?|icons?|banners?|menus?|placeholder)(?:[/_.-]|$))"
    r"|(?:/Themes?)"
    r"|(?:\.svg$)",
    re.IGNORECASE,
)

# Plausible resized-size range for the appended-suffix rule. Below 40 is a
# SKU fragment, above 2000 is not a web render size.
_MIN_SUFFIX_SIZE = 40
_MAX_SUFFIX_SIZE = 2000

# Penalty bands for a URL that carries an explicit resize size. A 1000px
# render is nearly the original (mild), a 500px one is a real downgrade, and
# a 74-228px tile is a thumbnail. Size beats bucket: a big render outscores a
# small one from the same /cache/ or /thumbs/ directory.
_SIZE_PENALTY = ((600, 0.5), (300, 1.5), (0, 3.0))


def is_probably_not_a_photo(url: str) -> bool:
    """True for site furniture (logos, flags, banners, svg icons).

    The detail spiders' gallery selectors are intentionally broad, so this
    is the single veto both the spiders and the scorer apply. Errs toward
    keeping a URL: only clear furniture is rejected.
    """
    if not url:
        return True
    try:
        path = urlparse(url).path
    except Exception:
        return True
    if not path or path.endswith("/"):
        return True
    return bool(_NON_PRODUCT_RE.search(path))


def _basename(url: str) -> str:
    try:
        return urlparse(url).path.rsplit("/", 1)[-1]
    except Exception:
        return ""


def strip_size_suffix(url: str) -> str | None:
    """The same photo's original URL when one is derivable, else None.

    TMS: "-1000x1000.jpg" is dropped, and a "/image/cache/" segment collapses
    to "/image/" — that is exactly how OpenCart stores its originals. Both
    steps must apply together, or a cache URL would be rewritten to another
    cache URL.
    1PC: a trailing "_510.jpeg" is dropped ("/images/thumbs/<id>_<slug>.jpeg"
    is what the page links as the full-size image, verified Sep 2026).

    Never guesses: returns None when there is no resize marker to strip, so a
    caller can always tell "no better URL known" from "better URL here".
    """
    if not url:
        return None
    changed = False
    stripped = url

    if _CACHE_SEGMENT_RE.search(stripped) and _CACHE_SIZE_RE.search(stripped):
        stripped = _CACHE_SIZE_RE.sub(r"\1", stripped)
        stripped = _CACHE_SEGMENT_RE.sub("/image/", stripped, count=1)
        changed = True
    elif _CACHE_SIZE_RE.search(stripped):
        stripped = _CACHE_SIZE_RE.sub(r"\1", stripped)
        changed = True
    else:
        match = _APPENDED_SIZE_RE.search(_basename(stripped))
        if match:
            size = int(match.group(1))
            if _MIN_SUFFIX_SIZE <= size <= _MAX_SUFFIX_SIZE:
                # Only the basename is touched — keep query strings intact.
                head, sep, _tail = stripped.rpartition("/")
                stripped = f"{head}{sep}{_basename(stripped)[:match.start()]}{match.group(2)}"
                changed = True

    return stripped if changed and stripped != url else None


def _resize_size(url: str) -> int | None:
    """The explicit resize size in a URL (TMS -1000x1000, 1PC _510), or None.

    This is the only size signal available before a single byte is fetched,
    and it is what separates a near-original render from a 74px tile.
    """
    if not url:
        return None
    basename = _basename(url)
    match = _CACHE_SIZE_RE.search(basename)
    if match:
        digits = re.findall(r"\d{2,4}", match.group(0))
        if digits:
            return int(digits[0])
        return None
    match = _APPENDED_SIZE_RE.search(basename)
    if match:
        size = int(match.group(1))
        if _MIN_SUFFIX_SIZE <= size <= _MAX_SUFFIX_SIZE:
            return size
    return None


def candidate_urls(url: str) -> list[str]:
    """Ordered candidate URLs for one known photo: originals first.

    Returned best-first so a caller that simply walks the list gets the
    biggest available file before falling back to the URL it started with.
    """
    if not url:
        return []
    out: list[str] = []
    original = strip_size_suffix(url)
    if original and not is_probably_not_a_photo(original):
        out.append(original)
    if url not in out and not is_probably_not_a_photo(url):
        out.append(url)
    return out


def photo_key(url: str) -> str:
    """Identity of the *photo* behind a URL, size- and cache-insensitive.

    Two URLs with the same photo_key are the same shot rendered at different
    sizes; a URL whose key differs is a genuinely different photo. Used to
    decide whether re-downloading is an in-place upgrade (same shot, bigger)
    rather than a switch to a different picture.
    """
    if not url:
        return ""
    key = strip_size_suffix(url) or url
    try:
        parts = urlparse(key)
    except Exception:
        return key
    return f"{parts.netloc}{parts.path}".lower()


def best_of(urls) -> str | None:
    """The best-shaped URL of a list, first-wins on ties. None when empty.

    Used wherever several URLs for the same photo are already known (detail
    candidates vs. the listing tile) and the caller just needs the winner.
    """
    best: str | None = None
    best_score = float("-inf")
    for url in urls:
        if not url:
            continue
        score = url_shape_score(str(url))
        if best is None or score > best_score:
            best, best_score = str(url), score
    return best


def url_shape_score(url: str) -> float:
    """How promising a URL looks, from its shape alone (no network, no disk).

    Roughly 2..13 for photos, -10 for site furniture. Originals score high,
    resized derivatives low, furniture low enough that it can never win a tie.
    The scorer combines this with local file metrics when the file already
    exists (see image_score.score_candidate).
    """
    # NOTE: deliberately no disk or network here — this runs inside the
    # matcher, once per offer, and must stay free.
    if not url:
        return -10.0
    if is_probably_not_a_photo(url):
        return -10.0

    score = 5.0
    lowered = url.lower()
    if "/image/catalog/products/" in lowered or "/files/catalog/org/" in lowered:
        score += 2.5          # vendor original directories
    if "/graphics/product_images/full/" in lowered:
        score += 2.5
    if "/images/thumbs/" in lowered:
        # 1PC's only bucket: /images/thumbs/<id>_<slug>.jpeg IS its native
        # file (the page links exactly that as the full-size image), so the
        # word "thumbs" must not read as a downgrade. The resize suffix is
        # what distinguishes the render from the native file.
        score += 0.5
    if "/cache/" in lowered:
        score -= 1.0
    size = _resize_size(url)
    if size is not None:
        for floor, penalty in _SIZE_PENALTY:
            if size >= floor:
                score -= penalty
                break
    return score
