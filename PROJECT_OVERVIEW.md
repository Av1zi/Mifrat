# Mifrat — Project Overview

This document explains every part of the Mifrat project in plain concepts, with no code. It is written for a developer or curious reader who wants to understand what the project does, how data flows through it, and how each piece of the website works.

Related sources of truth:

- pc-parts-il-plan.md — why the architecture looks this way
- decisions.md (local-only, not committed) — running log of decisions
- README.md — short live status
- nano/NANO_README.md — Nano setup
- site/README.md — frontend setup
- SHORT_LINKS_SETUP.md — short link setup
- data/raw/RAW_README.md — raw snapshot convention

## 1. What this project is

Mifrat is a PCPartPicker-style site for the Israeli market.

The purpose is simple to state:

- Track real prices and availability for PC components sold in Israel.
- Bring listings from several different local vendors into one clean catalog where the same physical product sold by two vendors appears once with multiple offers.
- Let a visitor browse by category, filter and compare, view one product with all its vendor offers and price history, and assemble a full PC build with basic compatibility guidance.
- Show which vendor currently has the best price for each part.
- Refresh the data every day without manual work.

Non-goals for the current version:

- No user accounts. Sharing a build is done with links, not logins.
- No real database for the catalog. Versioned files in git act as the database.
- No backend server for browsing, filtering, or compatibility. All of that runs in the visitor browser. There is exactly one small server-side exception for short build links, explained later.
- No attempt to defeat serious bot protection. If a vendor actively blocks automated access, the project treats that as a stop signal for that source, not a challenge to work around, with one documented historical exception for Plonter described below.

The site is bilingual, Hebrew and English, right-to-left by default in Hebrew and left-to-right in English. Prices are stored as whole Israeli shekels and can be displayed in shekels or converted to dollars for viewing only.

## 2. Big picture — how the whole thing fits together

Think of the system as three stages that run every day:

1. Capture: small scraper programs visit each vendor and save what they saw that day.
2. Merge: a normalizer reads the latest snapshots from all vendors, cleans them, matches identical products together, and writes a shop-ready catalog plus small per-category files and price history.
3. Serve: a completely static website reads those small files directly in the browser. A hosting platform rebuilds and serves the site automatically whenever new data or new site code is pushed.

Concretely:

- Scrapers write one file per vendor per day under a date folder for raw data. Each line in those files is one listing as seen on the vendor site.
- The normalizer reads the newest available file per vendor. If today is missing for a vendor, it reuses that vendor most recent file from the last two weeks and marks those listings as stale so the site can show they are not fresh. If no file exists at all in that window, that vendor is skipped for the day and recorded as skipped.
- The normalizer produces a full internal catalog file plus a review queue file for uncertain matches, plus a set of small public files grouped by product category, plus a search index, plus a metadata summary, plus per-category price history files, plus a small quality-report file.
- The website copies those public files into its own public folder at build and development time, then serves them as static files. The browser fetches only the category the visitor is looking at, not the whole catalog.
- Hosting rebuilds automatically on every push to the main branch, whether the push was new site code or fresh daily data.

Two machines do the scraping because vendors behave differently from different networks:

- Cloud runners handle vendors that do not block datacenter addresses.
- A small home computer (Jetson Nano) handles the one vendor that blocks datacenter addresses and therefore must be visited from a normal residential home connection.

Spiders themselves are location-agnostic. Moving a vendor from cloud to home or back is a scheduling change, not a rewrite.

## 3. Repository map — where everything lives

- scraper folder: all data-collection and data-merging logic. Includes vendor spiders, shared settings, the daily runner entrypoint, the normalizer, the matcher, attribute extraction, price-history builder, reference-spec enrichment, detail-page enrichment helpers, image downloader, and size checks.
- site folder: the static website. Vite plus TypeScript with no UI framework. Includes page views, shared state and routing, catalog access, filtering and compatibility logic, formatting and translation, and the tiny short-link worker.
- data folder: the database. Raw daily snapshots, the built catalog, the review queue, manual merge decisions, public site files, price history, detail enrichment ledgers, downloaded images, and reference label files. Some subfolders are intentionally not committed.
- nano folder: setup and scheduling for the home computer that scrapes the one blocked vendor.
- scripts folder: shared helper for committing and pushing with retry, used by automated jobs.
- Workflows folder for automation: cloud scraping schedule, normalize-and-deploy pipeline, weekly old-data cleanup.
- Root configuration: package and worker configuration for the hosting platform, dependency lists for Python and for the site, crawler configuration.

## 4. Scraping layer — how data is collected

### 4.1 General principles

The project prefers to use a vendor own internal data source when one exists and behaves like normal browsing. Examples are a builder endpoint that returns product tiles, a full-catalog feed, or a structured data endpoint used by the vendor own pages. Plain page parsing is the fallback when no such source exists.

Spiders only collect what the vendor shows. They do not clean, translate, categorize beyond a rough guess, or merge. Cleaning and matching happen later in the normalizer so scraping stays simple and comparable across vendors.

Every listing conceptually contains: which vendor it came from, the vendor own identifier for the item, the page address, the raw title exactly as shown, the price in shekels, whether it looked in stock, any promotion information if visible, a rough category guess, extra vendor-specific details for later use, an image address if the listing had one, and the time it was scraped.

A separate detail concept exists for deeper product pages: vendor, identifier, address, a table of specification labels and values, a main image, scrape time, and extras.

### 4.2 The only supported entrypoint for real runs

For real daily data, there is one supported way to run a vendor spider. It takes the vendor name, runs that spider, and writes the dated output file for today, replacing today file if it already exists. It refuses to succeed silently on zero items — it exits with failure if the output is missing or empty so broken runs are visible instead of producing an empty day.

Direct crawler commands are for local testing only and must write to clearly marked test files that are ignored by version control, so test runs never pollute the real daily folder.

### 4.3 Shared crawler behavior

Global crawler settings shape all spiders to be polite and robust: delays between requests with randomization, low parallelism per domain, automatic throttling that slows down when the server is slow, generous timeouts, browser-like headers including Hebrew language preference, and structured logging.

Two quirks are intentional and must not be cleaned up:

- The async reactor setting must stay the very first line of the settings file, otherwise the browser-driven spider fails to start.
- Every spider defines two entry methods that share one request builder. Newer crawler versions use one, older environments use the other. Removing either causes silent zero-request runs in one environment.

### 4.4 TMS spider — home-only vendor

Purpose: collect core PC components from TMS, which uses a custom storefront theme, not a standard shop template.

What it visits: a fixed set of category pages covering processors, graphics cards split by brand family plus professional cards, motherboards, desktop and server power supplies, desktop and server memory, solid-state drives, hard drives, CPU cooling, case fans, and desktop plus industrial cases. It follows the site own pagination using page numbers derived from the results-count footer, with an older pagination-link selector kept only as fallback. It never constructs page-size URLs because those are disallowed by the vendor own robots file.

How it reads a page: it looks at product cards to get identifier, title, price, promotion if two prices are present, and thumbnail. It deduplicates by identifier and address within the run.

Stock is special: stock is not in the page HTML. After each category page, the spider makes one batched availability request for all identifiers seen on that page and interprets color and status signals as in stock, out of stock, or unknown. Unknown never causes an item to be dropped.

Promotions and bundles: if a card shows two shekel amounts with new-PC wording, the second amount is kept as a promotion and the listing is flagged as a new-PC deal. If the card says the item is only available as part of a bundle, it is flagged as bundle-only so later stages can treat it accordingly.

Network and politeness rules for TMS are strict because it runs from a home connection and the vendor blocks datacenter addresses: plain HTTP only with no browser automation on the home machine, obey robots rules, very slow and strictly sequential requests, minimal bot-identifying headers, and an automatic hard stop after two block responses in one run. No retries against blocks, no proxies, no evasion. Repeated blocks mean de-escalate or drop the source.

### 4.5 1PC spider — cloud vendor

Purpose: collect core components from 1PC through the vendor own builder data endpoint.

What it visits: a fixed mapping of internal category identifiers to canonical guesses such as processor, CPU cooling, motherboard with platform dependency, memory, case, power supply, case fans, graphics, solid-state, and hard drive. The mapping was confirmed to return full unfiltered categories.

How it works: it posts form-style requests for pages of a category and reads the returned product-tile fragments. Each tile carries a numeric product identifier, title, price, thumbnail, and pagination signal. Prices are rounded carefully to whole shekels to remove floating-point noise. Titles are cleaned of occasional data-format bleed. The numeric identifier becomes the vendor identifier, stock is recorded as true because the endpoint only returns available items and carries no explicit stock signal, and pagination continues while the response indicates a next page.

### 4.6 Plonter spider — cloud vendor with browser automation

Purpose: collect core PC components from Plonter full-catalog feed, which returns the entire catalog in one response.

What it visits: one feed address. The response is a tab-separated feed with columns for identifier, title, description, category, division, shelf, total price, a tree path of internal codes, image filename, amount, and English division.

Filtering is essential because the feed contains the whole store including networking, peripherals, and cables. The spider only keeps rows whose English division matches core PC component families: hard drives, motherboards, processors, fans and cooling, liquid cooling, computer cases, memory, display adapters, and power supplies.

Other behavior: canonical product addresses are built from the identifier, thumbnails are built from the image filename, the internal tree path is preserved for later attribute extraction, stock is recorded as true because the feed only lists available items, and price is taken as shown.

Browser automation is required because the vendor sits behind a bot-management challenge that returns a challenge page to plain requests. The spider therefore runs this source through a real Chromium browser integration. Installing the Python package alone is not enough; the browser binary must be installed separately or the spider silently gets the challenge page. Encoding must not be forced manually because the browser path already decodes correctly. This is a deliberate, documented exception to the general no-evasion stance.

### 4.7 Ivory spider — cloud vendor

Purpose: collect core components from Ivory structured data endpoint used by its own builder pages.

What it visits: a set of platform-specific and shared categories. Processor and motherboard categories are requested per platform (Intel and AMD variants). Shared categories such as air cooling, liquid cooling, memory, solid-state, hard drive, graphics, power supply, case, and case fans are requested once because they are identical regardless of platform.

How it works: it makes plain requests to the endpoint and reads grouped product records containing identifier, title, barcode, parent grouping, price, picture path, internal cut identifiers, and description. The barcode is the true vendor identifier, the catalog identifier becomes the product address, picture paths are normalized into full image addresses, and internal cut identifiers plus description and parent grouping are preserved for later attribute extraction. Deduplication is done by catalog identifier. Stock is recorded as true because the payload carries no stock signal.

Blocking behavior: if every request in a run is blocked, that is treated as a datacenter ban signal. The spider does not retry, proxy, or evade; the normalizer stale-forwarding covers the gap.

### 4.8 KSP spider — disabled stub

Purpose: placeholder only. It defines the vendor domain but no start addresses and its parsing explicitly fails if ever called. It is never scheduled. The rule is to check for an official data-access approval first, to have the other vendors stable before revisiting, and to treat bot-management or CAPTCHA as a stop signal, not a challenge.

### 4.9 Schedules — cloud vs home

Cloud scraping runs on hosted automation on a matrix of the three cloud-safe vendors, with independent jobs so one vendor failure does not stop the others. It runs once late at night Israel time with a random spread to avoid thundering-herd timing, plus a morning fallback that skips vendors whose output already exists and is non-empty. It can also be started manually. It installs dependencies, installs the browser binary needed by Plonter, runs the per-vendor entrypoint, then commits only that vendor dated file using the narrow-commit helper. Narrow commits matter because parallel jobs on slightly stale checkouts must not stage each other files as deleted.

Home scraping runs on the Nano for TMS only. A system service runs the home script with a time limit and logs to the system journal. A daily timer fires in the evening UTC with a large randomized delay so the run lands late at night or overnight Israel time and can catch up after downtime. A morning fallback timer runs only if a success marker for today does not already exist. The home script pulls latest code, runs the spider, checks for zero items, commits and pushes the snapshot first with retries, then does best-effort detail enrichment and image downloading, then pushes again, failing loudly if the main snapshot push fails.

Binding home rules: at most one run per day, strictly sequential and throttled, browser-shaped traffic, hard stop on repeated blocks, de-escalate or drop on repeated blocks, never use proxies or retries against blocks.

### 4.10 Outputs and hygiene of scraping

Listing snapshots live under date folders with one file per vendor. Detail snapshots are append-only under a detail folder. Pending and completed ledgers track detail enrichment. Downloaded images live under an images folder with thumbnails alongside.

Real runs use the supported entrypoint or the home script. Local tests use ignored test files. Detail runs append, never overwrite. Commits use a shared helper that takes an explicit message plus only the files the job wrote, guards existence, rebases with a strategy that favors incoming changes on conflict, and uses a bot identity. Never stage a shared tree broadly because parallel jobs can otherwise delete sibling files.

Robot and throttle summary: global default is to ignore robots rules, but the home-run vendor explicitly obeys them. Page-size query tricks are never constructed for that vendor. Cloud vendors run with modest delay and throttling and low parallelism; the home vendor runs even slower with single-request parallelism. Zero secrets live in automation or git. The home machine uses a repo-scoped deploy key. Hosting identifiers are public by design; credentials, tokens, login sessions, private keys, and local environment values are never committed or shared.

## 5. Detail enrichment — deeper specs and better images

Purpose: listing pages give title, price, and thumbnail, but product pages often have a fuller specification table and a better main image. Detail enrichment collects those deeper pages for a controlled subset of items and merges them later.

Lifecycle:

- Build a pending list by comparing the latest listing snapshot against a ledger of already-scraped detail identifiers. Only missing identifiers become pending, processed in limited chunks so daily work stays bounded.
- Crawl pending detail pages with per-vendor detail spiders and append results to the per-vendor detail file.
- Download images for those detail results, creating a standard-size image and a small thumbnail, skipping items that already have images and skipping image addresses without a real filename.
- Mark identifiers as done only if the detail result contained a non-empty specification table. An image alone does not count as done; an empty table means the page was likely a challenge or miss and stays pending for a future attempt.

Per-vendor detail reading is tailored: one vendor uses labeled content rows with Hebrew label mapping, another uses definition and table structures plus structured metadata including brand, availability, and catalog number, another uses specification tables with subgroup handling plus real identifier and manufacturer number discovery from metadata and structured data, and Plonter uses browser automation over table rows with Hebrew labels and directional values. Everywhere, the detail main image is preferred over the listing thumbnail when present, and junk, empty, Hebrew-navigation, or mojibake-contaminated pairs are discarded.

## 6. Normalize and match — how raw listings become one catalog

### 6.1 Orchestration

The normalizer is the only supported way to build the catalog. Conceptually it does this:

1. Find the latest snapshot per vendor for today, falling back up to two weeks per vendor if today is missing.
2. Load each snapshot tolerantly, recovering even mildly malformed concatenated objects.
3. Enrich every listing: normalize vendor identity and identifier, normalize price, normalize category, build searchable text, detect brand and manufacturer number, preserve bundle and promotion flags, and extract structured attributes.
4. Remove duplicates within the enriched set and merge in detail specifications and better images.
5. Match listings that represent the same physical product using a strict hierarchy, assign a stable product identifier to each listing, and build product records with offers from all vendors.
6. Suggest uncertain near-matches for human review without ever auto-merging them, and detect vendor-duplicate and naming-conflict cases for a quality report.
7. Write the full catalog and review queue, fail if there are zero listings in total, then write small public site files and price history.

### 6.2 Listing identity and prices

Vendor identities are canonicalized so aliases for the same shop collapse to one name. Each listing gets a stable key used for deduplication and manual merges. Special handling exists for numeric builder identifiers and catalog query identifiers so unrelated items never collide just because they share a short numeric form. If no usable identifier exists, a hash of address or payload is used so the item is still trackable.

Prices are normalized to integer shekels with careful rounding that removes floating-point noise and stray separators.

### 6.3 Category normalization

Each listing starts with a rough vendor guess, but titles, addresses, identifiers, and Hebrew hints can correct it. Air cooling is distinguished from liquid cooling before generic cooler wording can confuse them. Fan, accessory, and case guards prevent common misclassification. Hebrew words for liquid cooling, case fans, processor cooling, and paste help disambiguate. Several small accessory families are grouped under one accessories umbrella while preserving the specific accessory type as an attribute. Mining and riser items go to a generic other bucket, and graphics-card holders go to accessories. The goal is a small, stable set of canonical categories the site can rely on.

### 6.4 Search text, brand, and manufacturer number

A normalized match text is built from identifier plus raw title after cleaning. Brand is detected by longest known alias match. Manufacturer numbers are extracted with patterns that understand common affixes and packaging hints, preferring longer and more specific forms and stripping known prefixes that would otherwise split identical products. Short numeric-only identifiers are not treated as manufacturer numbers unless they are long enough to plausibly be universal codes.

### 6.5 Attribute extraction

Attributes are structured facts like socket, chipset, memory type, form factor, wireless support, capacity, speed, wattage, dimensions, and similar. Extraction is text-only over the normalized match text so every vendor is treated uniformly. Vendor-specific extras such as internal cut labels, tree paths, and detail specification tables are only additive: they can fill gaps but never override what the title already says.

Detail pairs are sanitized: mojibake artifacts, empty values, Hebrew navigation keys, blacklisted keys, and noise values meaning none or not applicable are dropped. Known label aliases are unified, yes-no values are normalized, clock ranges are split into base and boost, and socket, form-factor, and packaging wording is cleaned. Per-category parsers then handle motherboards, processors, graphics, memory, power supplies, storage, cases, and coolers, plus fragment parsing, tree-path parsing, Hebrew description parsing, and internal cut-label translation with promotion-label guards. Duplicates are unified, filter values are canonicalized, digit-less measure fragments are dropped, and overly long prose values are discarded so they cannot become filter labels.

### 6.6 Matching hierarchy — the hard part

The matcher decides which listings are the same physical product. It is conservative by design: uncertain pairs stay separate and are suggested for human review instead of being silently merged.

In order:

1. Manual merges win. A committed ledger maps known listing keys to a chosen product. Blocked pairs veto merging at every tier.
2. Processor model identity. Only processors use this tier. It understands series and sub-series distinctions that must never merge and packaging distinctions where boxed and tray versions stay separate with a tray suffix.
3. Exact manufacturer number. Listings with the same compact manufacturer key in the same category merge, still respecting packaging splits and conflict vetoes.
4. Exact normalized vendor identifier. Same idea for vendor identifiers that are long and specific enough.
5. Cross-key unification. If the manufacturer-number view and identifier view point at the same category and part, they unify under the manufacturer-number identity.
6. Conflict guards. If compact numbers match but critical attributes conflict, the group splits into singletons. If compact numbers match and only model-title tokens differ, the group stays together but is flagged as a naming conflict with the differing titles preserved for review.
7. Everything else becomes a singleton product unique to its listing key.

After grouping, products get: a stable product identifier, a canonical name built from structured identity fields rather than vendor prose, a short description, category, brand, model, merged attributes with majority-vote conflict detection, how it was matched, vendor count, offers sorted for display, first available image, duplicate-vendor flags, naming-conflict flags, best offer selection preferring in-stock cheapest, and optional reference-spec blocks.

Presentation hygiene matters: raw titles and structured attributes stay separate. Canonical names come from identity fields when available. Vendor feature prose belongs in attributes or description, never in the name. Encoding artifacts are discarded during matching and extraction so they cannot leak into the catalog or site.

### 6.7 Stale forwarding

If a vendor has no snapshot today, the normalizer walks backwards day by day up to two weeks and reuses the first file it finds for that vendor. Reused listings are stamped with their true snapshot date and marked stale when that date is not today. A log notes fresh versus stale per vendor. Vendors with nothing in the window are recorded as skipped and surfaced in metadata so the site can explain gaps. A vendor having a bad day never wipes its prices off the site, but stale data is always visibly stale.

### 6.8 Review queue and manual decisions

Near-matches are suggested by comparing listings within the same category and brand, skipping generic categories, brand-less items, items already in the same product, already-multi items, blocked pairs, and pairs with differing manufacturer numbers or critical conflicts. A high string-similarity threshold is required. Suggestions plus vendor-duplicate and naming-conflict cases go to a review file for humans.

A tiny local review tool can serve that queue for decisions. A promotion helper turns confirmed matches into new manual products and confirmed non-matches into blocked pairs, idempotently and in sorted order. Fuzzy logic never auto-merges.

### 6.9 Reference-spec enrichment

An optional reference dataset can add physical facts the vendors rarely provide, such as processor power draw, graphics-card length, case volume and bay counts, and cooler noise and speed. The reference index is rebuilt fresh and is ignored by version control; the pipeline degrades gracefully when it is missing. Matching is name-based with per-category thresholds and only attaches a separate reference block — it never merges into vendor attributes and never drives filters, variants, or compatibility, because a wrong fuzzy reference match must not corrupt scraped facts. A second exact-match enrichment keyed by manufacturer number adds reference specs the same additive way.

### 6.10 Price history

Price history is built from the last several months of date folders that contain vendor files. Per date, prices are keyed by both normalized identifier and address so identifier rewrites (for example numeric builder identifiers replaced by real manufacturer numbers) still resolve. Per product, the history records per-vendor price series with null for absent days, keeping only vendors that were ever priced. Output is one small minified file per category with shared date and timestamp arrays, pruned of orphaned products. It can also be rebuilt standalone from the catalog.

Old raw snapshots are periodically thinned: recent days are kept daily, older months keep one snapshot per week, and data older than a year keeps one per month. Detail files are never thinned. The normalizer only needs the last two weeks, while git history retains the older blobs.

### 6.11 Images

Detail main images win over listing thumbnails. Image addresses without a real filename are rejected. Real identifier replacements rebuild search text and attributes so names stay correct. Downloads create a web-sized image and a small thumbnail per vendor and identifier, skipping existing files. The public site uses local image paths only and never hotlinks vendor hosts at runtime; missing images fall back to an initials-style placeholder. The build fails if any public product still references a remote image, which enforces the local-only rule.

### 6.12 Public site files

The full internal catalog is sharded into small client-optimized files: one trimmed file per category with only the fields the frontend needs, sorted by current best price; a tiny search index of identifier, category, price, brand, and name; a metadata summary with generation time, skipped vendors, and per-category counts and price ranges; per-category price history; and a quality-report file with duplicate-vendor and naming-conflict cases. A trimming allowlist must explicitly include any new field the frontend needs or it is silently dropped before it reaches the browser. Files are written atomically and orphaned files are cleaned up. A size guard fails the build if any public file grows too large or a category grows disproportionately without product growth.

### 6.13 Triggers and guards

After cloud scraping finishes, detail enrichment runs for a bounded chunk per vendor, appending detail results, downloading images, marking completed identifiers, and committing narrowly per vendor. The home machine does the same for its vendor with a smaller chunk. The normalize-and-deploy pipeline triggers on new raw data pushes, on cloud-scrape completion (needed because automation-token pushes do not fire push triggers), on a midday fallback schedule, or manually. It allows concurrent runs to queue rather than cancel, refreshes the optional reference index on a best-effort basis, builds the catalog and site files, checks sizes, and commits the catalog, review queue, and public site files. Hosting then redeploys automatically.

## 7. Data artifacts — what each file means

- Raw snapshots: the ground truth of what each vendor showed on a given day. One file per vendor per day. Used only by the normalizer and history builder, never directly by the browser.
- Full catalog: the internal database. Every enriched listing with its assigned product, plus every product with offers, attributes, images, flags, and reference blocks. Used by the history builder and by the site-file writer.
- Review queue: uncertain near-matches plus quality cases for humans. Never drives the site.
- Manual products ledger: committed human decisions about what belongs together and what must stay apart. Highest priority in matching.
- Public category files: what the browser actually reads. Trimmed, sorted, minified, one per category.
- Search index: tiny table for fast global search without downloading every category.
- Metadata file: generation time, skipped vendors, and per-category counts and price extremes. Powers home and category-overview pages.
- History files: per-category date arrays plus per-product per-vendor price series. Powers product price charts.
- Quality file: duplicate-vendor and naming-conflict cases with titles and offers. Powers the data-quality page.
- Detail files and ledgers: append-only detail results plus pending and completed identifier tracking.
- Images: local vendor-scoped standard images and thumbnails, only for referenced products.
- Label files: committed translation tables for opaque internal cut identifiers.
- Reference index: ignored, rebuilt cache for optional enrichment.

## 8. Website — how the storefront works

### 8.1 Stack and build

The site is static: Vite plus TypeScript with no UI framework. The entire application logic is a small amount of JavaScript. Styling is plain CSS. Fonts are self-hosted. There is no runtime server for browsing.

Local development and production builds both start with a copy step that copies the public data files from the repository data folder into the site public folder, plus only the images actually referenced by those JSON files. If the data folder is missing, the instructions are to run the normalizer first or pull latest data. The build then type-checks and bundles to a distribution folder.

Hosting configuration lives in the hosting dashboard, not in the repo: the project root is the site folder, the build command builds the site, and the output folder is served. Because the checkout includes the whole repository, the copy step can still reach the data folder even though the site root is a subfolder. Every push to the main branch rebuilds, whether the push changed site code or just daily data.

### 8.2 Routing and shell

The site is a hash-based single-page application with no router library, plus one clean path for shared build links.

Routes conceptually:

- Home: empty hash.
- Category overview: categories list.
- One category: category plus query parameters for search text, sort order, stock-only toggle, attribute filters, numeric ranges, and an optional build-picker slot.
- One product: category plus product identifier.
- Builder: build query with one parameter per slot, repeatable for multi-item slots.
- Shared build: clean short-link path with a short identifier.
- Static pages: privacy, terms, cookies, data-quality.
- Unknown routes show a not-found page.

Navigation helpers build these hashes, update history for major moves, replace the route without adding history for filter tweaks, and leave the short-link path when the user starts editing so a reload stops fetching the shared snapshot.

The shell always shows: a header with brand, language and currency selectors, and theme toggle; a navigation bar with builder link, products mega-menu button, home link, and global search; a main content area; and a footer with disclaimer, source link, and legal and quality links. The mega-menu groups popular categories with photo tiles plus core, cooling, and accessory groups. Photos load asynchronously with icon fallback so layout does not shift. Global search is debounced, uses the tiny index for instant interim hits, then lazily enriches top hits with per-category data for photos and prices, with keyboard navigation. Language and direction are applied to the document on every route change.

### 8.3 Home page

Purpose: explain the site and get the visitor started.

Contents: a hero with title, subtitle, start-build and browse actions; live statistics such as total parts, active categories, and refresh freshness from metadata; short how-it-works steps; and feature highlights. All numbers come from the metadata file, not hardcoded.

### 8.4 Categories overview page

Purpose: show every category at a glance.

Contents: a grid of category cards in a fixed order, each with a representative photo loaded asynchronously, the localized category name, product count, and price range from minimum to maximum formatted in the chosen currency. Clicking a card opens that category.

### 8.5 Category page — the workhorse

Purpose: browse, filter, sort, compare, and pick parts for a build.

Contents: breadcrumbs, category title, an optional picker banner when opened for a specific build slot, a filter rail, a toolbar with search and sort, a product table with thumbnail, name, up to four automatically chosen specification columns, stock indicator, price, and add actions, plus infinite scroll that loads more rows as the visitor scrolls.

How it works:

- It downloads the one category file for the current category and caches it.
- It computes which attributes are actually useful as filters: only allowlisted attributes per category, with a reasonable number of distinct values, stringified consistently, including vendor names from offers.
- It computes numeric ranges for measure-like attributes.
- Filtering supports stock-only, free-text search over name, brand, model, identifier, and manufacturer number, checkbox filters for vendor and attributes, and min-max ranges.
- Sorting supports price low-to-high, high-to-low, vendor count, and name.
- Specification columns are chosen by coverage so the table shows the most informative columns for that category without overwhelming the row.
- Compatibility awareness: when opened as a picker for a build slot, the page can hide or dim options incompatible with the current partial build and show how many were hidden. Compatible auto-selection can pre-check locked values implied by the build, such as socket. Individual options can appear dead or soft-off with explanation when they conflict.
- Clicking a row opens the product. Quick-add adds the item to the local build without leaving the page. In picker mode the action returns to the builder.

### 8.6 Product page

Purpose: answer whether this is the right part and where to buy it cheapest right now.

Layout: breadcrumbs, a title band with category eyebrow, display name, description, and brand plus identifier; a side column with large image, add-to-build action, variant selectors, specification card with show-more, and reference-spec block when available; and a main column with the offer table, stale markers, disclaimer, price-history chart, and similar products.

Offer table: one row per vendor offer with merchant name, base price, shipping if known, availability, total, and buy link. Rows sort in-stock first then by price. Stale offers are tagged. No vendor hosts are contacted except when the visitor clicks a buy link.

Variants: when the same conceptual family differs along a small set of dimensions (for example memory type and capacity, or chipset and socket, or graphics chip, or wattage), the page shows pill selectors. Groups are identity-gated and value-sorted with stable order so selectors never jump sides when navigating.

Similar products: up to a handful of cards chosen by curated per-category specification priority with extra weight for identity matches and a minimum score threshold.

Price history: a simple chart built from the per-category history file showing per-vendor series over time with gaps for absent days. If no history exists, the chart is hidden rather than showing an empty box.

### 8.7 Builder page

Purpose: assemble a full PC from compatible parts, see the total, check compatibility, and share the build.

Slots: processor, cooler (air or liquid), motherboard, memory, storage, graphics, case, power supply, and extras for fans, other cooling, accessories, and generic items. Memory, storage, graphics, power supply, and extras can hold multiple picks; other slots hold one.

Contents: one row per slot showing empty, filled, or add-another states; a compatibility banner that is calm when empty, reassuring when compatible, and warning when something conflicts; an estimated power block; a share section with copy button, read-only link field, and short-link status; a markup exporter that copies a markdown or text table of the build; options for parts count and starting over; a total row that sums best offers; and a compatibility note explaining limits.

How it works: best offer means cheapest in-stock offer per picked product. Totals sum those. Compatibility is forgiving: it only warns when both sides are known and actually conflict. Checks include processor-memory-board socket alignment with chipset-to-socket knowledge plus name-inferred sockets, memory generation matching, board capacity limits, graphics length versus case clearance, cooler socket support, and power-supply headroom versus estimated draw with processor draw coming from reference data when available. The picker can imply filter values from the current build, for example a chosen processor implying its socket in the motherboard picker.

Persistence: the current build lives in local browser storage under stable keys. No login is needed.

### 8.8 Shared short links

Problem: a full build carries too much information to fit reliably in eight characters by pure encoding. Fixed short identifiers therefore mathematically require a server-side lookup. This is the one deliberate exception to the no-backend rule: everything else stays client-side, only short-link storage lives server-side.

How it works: a shared codec validates and canonicalizes builds (slot limits, identifier count and length limits, de-duplication and sorting for stable hashing). Creating a link posts the build to an API that rate-limits per address, validates size and shape, refuses oversized stores, de-duplicates by hash so identical builds reuse the same identifier, inserts with retry on identifier collision, and returns the winner on races. Fetching a link returns the stored build with long cache lifetime. The worker also serves the application shell for short-link paths with strict security headers and runs before static assets for API and short-link routes.

Storage is a tiny table with identifier, build payload, hash for de-duplication, and creation time. Rows are insert-only; they are never updated or deleted. Identifiers are short fixed-length strings from a URL-safe alphabet with confusable edge rules, generated with rejection sampling and validated on read, with an unknown-identifier panel when the identifier is malformed or missing.

User experience: the builder auto-creates a short link after edits settle, showing the long link first until the short one arrives so sharing still works offline or in local development. Old long hash links keep working forever and are never broken.

First-time setup (creating the database, applying the migration, wiring bindings, and optionally adding rate-limit rules) is documented in the short-links setup file. Hosting identifiers for the worker and database are public by design; credentials are never committed.

### 8.9 Data-quality page

Purpose: be transparent about uncertain data.

Contents: articles for vendor-duplicate cases (same vendor appearing twice under different identifiers in one product) and naming-conflict cases (same compact number with differing model-title tokens), each with product reference, category, vendor, titles, and offer details including listing key, identifier, title, and price.

### 8.10 Legal and utility pages

Privacy, terms, and cookies pages are static bilingual cards explaining local preferences (language, currency, build, theme, effects), short-link snapshots, currency-rate fetching, hosting request handling, and the absence of tracking, advertising cookies, or consent banners. The not-found page offers home and builder links.

### 8.11 Data access in the browser

The browser only uses same-origin fetches with a timeout: metadata for home and overviews, the tiny index for search and build-part resolution, one category file at a time with retry on failure, history files for charts, and the quality file for the quality page. Representative images come from the already-cached category data. Types distinguish products, offers, index rows, category and site metadata, quality cases, history files, language, currency, and sort keys.

### 8.12 Images in the site

Only referenced images are copied to the public folder. List rows use small thumbnails; product and similar-card views use larger images. Images use contain-fit on a white background with lazy loading except the main product image, which loads eagerly. A URL sanitizer only allows local image paths; remote addresses resolve to nothing so the browser never contacts vendor hosts for images, falling back to a placeholder. Link addresses are allowlisted to safe web, local, or hash targets.

### 8.13 Internationalization, currency, icons, and page titles

Translations live in one module with category order, localized category, vendor, and attribute labels, plus well over a hundred interface strings addressed by key. Language, currency, and theme persist locally with system-theme fallback. Prices format per locale and currency; dollar mode fetches a daily exchange rate from a public rate API, caches it for a day, and silently stays on shekels if the fetch fails, so shekel mode makes zero external requests. Icons are inline stroke icons with per-category mapping and no emoji, icon fonts, or content-delivery networks. Page titles combine the current page with the site name in the active language. Utilities handle HTML escaping, error panels, identifier extraction, and display-name cleanup that strips duplicated model tokens.

### 8.14 Deployment

Dashboard settings point at the site folder, build with the site build command, and serve the distribution folder. Because the checkout contains the whole repository, the copy step can read the data folder even though the site root is a subfolder. No environment variables or secrets are needed. Every main-branch push rebuilds, whether it changed site code or daily data. The newer worker-based deployment uses the same assets plus bindings for the short-link database and asset serving, with a custom domain serving both the site and short-link paths from the same worker.

## 9. Operations and automation

Cloud scraping is a scheduled matrix over the three cloud-safe vendors with no fast failure, late-night primary plus morning fallback that skips already-present outputs, manual dispatch, write permission, dependency and browser-binary installation, per-vendor runs, and narrow per-file commits.

Normalize-and-deploy triggers on new raw-data pushes, on cloud-scrape completion (because automation-token pushes do not fire push triggers), on a midday fallback schedule, or manually. It never cancels in-progress runs, refreshes the optional reference index on a best-effort basis, builds the catalog and site files, checks sizes, and commits the catalog, review queue, and public site files. Hosting redeploys on that push.

Weekly cleanup thins old raw snapshots to weekly beyond three months and monthly beyond a year, never touching detail files. The normalizer only reads the last two weeks, while git history preserves older blobs.

The home computer uses a service plus daily and fallback timers with randomized delay and catch-up behavior, a dedicated low-privilege user, modern Python via a version manager, pinned crawler versions matching cloud, a repo-scoped deploy key, RAM-friendly logging, and required time synchronization. No browser automation lives there because the home vendor does not need it and the install is heavy on that hardware.

Shared commit hygiene: always commit narrowly with only the files the job wrote, never stage a shared tree, because parallel jobs on stale checkouts can otherwise stage siblings as deleted. The helper guards existence, uses a bot identity, and rebases with retry.

Secrets hygiene: zero secrets in automation and git, ever. Environment examples, keys, virtual environments, temporary files, test outputs, and local hosting state are ignored. Hosting identifiers such as worker name, database identifier and name, and binding names are public by design and safe to commit. Credentials such as tokens, login sessions, private keys, and local environment values must never appear in files, screenshots, or logs. If a credential ever reaches a commit, rotate it immediately; deleting the commit is not enough.

## 10. Design decisions and quirks to leave alone

- The reactor setting must stay the first line of the crawler settings file.
- Every spider keeps both entry methods sharing one request builder for version compatibility.
- Robots handling is split: ignore globally, obey for the home-run vendor. Never construct page-size URLs for that vendor; follow pagination links or page numbers derived from the results-count footer.
- Home-IP rules are binding: one run per day, sequential, throttled, browser-like, hard stop after repeated blocks, de-escalate or drop on repeated blocks. No retries against blocks, proxies, or bot-defense evasion. The Plonter browser-automation feed is the one documented exception.
- Matching stays strict: manual merges, then exact manufacturer number, then exact identifier, then singleton. Fuzzy suggestions go to the review queue only and never auto-merge. Listing keys stay stable. Numeric builder identifiers and catalog query identifiers need special handling to avoid collisions.
- Attribute extraction is additive only: vendor extras fill gaps but never override title-derived facts.
- Any new frontend field must be allowlisted in the site-file trimmer or it is silently dropped before reaching the browser.
- Compatibility stays client-side as plain rules over attributes. The only server-side piece is short-link storage, which is mathematically required for fixed short identifiers. Legacy long links keep working.

## 11. How to verify changes without a test suite

There is no automated test suite. Verification is:

- Run one vendor test crawl to an ignored test file and confirm items look sane.
- Run the normalizer locally and confirm the catalog, review queue, public files, and history build without failures or size-guard violations.
- Build the site locally and confirm it renders with fresh data.

Dependency setup is a Python package install plus a separate browser-binary install before running the browser-driven vendor. The site needs a package install before development or build. If public data is missing, run the normalizer or pull latest before starting the site.

## 12. Glossary in plain words

- Listing: one row a vendor showed on a given day, with title, price, availability, address, and image as seen.
- Listing key: the stable handle used to track the same vendor row over time and across manual merges.
- Product: one real-world part, possibly with offers from several vendors.
- Product identifier: the stable handle for that product, encoding how it was matched.
- Offer: one vendor price and availability for a product, with last-seen date and stale flag.
- Stale: data reused from a previous day because today snapshot was missing. Visible to visitors, never hidden.
- Skipped vendor: a vendor with no usable snapshot in the lookback window for that run.
- Match text: cleaned searchable text built from identifier plus title, used for brand, number, and attribute work.
- Manufacturer number: the maker part code used to recognize the same product across vendors.
- Manual merge: a human decision that two listing keys belong together, stored in a committed ledger.
- Blocked pair: a human decision that two listings must never merge, checked at every matching tier.
- Singleton: a product with only one listing because nothing else matched it confidently.
- Reference specs: optional physical facts from an external dataset, kept separate from scraped facts and never used for filtering or compatibility.
- Detail enrichment: deeper specification tables and better images collected from product pages for a bounded daily chunk.
- Short link: a fixed short identifier that maps to a full build via server-side storage because pure URL encoding cannot fit a build in that few characters.
