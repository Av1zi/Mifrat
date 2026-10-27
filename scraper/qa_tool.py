"""Local QA workbench: see every data problem and fix it from one page.

Run from the repository root:
    python -m scraper.qa_tool        # then open http://127.0.0.1:8766

Cases come from data/site/qa.json (spec conflicts, core gaps, naming
conflicts, duplicate-vendor listings) and data/review_queue.json (fuzzy
"same product?" pairs). Fixes are written straight to the committed ledgers:

- spec value            -> data/specs/overrides.json (tier -1, always wins)
- different products    -> data/matching/manual_products.json blocked_pairs
- same product (fuzzy)  -> data/matching/review_decisions.json, then promoted
                           into manual_products.json (scraper.promote_decisions)
- "looks fine"          -> data/matching/qa_dismissed.json

Nothing changes on the site until the pipeline is rebuilt (button on the
page runs scraper/normalize_and_match.py).
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import combinations
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CATALOG = ROOT / "data" / "catalog.json"
QA = ROOT / "data" / "site" / "qa.json"
QUEUE = ROOT / "data" / "review_queue.json"
OVERRIDES = ROOT / "data" / "specs" / "overrides.json"
MANUAL = ROOT / "data" / "matching" / "manual_products.json"
DECISIONS = ROOT / "data" / "matching" / "review_decisions.json"
DISMISSED = ROOT / "data" / "matching" / "qa_dismissed.json"
PORT = 8766

_lock = threading.Lock()
_rebuild = {"running": False, "log": ""}


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def _offer(o: dict) -> dict:
    return {
        "key": o.get("listing_key"), "vendor": o.get("vendor_id"),
        "title": o.get("title_raw"), "price": o.get("price_ils"),
        "url": o.get("url"), "sku": o.get("vendor_sku"),
        "stock": o.get("in_stock"),
    }


def build_cases() -> list[dict]:
    catalog = _read(CATALOG, {})
    products = {p["product_id"]: p for p in catalog.get("products", [])}
    listings = {l["listing_key"]: l for l in catalog.get("listings", [])
                if l.get("listing_key")}
    overrides = _read(OVERRIDES, {}).get("products", {})
    manual = _read(MANUAL, {})
    blocked = {frozenset(p) for p in manual.get("blocked_pairs", [])}
    decisions = _read(DECISIONS, {})
    dismissed = _read(DISMISSED, {})
    cases: list[dict] = []

    for c in _read(QA, {}).get("cases", []):
        pid = c.get("product_id")
        product = products.get(pid, {})
        kind = c["kind"]
        extra = c.get("field") or c.get("vendor") or ""
        cid = f"{kind}|{pid}|{extra}"
        offers = [_offer(o) for o in product.get("offers", [])]
        case = {
            "id": cid, "kind": kind, "category": c.get("category"),
            "product_id": pid, "name": product.get("canonical_name") or pid,
            "offers": offers, "state": "open", "specs": product.get("specs") or {},
        }
        if kind == "spec_conflict":
            case.update(field=c["field"], kept=c.get("kept"), dropped=c.get("dropped"))
            if c["field"] in (overrides.get(pid) or {}):
                case["state"], case["fixed_value"] = "fixed", overrides[pid][c["field"]]
        elif kind == "core_gap":
            fields = c.get("fields") or []
            case["fields"] = fields
            if fields and all(f in (overrides.get(pid) or {}) for f in fields):
                case["state"] = "fixed"
        elif kind in ("naming_conflict", "duplicate_vendor"):
            case["vendor"] = c.get("vendor")
            keys = [o["key"] for o in offers if o["key"]]
            if kind == "duplicate_vendor":
                keys = [o["key"] for o in offers
                        if o["key"] and o["vendor"] == c.get("vendor")]
            pairs = [frozenset(p) for p in combinations(keys, 2)]
            if pairs and all(p in blocked for p in pairs):
                case["state"] = "fixed"
        if dismissed.get(cid):
            case["state"] = "dismissed"
        cases.append(case)

    queue = _read(QUEUE, [])
    # Decisions are matched by listing pair, not queue index: the queue is
    # regenerated on every rebuild and its indexes shift.
    by_pair = {frozenset((d.get("listing_a"), d.get("listing_b"))): d.get("decision")
               for d in decisions.values()}
    for i, item in enumerate(queue):
        a = listings.get(item.get("listing_a"), {})
        b = listings.get(item.get("listing_b"), {})
        decision = by_pair.get(frozenset((item.get("listing_a"), item.get("listing_b"))))
        cid = f"fuzzy|{i}|"
        state = {"match": "fixed", "not_match": "fixed"}.get(str(decision or ""), "open")
        if dismissed.get(cid):
            state = "dismissed"
        cases.append({
            "id": cid, "kind": "fuzzy", "category": item.get("category"),
            "name": f"score {item.get('score')}", "state": state,
            "decision": decision, "index": i,
            "offers": [_offer(a) | {"key": item.get("listing_a"),
                                    "title": a.get("title_raw") or item.get("title_a")},
                       _offer(b) | {"key": item.get("listing_b"),
                                    "title": b.get("title_raw") or item.get("title_b")}],
        })
    return cases


def _coerce_value(category: str, field: str, raw: Any) -> Any:
    """Validate through the same coercion the spec merge uses."""
    from scraper.specs import schema
    from scraper.specs.values import InvalidValue, coerce
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            pass
    spec = schema.field_for_key(category, field) or schema.field_map(category).get(field)
    if spec is None:
        raise ValueError(f"unknown field '{field}' for {category}")
    try:
        coerce(spec, raw, category)
    except InvalidValue as exc:
        raise ValueError(f"invalid value for {field}: {exc}") from exc
    return raw


def act(body: dict) -> dict:
    kind = body.get("action")
    cid = body.get("id", "")
    with _lock:
        if kind == "set":
            pid, field = body["product_id"], body["field"]
            value = _coerce_value(body.get("category", ""), field, body.get("value"))
            data = _read(OVERRIDES, {"products": {}})
            data.setdefault("products", {}).setdefault(pid, {})[field] = value
            _write(OVERRIDES, data)
        elif kind == "clear":
            data = _read(OVERRIDES, {"products": {}})
            (data.get("products", {}).get(body["product_id"]) or {}).pop(body["field"], None)
            _write(OVERRIDES, data)
        elif kind == "split":
            keys = [k for k in body.get("keys", []) if k]
            manual = _read(MANUAL, {"products": [], "blocked_pairs": []})
            have = {frozenset(p) for p in manual.setdefault("blocked_pairs", [])}
            for a, b in combinations(keys, 2):
                if frozenset((a, b)) not in have:
                    manual["blocked_pairs"].append(sorted((a, b)))
            _write(MANUAL, manual)
        elif kind in ("match", "not_match"):
            queue = _read(QUEUE, [])
            idx = int(body["index"])
            decisions = _read(DECISIONS, {})
            decisions[str(idx)] = {"decision": kind,
                                   "listing_a": queue[idx]["listing_a"],
                                   "listing_b": queue[idx]["listing_b"]}
            _write(DECISIONS, decisions)
            subprocess.run([sys.executable, "-m", "scraper.promote_decisions"],
                           cwd=ROOT, capture_output=True, check=False)
        elif kind == "dismiss":
            data = _read(DISMISSED, {})
            data[cid] = True
            _write(DISMISSED, data)
        elif kind == "undismiss":
            data = _read(DISMISSED, {})
            data.pop(cid, None)
            _write(DISMISSED, data)
        else:
            raise ValueError("unknown action")
    return {"ok": True}


def start_rebuild() -> None:
    if _rebuild["running"]:
        return

    def run() -> None:
        _rebuild.update(running=True, log="running normalize_and_match…")
        proc = subprocess.run(
            [sys.executable, "scraper/normalize_and_match.py"], cwd=ROOT,
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-6:]
        _rebuild.update(running=False,
                        log=("done" if proc.returncode == 0 else "FAILED") +
                        "\n" + "\n".join(tail))

    threading.Thread(target=run, daemon=True).start()


PAGE = r"""<!doctype html><meta charset="utf-8"><title>Mifrat QA</title>
<style>
body{font:14px system-ui;margin:0;background:#15161a;color:#e6e6e6}
header{position:sticky;top:0;background:#1d1f25;padding:8px 14px;border-bottom:1px solid #333;z-index:5;display:flex;gap:10px;flex-wrap:wrap;align-items:center}
select,input,button{background:#262932;color:#e6e6e6;border:1px solid #444;border-radius:4px;padding:4px 8px;font:inherit}
button{cursor:pointer}button:hover{background:#343845}
button.go{background:#1f5f3a;border-color:#2f8f58}button.no{background:#6a2b2b;border-color:#944}
main{padding:10px 14px;max-width:1250px}
.card{border:1px solid #333;border-radius:6px;margin:8px 0;padding:8px 10px;background:#1b1d23}
.card.fixed{opacity:.45}.card.dismissed{opacity:.3}
.top{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.tag{font-size:11px;padding:1px 6px;border-radius:9px;background:#333}
.k-spec_conflict{background:#4a3b12}.k-core_gap{background:#4a1f3a}.k-naming_conflict{background:#123a4a}
.k-duplicate_vendor{background:#2f2f4a}.k-fuzzy{background:#1f4a2b}
.off{display:grid;grid-template-columns:70px 1fr 80px;gap:6px;padding:2px 0;font-size:13px}
.off a{color:#8cf;text-decoration:none}.dim{color:#999}
.acts{margin-top:6px;display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.val{font-family:ui-monospace,monospace;background:#101216;padding:1px 5px;border-radius:3px}
#msg{color:#fb7;margin-left:8px}
</style>
<header>
<select id="kind"><option value="">all kinds</option></select>
<select id="cat"><option value="">all categories</option></select>
<select id="field"><option value="">all fields</option></select>
<select id="state"><option value="open">open</option><option value="fixed">fixed</option><option value="dismissed">dismissed</option><option value="">all</option></select>
<input id="q" placeholder="search name / title / id" size="28">
<span id="count"></span>
<button id="rebuild" title="runs normalize_and_match.py (~3 min)">Rebuild data</button><span id="rb" class="dim"></span>
<span id="msg"></span>
</header>
<main id="list"></main>
<script>
let cases=[];const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const show=v=>typeof v==='string'?v:JSON.stringify(v);
async function post(body){const r=await fetch('/api/act',{method:'POST',body:JSON.stringify(body)});
 const j=await r.json().catch(()=>({error:'bad response'}));
 if(!r.ok){$('msg').textContent=j.error||'error';return false}$('msg').textContent='';return true}
async function load(){cases=await (await fetch('/api/cases')).json();fill();render()}
function fill(){for(const [id,key] of [['kind','kind'],['cat','category'],['field','field']]){
 const sel=$(id),cur=sel.value,vals=[...new Set(cases.map(c=>c[key]).filter(Boolean))].sort();
 sel.innerHTML='<option value="">all '+id+'</option>'+vals.map(v=>`<option ${v===cur?'selected':''}>${esc(v)}</option>`).join('')}}
function offers(c){return c.offers.map(o=>`<div class="off"><span class="dim">${esc(o.vendor||'')}</span>
 <a href="${esc(o.url||'#')}" target="_blank">${esc(o.title||o.key)}</a><span>${o.price??''}₪</span></div>`).join('')}
function acts(c){
 const d=(l,a,cls='')=>`<button class="${cls}" data-a="${a}" data-id="${esc(c.id)}">${l}</button>`;
 let h='';
 if(c.kind==='spec_conflict'){
  h+=`kept <span class="val">${esc(show(c.kept))}</span> · dropped <span class="val">${esc(show(c.dropped))}</span><br>`;
  h+=`<div class="acts"><button class="go" data-a="set" data-id="${esc(c.id)}" data-v="kept">Use kept</button>
   <button class="go" data-a="set" data-id="${esc(c.id)}" data-v="dropped">Use dropped</button>
   <input data-in="${esc(c.id)}" placeholder="other value (JSON ok)"><button data-a="setin" data-id="${esc(c.id)}">Set</button>`;
 }else if(c.kind==='core_gap'){
  h+=`missing: <b>${esc(c.fields.join(', '))}</b><div class="acts">`;
  for(const f of c.fields)h+=`<input data-in="${esc(c.id)}|${esc(f)}" placeholder="${esc(f)} value (JSON ok)">`;
  h+=`<button class="go" data-a="setgap" data-id="${esc(c.id)}">Set</button>`;
 }else if(c.kind==='fuzzy'){
  h+=`<div class="acts">${d('Same product','match','go')}${d('Different','not_match','no')}`;
 }else{
  h+=`<div class="acts">${d('Different products (block pairs)','split','no')}`;
 }
 if(c.state==='fixed'&&c.kind==='spec_conflict')h+=` ${d('Undo override','clear')} <span class="dim">now ${esc(show(c.fixed_value))}</span>`;
 h+=c.state==='dismissed'?d('Reopen','undismiss'):d('Looks fine','dismiss');
 return h+'</div>'}
function render(){const k=$('kind').value,cat=$('cat').value,f=$('field').value,st=$('state').value,q=$('q').value.toLowerCase();
 const rows=cases.filter(c=>(!k||c.kind===k)&&(!cat||c.category===cat)&&(!f||c.field===f||(c.fields||[]).includes(f))&&(!st||c.state===st)
  &&(!q||(c.name+c.product_id+c.offers.map(o=>o.title).join(' ')).toLowerCase().includes(q)));
 $('count').textContent=rows.length+' / '+cases.length;
 $('list').innerHTML=rows.slice(0,150).map(c=>`<div class="card ${c.state}">
  <div class="top"><span class="tag k-${c.kind}">${c.kind}${c.field?': '+esc(c.field):''}</span><b>${esc(c.name)}</b>
  <span class="dim">${esc(c.category||'')} ${c.kind==='fuzzy'?'':esc(c.product_id||'')}</span></div>${offers(c)}${acts(c)}</div>`).join('')
  +(rows.length>150?'<p class="dim">showing first 150 – filter to narrow</p>':'')}
document.addEventListener('click',async e=>{const b=e.target.closest('button[data-a]');if(!b)return;
 const c=cases.find(x=>x.id===b.dataset.id);const a=b.dataset.a;let body={action:a,id:c.id,category:c.category,product_id:c.product_id};
 const inp=n=>document.querySelector(`[data-in="${CSS.escape(n)}"]`);
 if(a==='set'){body.field=c.field;body.value=b.dataset.v==='kept'?c.kept:c.dropped}
 else if(a==='setin'){const v=inp(c.id).value;if(!v)return;body.action='set';body.field=c.field;body.value=v}
 else if(a==='setgap'){for(const f of c.fields){const v=inp(c.id+'|'+f).value;if(v){if(!await post({...body,action:'set',field:f,value:v}))return}}await load();return}
 else if(a==='clear'){body.field=c.field}
 else if(a==='match'||a==='not_match'){body.index=c.index}
 else if(a==='split'){body.keys=c.kind==='duplicate_vendor'?c.offers.filter(o=>o.vendor===c.vendor).map(o=>o.key):c.offers.map(o=>o.key)}
 if(await post(body))await load()});
for(const id of['kind','cat','field','state'])$(id).onchange=render;$('q').oninput=render;
$('rebuild').onclick=async()=>{await fetch('/api/rebuild',{method:'POST'});poll()};
async function poll(){const s=await (await fetch('/api/status')).json();$('rb').textContent=s.running?'rebuilding…':s.log.split('\n')[0];
 if(s.running)setTimeout(poll,3000);else if(s.log.startsWith('done'))load()}
load();poll();
</script>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/":
            self._send(200, PAGE.encode("utf-8"), "text/html")
        elif self.path == "/api/cases":
            self._send(200, json.dumps(build_cases(), ensure_ascii=False).encode("utf-8"))
        elif self.path == "/api/status":
            self._send(200, json.dumps(_rebuild).encode("utf-8"))
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        try:
            if self.path == "/api/rebuild":
                start_rebuild()
                self._send(200, b'{"ok":true}')
                return
            body = json.loads(self.rfile.read(length) or b"{}")
            self._send(200, json.dumps(act(body)).encode("utf-8"))
        except Exception as exc:  # shown in the page header
            self._send(400, json.dumps({"error": str(exc)}).encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        return


if __name__ == "__main__":
    print(f"QA workbench: http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
