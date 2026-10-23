#!/usr/bin/env python
"""
probe_sources.py - can this machine reach a candidate spec source, and may it?

For each host: robots.txt (status + whether `*` may fetch the sample path) and
one sample product page (status + size). Run it from the cloud runner AND from
the Nano: several brands (Gigabyte, MSI) answer 403 to datacenter addresses,
and a source that answers from the home IP runs there, exactly like TMS.

    python scripts/probe_sources.py              # every candidate
    python scripts/probe_sources.py gigabyte msi # a few
    python scripts/probe_sources.py --json out.json

A 403 / 429 / challenge page is a stop signal, never something to work around:
the verdict column says "blocked" and that source is not built from that
machine. robots.txt disallow is reported; overriding it is an explicit,
per-host owner decision recorded in scraper/mfr/README.md, never automatic.
One request per host per kind, 1 s apart.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# name -> (base URL, a real product page path)
CANDIDATES = {
    "gigabyte": ("https://www.gigabyte.com", "/Graphics-Card/GV-N5070WF3OC-12GD"),
    "msi": ("https://www.msi.com", "/Motherboard/MAG-B850-TOMAHAWK-MAX-WIFI/Specification"),
    "asrock": ("https://www.asrock.com", "/mb/AMD/B850%20Pro%20RS/index.asp"),
    "noctua": ("https://www.noctua.at", "/en/products/nh-u12a"),
    "fractal": ("https://www.fractal-design.com", "/products/cases/north/north/"),
    "kingston": ("https://www.kingston.com", "/en/memory/gaming/kingston-fury-beast-ddr5-memory"),
    "westerndigital": ("https://www.westerndigital.com", "/products/internal-drives/wd-black-sn850x-nvme-ssd"),
    "seagate": ("https://www.seagate.com", "/products/hard-drives/barracuda-hard-drive/"),
    "samsung": ("https://semiconductor.samsung.com", "/consumer-storage/internal-ssd/990-pro/"),
    "gskill": ("https://www.gskill.com", "/product/165/390/1665020865/F5-6000J3038F16GX2-TZ5RK"),
    "seasonic": ("https://seasonic.com", "/focus-gx/"),
    "arctic": ("https://www.arctic.de", "/en/Liquid-Freezer-III-Pro-360/ACFRE00180A"),
    "silverstone": ("https://www.silverstonetek.com", "/en/product/info/power-supplies/HELA1200R/"),
    "supermicro": ("https://www.supermicro.com", "/en/products/motherboard/x13sae-f"),
    "icecat": ("https://live.icecat.biz", "/api?UserName=openIcecat-live&Language=en&Brand=Samsung&ProductCode=MZ-V9P1T0BW"),
    "bug": ("https://www.bug.co.il", "/"),
    "overclockers": ("https://www.overclockers.co.uk", "/"),
    "alternate": ("https://www.alternate.de", "/"),
    "ldlc": ("https://www.ldlc.com", "/en/"),
    "canadacomputers": ("https://www.canadacomputers.com", "/"),
    "mwave": ("https://www.mwave.com.au", "/"),
    "newegg": ("https://www.newegg.com", "/"),
    "techpowerup": ("https://www.techpowerup.com", "/"),
}

# Hosts whose terms forbid automated use whatever robots says: probed for the
# record, never built.
TERMS_FORBID = {"techpowerup"}


def fetch(url, timeout=20.0):
    request = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(3_000_000)
            return response.status, len(body), body[:4000].decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        body = error.read(4000) if error.fp else b""
        return error.code, len(body), body.decode("utf-8", "replace")
    except Exception as error:  # noqa: BLE001 - a probe reports, never raises
        return 0, 0, f"{type(error).__name__}: {error}"


_CHALLENGE = ("cf-chl", "challenge-platform", "Attention Required", "Access Denied",
              "captcha", "_Incapsula_", "perimeterx", "akamai")


def probe(name):
    base, path = CANDIDATES[name]
    robots_status, _, robots_body = fetch(base + "/robots.txt")
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(robots_body.splitlines() if robots_status == 200 else [])
    allowed = parser.can_fetch("*", base + path)
    time.sleep(1)
    status, size, head = fetch(base + path)
    challenge = any(marker.lower() in head.lower() for marker in _CHALLENGE)
    if name in TERMS_FORBID:
        verdict = "excluded (terms forbid scraping)"
    elif status in (403, 429) or challenge or status == 0:
        verdict = "blocked from here"
    elif not allowed:
        verdict = "reachable, robots.txt disallows (owner override needed)"
    elif 200 <= status < 300:
        verdict = "ok"
    else:
        verdict = f"HTTP {status}"
    return {"name": name, "robots": robots_status, "robots_allows": allowed,
            "status": status, "bytes": size, "challenge": challenge, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="*", help=f"subset of: {', '.join(CANDIDATES)}")
    ap.add_argument("--json", help="write results as JSON")
    args = ap.parse_args()
    names = args.names or list(CANDIDATES)
    unknown = [n for n in names if n not in CANDIDATES]
    if unknown:
        print(f"unknown: {', '.join(unknown)}")
        return 2
    rows = []
    print(f"{'source':<16}{'robots':>7}{'allows':>8}{'page':>6}{'bytes':>9}  verdict")
    for name in names:
        row = probe(name)
        rows.append(row)
        print(f"{name:<16}{row['robots']:>7}{str(row['robots_allows']):>8}{row['status']:>6}"
              f"{row['bytes']:>9}  {row['verdict']}")
        time.sleep(1)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(rows, handle, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
