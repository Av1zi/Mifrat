"""Local browser review tool for fuzzy product-match candidates.

Run from the repository root:
    python -m scraper.review_queue

Then open http://127.0.0.1:8765. Decisions are saved to
data/matching/review_decisions.json and are deliberately separate from the
automatic matcher until they are promoted to manual_products.json.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
QUEUE_PATH = ROOT / "data" / "review_queue.json"
DECISIONS_PATH = ROOT / "data" / "matching" / "review_decisions.json"
PORT = 8765


def load_data() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    decisions = (
        json.loads(DECISIONS_PATH.read_text(encoding="utf-8"))
        if DECISIONS_PATH.exists()
        else {}
    )
    return queue, decisions


def listing_index() -> dict[str, dict[str, Any]]:
    catalog = json.loads((ROOT / "data" / "catalog.json").read_text(encoding="utf-8"))
    return {
        item["listing_key"]: item
        for item in catalog.get("listings", [])
        if item.get("listing_key")
    }


def render_page() -> bytes:
    queue, decisions = load_data()
    listings = listing_index()
    rows = []
    for index, item in enumerate(queue):
        decision = decisions.get(str(index), {}).get("decision")
        a = listings.get(str(item.get("listing_a") or ""), {})
        b = listings.get(str(item.get("listing_b") or ""), {})
        rows.append(
            f"""<article class="card" data-index="{index}">
<div><b>#{index}</b> {item.get("category","")} · score {item.get("score","")}</div>
<p><a target="_blank" href="{a.get("url","")}">{a.get("title_raw", item.get("title_a",""))}</a></p>
<p><a target="_blank" href="{b.get("url","")}">{b.get("title_raw", item.get("title_b",""))}</a></p>
<button onclick="decide({index},'match')">Match</button>
<button onclick="decide({index},'not_match')">Not a match</button>
<span class="decision">{decision or ""}</span>
</article>"""
        )
    html = """<!doctype html><meta charset="utf-8"><title>Mifrat review queue</title>
<style>body{font:16px system-ui;max-width:1000px;margin:2rem auto;background:#111;color:#eee}
.card{border:1px solid #555;padding:1rem;margin:1rem 0}.card a{color:#8cf}
button{margin-right:.5rem;padding:.4rem .8rem}.decision{margin-left:1rem;color:#8f8}</style>
<h1>Review queue</h1><p>Open both product links, then record the decision.</p>
""" + "".join(rows) + """<script>
async function decide(index,decision){let r=await fetch('/decision?index='+index+'&decision='+decision,{method:'POST'});
if(r.ok){location.reload()}else{alert(await r.text())}}
</script>"""
    return html.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/":
            self.send_error(404)
            return
        body = render_page()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        query = parse_qs(urlparse(self.path).query)
        index = query.get("index", [None])[0]
        decision = query.get("decision", [None])[0]
        if index is None or decision not in {"match", "not_match"}:
            self.send_error(400, "invalid decision")
            return
        queue, decisions = load_data()
        if not index.isdigit() or int(index) >= len(queue):
            self.send_error(400, "invalid queue index")
            return
        decisions[index] = {"decision": decision, "listing_a": queue[int(index)]["listing_a"], "listing_b": queue[int(index)]["listing_b"]}
        DECISIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        DECISIONS_PATH.write_text(json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8")
        self.send_response(204)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        return


if __name__ == "__main__":
    print(f"Review queue: http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
