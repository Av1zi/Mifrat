"""Offline gate: the cover downloader only fetches vendor images, bounded.

scraper/download_images.py fetches URLs scraped from vendor pages on the Nano
(home LAN) and in CI. The 2026-11-10 security audit (F-2, D-3) found no host
allowlist, followed redirects, an unbounded body and every Pillow format
decoded. This pins the fix with NO vendor traffic: a local http.server on
127.0.0.1 (ephemeral port) serves generated fixtures, and the allowlist is
injected to 127.0.0.1 only (plain http is allowed for the test server alone).

Asserts:

- small JPEG / PNG / WEBP / GIF are accepted and written as WebP covers
  (into a temp IMAGES_DIR — nothing is written under data/);
- TIFF and BMP (also TIFF bytes behind a .jpg name) are refused, as are
  images over Image.MAX_IMAGE_PIXELS (40 MP), both in Pillow's warn-only band
  (a 41 MP PNG that really decodes) and above it;
- redirects: relative / scheme-relative Locations work, 3 hops pass, a 4th
  is refused, and a hop to a non-allowed host / file: / ftp: / https-foreign
  is refused WITHOUT connecting (a second local server counts hits);
- a 50 MB body is refused at the 10 MB cap whether Content-Length is honest,
  missing (close-delimited), chunked, unparseable or gzip-inflated; a lying
  short Content-Length cannot smuggle more than it declares;
- a slow drip is cut by the overall deadline;
- a refused URL leaves LAST_HTTP_STATUS None (never counts toward the
  2x403/429 stop) while a real 403 still reports 403, through redirects too;
- URL parsing tricks (userinfo, backslash, control chars, suffix look-alikes,
  IP literals, http/file/ftp/data schemes) are refused by refuse_reason();
- every spider's allowed_domains is on IMAGE_HOSTS, and every image URL in
  data/catalog.json, the latest raw snapshot per vendor and data/raw/detail/
  passes refuse_reason() with the production defaults (read-only).

Run: python scripts/check_image_fetch.py [--hosts]   (exit 0 = pass, 1 = fail)
     --hosts prints the scheme+host histogram of the current data.
"""
from __future__ import annotations

import json
import re
import struct
import sys
import tempfile
import threading
import time
import warnings
import zlib
from collections import Counter
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO, StringIO
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import urllib3.response  # noqa: E402
from PIL import Image  # noqa: E402

from scraper import download_images as di  # noqa: E402
from scraper import site_data  # noqa: E402
from scraper.image_urls import candidate_urls  # noqa: E402

BIG = 50 * 1024 * 1024
FIXTURES: dict[str, bytes] = {}
HITS: Counter = Counter()
SENT: dict[str, int] = {}
DONE: dict[str, threading.Event] = {}


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


def _encoded(img: Image.Image, fmt: str, **kw) -> bytes:
    buf = BytesIO()
    img.save(buf, fmt, **kw)
    return buf.getvalue()


def _png(width: int, height: int, pixels: bool) -> bytes:
    """A black greyscale PNG. Pillow checks the size at open, so without
    `pixels` the IDAT is a stub; with it the file really decodes (a few KB)."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    raw = bytes((width + 1) * height) if pixels else b"\0"
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _gzip_zeros(total: int) -> bytes:
    comp = zlib.compressobj(9, zlib.DEFLATED, 31)
    block = bytes(1 << 20)
    out = bytearray()
    for _ in range(total >> 20):
        out += comp.compress(block)
    return bytes(out + comp.flush())


def build_fixtures() -> None:
    rgb = Image.new("RGB", (64, 48), (200, 40, 40))
    rgba = Image.new("RGBA", (64, 48), (0, 0, 0, 0))
    rgba.paste((30, 120, 200, 255), (10, 10, 40, 40))
    FIXTURES.update({
        "/ok.jpg": _encoded(rgb, "JPEG", quality=85),
        "/ok.png": _encoded(rgba, "PNG"),
        "/ok.webp": _encoded(rgba, "WEBP", quality=80),
        "/ok.gif": _encoded(rgb.convert("P"), "GIF"),
        "/x.tif": _encoded(rgb, "TIFF"),
        "/x.bmp": _encoded(rgb, "BMP"),
        "/tiff-named.jpg": _encoded(rgb, "TIFF"),
        "/mp41.png": _png(8000, 5126, True),       # 41 MP, decodable: Pillow only warns
        "/mp100.png": _png(10000, 10000, False),   # 100 MP: over Pillow's own 2x error
        "/gzip-bomb.jpg": _gzip_zeros(BIG),
    })


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args) -> None:
        return

    def _stream_zeros(self, total: int, chunked: bool = False) -> None:
        block = bytes(64 * 1024)
        sent = 0
        try:
            while sent < total:
                if chunked:
                    self.wfile.write(b"%x\r\n" % len(block) + block + b"\r\n")
                else:
                    self.wfile.write(block)
                sent += len(block)
            if chunked:
                self.wfile.write(b"0\r\n\r\n")
        except OSError:
            pass
        finally:
            SENT[self.path] = sent
            DONE.setdefault(self.path, threading.Event()).set()

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        path = self.path
        HITS[path] += 1
        port = self.server.server_address[1]  # type: ignore[index]
        other = getattr(self.server, "other_port", 0)
        hops = re.fullmatch(r"/hops/(\d+)", path)
        if path in FIXTURES:
            body = FIXTURES[path]
            self.send_response(200)
            if path == "/gzip-bomb.jpg":
                self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif hops:
            n = int(hops.group(1))
            if n == 0:
                self._redirect("/ok.jpg")
            else:
                self._redirect(f"/hops/{n - 1}")
        elif path == "/rel/":
            self._redirect("../ok.png")
        elif path == "/scheme-rel":
            self._redirect(f"//127.0.0.1:{port}/ok.webp")
        elif path == "/to-foreign":
            self._redirect(f"http://localhost:{other}/ok.jpg")
        elif path == "/to-lan":
            self._redirect("http://10.100.102.1/ok.jpg")
        elif path == "/to-https-foreign":
            self._redirect("https://evil.example/ok.jpg")
        elif path == "/to-file":
            self._redirect("file:///C:/Windows/win.ini")
        elif path == "/to-ftp":
            self._redirect(f"ftp://127.0.0.1:{port}/ok.jpg")
        elif path == "/403":
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif path == "/to-403":
            self._redirect("/403")
        elif path == "/big-cl":
            self.send_response(200)
            self.send_header("Content-Length", str(BIG))
            self.end_headers()
            self._stream_zeros(BIG)
        elif path in ("/big-nocl", "/big-badcl"):
            self.send_response(200)
            if path == "/big-badcl":
                self.send_header("Content-Length", "lots")
            self.send_header("Connection", "close")
            self.end_headers()
            self._stream_zeros(BIG)
        elif path == "/big-chunked":
            self.protocol_version = "HTTP/1.1"
            self.send_response(200)
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Connection", "close")
            self.end_headers()
            self._stream_zeros(BIG, chunked=True)
        elif path == "/big-lying":
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.end_headers()
            self._stream_zeros(BIG)
        elif path == "/drip":
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.end_headers()
            try:
                for _ in range(40):
                    self.wfile.write(b"\0")
                    self.wfile.flush()
                    time.sleep(0.2)
            except OSError:
                pass
        else:
            self.send_error(404)


class QuietServer(ThreadingHTTPServer):
    other_port = 0

    def handle_error(self, request, client_address) -> None:
        return


def _serve() -> QuietServer:
    server = QuietServer(("127.0.0.1", 0), FixtureHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _fetch(url: str, hosts=("127.0.0.1",), schemes=("http",)) -> tuple[bytes | None, str]:
    try:
        return di.fetch_image_bytes(url, hosts=hosts, schemes=schemes), ""
    except di.RefusedImage as exc:
        return None, f"refused: {exc}"
    except Exception as exc:
        return None, f"error: {type(exc).__name__}: {exc}"


def _wait_done(path: str) -> int:
    DONE.setdefault(path, threading.Event()).wait(10)
    return SENT.get(path, -1)


def check_urls(c: Checks) -> None:
    allowed = [
        "https://tms.co.il/image/catalog/products/A/b.jpg",
        "https://www.ivory.co.il/files/catalog/org/1.webp",
        "https://TMS.CO.IL/x.jpg",
        "https://ksp.co.il/shop/items/112515.jpg?v=5",
        "https://www.plonter.co.il/graphics/product_images/full/GV-N5060EAGLEMAX OC-8GD.jpg",
        "https://tms.co.il/image/catalog/products/\u200eVCQ/AE9.jpg",
    ]
    for url in allowed:
        c.eq(di.refuse_reason(url), None, f"allowed: {url!r}")
    refused = [
        "http://tms.co.il/x.jpg", "ftp://tms.co.il/x.jpg", "file:///etc/passwd",
        "data:image/png;base64,iVBORw0KGgo=", "//tms.co.il/x.jpg", "/images/x.jpg", "",
        "https://evil.example/x.jpg", "https://eviltms.co.il/x.jpg",
        "https://tms.co.il.evil.example/x.jpg", "https://tms.co.il./x.jpg",
        "https://tms.co.il@evil.example/x.jpg", "https://evil.example@tms.co.il/x.jpg",
        "https://evil.example\\@tms.co.il/x.jpg", "https://evil.example\\.tms.co.il/x.jpg",
        "https://evil.example#@tms.co.il/x.jpg", "https://tms.co.il\t.evil.example/x",
        "https://tms.co.il\n/x.jpg", "https://tms.co.il\u3002evil.example/x.jpg",
        "https://127.0.0.1/x.jpg", "https://10.100.102.1/x.jpg", "https://[::1]/x.jpg",
        "https://169.254.169.254/latest/meta-data", "https://localhost/x.jpg",
    ]
    for url in refused:
        c.ok(di.refuse_reason(url) is not None, f"refused: {url!r}")
    c.eq(Image.MAX_IMAGE_PIXELS, 40_000_000, "Image.MAX_IMAGE_PIXELS is 40 MP")
    try:
        di._open_image(BytesIO(FIXTURES["/mp41.png"])).close()
        c.ok(False, "_open_image raises in Pillow's warn-only band (41 MP)")
    except Exception as exc:
        c.ok("decompression bomb" in str(exc),
             "_open_image raises in Pillow's warn-only band (41 MP)", str(exc))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", Image.DecompressionBombWarning)
        with Image.open(BytesIO(FIXTURES["/mp41.png"])) as img:
            img.load()
            c.eq(img.size, (8000, 5126), "control: the 41 MP fixture decodes without the guard")
    c.eq(di.IMAGE_FORMATS, ("JPEG", "PNG", "WEBP", "GIF"), "decoded formats")
    c.eq(sorted(di.IMAGE_SCHEMES), ["https"], "production schemes are https only")


def check_fetch(c: Checks, base: str, port: int, other: QuietServer) -> None:
    for path in ("/ok.jpg", "/ok.png", "/ok.webp", "/ok.gif"):
        data, err = _fetch(base + path)
        c.eq(data, FIXTURES[path], f"{path} is fetched intact {err}")

    data, err = _fetch(base + "/hops/2")
    c.eq(data, FIXTURES["/ok.jpg"], f"3 redirects are followed {err}")
    before = HITS["/ok.jpg"]
    data, err = _fetch(base + "/hops/3")
    c.ok(data is None and "more than 3 redirects" in err, "a 4th redirect is refused", err)
    c.eq(HITS["/ok.jpg"], before, "the target past the 4th redirect is never requested")
    data, err = _fetch(base + "/rel/")
    c.eq(data, FIXTURES["/ok.png"], f"a relative Location resolves {err}")
    data, err = _fetch(base + "/scheme-rel")
    c.eq(data, FIXTURES["/ok.webp"], f"a scheme-relative Location resolves {err}")

    oport = other.server_address[1]
    for path, want in (("/to-foreign", "localhost"), ("/to-lan", "10.100.102.1"),
                       ("/to-https-foreign", "scheme"), ("/to-file", "scheme"),
                       ("/to-ftp", "scheme")):
        start = time.monotonic()
        data, err = _fetch(base + path)
        c.ok(data is None and err.startswith("refused: redirect to") and want in err,
             f"{path} is refused at the hop", err)
        c.ok(time.monotonic() - start < 5, f"{path} is refused without connecting")
    c.eq(sum(other.hits.values()), 0,  # type: ignore[attr-defined]
         "the non-allowed redirect target never saw a request")
    data, err = _fetch(f"http://localhost:{oport}/ok.jpg",
                       hosts=("127.0.0.1", "localhost"))
    c.ok(data == FIXTURES["/ok.jpg"] and sum(other.hits.values()) == 1,  # type: ignore[attr-defined]
         "control: the same target IS reachable once allowed", err)

    data, err = _fetch(base + "/ok.jpg", schemes=None)
    c.ok(data is None and "scheme 'http'" in err,
         "plain http is refused with the production schemes", err)
    data, err = _fetch(base + "/ok.jpg", hosts=None)
    c.ok(data is None and "allowlist" in err, "127.0.0.1 is refused with the production hosts", err)

    start = time.monotonic()
    data, err = _fetch(base + "/big-cl")
    c.ok(data is None and "Content-Length" in err, "a declared 50 MB body is refused up front", err)
    c.ok(time.monotonic() - start < 10, "the declared-size refusal is immediate")
    for path in ("/big-nocl", "/big-chunked", "/big-badcl"):
        data, err = _fetch(base + path)
        c.ok(data is None and err.startswith("refused:") and str(di.MAX_IMAGE_BYTES) in err,
             f"{path}: 50 MB body is cut at the 10 MB cap", err)
        sent = _wait_done(path)
        c.ok(0 <= sent < BIG, f"{path}: the server could not push all 50 MB", f"sent {sent}")
    data, err = _fetch(base + "/gzip-bomb.jpg")
    c.ok(data is None and str(di.MAX_IMAGE_BYTES) in err,
         "a gzip body inflating to 50 MB is cut at the 10 MB cap", err)
    data, err = _fetch(base + "/big-lying")
    c.eq(len(data or b""), 1000, f"a short Content-Length bounds the read {err}")

    # urllib3 < 2.3 (a stale Nano env) has no HTTPResponse.read1.
    saved_read1 = urllib3.response.HTTPResponse.read1
    setattr(urllib3.response.HTTPResponse, "read1", None)
    try:
        data, err = _fetch(base + "/ok.png")
        c.eq(data, FIXTURES["/ok.png"], f"without read1 a fetch still works {err}")
        for path in ("/big-nocl", "/gzip-bomb.jpg"):
            data, err = _fetch(base + path)
            c.ok(data is None and str(di.MAX_IMAGE_BYTES) in err,
                 f"without read1 {path} is still cut at the 10 MB cap", err)
    finally:
        setattr(urllib3.response.HTTPResponse, "read1", saved_read1)

    saved = di.FETCH_DEADLINE
    di.FETCH_DEADLINE = 1.5
    try:
        start = time.monotonic()
        data, err = _fetch(base + "/drip")
        took = time.monotonic() - start
    finally:
        di.FETCH_DEADLINE = saved
    c.ok(data is None and "took over" in err, "a slow drip is cut by the deadline", err)
    c.ok(took < 5, "the deadline holds although every read is within the timeout",
         f"{took:.1f}s")


def check_save(c: Checks, base: str, tmp: Path) -> None:
    log = StringIO()
    with redirect_stdout(log):
        _check_save(c, base, tmp)
    out = log.getvalue()
    c.ok(f"  REFUSED {base}/to-lan -> " in out and "not on the image allowlist" in out,
         "a refusal is logged as REFUSED with its reason", out)
    c.ok(f"  FAILED {base}/403 -> " in out, "an HTTP error is still logged as FAILED", out)


def _check_save(c: Checks, base: str, tmp: Path) -> None:
    images = tmp / "images"
    original = (site_data.IMAGES_DIR, di.IMAGE_HOSTS, di.IMAGE_SCHEMES)
    site_data.IMAGES_DIR = images
    di.IMAGE_HOSTS = frozenset({"127.0.0.1"})
    di.IMAGE_SCHEMES = frozenset({"http"})
    try:
        for path, alpha in (("/ok.jpg", False), ("/ok.png", True), ("/ok.webp", True),
                            ("/ok.gif", False)):
            dest = images / "t" / f"{path.strip('/').replace('.', '_')}.webp"
            c.ok(di.download_and_save(base + path, dest), f"{path} is saved")
            c.eq(di.LAST_HAD_ALPHA, alpha, f"{path} alpha detection")
            with Image.open(dest) as out:
                c.eq(out.format, "WEBP", f"{path} is written as WebP")
            c.eq(di._long_edge(dest), 64, f"{path} long edge reads back")
        for path in ("/x.tif", "/x.bmp", "/tiff-named.jpg", "/mp41.png", "/mp100.png"):
            dest = images / "t" / "refused.webp"
            c.ok(not di.download_and_save(base + path, dest), f"{path} is not decoded")
            c.ok(not dest.exists(), f"{path} writes no cover")
            c.eq(di.LAST_HTTP_STATUS, None, f"{path} is not an HTTP failure")
        tif = images / "t" / "local.tif"
        tif.write_bytes(FIXTURES["/x.tif"])
        c.eq(di._long_edge(tif), None, "a local TIFF is not opened either")

        dest = images / "t" / "r.webp"
        for path in ("/to-foreign", "/to-lan", "/to-file", "/hops/3", "/big-nocl"):
            c.ok(not di.download_and_save(base + path, dest), f"{path} is not saved")
            c.eq(di.LAST_HTTP_STATUS, None,
                 f"{path}: a refusal never counts toward the 2x403/429 stop")
        c.ok(not di.download_and_save(base + "/403", dest), "a 403 is not saved")
        c.eq(di.LAST_HTTP_STATUS, 403, "a real 403 still reports 403")
        c.ok(not di.download_and_save(base + "/to-403", dest), "a redirect to a 403 fails")
        c.eq(di.LAST_HTTP_STATUS, 403, "a 403 behind a redirect still reports 403")
        c.ok(di.download_candidates([base + "/to-lan", base + "/ok.jpg"], dest),
             "a refused candidate falls through to the next one")
        try:
            di.download_and_save(base + "/ok.jpg", ROOT / "data" / "x.webp")
        except Exception:
            pass
        c.ok(not (ROOT / "data" / "x.webp").exists(), "the write guard still holds")
    finally:
        site_data.IMAGES_DIR, di.IMAGE_HOSTS, di.IMAGE_SCHEMES = original


def _spider_domains() -> set[str]:
    domains: set[str] = set()
    for path in sorted((ROOT / "scraper" / "spiders").glob("*.py")):
        for group in re.findall(r"allowed_domains\s*=\s*\[([^\]]*)\]",
                                path.read_text(encoding="utf-8")):
            domains.update(re.findall(r"[\"']([^\"']+)[\"']", group))
    return domains


def _image_urls(obj, out: list[str]) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if "image" in key.lower():
                if isinstance(value, str):
                    out.append(value)
                elif isinstance(value, list):
                    out.extend(v for v in value if isinstance(v, str))
            if isinstance(value, (dict, list)):
                _image_urls(value, out)
    elif isinstance(obj, list):
        for value in obj:
            _image_urls(value, out)


def _current_data_files() -> list[Path]:
    raw = ROOT / "data" / "raw"
    latest: dict[str, Path] = {}
    if raw.is_dir():
        for day in sorted(p for p in raw.iterdir() if p.is_dir() and p.name[:2] == "20"):
            for f in day.glob("*.jsonl"):
                latest[f.name] = f
    return [*latest.values(), *sorted((raw / "detail").glob("*.jsonl"))]


def check_current_data(c: Checks, show: bool) -> None:
    domains = _spider_domains()
    c.ok(len(domains) >= 6, "spider allowed_domains are found", repr(sorted(domains)))
    for domain in sorted(domains):
        c.eq(di.refuse_reason(f"https://{domain}/x.jpg"), None,
             f"spider domain {domain} is on IMAGE_HOSTS")
        c.eq(di.refuse_reason(f"https://www.{domain}/x.jpg"), None,
             f"www.{domain} is on IMAGE_HOSTS")

    sources: dict[str, list[str]] = {}
    catalog = ROOT / "data" / "catalog.json"
    if catalog.is_file():
        urls: list[str] = []
        _image_urls(json.loads(catalog.read_text(encoding="utf-8")), urls)
        sources["data/catalog.json"] = urls
    for path in _current_data_files():
        urls = []
        with path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        _image_urls(json.loads(line), urls)
                    except ValueError:
                        pass
        sources[path.relative_to(ROOT).as_posix()] = urls
    c.ok("data/catalog.json" in sources, "data/catalog.json is readable")

    hosts: Counter = Counter()
    refused: Counter = Counter()
    examples: dict[str, str] = {}
    for urls in sources.values():
        for url in urls:
            if not url:
                continue
            for candidate in candidate_urls(url) or [url]:
                parts = urlparse(candidate)
                label = f"{parts.scheme}://{(parts.hostname or '-').lower()}"
                hosts[label] += 1
                reason = di.refuse_reason(candidate)
                if reason:
                    refused[label] += 1
                    examples.setdefault(label, f"{candidate} ({reason})")
    c.ok(sum(hosts.values()) > 1000, "current data has image URLs to check",
         str(sum(hosts.values())))
    c.eq(dict(refused), {}, "every current image URL passes the production allowlist"
         + "".join(f"\n      e.g. {e}" for e in examples.values()))
    if show:
        print(f"  {len(sources)} files: " + ", ".join(sources))
        for label, n in hosts.most_common():
            print(f"    {n:8d}  {label}  ({refused[label]} refused)")


def main() -> int:
    show = "--hosts" in sys.argv[1:]
    checks = Checks()
    build_fixtures()
    check_urls(checks)
    server, other = _serve(), _serve()
    other.hits = Counter()  # type: ignore[attr-defined]
    other.RequestHandlerClass = type("OtherHandler", (BaseHTTPRequestHandler,), {
        "log_message": lambda self, *a: None,
        "do_GET": lambda self: (other.hits.update([self.path]),  # type: ignore[attr-defined]
                                FixtureHandler.do_GET(self)),
    })
    server.other_port = other.server_address[1]
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            check_fetch(checks, base, server.server_address[1], other)
            check_save(checks, base, Path(tmp))
    finally:
        for s in (server, other):
            s.shutdown()
            s.server_close()
    check_current_data(checks, show)

    if checks.failures:
        print(f"[image-fetch] FAIL — {len(checks.failures)} of {checks.count} "
              f"assertions failed")
        for failure in checks.failures:
            print(f"  - {failure}")
        return 1
    print(f"[image-fetch] pass — {checks.count} assertions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
