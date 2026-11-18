# KSP component-stream transport

## Status

Owner-approved delayed recovery: **no live traffic before Nov 22, 01:00 UTC**,
the first night slot after 72 hours from the Nov 18 request. KSP's Nano
catalog requests returned 403 on Nov 18. The new transport is implemented
and tested offline; acceptance without browser state remains unverified.
The first scheduled run is a normal, bounded attempt, not a guarantee of
access. First 403/429/challenge stops it and restores the pause; no variants,
cookie transfer, CAPTCHA or retries against rejection.

## Evidence

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
- `scraper/spiders/ksp_stream.py`: unscheduled experimental adapter. Reuses
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

The parser currently passes 40 assertions. Integration includes a real
Scrapy engine with an in-memory downloader and the normal enrichment/matching
path. A component-level rejection inside an HTTP-200 stream is still a block,
not a partial crawl. The response never leaks into an exception message.

## Timer installation and safety

After pulling the release on the Nano, as the normal user:

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
disabled. The old Eilat API is not called: current Eilat prices are captured
as listing metadata, while attaching them to Eilat mode is deferred.

`python scraper/run_spider.py ksp` uses the stream spider after the date,
keeping the original `data/raw/<night>/ksp.jsonl` atomic publish path and
the original completeness gates. It starts with a public category-page
warmup and obeys robots. No dynamic tt or browser cookies are carried over.

The site's small bilingual notice remains until a successful KSP snapshot
after the scheduled date is published; it doesn't vanish at a deadline if
the attempt fails. Other vendors continue normally.

Still unverified: cookie-free endpoint acceptance and a complete live crawl.
If the transport requires challenge/clearance state, do not emulate it;
pursue KSP's sanctioned affiliate/product feed instead.

No claim is made that changing transport alone resolves the observed 403.
