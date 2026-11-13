# QA resolution pass: prompt

Hand this to an agent working in `D:\Mifrat`.

---

You are clearing the Mifrat QA queue. Mifrat is an Israeli PC-parts price comparison site. A Python pipeline scrapes 5 vendors (TMS, 1PC, KSP, Ivory, YahavPC), merges listings into products, and publishes a static site. **Goal: resolve every QA case you can verify with confidence, using real evidence from vendor and manufacturer websites. Leave the owner only the cases you could not verify. Aim for zero.**

## 0. Read first (binding)

`AGENTS.md`, `decisions.md` (owner rules; newer entries win), `README.md` (§ Scraping rules), `GLOSSARY.md`, and the docstring of `scraper/qa_tool.py`. Rules that decide most cases:

- Box and Tray are always two products. A listing stays where its own label puts it. With no label, use the maker PN (Intel `BX` = Box, `CM` = Tray), otherwise Box + flag.
- Two versions (two maker codes, or two EANs split by one vendor) are two products. Two colours of one model are two colour-variant products.
- A shared manufacturer PN beats a title word. Vendor titles get things wrong (example: TMS calls the ASUS Prime RX 9070 OC `90YV0L71-M0NA00` a "9070 XT"; it is one product with the other vendors' listings).
- A TMS `C...B`/`C...T` code is a retailer code. It does not tell you the packaging.
- A 13-digit 1PC `מק"ט` is an EAN, not a part number.

## 1. The queue

- `data/site/qa.json` → `cases` (about 1155: spec_conflict 349, variant_conflict 339, identity_merge 233, packaging_conflict 96, duplicate_vendor 78, core_gap 51, split_candidate 8, unflagged_deal 1). Spec cases are capped at 30 per category, so new ones show up after each rebuild.
- `data/review_queue.json`: about 1250 fuzzy "same product?" pairs (`listing_a`, `listing_b`, titles, score).
- `data/catalog.json`: `products[]` (with `offers`, `specs`) and `listings[]` (`listing_key`, `url`, `title_raw`, `vendor_sku`, `mpn`, `attributes`, `price_ils`). Every listing has its vendor URL.

Print a count per kind and category before you start and after each round.

## 2. Writing decisions (ledgers only)

Write every decision through the QA tool's own function, so the values get validated and stored in the format the pipeline expects. Never hand-edit generated files.

```
python -c "from scraper.qa_tool import act; act({...})"
```

| Finding | Action | Ledger |
|---|---|---|
| Spec value is wrong or missing (spec_conflict, core_gap) | `{"action":"set","product_id":..,"category":..,"field":..,"value":..}` | `data/specs/overrides.json` |
| The case is wrong and the data is already correct | `{"action":"dismiss","id":"<kind>\|<product_id>\|<field or vendor or ''>"}` | `data/matching/qa_dismissed.json` |
| Listings merged into one product are really different products | `{"action":"split","keys":[only the listing keys that must not be together]}` | `manual_products.json` `blocked_pairs` |
| Fuzzy pair | `{"action":"match"\|"not_match","index":i}` (this runs `scraper.promote_decisions`) | `review_decisions.json` |
| Separate products that are really one product (not in the fuzzy queue) | add a `products[]` entry in `data/matching/manual_products.json` in the existing shape (`product_id`, `canonical_name`, `category`, `brand`, `model`, `attributes`, `listing_keys`) | same |

- Only block the pairs that are actually wrong. `split` blocks every pair among the keys you pass, so in a 4-offer product where one listing is wrong, block only that listing against each of the others.
- Do not `dismiss` fuzzy cases. Their ids are queue indexes and they shift on every rebuild. Use match or not_match.
- Use one writer at a time for the ledgers. If you run subagents in parallel (one per category works well), they collect evidence and return decisions. Only the main agent writes.

## 3. Evidence standard

A case counts as resolved only with **confident** evidence:

- **Identity** (same product or not): the maker PN or EAN on each vendor's product page, checked against the manufacturer's page or datasheet for that PN, including colour, version, Box/Tray, capacity, memory, rev and kit size. Matching titles are not evidence. One title word against a shared PN is a title error, not a split.
- **Spec value**: the manufacturer's official spec page or datasheet for that exact PN or SKU. If that is not available, two independent sources that agree (for example two vendors' detail pages plus Icecat). A single vendor page is not enough to override a value.
- If sources disagree or the page for that exact SKU cannot be found, **leave the case open**. Do not guess. A wrong override or merge is worse than an open case.

Check the local evidence before going to the web: `data/raw/detail/`, `data/detail_scraped/`, `data/mfr/`, `data/icecat/`, `data/xref/`, `data/pcpartdb/`, `data/extract/`, and the listing's own `attributes` and `vendor_meta`.

## 4. Browsing rules (strict: vendor bans hit the owner's home IP)

- **TMS, 1PC, KSP** (home vendors): open pages like a person would. One page at a time, 5–15 s between requests to the same vendor, no parallel requests to one vendor, at most about 150 pages per vendor per day. Do not use API endpoints, `?limit=` URLs or fuzzed URLs. Only open the listing `url` from the catalog. On a 403, a 429, a captcha or a "blocked" page, **stop using that vendor for the rest of the session** and fall back to the manufacturer site or other vendors. Never retry. Never solve captchas. No proxies.
- Ivory and YahavPC are less sensitive but still need polite pacing. Manufacturer sites: 1 request per second.
- If a vendor page is gone or 404s, the catalog still has its title and SKU. Search the manufacturer site for the PN instead.

## 5. Per-kind playbook

- **identity_merge / split_candidate**: open every offer's page and read the PN or EAN. If all are the same product, dismiss. If some are different, split only the wrong pairs.
- **variant_conflict**: decide whether the axis (colour, RGB, capacity, rev) is real. If the PNs differ, they are separate products: dismiss if they are already separate, split if they are merged.
- **packaging_conflict**: read each listing's label or PN for Box vs Tray. Put each listing where its own evidence puts it (split pairs if needed). Do not use the TMS C-code as packaging evidence.
- **duplicate_vendor**: one vendor listing the same item twice. If it is a relisting, bundle (`-PC`) or clearance twin of one product, dismiss. If the two are actually different SKUs (different codes or axes), split.
- **spec_conflict**: compare `kept` and `dropped` with the manufacturer spec. If `kept` is right, dismiss. If `dropped` or some other value is right, `set` it.
- **core_gap**: find the missing field on the manufacturer page and `set` it.
- **unflagged_deal** and anything else that is a code bug, not a data issue: do not patch it. List it in the report.
- **Fuzzy pairs**: match only on a PN or EAN match confirmed on both sides. Use not_match when there is clear evidence they differ. Otherwise leave it open.

## 6. Loop

1. Work in batches of about 50 cases. After each batch, rebuild with `python scraper/normalize_and_match.py`, then re-read `qa.json`. Splits and merges create new cases, and more spec cases come out from under the per-category cap.
2. Keep going until a full round produces no new confident decisions.
3. Gates that must pass before you finish: `python scripts/check_ledgers.py`, `check_identity_merge.py`, `check_publish_set.py`, `check_spec_invariants.py`, `check_spec_merge.py`, `check_qa_tool.py`, `check_categories.py`, plus `npm --prefix site test` and `npm --prefix site run build`. If a gate fails because of one of your decisions, undo that decision. Do not loosen the gate.
4. Compare product, offer and best-price counts before and after with `python scripts/report_identity_delta.py`.

## 7. Scope limits

- Change only the ledgers listed in §2 and your report files. No production code, workflows, raw snapshots, or hand-edited generated catalog, site or history files.
- If many cases share one root cause, resolve the individual cases and describe the pattern in the report as a proposed code fix (module, rule, examples). Do not implement it.
- Commit in small batches with clear messages. Do **not** add yourself or any AI as author or co-author, and no `Co-Authored-By` trailers: all work is attributed to the repo owner only. Do **not** push.

## 8. Deliverables

1. `docs/qa-resolution/2026-11-13.jsonl`: one line per decided case with `case_id`, `kind`, `product_id`, `action`, `value` (if any), `evidence_urls`, and a one-line `reason`.
2. `docs/qa-resolution/2026-11-13.md`: counts by kind (start → resolved → left), the systemic patterns and proposed code fixes, vendors that blocked you, and **the list of cases left open**. For each open case, give what you checked and what evidence was missing, so the owner can decide in under a minute.
3. A short entry in `decisions.md` (required by AGENTS.md) summarizing the pass, the ledger deltas, and the before/after counts.
