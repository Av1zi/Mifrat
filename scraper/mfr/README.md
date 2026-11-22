# Manufacturer specs — tier 0.5

Fetch manufacturer product pages into `data/mfr/<brand>.json`; normalize reads
those typed facts above vendor structure and below verified reference/overrides.
The [preserved feasibility and parser evidence](../../docs/archive/2026-11-22/mfr-README.md)
contains dated per-brand measurements, not fresh access permission.

```bash
python -m scraper.mfr --list
python -m scraper.mfr corsair --dry-run # match only, no fetch
python -m scraper.mfr corsair --offline # re-parse existing cache, no network
python -m scraper.mfr corsair           # live fetch, source rules apply
python scripts/fill_report.py
```

## Binding source rules

The [root scraping rules](../../README.md#scraping-rules) also apply:

- Home/local execution, not cloud runners; one request/s per host, browser
  headers, no proxies, retries against blocks or evasion.
- Obey robots. First 403/429 ends the brand's run; an actively blocked brand
  is dropped, not a reason to try another identity.
- Approved narrow robots exceptions only: Fractal `/products/` (Oct 22 owner
  decision, removable on request; `/api/` stays untouched), LDLC `/en/search/`
  and Overclockers `/search` for exact-part-number xref discovery. All three
  live in shared `mfr/client.py:ROBOTS_OVERRIDES`; none grants an override for
  other paths or sources. The identified xref client does not rotate identity
  to overcome a block.
- Normally fetch pages matched to catalog products. Some approved brand
  importers discover/fetch in-scope pages to read exact identifiers; inspect
  that brand's `index()` before assuming `--dry-run` bounds the live request
  count. HTML stays in ignored `.cache/`; only extracted JSON is published.
- Join on identifiers the page states, or a unique supported name/slug match.
  Ambiguous matches are refused; wrong manufacturer facts outrank good vendor
  facts. Values pass `common.typed()` coercion, canon and validation.

## Brand status and exceptions

Use `--list` / `__init__.BRANDS` for installed importers. The historical source
reviews found these access or coverage constraints:

- Gigabyte, MSI and Intel ARK: 403/WAF stop signals. Cougar: connection
  rejection treated as a block. Noctua: performance data requires a
  robots-disallowed `/api/`; not fetched.
- ASUS importer covers supported motherboard pages, not every ROG board or
  GPU order-code page. Cooler Master PSU series pages and Seasonic multi-wattage
  pages were declined to avoid joining one SKU to another's specs.
- Corsair, Antec, Cooler Master, Lian Li, be quiet!, AMD, NZXT, Thermalright,
  Fractal and SilverStone have implemented importers with category-specific
  limits. The archive records how exact identifiers and variant blocks were
  verified. These dated verdicts do not prove today's network acceptance.
- LDLC xref was available from the Nano, not the cloud; run via
  `nano/run_xref.sh`. Supermicro was investigated but not implemented.

## Parser and schema safety

Split family pages into model/variant blocks before joining. Do not infer
missing fan counts, combine ambiguous drive-bay positions, or read pump RPM
as fan RPM. Full connector lists can establish explicit zero counts; unknown
placeholders do not. Explicit negatives use "No", never "None".

A schema version change requires `scripts/migrate_mfr_schema.py`; the store
skips mismatched versions, and raw cache is not committed. Field/schema work
belongs in [the spec guide](../specs/README.md).

## Adding a brand

1. With permitted access, establish robots policy, page feasibility and safe
   identifier joins. Stop on rejection; historical success is not permission
   to retry a current block.
2. Implement `<brand>.py` (`BRAND`, `BASE_URL`, `CATEGORIES`, `index`, `match`,
   `parse`) and register it in `__init__.BRANDS`.
3. Preview with `--dry-run`; pin parser/variant behaviour with offline fixtures
   before a bounded live run. Measure against existing sourced facts.
4. Record source restrictions/evidence here or in a dated report and add a
   short local decision entry. Publish only authorized output paths.
