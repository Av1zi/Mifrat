# Mifrat

Price comparison for PC parts sold in Israel: vendor listings are collected daily and merged into one catalog of products, each with offers from one or more vendors.

## Sources

**Vendor**:
An Israeli shop whose catalog is scraped (TMS, 1PC, KSP, Ivory, YahavPC).
_Avoid_: store, retailer, site

**Home vendor**:
A vendor scraped only from the home connection, because it blocks datacenter addresses (TMS, 1PC, KSP).
_Avoid_: Nano vendor, local vendor

**Cloud vendor**:
A vendor scraped from hosted automation (Ivory, YahavPC).

**Manufacturer**:
The company that makes a part; its own product pages are a spec source, never a price source.
_Avoid_: brand site, maker (in prose about sources)

**Snapshot**:
Everything one vendor showed on one day, kept as one raw file.
_Avoid_: dump, scrape

## Catalog

**Listing**:
One row a vendor showed on a given day, with title, price, availability, address and image as seen.
_Avoid_: item, row (outside the raw file)

**Listing key**:
The stable handle that tracks the same vendor row over time and across manual merges.

**Product**:
One physical SKU: a category, a model code and the variant axes that change the physical part. A product holds one offer per vendor that sells it.
_Avoid_: item, part (when the merged catalog entry is meant)

**Product id**:
The stable handle for a product, used in links and price history.
_Avoid_: pid in user-facing text

**Retired product id**:
A product id that no longer names a product because its listings moved to another product, or split across several.
_Avoid_: dead id, absorbed pid

**Pid alias**:
A retired product id that points at the product now holding its listings, so old links and history keep resolving.

**Offer**:
One vendor's price and availability for a product, with its last-seen date.
_Avoid_: listing (once merged)

**Stale**:
An offer reused from an earlier snapshot because the vendor had none today. Always shown as stale, never hidden.

**Skipped vendor**:
A vendor with no usable snapshot inside the lookback window for a catalog build.

## Operations

**Crawl**:
One run of a vendor's spider: the rows of a snapshot file scraped together (gaps under 6 h). A file can hold two crawls when a run appended to it.
_Avoid_: scrape (as a noun for one run), snapshot (that is the file)

**Partial crawl**:
A crawl with fewer items than the vendor's floor or than 85% of its typical size; its absences never count.
_Avoid_: suspect crawl (internal name)

**Missing listing**:
A listing absent from the vendor's latest valid crawl only; often noise.

**Gone listing**:
A listing absent from two valid crawls at least 36 hours apart. Seen again later, it is back on sale.
_Avoid_: delisted, removed

**Finding**:
One current problem the alert rules see (scrape not done, site down, partial crawl); an alert opens, reminds and resolves per finding.

**Daily report**:
The 10:00 Israel-time phone message with one line per vendor; silent when every line is OK.

## Identity

**Model code**:
The canonical code a manufacturer gives a part within a category; the core of product identity.
_Avoid_: model name, title

**Variant axis**:
A property that makes two parts with one model code physically different (packaging, colour, capacity, memory type, lighting).

**Packaging**:
The Box or Tray variant axis of a CPU; Box and Tray are always two products.

**Manufacturer part number**:
The maker's own part code. Two different ones under one model code mean two variants.
_Avoid_: MPN in user-facing text

**Retailer SKU**:
A vendor's own catalogue code. Never identity on its own.
_Avoid_: part number

**Manual merge**:
A human decision that listings belong to one product.

**Blocked pair**:
A human decision that two listings must never merge.

**Singleton**:
A product with one listing because nothing else matched it confidently.

**Identity case**:
A merge or split decision published on the quality page for a human to check (identity merge, packaging conflict, variant conflict, split candidate).

**Review queue**:
Near-match pairs suggested for a human decision; never merged automatically.

## Specs

**Spec**:
One typed fact about a product (socket, wattage, length). Unknown is empty, never guessed.
_Avoid_: attribute

**Source tier**:
The trust rank of a spec's source: reference, manufacturer, vendor structure, extracted, title, weak vendor.

**Reference specs**:
Physical facts from an external dataset, the most trusted tier when the product link is certain.

**Spec conflict**:
Two sources of the same tier disagreeing on one spec; both are kept for the quality page.

**Detail enrichment**:
Specs and better images read from vendor product pages, a bounded chunk per day.

## Site

**Cover**:
The one photo chosen to represent a product.
_Avoid_: thumbnail (that is a smaller copy of the cover)

**Build**:
A visitor's chosen set of parts, one or more per slot.
_Avoid_: list, cart

**Short link**:
A fixed short id that maps to a stored build.
