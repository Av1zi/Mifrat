# KSP component-stream transport

## Status

The owner-approved Nov 22, 01:00 UTC delayed recovery **ran and failed**:
robots and category warmup returned 200, the stream POST returned 403, and
no snapshot was written. The one-shot marker is consumed, KSP is paused and
the daily timers remain disabled. Do not reinstall the past-date timer or
delete attempt/block markers to retry it.

Owner-approved header update (2026-11-22): fixed Windows Chrome/158 UA and
aligned UA-hint versions, retaining the supported `chrome146` TLS profile.
UA-dependent cookie-free stream responses were observed on the owner's PC;
Nano acceptance and a complete crawl remain unverified. The header/TLS
version mismatch is deliberate and potentially fragile. This is one reviewed
configuration change, not automatic identity rotation. First
403/429/challenge still stops the run and persists the pause; no cookies,
dynamic `tt`, CAPTCHA, fallback or retry against rejection.

### Nov 26 browser diagnostics (consumed)

The CPU-category document returned HTTP 200, but the first capture ended
before any price response was recorded. An offline fixture confirmed the
capture could close before the browser received prices. In the owner-approved
follow-up, the category document again returned 200; a KSP subrequest
returned 403 before a price response was captured. The tab was closed at the
block. Both manual attempt markers remain consumed, `ksp.paused` stays in
place, and listing/detail timers remain disabled.

`scripts/ksp_price_shape.py --stdin` still works offline with a permitted
capture: only fixed public field names, types and counts leave it. Do not
export raw headers, HAR, request bodies, cookies, dynamic `tt`, response
strings or arbitrary JSON keys. An encoded JSON string remains an invalid
production price batch.

### KSP-approved price source

KSP's [affiliate program terms](https://ksp.co.il/affiliate/) (§4.8) mention
an API. Its public terms do not establish catalog coverage or authorize
Mifrat's recurring price comparisons. Ask [aff@ksp.co.il](mailto:aff@ksp.co.il)
whether they can approve that use and provide API or feed documentation and a
sample. Confirm PC-part category coverage, stable product IDs and links,
current regular ILS prices and stock, and any refresh or link requirements.
Use Eilat prices and availability only if the source supplies them separately.

### Non-API lead (Nov 27)

Search-indexed copies of KSP's [mobile CPU category](https://ksp.co.il/mob/cat/2)
show regular and Eilat prices in the visible cards. The structured `ItemList`
has ten initial products and regular prices; the page also shows a “show
more” control. This does not establish full HTML pagination, current stock
coverage, or permission to collect and republish those prices. KSP's
[site terms](https://ksp.co.il/mob/help/regulations) state that reuse of site
content requires KSP's approval. The evidence is from the search index.

## Evidence

Nov 22 PC diagnostics (not a published snapshot): cookie-free POSTs with
literal `tt=0` and the script's body returned 403 using the Windows Chrome/146
UA and 200 using Chrome/158, with the same `chrome146` TLS profile. Browser
headers with the script body also returned 200; script headers with the browser
body returned 403. These are UA-dependent responses, not proof of a deliberate
scraper blocklist or a separate Nano IP restriction being absent. Earlier
claims that TLS alone caused the block or that the Nano was definitively not
blocked were too strong. No more header/version probing is part of this fix.

Implementation validation on Nov 22: the updated **actual Scrapy runner**
received four HTTP200 responses (robots, warmup, category, current-price
batch), but stopped with zero rows because the price payload was not a map.
A fixed listing/price diagnostic confirmed a completed price component whose
unwrapped payload was a string. The parser correctly refuses it; embedded
listing prices are not a fallback. A later native headed-browser category
load also received a stream HTTP403, ending all live testing. Header access
is intermittent; this change is not a recovered scrape and must not be used
to enable timers. Further recovery requires the approved source above.

Observed through normal UI navigation in the owner's attached Chromium:

- CPU category: `/web/cat/31635..2..61615`, 45 products, 12 on the first page.
- Category request: POST `/m_action/sse/streams`, component
  `cat.categoryListing`, `categoryPath`, `sort`, `number=12`,
  `tags_size=30`, `withSuggestion=1`. Subsequent pages use `page`.
- Price request: same stream endpoint, component `item.bms`, comma-separated
  `uins` from that category page.
- SSE events: `partial` with `requestId`, `key`, `ok`, `data`; terminal
  `done` with `status=completed`.
- Product data lives inside `result`/`data` envelopes. `uin` is the product
  link/identity, while `uinsql` is a different displayed retailer SKU.
- The public storefront source uses `tt=0` as its default but category
  browser requests can carry dynamic `tt`. **No dynamic value, persistent
  header, session cookie, clearance or challenge data was copied.**

`scraper/fixtures/ksp/cpu_stream.json` retains only the 12 captured product
records, their price records and request/response protocol fields. It is a
fixture, **not a complete snapshot and never publishable as one**.

## Implementation

- `scraper/ksp_stream.py`: strict SSE parser. Requires every requested
  component and successful completion; matches both request id and key.
  Rejects malformed/oversized/truncated input, failed components, duplicate
  responses, missing prices and identity mismatches. Supports UTF-8,
  multiline data, CRLF and comment heartbeats. Errors never echo the body.
- `scraper/spiders/ksp_stream.py`: delayed-recovery adapter. Reuses
  the existing KSP product mapper and all category/total coverage checks.
  Resolves every page's current-price batch before accepting that page.
  Requests are sequential, the fixed profile/pacing stays unchanged, and
  there is no legacy/new transport fallback or retry against any block.
  HTTP-200 component-level 403/429 also pauses KSP.
- Constructor fails closed before the scheduled date unless fixture tests
  explicitly approve it. All 13 routes are captured from KSP's own filter
  `action` values and stored in `scraper/ksp_category_routes.json`. Even
  fixture approval cannot bypass `ksp.paused`. Cookies are disabled; context uses the literal public
  default `tt=0`. This default has **not** been verified on the Nano.

## Verification

```text
python scripts/check_ksp_stream.py
python scripts/check_ksp_stream_spider.py
python scripts/check_scrape_outcomes.py
```

Tests use the saved response and an in-memory Scrapy downloader. They make
no vendor requests. They cover the actual mapper/completeness path, next-page
requests, current prices, regular/Eilat separation, blocked components,
missing batches, route validation and the pause guard.

The integration check also pins the approved UA/hint versions on actual
robots, warmup, listing and price requests, and verifies the fixed TLS profile.
This catches configuration regressions; it cannot predict vendor acceptance.

The parser and diagnostic checks include a real
offline sanitizer CLI, bounded shape traversal, secret-bearing keys/values,
encoded JSON rejection, and component blocks. Integration includes a real
Scrapy engine with an in-memory downloader and the normal enrichment/matching
path. A component-level rejection inside an HTTP-200 stream is still a block,
not a partial crawl. The response never leaks into an exception message.

## Timer installation and safety

Historical Nov 18 installation (already consumed on Nov 22; **do not rerun
this to recover from the failed attempt**):

```bash
bash nano/install_ksp_recovery.sh
```

This runs offline checks, writes the pause, keeps listing/detail daily timers
disabled, installs only the relevant KSP units, and arms the one-shot timer.
It does not crawl. `pc-parts-il-ksp-resume.timer` runs Nov 22, 01:00–01:30 UTC
(03:00–03:30 Israel). No persistent daytime catch-up.

At that time, the resume wrapper consumes a one-shot marker and clears the
known pause once. It holds the shared checkout lock. A failed run re-pauses
KSP; a second resume invocation cannot repeatedly unblock it. Only a
successful full run enables the ordinary daily listing timer. Detail remains
disabled. The old Eilat API is not called: current Eilat prices and explicit
availability arrive in the same price response as the regular price and are
attached to offers by `scraper/eilat.py`. No second Eilat crawl is required.
Unknown/null fields do not claim that a product is not sold in Eilat; old
snapshots remain readable, and stale observations stay stale. Neither Eilat
prices nor their availability alter regular minima or price history.

`python scraper/run_spider.py ksp` uses the stream spider after the date,
keeping the original `data/raw/<night>/ksp.jsonl` atomic publish path and
the original completeness gates. It starts with a public category-page
warmup and obeys robots. No dynamic tt or browser cookies are carried over.

The site's small bilingual notice remains until a successful KSP snapshot
after the scheduled date is published; it doesn't vanish at a deadline if
the attempt fails. Other vendors continue normally.

The latest successful snapshot is Nov 16. Until there is a complete fresh
snapshot, the catalog applies the normal 14-day stale-forward window.
