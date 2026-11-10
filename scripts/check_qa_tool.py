"""Offline gate: the local QA workbench refuses cross-site and rebinding writes.

scraper/qa_tool.py writes committed ledgers (spec overrides, blocked pairs,
review decisions, dismissals) from a page on 127.0.0.1. The 2026-11-10
security audit (E-2) showed any website could POST to it (text/plain CSRF)
and a DNS-rebinding page could read it (no Host check); F-3 showed a scraped
`javascript:` offer URL would become a clickable same-origin link.

This serves the REAL qa_tool.Handler on an ephemeral 127.0.0.1 port with
act / start_rebuild / build_cases replaced by recorders and _write disabled,
so no ledger is written and no normalize runs whatever arrives. Asserts:

- a foreign Host is refused on GET and POST (DNS rebinding);
- a POST that is cross-site, foreign-Origin, non-JSON, or missing / carrying a
  wrong X-QA-Token never reaches act() or start_rebuild();
- a same-origin JSON POST with the page's token does reach them;
- GET / embeds the token, a CSP whose nonce matches the inline script/style,
  nosniff and X-Frame-Options: DENY;
- the page renders an offer `href` only for http(s) URLs, with
  rel="noopener noreferrer" (evaluated with node when it is on PATH).

Run: python scripts/check_qa_tool.py   (exit 0 = pass, 1 = fail)
"""
from __future__ import annotations

import http.client
import json
import re
import shutil
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scraper import qa_tool  # noqa: E402

REACHED: list[str] = []


def _fake_act(body: dict) -> dict:
    REACHED.append(f"act:{body.get('action')}")
    return {"ok": True}


def _fake_rebuild() -> None:
    REACHED.append("rebuild")


def _no_write(path, data) -> None:
    raise RuntimeError(f"check_qa_tool: ledger write to {path} blocked")


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


def _request(port: int, method: str, path: str, headers: dict[str, str],
             body: bytes | None = None) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for name, value in headers.items():
            conn.putheader(name, value)
        if body is not None:
            conn.putheader("Content-Length", str(len(body)))
        conn.endheaders(body)
        resp = conn.getresponse()
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read()
    finally:
        conn.close()


def check_server(c: Checks, port: int) -> None:
    good = f"127.0.0.1:{port}"
    origin = f"http://{good}"
    token = qa_tool.TOKEN
    js = "application/json"
    body = json.dumps({"action": "dismiss", "id": "gate-case"}).encode("utf-8")

    def post(label: str, headers: dict[str, str], want: int, path: str = "/api/act",
             payload: bytes | None = body) -> None:
        before = len(REACHED)
        status, _h, reply = _request(port, "POST", path, headers, payload)
        c.eq(status, want, f"{label}: status")
        reached = REACHED[before:]
        if want == 200:
            c.ok(bool(reached), f"{label}: the stub is reached", repr(reply[:80]))
        else:
            c.eq(reached, [], f"{label}: nothing reached")

    # DNS rebinding: a foreign Host is refused before anything is served.
    for path in ("/", "/api/cases", "/api/status"):
        status, _h, _b = _request(port, "GET", path,
                                  {"Host": f"rebind.attacker.example:{port}"})
        c.eq(status, 403, f"GET {path} with a foreign Host is refused")
    post("foreign Host + valid token", {"Host": f"evil.example:{port}",
         "Content-Type": js, "X-QA-Token": token}, 403)
    post("Host on another port", {"Host": f"127.0.0.1:{port + 1}",
         "Content-Type": js, "X-QA-Token": token}, 403)

    # The audit PoC requests, verbatim (CSRF from a foreign page).
    post("PoC text/plain cross-site act", {
        "Host": good, "Origin": "https://evil.example",
        "Content-Type": "text/plain;charset=UTF-8", "Sec-Fetch-Site": "cross-site"}, 403)
    post("PoC cross-site rebuild", {"Host": good, "Origin": "https://evil.example",
         "Content-Type": "text/plain"}, 403, "/api/rebuild", b"")
    post("cross-site even with the token", {
        "Host": good, "Origin": "https://evil.example", "Content-Type": js,
        "Sec-Fetch-Site": "cross-site", "X-QA-Token": token}, 403)
    post("same-site sibling port", {
        "Host": good, "Origin": "http://127.0.0.1:18080", "Content-Type": js,
        "Sec-Fetch-Site": "same-site", "X-QA-Token": token}, 403)
    post("foreign Origin, no Sec-Fetch-Site", {
        "Host": good, "Origin": "http://localhost:18080", "Content-Type": js,
        "X-QA-Token": token}, 403)
    post("Origin null (sandboxed frame / file://)", {
        "Host": good, "Origin": "null", "Content-Type": js, "X-QA-Token": token}, 403)

    # Same origin but not JSON / no token.
    post("same-origin text/plain", {"Host": good, "Origin": origin,
         "Sec-Fetch-Site": "same-origin", "Content-Type": "text/plain",
         "X-QA-Token": token}, 415)
    post("same-origin, no Content-Type", {"Host": good, "Origin": origin,
         "X-QA-Token": token}, 415)
    post("same-origin JSON without the token", {"Host": good, "Origin": origin,
         "Sec-Fetch-Site": "same-origin", "Content-Type": js}, 403)
    post("same-origin JSON with a wrong token", {"Host": good, "Origin": origin,
         "Sec-Fetch-Site": "same-origin", "Content-Type": js,
         "X-QA-Token": token[:-1] + ("A" if token[-1] != "A" else "B")}, 403)
    post("rebuild without the token", {"Host": good, "Origin": origin,
         "Content-Type": js}, 403, "/api/rebuild", b"{}")

    # What the page itself sends.
    post("page POST (same-origin JSON + token)", {
        "Host": good, "Origin": origin, "Sec-Fetch-Site": "same-origin",
        "Content-Type": "application/json", "X-QA-Token": token}, 200)
    post("page POST via localhost", {
        "Host": f"localhost:{port}", "Origin": f"http://localhost:{port}",
        "Sec-Fetch-Site": "same-origin", "Content-Type": js, "X-QA-Token": token}, 200)
    post("non-browser client (no Origin / Sec-Fetch-Site) + token", {
        "Host": good, "Content-Type": "application/json; charset=utf-8",
        "X-QA-Token": token}, 200)
    post("page rebuild", {"Host": good, "Origin": origin, "Sec-Fetch-Site": "same-origin",
         "Content-Type": js, "X-QA-Token": token}, 200, "/api/rebuild", b"{}")
    c.ok("act:dismiss" in REACHED and "rebuild" in REACHED,
         "the accepted requests reached act() and start_rebuild()", repr(REACHED))

    status, headers, page_bytes = _request(port, "GET", "/", {"Host": good})
    page = page_bytes.decode("utf-8")
    c.eq(status, 200, "GET / with the bound Host is served")
    c.ok(token in page, "the page embeds this run's X-QA-Token")
    c.ok("__QA_TOKEN__" not in page and "__NONCE__" not in page,
         "no placeholder is left in the served page")
    csp = headers.get("content-security-policy", "")
    nonce = re.search(r"'nonce-([A-Za-z0-9_-]+)'", csp)
    c.ok(bool(nonce), "the page carries a nonce CSP", csp)
    if nonce:
        c.ok(f'<script nonce="{nonce.group(1)}">' in page,
             "the inline script carries the CSP nonce")
        c.ok(f'<style nonce="{nonce.group(1)}">' in page,
             "the inline style carries the CSP nonce")
    for directive in ("default-src 'none'", "connect-src 'self'", "base-uri 'none'",
                      "form-action 'none'", "frame-ancestors 'none'"):
        c.ok(directive in csp, f"CSP has {directive}", csp)
    c.ok("unsafe-inline" not in csp and "unsafe-eval" not in csp,
         "CSP allows no unsafe-inline / unsafe-eval", csp)
    c.eq(headers.get("x-content-type-options"), "nosniff", "nosniff is sent")
    c.eq(headers.get("x-frame-options"), "DENY", "X-Frame-Options: DENY is sent")
    c.ok("'x-qa-token':TOKEN" in page and "'content-type':'application/json'" in page,
         "the page's POST headers carry the token and JSON content-type")
    c.eq(page.count("headers:HDRS"), 2, "both POSTs (act + rebuild) send them")
    _status, again, _b = _request(port, "GET", "/", {"Host": good})
    c.ok(again.get("content-security-policy") != csp, "the CSP nonce is per response")

    status, _h, cases = _request(port, "GET", "/api/cases", {"Host": good})
    c.eq((status, json.loads(cases)), (200, [{"gate": True}]),
         "GET /api/cases with the bound Host is served (stubbed)")


def check_offer_links(c: Checks) -> None:
    page = qa_tool.PAGE
    c.eq(page.count('target="_blank"'), page.count('target="_blank" rel="noopener noreferrer"'),
         "every target=_blank link has rel=noopener noreferrer")
    c.eq(len(re.findall(r'href="\$\{', page)), 1,
         "offer hrefs are built in exactly one place (the guarded link helper)")
    node = shutil.which("node")
    if not node:
        print("  note: node not on PATH — offers() href guard checked statically only")
        c.ok(r"/^https?:\/\//i.test(" in page, "the link helper tests the URL scheme")
        return
    script = page.split("<script", 1)[1].split(">", 1)[1].rsplit("</script>", 1)[0]
    helpers = "\n".join(line for line in script.splitlines()
                        if line.startswith(("const esc=", "const link=")))
    offers = re.search(r"function offers\(c\)\{.*?\.join\(''\)\}", script, re.S)
    c.ok(bool(offers), "offers() is found in the page script")
    if not offers:
        return
    urls = ["javascript:fetch('/api/act')", " JavaScript:alert(1)", "data:text/html,x",
            "vbscript:x", "//evil.example/x", "/relative", "", None,
            "https://tms.co.il/p/1", "HTTP://1pc.co.il/x?a=1&b=\"2\""]
    program = (helpers + "\n" + offers.group(0) + "\n"
               + "const urls=" + json.dumps(urls) + ";\n"
               + "process.stdout.write(JSON.stringify(urls.map(u=>offers({offers:"
                 "[{vendor:'v',title:'t',key:'k',price:1,url:u}]}))));\n")
    proc = subprocess.run([node, "-e", program], capture_output=True, text=True,
                          encoding="utf-8", timeout=30)
    c.ok(proc.returncode == 0, "node evaluates offers()", proc.stderr[:200])
    if proc.returncode != 0:
        return
    rendered = json.loads(proc.stdout)
    for url, html in zip(urls, rendered):
        has_href = "href=" in html
        want = isinstance(url, str) and bool(re.match(r"https?://", url, re.I))
        c.eq(has_href, want, f"offers() href for {url!r}")
        if has_href:
            c.ok('rel="noopener noreferrer"' in html, f"offers() rel for {url!r}")
    c.ok('&quot;2&quot;' in rendered[-1] and '&amp;b=' in rendered[-1],
         "a kept href is HTML-escaped")


def main() -> int:
    qa_tool.act = _fake_act
    qa_tool.start_rebuild = _fake_rebuild
    qa_tool.build_cases = lambda: [{"gate": True}]
    qa_tool._write = _no_write
    checks = Checks()
    server = ThreadingHTTPServer(("127.0.0.1", 0), qa_tool.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        check_server(checks, server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
    check_offer_links(checks)

    if checks.failures:
        print(f"[qa-tool] FAIL — {len(checks.failures)} of {checks.count} "
              f"assertions failed")
        for failure in checks.failures:
            print(f"  - {failure}")
        return 1
    print(f"[qa-tool] pass — {checks.count} assertions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
