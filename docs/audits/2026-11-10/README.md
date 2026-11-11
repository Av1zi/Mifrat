# Data audit 2026-11-10: consolidation of lanes 01–08

- **Snapshot:** git HEAD `1e353d17`, `data/catalog.json` `generated_at` `2026-11-09T22:13:04.288166+00:00` (7095 listings, 4383 products). Both were re-checked before this file was written and had not changed.
- **Pin consistency:** all eight lanes report HEAD `1e353d17` and the same `generated_at`. **Every lane first pinned `1534928e` and re-pinned** when HEAD moved during the audit. `git diff 1534928e..1e353d17 -- data` is empty, and lanes 01, 02, 03 and 05 also confirmed that their code paths (`identity.py`, `matching.py`, `derive.py`, `ksp.py`, `specs/`) did not change. No lane is inconsistent.
- **Inputs:** `01-duplicates` … `08-references`, each a `.md` and a `.jsonl` in this folder. `docs/audits/` was untracked while the lanes ran and was committed afterwards (2026-11-10).
- **Scratch:** `tmp/data-audit/00-consolidation/` (`load.py`, `dedupe.py`, `spotcheck_s1.py`, `onepc_source.py`, `hash_outputs.py`, and their JSON outputs). The phase 2 rule prototypes are in `rules/` (§3).
- **Severity scale (brief):** S1 = the visitor sees wrong data (two parts in one product, wrong price or best offer, contradicting spec, wrong category, dead link). S2 = data we hold is lost, or one part is split. S3 = hygiene.

## 1. Top line

Counts are findings as each lane rated them. "Silent" means no QA case or review-queue entry.

| Lane | S1 | S2 | S3 | Silent |
|---|---|---|---|---|
| 01 duplicates | 4 | 2 | 2 | mostly flagged: 3 silent instances (S1-1 1/22, S2-4 1/18, S3-7 1/6) |
| 02 wrong merges | 5 | 14 | 4 | F-05, F-09 (3 of 4), F-20, F-21 silent; the rest flagged |
| 03 misfiled | 3 | 3 | 6 | 29 of 31 products silent (2 F4 flagged) |
| 04 missing fields | 2 | 3 | 4 | all silent except S3-b (deliberate, flagged) |
| 05 wrong values | 4 | 5 | 3 | all silent |
| 06 offers, prices | 1 | 1 | 3 | all silent |
| 07 raw fidelity | 1 | 3 | 2 | all silent except F3 (111 of 112 flagged) |
| 08 references | 0 | 4 | 8 | all silent |
| **Total** | **20** | **35** | **32** | 87 findings; about 85% of instances are silent |

**Re-rated to the brief's scale** (detail in §4 and §6):

- 04 S1-a splits into 4 S1 boards (wrong socket shown) and 8 S2 boards (chipset lost).
- 04 S1-b (empty brand) is S2: the brand is held data that was lost, not a wrong value.
- 06 F1 counts only the 149 `bundle_only` products as S1. The 57 `new_pc_deal` products show the regular price (lane 06's own false-positive note).
- 06 F2 / 07 F1 are S1 for the 11 listings that are the headline best offer, S2 for the other 14.
- The colour, finish and Box/Tray merges in 02 (F-06, F-07, F-10…F-17) are S1: two parts in one product.
- Every 03 misfile is S1 (wrong category), including the ones the lane rated S2 or S3. 03 F12 (`includes_cooler`) is S1 at medium confidence.
- 05 F06, F07 and F09 contradict their own titles, so they are S1. F09 is at medium confidence.

**JSONL dedupe:** 2183 rows. 77 are lane 01's rejected rows (R-1/R-2/R-3), leaving 2106. Matching on (sorted product_ids, field) gives 89 duplicate groups and removes 98 rows. Only 17 groups span two lanes:
- 16: 04 S1-a / S2-a chipset rows = 08 F2.
- 1: `tms:11348-03-20G`, 06 F2 = 07 F1.

That key misses most cross-lane duplicates, because lane 01 rows have an empty `field` and lanes 05/07/08 write sample rows. Cross-lane duplicates were therefore matched on product ids (183 products appear in more than one lane) and read by hand. They are listed per finding in §4, and both lanes are cited there.

**JSONL gaps.** Some JSONL files hold samples, not one row per instance:

| Finding | Rows in JSONL | Instances in the report |
|---|---|---|
| 05 F01 | 5 | 8 products |
| 05 F02 | 4 | 10 |
| 05 F03 | 5 | 8 boards (the summary table says 5; all 8 re-checked, §2) |
| 05 F08 | 2 | 42 |
| 05 F10 | 3 | 23 |
| 07 F1 | 2 | 25 |
| 07 F3 | 2 | 112 |
| 08 F4 | 1 | 277 |
| 08 F10 | 1 | about 1,500 |

Two counts in the reports don't match their own files:
- 03 says 31 JSONL rows; the file has 32.
- 07 F1's text says "2216 keys in both crawls". The script says 2204 are in both, 4 only in crawl A and 8 only in crawl B (2216 in total).

## 2. S1 findings ranked (visitor impact × count)

Weight 3: the headline price is wrong, or a compatibility spec (socket, chipset, memory type) is wrong. Weight 2: two parts in one product, wrong category, or another wrong spec. Weight 1: a non-headline offer row, or medium confidence with little effect on choice. Score = weight × count.

| # | What the visitor sees | Lanes (duplicates merged) | Count | Score | Confidence | Silent | Cluster |
|---|---|---|---|---|---|---|---|
| 1 | Best price is a TMS/Yahav **bundle-only** offer, shown as a plain price | 06 F1; overlaps 01 S2-4 (10 Yahav `-PC` copies) | 149 products (139 TMS, 10 Yahav) | 447 | medium (is the price conditional? not verified) | yes | H |
| 2 | **Contradicting compatibility specs**: AM5/LGA1200/LGA1700 socket on Intel/AM4 boards (4); chipset X670 or X870 on X870E boards, B550 on a B450, H510/H470 on H410 boards, X670E on an X670 (8); DDR6 and GDDR4 on GPUs (3); `thread_count` below `core_count` (10) | 04 S1-a (4 of 12) = 05 F04; 05 F03, F05, F02 | 25 products | 65 | high (F04 medium) | yes | F, G |
| 3 | **Wrong category**: AIOs in `other` / `cooler_air`, fan kits in `accessories`, glass panels and servers in `case`, kits, LCD modules, a bracket, a controller, a cage and water blocks in part categories | 03 F1–F6, F8–F11, F13 | 31 products | 62 | high | 29 of 31 | I |
| 4 | **Two variants in one product** (colour, lighting, blade, finish, GPU model); on 6 of them the best offer is the other variant (C5 Curve 404, GX-1200 1091, GSK850V2 426, 100R 545, A13 413, 9070 3190) | 01 S1-1, S1-3 = 02 F-01, F-10…F-17; 02 F-13 = 01 S3-6; 02 F-05 | 24 products | 54 | high (F-05 medium) | mostly flagged; F-05 silent | A, A2 |
| 5 | **Superseded TMS price** from the 03:33 crawl while the 21:25 crawl had moved on; 11 are the headline best offer | 06 F2 = 07 F1 | 25 listings | 47 | high | yes | E |
| 6 | **E-suffix chipset folded** (B650E → B650, X870E → X870) | 05 F09 | 37 boards | 37 | medium (could be the vendor's label) | yes | F |
| 7 | Other specs that contradict the title: 8000 GB for 7.68 TB (2), 512 MB cache for 256 MB (1), `includes_cooler` true where the box says no cooler (1) | 05 F06, F07; 03 F12 | 4 | 8 | high (F12 medium) | yes | F, G |
| 8 | **Box and Tray in one product** (14600K, 14900K, 7500) | 01 S1-2 (14600K), 02 F-06, F-07, F-19 | 3 (+ 245KF disputed, §6) | 6 | high | flagged | F, D |
| 9 | **Other brand's fan** is the best offer (Arctic F12 at 24, P14 at 32, both stale KSP) on Antec products | 02 F-03, F-04 | 2 | 6 | high | flagged | C |
| 10 | **Glass panel** (95) is the best offer of the NX410 case | 01 S1-4 = 02 F-02 | 1 | 3 | high | flagged | I (B) |

**Dead links:** none confirmed. 06 F5 has 40 TMS `?product_id=` URLs that were not checked offline. If they don't resolve, they become S1.

**Spot-check (step 4).** Every S1 count was re-run from the lane's own script, and all reproduce:

| Lane | Script | Reproduced counts |
|---|---|---|
| 01 | `scan2_multi_pn.py` | 147 multi-PN, 93 distinct, 90 distinct-unsplit, 21 silent |
| 03 | `s8_counts.py` | F1 5, F2 4, F3 4, F4 6 |
| 04 | `scan_brand_vocab.py` | 207 empty, 110 vocabulary hits |
| 05 | `scan_contradictions.py` | C1 threads < cores: 10 |
| 06 | `s06_stock_bundle_urls.py` | 206 best offers bundle or new-PC, 81 no-priced products |
| 07 | `s02c_tms_two_crawls.py` | 72 differ, 25 superseded |

Two counts were also recomputed from `data/catalog.json` directly:
- 149 `bundle_only` + 57 `new_pc_deal` best offers.
- 25 superseded TMS rows, of which 11 are the best offer.

Lane 04's builder writes into `docs/`, so it was not run. Instead, its 12 S1-a rows were read back against the catalog: all 12 have a null chipset (`onepc_source.py`).

Two examples per S1 finding were checked directly in the data (`spotcheck_s1.json`, 31 checks). All reproduce, including the raw TMS lines:
- `11348-03-20G`: line 202 = 3750 at 03:33, line 2415 = 4573 at 21:25.
- `CP32G56C46U5`: line 319 = 2079, line 2535 = 2167.

The lane scratch outputs were hashed before and after the re-runs. Only `07-raw-fidelity/s02c_out.json` changed, and only in key order (set iteration). **No S1 finding failed to reproduce.** Two lane claims were corrected:
- 04 S1-a: only 4 of its 12 boards show a wrong value (§6).
- 05 F03: 8 boards, not 5. All 8 contradict the title or another vendor.

## 3. Root-cause clusters: rules and fix order

Each cluster is stated as one general rule. The rule names no product, so it also covers products this audit never saw. Every rule was prototyped read-only against the pinned catalog. The scripts are in `tmp/data-audit/00-consolidation/rules/` (`rule_e.py`, `rule_h.py`, `rule_a2.py`, `rule_axis.py`, `rule_i2.py`, `rule_fg.py`, `rule_misc.py`), and each writes a `*_out.json`.

- **Caught** = audit instances the rule flags.
- **False alarms** = flags on the current catalog where the data is in fact right.
- **Check types:**
  - **Hard gate:** a `scripts/check_*.py` that exits 1 and fails `normalize-and-deploy`.
  - **QA flag:** an `identity_merge`, `spec_conflict` or `duplicate_vendor` case.
  - **Budget:** a count that may not grow.

### 3.1 Fix order

**Ranking key:** first S1 instances caught, then future scope (what the rule watches on every build), then S2/S3 counts.

**F/G still comes before A.** The bad vendor attributes that F/G removes feed the identity axes that A splits on.

**`scripts/check_identity_merge.py` exits 0** on the pinned catalog (I1 on 1906 products, I2 on 4201 identities, I3 on 216 CPUs), but it is not in `normalize-and-deploy.yml`. Add it to the workflow before order 4, then add A's rule to it as a fourth invariant.

| Order | Cluster | Rule (short) | Check | Caught now | False alarms now | Future cases prevented |
|---|---|---|---|---|---|---|
| 1 | **H** bundle | A conditional offer never outranks a plain one. When it is the only offer, it ships labelled. | Hard gate + QA | 149/149 (S1) | 0 | Every flagged offer from any vendor: 220 TMS flags today, plus the Yahav `-PC` bundle listings |
| 2 | **F/G** spec vs title | A shipped value agrees with some title that states the field, and it passes the physical invariants, whatever tier it comes from. | Hard gate (invariants) + auto-fix when ≥2 sources agree + QA (single source) | 48 product-level (13 gate, 19 auto-fixed, 16 to QA) + 4 listing-level sockets (S1) | 0 gate / 0 auto-fixed / 3 QA | Every value of 7 fields, from any vendor, reference, catalog, override or derive source, on every build |
| 3 | **I** category | A listing goes to the category of what its title says it *is*, and one maker PN sits in one category. | Hard gate | 30/31 (S1) | ≈0 | Every new listing with an is-a word, and every maker PN that crosses categories |
| 4 | **A** identity split | One vendor, two listings, two different maker identifiers of one kind = two parts. | Hard gate (`check_identity_merge.py` I4) | 22/26 labelled + 5/6 ambiguous; 28 catalog-wide (S1) | 0 after the `GV-` fix (0/112 correct merges) | Every product where one vendor prints two maker PNs or two EANs |
| 5 | **E** one crawl per day | Each vendor gets one crawl per snapshot day, and every listing reads its newest `scraped_at` row. | Hard gate | 25/25 (11 S1, 14 S2) | 0 over 290 vendor-days | Any vendor, any day, any double run |
| 6 | **P** same-vendor duplicates | One vendor gives one offer per part. Vendor decoration (`-PC`, clearance prefix) is not identity. | QA (`duplicate_vendor`) | 32/32 (S2/S3) | 0 confirmed; 11 unverified groups | Every repeated or decorated listing |
| 7 | **A2** axis vocabulary | Every known colour, finish, lighting or size word is an axis value, and the GPU chip model is a GPU axis. | QA (`identity_merge`) | 8/31 + 2 real extras | 3 | Every axis word added to the tables |
| 8 | **J** text hygiene | No shipped string holds an entity, a bidi control or NBSP. | Hard gate | 52 entity + 23 bidi values in 40 products, plus 9 site files | 0 expected | All vendor text |
| 9 | **N** empty brand | An empty brand takes the one catalog brand named in the product's own name. | Budget + QA | 110/110 (S2) | not hand-checked; 13 sent to QA | Every new product with an unknown brand alias |
| 10 | **D** packaging | A CPU offer whose title states Box/Tray sits in a product of that packaging. | Hard gate | 6/6 at pair level + 3 real extras | 0 | Every CPU move |
| 11 | **C** brand join | Offers join only if their brands agree after a brand-family table. | Hard gate | 2/2 | 0 with the family table (14 without) | Every code-only join |
| 12 | **M** schema | Every vendor value for a schema-keyed field is a known key or an explicit unknown. | Hard gate | 17 rows + 3 C621A boards | 0 | The next chipset generation and every enum value |
| 13 | **O** count parser | No count is read from a digit that is part of a decimal number or a dimension. | Fixture gate | 12 values / 8 products | 0 | 11 other count regexes in `vendor_struct.py` with the same shape |
| 14 | **K** pid stores | Every pid-keyed store resolves through `pid_aliases` when it is read. | Hard gate + budget | 28 (gate); 277 + 1,127 + 16 (budget) | 0 | Every future rekey |
| 15 | **L** ledgers | Every ledger entry points at something live and changes the output. | Hard gate (overrides) + budget | 1 dead + 3 aliased overrides; F6–F12 (budget) | 0 | Every rekey and every listing that drops out |
| — | **V** live checks | No rule. | Owner or Nano | — | — | — |

### 3.2 Rules per cluster

#### H: conditional offers (1)
- **Rule (owner answer Q1):** an offer whose price depends on a condition never outranks a plain offer for the same product. Conditions include a bundle with a PC, a new-PC deal and "with purchase of". The product shows the full price of its cheapest plain offer. A conditional offer gets a small green chip, and hovering it shows the conditional price. The vendor's flag decides; a deal phrase in a title without the flag becomes a QA case.
  - **No full price held:** a bundle offer carries one price, the bundle price. Only 3 of the 234 have a separate `price_promo_ils`. So for the 129 products whose only offers are bundles, the shown price is the bundle price, with the chip on it. The chip says "with a PC purchase", not "discount": a visitor cannot buy the part alone at that price.
- **Where:**
  - `scraper/matching.py` `choose_best_offer` (L4718) does the ranking.
  - `site_data._trim_offer` keeps `bundle_only` and `new_pc_deal`.
  - The site renders the chip and its hover, using the existing "Bundle only" i18n string.
- **Check:** hard gate (an extension of `check_publish_set.py`). No best offer is `bundle_only` while a plain offer exists, and every shipped `bundle_only` offer still carries its flag. **Caught 149/149, 0 false alarms.**
  - In 20 products a bundle price beats a plain offer. The shown price is too low by a median of 100 ILS (max 510 ILS).
  - 129 products have only bundle offers and ship them unlabelled.
  - QA flag: a deal phrase with no flag (1 Yahav offer today).
- **Ledger-only:** none.
- **Rejected:**
  - Detecting bundles from the title phrase. 220 flagged TMS offers have no phrase and would be missed.
  - Deleting bundle offers. 129 products would lose their only offer (owner Q1: label them instead).

#### F/G: a spec value against the product's own titles (2)
- **Rule:** a shipped spec value must agree with at least one of the product's titles that states that field, and it must pass the physical invariants. A title that states nothing is never evidence. The rule applies to every tier (vendor, reference, catalog, override, derived), so it covers both F (a vendor attribute wins) and G (a higher tier wins).
  - **When a title may change the value (owner answer Q4, "as long as we can rely on it"):** each vendor counts once, whether through its title or its attribute. The value is changed automatically only when at least two independent sources agree against it and no invariant breaks. The sources can be two vendors' titles, or one title plus another vendor's attribute or the reference. A contradiction with only one source behind it becomes a QA flag, not a change.
  - **Why one source is not enough** (`rule_fg_trust.py`):
    - The Lexar Thor listing has a Yahav attribute DDR5 and a Yahav title DDR4. "Its own title wins" would ship DDR4 on a 6000 MHz CL40 kit, which is wrong.
    - On the two RTX 5050 cards, Yahav's title and Yahav's attribute both say GDDR7, while 1PC says GDDR6 (right). That is one vendor against another, so no change.
  - **What it changes today:** of the 38 title-witness flags, 19 have titles from two or more vendors agreeing. All 19 are real chipset errors, so nothing wrong is changed. The 19 single-source flags (16 real, 3 false) go to QA.
  - At listing level, the 4 wrong 1PC sockets of 04 S1-a are each contradicted by the 1PC title and by TMS, so they qualify.
  - **Witnessed fields:**
    - Chipset.
    - Socket. A chipset in the title outranks a socket word, and is read through its `CHIPSET_INFO` socket.
    - Storage capacity, with a 1.024× tolerance.
    - Memory type on boards, memory and GPUs. The GPU `G` prefix is ignored.
    - CPU packaging (boxed = box).
    - `includes_cooler`, from an explicit "ללא קירור" / "without cooler" in the title.
  - **Invariants:**
    - `thread_count ≥ core_count`.
    - GPU `memory_type` must be a real GPU memory standard (GDDR3/5/5X/6/6X/7, HBM*, DDR3/4/5).
- **Where:**
  - Listing level: `scraper/specs/build.py` `listing_facts` (L68).
  - Product level: `scraper/specs/validate.py` `cross_check` (L180). It must drop whichever of socket and chipset the title contradicts; today it always drops the chipset.
  - Invariants: validator checks.
- **Check:**
  - **Hard gate, invariants** (new `scripts/check_spec_invariants.py`): **13 flags, 13 real.**
    - Threads 10/10 = 05 F02: 5 from the reference tier, 5 from vendors.
    - GPU memory 3/3: 2 × GDDR4 = 05 F05, one of them locked by override `mpn:gpu:4711377107549`; 1 × DDR6.
  - **QA flag `spec_conflict`, title witness:** **38 flags, 35 real, 3 false.**
    - Chipset 25: 05 F03 8/8 plus 19 E-suffix folds from F09, with 2 boards in both.
    - Socket 4: the 4 visible wrong sockets of 04 S1-a.
    - Capacity 3: 05 F06 × 2, plus WD23PURZ (1000 GB against a 2TB title).
    - Packaging 2.
    - `includes_cooler` 1 (03 F12).
    - The 3 false alarms are titles that are wrong: two Yahav RTX 5050 titles say GDDR7, and a Lexar Thor title says DDR4. This is why the witness is a QA flag, not a gate.
  - **Not caught at product level:**
    - 04 S1-a's 5 wrong 1PC chipsets. `cross_check` already nulls them; the listing-level drop is what restores the right value.
    - 05 F07, cache size: the field is not parsed. Add it.
    - 02 F-20 (speed), F-21 (memory type) and F-09/F-22 (colour). Another title of the same product agrees with the shipped value, so only the listing-level drop sees these. The listing level was traced but not prototyped.
  - **F09 correction:** only 22 boards carry an E chipset in a title, the name or the id, not 37. 19 are flagged. The other 3 are two EAGLE substring hits and `b650-e-gaming-tuf-wifi-atx-2`, whose titles mix B650-E and B650E-E (§3.3).
- **Ledger-only:** none.
  - The 3 wrong-title products are dismissed QA cases, not overrides.
  - The GDDR4 override is a cause to fix, not an exception.
  - B650E/X870E stay distinct from B650/X870 (owner answer Q5), so the vendor-label fold that F09 found is a bug to fix, not a mapping.
- **Rejected:**
  - The title always wins, or "a vendor's own title beats its own attribute". Either would write DDR4 on the DDR5 Lexar kit, and the first would also write GDDR7 on two GDDR6 cards.
  - A vendor majority wins. 1PC copies TMS codes (decisions.md line 30), so two agreeing vendors can be one source.
  - A title that omits a value counts against it. Most titles state 2–3 fields.
  - Always dropping the chipset in `cross_check` (today's behaviour). It keeps the wrong socket on 4 boards.

#### I: category from what the item is (3)
- **Rule:** a listing goes to the category of what its title says it *is*, not what it fits. The is-a words are: panel/glass "only/בלבד", fan kit (ערכת/יחידת מאווררים), module, bracket, drive cage, water block / custom loop, barebone/server, controller / Lighting Node, and water-cooling words (קירור מים, liquid). Separately, one maker PN sits in one category: when two products share a maker PN across categories, one of them is wrong.
- **Where:**
  - The classifier rules in `scraper/matching.py` (~L396–650: `_HEBREW_LIQUID_RE`, `_FRAME_ACCESSORY_RE`, and new is-a rules).
  - One fixture case per rule in `scripts/check_categories.py`.
- **Check:** hard gate, as a catalog pass added to `check_categories.py`. **Caught 30/31.**
  - It is the union of two parts:
    - **I-1:** a maker PN of ≥6 characters, not a retailer number, appears in two categories.
    - **I-3r:** the is-a words.
  - How I-3r decides:
    - The panel rule fires on any single listing.
    - The other words need half of the product's titles.
    - Controller, kit and bracket words are skipped when a title of the product names a fan.
    - "תאימות לתושבת" ("fits the bracket") does not count as a bracket.
  - It flags 38 products. The 8 not in the audit are the correct-category partners of I-1 pairs, so false alarms are ≈0. I-3r alone catches 27/31 with 0 extra.
- **Ledger-only:** `model:cooler_air:a21da-d36m-elw-r1`. It has one 1PC listing with the generic title "קירור למעבד". The only evidence that it is an AIO is Cooler Master's code grammar (`ELW-D36M`). This is the one miss of 31.
- **Rejected:**
  - **I-2, head-noun vote:** 0 caught, 54 extra. מארז, מאוורר and כרטיס name both the item and the part it fits.
  - **I-2b, an unseen head phrase:** 6 caught, 13 false. Use it as a report only; it found one possible case, a Lenovo ThinkSystem M.2 RAID adapter in `storage`.
  - **I-5, maker-code family vote:** 11 caught, all already in the gate, and 12 false. FD-, CW- and TUF- span a maker's whole range.

#### A: two maker identifiers from one vendor = two parts (4)
- **Rule:** when one vendor has two listings in one product, and they carry two different identifiers of the same kind (two maker PNs, or two EANs), the product holds two parts and must split.
  - Retailer codes do not count: all-digit ids under 8 digits, and TMS CPU codes `^C(?:\d{3,5}|ULTRA)\w*[TB]$`.
  - Codes are compared after `mpn_part_key` / `_strip_gv_prefix`, so Gigabyte's `GV-` prefix is not a difference.
- **Where:** `scraper/identity.py` `part_number_class` / `part_number_subgroups`, and an I4 invariant in `scripts/check_identity_merge.py`.
- **Check:** hard gate.
  - Against lane 01's labels: 22/26 true splits caught, 0/112 correct merges flagged, 5/6 ambiguous pairs flagged.
  - Catalog-wide there are 28 hits. The only class of false alarm is `GV-`, which the comparison above removes.
  - The 4 misses belong to other rules: the NX410 panel (I), NH-D15 HBC/LBC (F/G), and 14600K and 245KF (D).
  - Run it through the golden gate and `report_identity_delta.py` under several hash seeds before merging.
- **Ledger-only:** none. The owner's Q3 answer ("two different versions are two products") settles the 5 ambiguous splits without a maker page: D200L/P200L, TL-M10 FAN4-C/M (×2), Gammix SBKD35P/35 and A750BN. Each has two codes, so each becomes two products.
- **Rejected:**
  - Splitting on any two codes. It flags all 112 correct merges, where a vendor prints a maker PN and its own SKU.
  - A strict title-axis rule as the split condition. It catches 2.
  - A looser title-axis rule as a gate: 16 true, 5 false. It is kept as A2's QA flag.

#### E: one crawl per vendor per day (5)
- **Rule:** each vendor gets one crawl per snapshot day. For every listing key, the offer price, the stock and the history point all come from its newest `scraped_at` row: never the lowest price, never the first row. The rule works on rows, so any vendor's future double run is covered.
- **Where:**
  - Cause: `nano/run_tms.sh`. The night run must honour the day's success marker, then write `.part` and replace.
  - Read side: `matching.dedupe_enriched_listings` and `build_price_history._load_snapshot_prices`.
- **Check:** hard gate (new, for example `scripts/check_snapshot_rows.py`). For every repeated key in a vendor-day file, the offer price must equal the newest row. **Caught 25/25 (07 F1 = 06 F2), 0 false alarms over 290 vendor-days.**
  - A warning line reports vendor-days whose repeats come from two separate runs. Today there is 1: TMS 2026-11-09, 2204 keys, 18 h apart.
  - Repeats inside one crawl are normal: one listing appears on two category pages (435 keys over 128 vendor-days). Their 19 price differences are all on one old 1PC day, and the newest-row rule settles them too.
- **Ledger-only:** none.
- **Rejected:**
  - Lowest price wins (today's offer rule). On 11-09, 67 keys changed price between the two crawls, and the offer shows the superseded price on 25 of them.
  - First row wins (today's history rule).
  - Dropping a vendor-day that has two crawls. That loses the newest prices. Owner Q2 decides only whether the second run is kept.

#### P: one offer per vendor per part (6)
- **Rule:** one vendor gives one offer per part in a product. When two listings of one vendor in one product differ in no identifier and no axis, they are one offer, and the other listing is kept as a logged alias. Vendor decoration is stripped before comparing, across products too: the `-PC` SKU suffix and the clearance title prefix "מציאון ועודפים". MPNs under 5 characters are not used as a key. The plain listing is the offer. A `-PC` listing is a conditional offer under H, so it never lends its price.
- **Where:** `matching.dedupe_enriched_listings` and the offer list in `site_data`. `vendor_count` keeps counting vendors (owner answer Q10). The fix is that a vendor also shows only one offer.
- **Check:** QA flag, the existing `duplicate_vendor` kind. **Caught 32/32** (01 S2-4 18, S2-5 S 8, S3-6 M 6).
  - The decoration key catches 17.
  - The same-vendor rule catches the other 15. In each, one listing carries a retailer number (Corsair 2154xx/2223xx, TMS C-codes) and the other a maker PN.
  - The key forms 71 groups: 50 within one product and 21 across products. 11 of the cross-product groups look like real duplicates that the audit did not list (§3.3).
  - It is a QA flag, not a gate, because sellers reuse one title for two parts (Tray at 1178 and 1938 ILS under one title).
- **Ledger-only:** none.
- **Rejected:**
  - Merging on title alone. It hides the 14600K Tray price pair, which may be two parts.
  - Stripping `-PC` and merging the prices. That would show the bundle price as a plain price.

#### A2: axis vocabulary (7)
- **Rule:** every colour, finish, lighting or size word that the title readers know, in Hebrew or English, is an axis value. The GPU chip model (9070 vs 9070 XT) is a GPU axis. Two offers whose titles state different values on one axis are two parts, unless they share one maker PN.
- **Where:** `identity._compact` and the axis tables in `scraper/identity.py`.
- **Check:** QA flag `identity_merge` (title-axis conflict). **Caught 8/31** of the axis instances (01 S3-6 V pairs, 02 F-05, F-13, F-23).
  - 5 extras: 2 are real (argb-t5-white, 14900KF) and 3 are false (2 from the GPU regex, 1 Dominator).
  - The shared-maker-PN exemption should remove the false ones, but this was not re-measured.
  - The catch is low because most misses need the word added to the vocabulary first (אגוז, Aventurine). The flag is the backstop.
- **Ledger-only:** none. The owner's Q3 principle settles the old Q7 maker-page checks:
  - Antec Performance 1 M Black and Aventurine (02 F-14): two titles, two EANs, two products.
  - MSI A750BN PCIE5 III and the original A750BN (02 F-18): two EANs, two products.
  - ASUS Prime RX 9070 and "9070 XT" (02 F-05): one card. The owner checked: all three offers are the RX 9070 OC, and the TMS "XT" title is wrong. The shared maker PN `90YV0L71-M0NA00` keeps them together; the axis disagreement is a QA case, not a split.
- **Rejected:**
  - Stripping axis words from model codes. This is R2 in `docs/duplicate-groups-audit.md`, measured and rejected in the 2026-11-07..08 work: 2 merges for 322 renamed pids. The 2712-of-4232 count does not change that, so the phase 1 fix text for A2 is withdrawn.
  - Any colour-word difference as a gate. 3 of the 5 extras are false, and vendors write two-tone parts as "שחור/לבן".

#### J: text hygiene (8)
- **Rule:** no shipped string holds an HTML entity, a bidi control (U+200E/U+200F/U+202A–202E/U+2066–2069) or NBSP. Entities are decoded with or without the trailing `;`.
- **Where:** title normalisation and `_merge_detail_specs` (decode and strip), and the Yahav `real_sku`.
- **Check:** hard gate over `data/catalog.json` and `data/site/*.json` (new `scripts/check_text_hygiene.py`).
  - Catalog: entities in 27 products (52 values; lane 05 counted 42 in the model fields), bidi marks in 13 products (23 values), NBSP 0.
  - Site files, entities: `case_fan.json` 66, `qa.json` 39, `spec_report.json` 27, `cpu_cooler.json` 22.
  - Site files, bidi: `memory.json` 10, `psu.json` 10, `storage.json` 4, and `case.json`, `case_fan.json`, `index.json` 1 each.
  - The entity pattern accepts only numeric entities and the six named forms, so a plain `&` in a name does not fire. 0 false alarms expected.
- **Ledger-only:** none.
- **Rejected:** decoding only at site build. The bad values would stay in the catalog and in `qa.json`.

#### N: empty brand (9)
- **Rule:** a product with an empty brand whose own canonical name names exactly one catalog brand takes that brand. A catalog brand is a brand on ≥2 products with ≥3 characters, matched as a whole word. When the name holds two or more, the earliest match wins and a QA case is opened.
- **Where:** the brand step in normalize, as a fallback after `BRAND_ALIASES`.
- **Check:** budget: the empty-brand count may not grow (207 today, about 97 after the fix). **Caught 110/110 of 04 S1-b (S2).**
  - 13 names hold two brands and go to QA.
  - The 97 single-brand hits were not checked by hand.
- **Ledger-only:** none.
- **Rejected:**
  - The first Latin word of the title. Hebrew titles often name the host part ("מאוורר ל-…").
  - Growing `BRAND_ALIASES` by hand. Its 57 entries are why 110 products are empty.

#### D: CPU packaging (10)
- **Rule (owner answer Q3):** Box and Tray are always two products. A CPU offer sits in the product of the packaging that its own vendor states, and nothing moves it out.
  - Equal price and equal tags no longer count as proof of a mislabel; that becomes a QA flag only. This replaces the move in decisions.md line 29.
  - When the listing states no packaging, the maker's own part number decides: Intel `BX…` = Box, `CM…` = Tray; AMD `…BOX` = Box, `…MPK`/bare = Tray.
  - With no label and no part number, the offer joins the Box product (the retail default) and is flagged. This default is a proposal, not an owner answer.
  - A retailer `C…T` code that one vendor copies from another is never evidence.
- **Where:** the packaging move in `scraper/identity.py` (decisions.md line 29), with I1/I2 also run on manual products (line 34).
- **Check:** hard gate. **7 flags.**
  - 4 of the 6 instances are caught directly. The other 2 are the Tray partners of 14600K and 14900K, so all 6 are caught at pair level.
  - The 3 extras are real (14600k-2, 14600kf-2, 14900kf).
  - 0 false alarms.
- **Ledger-only:** none. KSP 340400 (245KF) now stays where KSP's own label puts it.
- **Rejected:**
  - Sibling-count direction, and the equal-price move (today's rule). It moves the 245KF against its own listing, and the owner wants Box and Tray kept apart.
  - A 1PC `C…T` code as Tray evidence. 1PC copies TMS codes onto Box listings (`C7500T-P`).

#### C: brands must agree before a join (11)
- **Rule:** two offers join only if their brands agree after a brand-family table that maps sub-brands to their maker: Lancool → Lian Li, AORUS → Gigabyte, XPG → ADATA, ROG → ASUS, and a chip brand to the board maker (NVIDIA → PNY). If one side has no brand, its title brand is used.
- **Where:** the code-only join in `scraper/matching.py` / `scraper/identity.py`.
- **Check:** hard gate. 16 products have offers that name two or more brands. **2/2 caught** (F12 and P14, Arctic against Antec). The other 14 are family aliases, so false alarms are 0 with the table.
- **Ledger-only:** none.
- **Rejected:**
  - Requiring a brand on both offers. KSP rows often carry none.
  - Exact string match on brands. That gives 14 false alarms.

#### M: schema values (12)
- **Rule:** every vendor value for a schema-keyed field is a known key or sits on an explicit unknown list. For chipsets the keys are `CHIPSET_INFO`; for enums, the enum. A label that maps to the wrong family also fails: C621A read as C621 gets LGA3647 instead of LGA4189.
- **Where:** `scraper/specs/schema.py` (`CHIPSET_INFO`, enums) and `validate.cross_check`.
- **Check:** hard gate, with `SOC` (SoC boards) on the unknown list.
  - **Today 17 rows fail:** W880, HM65, H81, B75 and HM770 once each, and SOC 12. On top of these come the 3 Supermicro X12SP boards (C621A).
  - 0 false alarms.
  - The enum gaps `80+`, `2U` and `CEB` (04 S2-c) fall under the same rule.
  - The next chipset generation fails on its first listing instead of being nulled silently.
- **Ledger-only:** none. **Owner answer Q5:**
  - Real chipsets are added without asking. W880 (LGA1851), HM770 (mobile, Raptor Lake), HM65 (mobile, LGA1155-era), B75 (LGA1155), H81 (LGA1150) and C621A (LGA4189) are all real Intel chipsets, so all six go into `CHIPSET_INFO`.
  - The E chipsets stay distinct.
  - Left to my call:
    - `80+` (the base "80 PLUS" PSU rating, below Bronze), `2U` (a rack-server case height) and `CEB` (a server board size) are real values, so they join the enums.
    - `pcie_x4_slots` is kept and added to the schema, because vendors already send it and dropping held data goes against Q2.
- **Rejected:**
  - Mapping an unknown label to the nearest key. H81 would become H810, on the wrong socket.
  - Silent drop (today's behaviour).

#### O: counts never come from a decimal (13)
- **Rule:** no count is parsed from a digit that is part of a decimal number or a dimension (`2.5"`, `3.5"`, `5.25"`).
- **Where:** `scraper/specs/resolvers/vendor_struct.py` `_emit_drive_bays` (L703–718; the faulty pattern is at L709). The same `(\d{1,2})` start with no `(?<![\d.])` guard appears at 11 other places: L153, 161, 162, 321, 403, 485, 901, 1012, 1036, 1239 and 1413. These were not checked for live misfires.
- **Check:** fixture gate, as cases with `2.5"` and `3.5"` rows in an existing check script. **Caught 12 Ivory values on 8 products** (05 F01, `drive_bays_fix_delta.json`). 0 false alarms.
- **Ledger-only:** none.
- **Rejected:** an Ivory-only special case. The same pattern parses every vendor's table.

#### K: pid-keyed stores follow aliases (14)
- **Rule:** every store keyed by product id resolves through `pid_aliases` when it is read, so a rekey never orphans a fact.
- **Where:** `scraper/extract/store.py` `_candidate_ids` (L73), and every other pid-keyed ledger reader.
- **Check:**
  - **Hard gate** in `check_extract.py`: no trusted alias-keyed fact is left unapplied. 08 F1 = 28, 0 false alarms. Of 08 F2's 21, 16 are `cross_check` / `CHIPSET_INFO` drops (F/G, M).
  - **Budget:** gone pids with no alias (F4 277), untrusted facts (F5 1,127) and quotes that fail the verbatim check (F3 16).
- **Ledger-only:** none. **Owner answer Q9 (my call):**
  - Prune the 277 entries whose pid is gone with no alias, and the 16 facts whose quote fails the verbatim check. The wrong PSU colour fact is one of the 16.
  - Keep the 1,127 untrusted facts. Once aliases resolve, they become reachable and can be reviewed for the trust list; deleting them would throw away held data (Q2).
  - Make the 28 alias-keyed trusted facts apply.
- **Rejected:** rekeying the store on every normalize. It would rewrite a git-tracked ledger every day, while the aliases already carry the mapping.

#### L: ledgers point at live data (15)
- **Rule:** every ledger entry points at something that exists now and changes the output.
- **Where:** a reconcile check over `overrides.json`, `manual_products.json`, blocked pairs, `qa_dismissed`, the enrichment files and the image directories.
- **Check:**
  - **Hard gate** for overrides: the dead override `mpn:gpu:100505849` (05 F12). The 3 alias-keyed overrides (08 F9) are applied through the MPN fallback, so they warn instead of failing.
  - **Budget/report:** gone manual pids (F6, 4), the stale blocked pair (F7, 1), stale dismissals (F8, 2), orphan enrichment (F10, about 1,500), orphan images (F11, 565 plus 1 blocklist entry) and detail-ledger drift (F12).
- **Ledger-only:** none. Pruning needs owner approval.
- **Rejected:** auto-prune on build. A listing absent for 14 days can come back (the F6 listings were last seen Sep–Oct).

#### V: live checks (—)
There is no offline rule. Two checks are left, both on the vendors' public pages. Opening them in a normal browser is enough, and unpushed repo work does not affect them:
- 06 F4: `https://1pc.co.il/web/product/206013` (Lenovo ThinkSystem 32GB RDIMM). Does the page really ask about 5,800 ILS? The day before it was 1151.
- 06 F5: does `https://tms.co.il/computer-hardware-components/motherboards?product_id=103905` open the Asus PRIME A520M-A page? If it does, all 40 such links are fine.

02 F-05, F-14 and F-18 are settled by owner answer Q3 (A2). 07 S-a (KSP tag order) is latent and needs no check.

#### Ledger-only, all clusters
1 entry: `model:cooler_air:a21da-d36m-elw-r1` (I). The owner's answers removed the other 8.

### 3.3 Unverified finds the rules surfaced

These are not in any lane report. Each needs a hand check before it is fixed.

- **Identity (A2):** `argb-t5-white` and the 14900KF products hold offers whose titles state different axis values.
- **Packaging (D, F/G):** `model:cpu:14600k-2` and `model:cpu:14600kf-2` are Box products with a 1PC "Tray" title.
- **Capacity (F/G):** WD23PURZ ships 1000 GB under a 2TB title.
- **Possible merge (F/G):** `model:motherboard:b650-e-gaming-tuf-wifi-atx-2` mixes B650-E and B650E-E titles, so it may be two boards in one product.
- **Category (I side finds):**
  - FD-A-BRKT-001, a bracket, filed in `storage`.
  - PowerColor bundles filed in `gpu`.
  - An IPPON M.2 adapter and a Lenovo ThinkSystem M.2 RAID adapter filed in `storage`.
- **Same-vendor duplicates (P), 11 cross-product groups:**
  - The KSP iCUE LINK cable kit, sold at 139 and in clearance at 106.
  - Two iCUE LINK 2×100 mm cable products, at 39 and 65.
  - The TMS NR200P.
  - The 1PC Air 5400 RS-R and LX-R.
  - The 1PC 12700F.
  - The 1PC 14600K Tray, at 1178 and 1938 ILS under one title.
  - The 1PC 14900KF Tray.
  - The TMS G.Skill and Dominator pairs.
- **Bundle flag (H):** one Yahav offer has a deal phrase in its title but no flag.

### 3.4 Cause and one fix per cluster (phase 1 detail, in the new order)

| Order | Cluster | Cause (traced unless marked) | One fix | Clears |
|---|---|---|---|---|
| 1 | **H: bundle and new-PC offers win best price** | `choose_best_offer` ignores `bundle_only`. `site_data._trim_offer` drops `bundle_only` and `new_pc_deal`. The i18n "Bundle only" label is never rendered. | Rank `bundle_only` after plain offers in `choose_best_offer` (or exclude it, per owner Q1). Keep the flag in `_trim_offer` and render the label. | 06 F1 (149), 04 Q5, the Yahav `-PC` bundle side of 01 S2-4. |
| 2 | **F: a single vendor attribute contradicts its own title and the other vendors, and wins** | The vendor tier takes one vendor's value; which vendor wins was not traced. **9 of 04 S1-a's 12 boards trace to the 1PC attribute:** wrong socket on 4 (AM5 on Z890 and B550, LGA1200 on H610, LGA1700 on H810; TMS right on each), wrong chipset on 5 (B760 on 2 × B840, H610 on H510 and H81, Z790 on Z890; TMS right where listed). `cross_check` then drops the chipset and keeps the socket, whichever is wrong. 5 of 05 F03's 8 chipsets and the DDR6 also equal 1PC. The 1PC colour attribute is wrong on 22 of 862 comparable offers; decisions.md line 36 reads 1PC packaging from that colour field. Other vendors: TMS speed (02 F-20), TMS 8 TB (05 F06), Ivory DDR4 (02 F-21), Ivory 512 MB (05 F07), vendor chipset labels without the E (05 F09). | When a vendor attribute contradicts its own title, use the title and log the conflict. When vendors disagree, the value that agrees with the title wins. In `cross_check`, drop and flag whichever of socket or chipset disagrees with the title and another vendor, not always the chipset. | 04 S1-a (9 of 12); 05 F03 (5), F04, F05 (DDR6), F06, F07, F09; 02 F-07, F-09, F-20, F-21, F-22; 01 S1-2 (14600K). |
| 2 | **G: a higher tier beats agreeing vendor evidence, plus missing cross-field guards** | Reference tier: 14600K threads 12 against 1PC's 20 (5 CPUs), P-Prime X670E. Catalog tier: H510/H470 on H410 boards, GDDR4 on a D4 card. Override `mpn:gpu:4711377107549` locks GDDR4. Derived `cpu.lineup_box_cooler` ignores "ללא קירור באריזה". | Reference, override and derive cannot overrule the title plus ≥2 vendors. Guards: `thread_count ≥ core_count`, reject DDR6/DDR7 as GPU memory. Fix the override. An explicit title negation beats the lineup default. | 05 F02 (all 10 with the guard), F03 (3), F05 (2); 03 F12. |
| 3 | **I: classifier gaps (includes B: panel joins case)** | Hebrew "קירור מים" missing from `_HEBREW_LIQUID_RE`; `ML360` / `PL240` fail `\b360\b`; a generic 1PC title votes `cooler_air`; `_FRAME_ACCESSORY_RE` catches RX360 fan kits; no rules for panel-only, server/barebone, kit, LCD module, bracket, Lighting Node, drive cage or water block; "Ryujin" alone makes an AIO. Decisions.md line 37 says `other` must stay near-empty. | Add the rules listed in 03 §Out-of-lane, plus the matching `scripts/check_categories.py` cases (none of F1–F12 is covered today). A cross-vendor MPN that is already an AIO decides the category (owner answer Q3). Reclassifying the panel stops it joining the case product. | 03 F1–F6, F8–F11, F13; 01 S1-4 = 02 F-02 (B); 06's out-of-lane SSD coolers in `storage` (unverified). |
| 4 | **A: identity split blocked by part-number class** | `identity.part_number_class` returns "vendor" for a code equal to the vendor SKU, or all digits, so `part_number_subgroups` never splits. 133 of 141 unsplit multi-PN products are own-SKU and 8 are digits-only. Two strict EANs in one product do not split either. The 2026-11-10 rule in decisions.md line 30 (a code printed by ≥2 vendors is a maker PN) does not reach pairs that only one vendor prints. | Treat two distinct maker-shaped codes or two distinct EANs in one product as a split condition, and a `-W` / `-WHITE` / `-B` suffix pair as a colour axis. Run through the golden gate and `report_identity_delta.py` under several hash seeds. | 01 S1-1, S1-3, S2-5 (23 VC), S3-7; 02 F-01, F-10, F-11, F-12, F-14…F-18. |
| 5 | **E: TMS same-day double crawl** | The `nano/run_tms.sh` night run (timer 21:15 UTC) appends to `data/raw/<day>/tms.jsonl`. The success-marker check runs only when `RUN_TMS_FALLBACK=1`. `matching.dedupe_enriched_listings` keeps the lowest price and logs nothing. `build_price_history._load_snapshot_prices` takes the first row. Together these break decisions.md line 7 (1 run/day). | The night run honours the day's success marker, or writes `.part` and replaces. Dedupe by newest `scraped_at` and log the dropped rows. History reads the same row as the offer. | 06 F2, F3; 07 F1, F2, S-b. 25 prices, 11 headline, 42 chart points. |
| 6 | **P: same-vendor duplicate listings** | Yahav lists one MPN under a `-PC` SKU and a plain SKU. KSP clearance titles ("מציאון ועודפים") duplicate a listing. `vendor_count` counts vendors, not offers. | Dedupe same-vendor offers on the normalised SKU (strip `-PC`) and keep the other as a logged alias. Strip the clearance prefix before comparing. Flag the one silent pair. | 01 S2-4, S2-5 (8 same-part), S3-6 (6 M, 29 A); 07 F3 (its silent pair = 01 S2-4 `KF560C30BBEA-32X2`). |
| 7 | **A2: axis vocabulary gaps** | `identity._compact` drops Hebrew colour words (אגוז); finish names (Aventurine) are not a colour; the GPU model (9070 vs 9070 XT) is not a GPU axis; model codes keep colour, light and size words (2712 of 4232). | Map Hebrew colour and finish words into the colour axis; add the GPU chipset model to the GPU axes. (Stripping axis words from codes is withdrawn: it is the rejected R2, §3.2 A2.) | 02 F-05, F-13 (= 01 S3-6 4000D), F-23; the 28 V pairs in 01 S3-6. |
| 8 | **J: text hygiene** | The decode needs a trailing `;`, so `&#39;&#39` survives in 21 models (42 values, model + `specs.model`), against the claim in decisions.md line 117. U+200E/U+200F/NBSP come from vendor text and the Yahav `real_sku`. | Decode `&#39` with or without `;`. Strip bidi marks and NBSP in title normalisation and in `_merge_detail_specs`. | 05 F08 = 07 F4; 05 F10 ⊇ 07 F5; 07 F6. |
| 9 | **N: brand vocabulary** | The 57-entry `BRAND_ALIASES` is the bottleneck: 110 empty brands are named in the product's own canonical name. | Fall back to the catalog's own brand vocabulary (brands on ≥2 products), earliest match. | 04 S1-b. |
| 10 | **D: packaging and curated edge cases** | A 1PC Box listing carries the TMS tray code `C7500T-P` (1PC copies TMS `C…` codes, decisions.md line 30); the packaging move picks direction by sibling count (decisions.md line 29); manual products are exempt from I1/I2 (decisions.md line 34). | Owner decision first (Q3). Then require a shared maker PN or another vendor's label before a move, and run I1/I2 on manual products. | 02 F-06, F-08, F-19; 01 S1-2 (245KF). |
| 11 | **C: code-only join without brand agreement** | A KSP row with no MPN and no brand joins on `f12` / `p14` alone. | Require vendor or title brand agreement before a code-only join. | 02 F-03, F-04. |
| 12 | **M: schema and validator gaps (owner decisions)** | `CHIPSET_INFO` lacks HM770, W880, HM65, B75, H81 and C621A. The 3 X12SP boards (C621A, LGA4189) carry the vendor label C621, which maps to LGA3647, so `cross_check` drops it. Enums lack `80+`, `2U` and `CEB`. Prose passes the validator. `pcie_x4_slots` is outside the schema. | Extend the schema or leave the values null on purpose; parse or reject prose. | 04 S1-a (3 of 12), S2-a (= 08 F2, 4 rows), S2-c, S3-a; 05 F11. |
| 13 | **O: vendor-table parser bug** | `vendor_struct._emit_drive_bays` reads the `5` of `2.5"` as a count. | Add a `(?<![\d.])` lookbehind and replay Ivory. | 05 F01. |
| 14 | **K: extract store routing** | `extract.store._candidate_ids` does not resolve `pid_aliases`. | Resolve aliases in `_candidate_ids` (or rekey), then decide trust and pruning (owner). | 08 F1, F3, F4, F5; the 5 non-chipset rows of 08 F2 (unverified: stale build or K). |
| 15 | **L: ledger and reference hygiene** | Stale curated ids, blocked pairs, dismissals, overrides, orphan enrichment and images, ledger drift, `model` not filled from `specs.model`. | One reconcile pass (owner approval before any prune). | 08 F6–F12; 05 F12; 04 S3-c. |
| — | **V: needs a live or maker-page check** | Cannot be settled offline. | Check on the Nano or the maker site. | 06 F4 (1PC 1151 → 5756), F5 (40 URLs); 02 F-05 (shared MPN), F-14 (Aventurine), F-18 (A750BN revision); 07 S-a (KSP tag order, latent). |

## 4. Finding ledger (every lane finding)

"Cons." is the consolidated severity. "=" marks a cross-lane duplicate (one instance kept, both lanes cited).

**01 duplicates**

| Finding | Lane | Cons. | Cluster | Duplicate / note |
|---|---|---|---|---|
| S1-1 | S1 | S1 | A | = 02 F-01, F-10, F-11, F-12, F-14 (C5 Curve, C120 reverse 3PK, GX-1200, GSK850V2, Performance 1 M) |
| S1-2 | S1 | S1 (14600K) / disputed (245KF) | F / D | 14600K: same mechanism as 02 F-07, flagged per decisions.md line 31. 245KF = 02 F-08 (by design, decisions.md line 29) |
| S1-3 | S1 | S1 | A | = 02 F-15, F-16, F-17, F-18 (100R, A13, E360, A750BN) |
| S1-4 | S1 | S1 | I (B) | nx410 = 02 F-02; 1-ft-performance-midtower = 03 F4 |
| S2-4 | S2 | S2 | P | silent pair = 07 F3 silent; 10 products overlap 06 F1 (Yahav `-PC` bundle) |
| S2-5 | S2 | S2 | A (23 VC), I (1 VX), D (1 VP), P (8 S), V (4 A) | VC pairs are the vendor side of S1-1 |
| S3-6 | S3 | S3 | A2 (28 V), P (6 M + 29 A) | 4000D wood = 02 F-13 |
| S3-7 | S3 | S3 | A, V | A750BN = 01 S1-3 / 02 F-18 |
| R-1, R-2, R-3 | rejected | — | — | lane false positives (58 correct merges, 18 alias twins, token scan) |

**02 wrong merges**

| Finding | Lane | Cons. | Cluster | Duplicate / note |
|---|---|---|---|---|
| F-01 | S1 | S1 | A | = 01 S1-1 |
| F-02 | S1 | S1 | I (B) | = 01 S1-4 |
| F-03, F-04 | S1 | S1 | C | |
| F-05 | S1 | S1 | A2, V | silent; best offer is stale KSP 3190 (non-XT) |
| F-06 | S2 | S1 | D | Box + Tray = two products (decisions.md line 27) |
| F-07 | S2 | S1 | F | 1PC packaging label contradicts title and MPN |
| F-08 | S2 | disputed | D | by design (decisions.md line 29); = 01 S1-2 245KF |
| F-09 | S2 | S3 | F | the merge is right; only the id slug colour is wrong |
| F-10, F-11, F-12, F-14 | S2 | S1 | A | = 01 S1-1 |
| F-13 | S2 | S1 | A2 | = 01 S3-6 |
| F-15, F-16, F-17 | S2 | S1 | A | = 01 S1-3 |
| F-18 | S2 | S2 (ambiguous) | A, V | = 01 S1-3 / S3-7 |
| F-19 | S2 | S2 | D | flagged; curated absorb rule (decisions.md lines 31, 117) |
| F-20, F-21, F-22 | S3 | S3 | F | |
| F-23 | S3 | S3 | A2 | |

**03 misfiled**

| Finding | Lane | Cons. | Cluster | Duplicate / note |
|---|---|---|---|---|
| F1, F2, F3 | S1 | S1 | I | |
| F4 | S2 | S1 | I (B) | 1-ft-performance-midtower = 01 S1-4 |
| F5 | S2 | S1 | I | both servers also have no price (04 S2-b, accepted) |
| F6, F8, F9, F10, F11, F13 | S3 | S1 | I | F13 settled by owner answer Q5 |
| F12 | S2 | S1 (medium) | G | spec, not category |

**04 missing fields**

| Finding | Lane | Cons. | Cluster | Duplicate / note |
|---|---|---|---|---|
| S1-a | S1 | 4 S1 + 8 S2 | F (9), M (3) | all 12 = 08 F2; b550m-k = 05 F04; lane's "expected" chipset is the wrong 1PC value on 5 boards (§6) |
| S1-b | S1 | S2 | N | |
| S2-a | S2 | S2 | M | = 08 F2 (4) |
| S2-b | S2 | accepted | — | decisions.md line 36 (TMS price on request keeps None); 06 §6 says the same |
| S2-c | S2 | S2 | M | owner Q6 (EAN in `part_numbers`) |
| S3-a | S3 | S3 | M | |
| S3-b | S3 | accepted | — | deliberate blocklist, flagged |
| S3-c | S3 | S3 | L | |
| S3-d | S3 | not reproduced | — | lane's own low-confidence suspicion (isolated-pass artifact); not counted |

**05 wrong values**

| Finding | Lane | Cons. | Cluster | Duplicate / note |
|---|---|---|---|---|
| F01 | S2 | S2 | O | |
| F02 | S1 | S1 | G | 5 reference rows, 5 vendor rows |
| F03 | S1 | S1 | F (5), G (3) | 8 boards, not 5 |
| F04 | S1 | S1 | F | = 04 S1-a |
| F05 | S1 | S1 | G (2), F (1) | |
| F06, F07 | S2 | S1 | F | value contradicts the title |
| F08 | S2 | S2 | J | = 07 F4 (21 products × model + `specs.model` = 42) |
| F09 | S2 | S1 (medium) | F | |
| F10 | S3 | S3 | J | includes 07 F5's `CO-9050082-WW` |
| F11 | S3 | S3 | M | |
| F12 | S3 | S3 | L | |

**06 offers, prices**

| Finding | Lane | Cons. | Cluster | Duplicate / note |
|---|---|---|---|---|
| F1 | S1 | S1 (149) / not a finding (57) | H | new_pc_deal shows the regular price (lane §5) |
| F2 | S2 | S1 (11) / S2 (14) | E | = 07 F1 |
| F3 | S3 | S3 | E | |
| F4, F5 | S3 | S3 | V | F5 becomes S1 if the URLs are dead |

**07 raw fidelity**

| Finding | Lane | Cons. | Cluster | Duplicate / note |
|---|---|---|---|---|
| F1 | S1 | S1 (11) / S2 (14) | E | = 06 F2 |
| F2 | S2 | S2 | E | cause of F1 |
| F3 | S2 | S2 | P | 111 flagged; overlaps 01 S2-4/S2-5/S3-6 |
| F4 | S2 | S2 | J | = 05 F08 |
| F5, F6 | S3 | S3 | J | |
| S-a, S-b, S-c | suspicion | — | V, E, — | S-b is part of F1; S-c unverified, not counted |

**08 references**

| Finding | Lane | Cons. | Cluster | Duplicate / note |
|---|---|---|---|---|
| F1, F3, F4 | S2 | S2 | K | |
| F2 | S2 | S2 | — / K | 16 of 21 = 04 S1-a (12) + S2-a (4), dropped by `cross_check` / `CHIPSET_INFO`, so not a stale build; 5 remain unverified (2 colour, 2 usb_ports, 1 interface) |
| F5 | S3 | S3 | K | |
| F6–F12 | S3 | S3 | L | |

Every lane finding is now in a cluster, marked as a duplicate, accepted under a binding rule, or marked not reproduced (04 S3-d only).

## 5. Areas proven clean

- **Publish set:** `check_publish_set.py` passes. 4,383 products agree across the catalog, 11 category files, index, meta and spec_report. Site rows match the catalog, and every newest-snapshot listing is in the catalog (08).
- **Row accounting:** 0 bad JSONL lines for every vendor; 0 raw keys missing from listings; the snapshot choice matches the 14-day rule, and KSP 11-07 is stale as accepted; no promo lost on dedupe (07).
- **Keys and links:** every listing's product, every offer's listing and every product's offers resolve. `pid_aliases` (7,085) has no loops, no dangling ends and no cross-category hops (01, 07, 08).
- **Price rules:** null prices never reach a best offer or site min price. `best_offer`, site `min_price` and `in_stock` match the recomputed rules for every product. Freshness flags are consistent. There are no zero or tiny prices, rounding equals `normalize_price`, and Yahav "included in" zero prices are dropped. No URL is on the wrong domain or shared between products (06).
- **Spec schema:** 0 validation drops and 0 enum drift in shipped specs. Title vs spec is clean for radiator size, fan size, GPU memory size, memory CAS/speed/total/modules, PSU wattage/efficiency and PCIe gen (05).
- **Categories:** `check_categories.py` passes 43/43. 0 mismatches between offer `category_normalized` and product category. Site `cooler_type` is consistent (AIO = Water, air = Air). Rackmount chassis, portable SSDs and Minisforum boards are correct (03).
- **Identity:** strict EAN has no false bridges. 58 multi-PN products are correctly merged (R-1). No `rekey` pairs were found (01). The O11 Dynamic Mini V2 lead is clean (02).
- **Images:** no missing cover, no shared cover, and all 35 `image_dark_ok` files exist (08).
- **Missing fields:** the detail join is essentially clean. Only 16 of 6,740 applicable nulls are recoverable from held sources, which matches decisions.md (04).

## 6. Contradictions between lanes

1. **TMS double crawl severity.** 07 F1 rates it S1; 06 F2 rates it S2. **Resolution:** S1 for the 11 listings that are the headline best offer (a wrong price shown), S2 for the other 14. The counts agree: 06's 67 price pairs plus 5 stock pairs make 07's 72 differing keys.
2. **Colour-variant merges.** 01 rates them S1; 02 rates the same products S2 (F-10…F-18). **Resolution:** S1. The brief lists "two parts in one product" as S1.
3. **Misfiles.** 03 rates F4/F5 S2 and six findings S3; the brief lists a wrong category as S1. **Resolution:** S1, ranked by score in §2.
4. **04 S1-a "chipset that vendor and title agree on".** This holds on only 4 of the 12 boards. On 5, the dropped chipset is the wrong 1PC value and `cross_check` was right to drop it: B760 on two B840 boards, H610 on an H510 and an H81, Z790 on a Z890. On each of these the title says otherwise, and TMS, where it lists the board, agrees with the title. On 3 (Supermicro X12SP*, C621A), the vendor label C621 maps to the wrong socket in `CHIPSET_INFO`. Only the 4 wrong sockets are visible errors, and all 4 come from the 1PC attribute (`onepc_source.py`). Lane 04 left "where the socket came from" open; this closes it.
5. **04 S1-b brand empty.** Lane 04 rates it S1. By the scale it is S2 (held but lost; no wrong value shown).
6. **06 F1 new_pc_deal.** The finding counts 57 new-PC offers, but 06's own false-positive note says TMS keeps the regular price as the display price. Only the 149 `bundle_only` remain, still at medium confidence.
7. **04 S2-b vs 06 §6.** 04 reports 81 null-price TMS products as S2; 06 calls them known and accepted. **Resolution:** accepted under decisions.md line 36.
8. **01 S1-2 (245KF) vs 02 F-08 and decisions.md line 29.** The KSP 340400 → Tray move is the reference case of the packaging rule. 01 counts it as S1; 02 reports it only for the direction question. **Resolution:** disputed, owner Q3.
9. **08 F2 "likely stale build".** 16 of the 21 are explained by 04's `cross_check` and `CHIPSET_INFO` drops in the current code, so staleness is not the cause for those.
10. **05 F03 count.** The summary says 5 boards; the body lists 8. All 8 reproduce.
11. **05 F08 vs 07 F4.** 05 leaves the cause open. 07 ties it to the `;`-less entity form and to the decode claim in decisions.md line 117. Same instances.
12. **03 plonter "not wired back in".** Plonter was dropped 2026-09-29 with its code kept on purpose (decisions.md lines 20, 115). 08 F12 calls its ledger inert. Accepted, not a finding.

## 7. Questions for the owner

1. **TMS bundle tile price.** Is 70 NIS on `tms:1009115` the whole price or a price with a PC? The answer decides whether 06 F1 is S1 or S2, and whether bundle offers are excluded from best price or only labelled (06 Q2, 04 Q5).
2. **TMS 2026-11-09 second crawl.** Keep it, drop it, or treat it as the day's crawl? What started the 21:25 UTC run (06 Q3, 07)?
3. **Packaging move direction.** Should a Box/Tray move need a shared maker PN or another vendor's label, rather than a sibling count? This affects KSP 340400 and decisions.md line 29 (02 F-08, 01 S1-2).
4. **Attribute vs title.** May a vendor's own title overrule its attribute (socket, chipset, colour, packaging, speed, memory type, capacity), with the conflict logged? This is the core of fix 2, F/G (§3.2; 04 Q2).
5. **Schema.** Should HM770, W880, HM65, B75, H81 and C621A be added to `CHIPSET_INFO`? Should B650E/X870E stay distinct from B650/X870? Should `80+`, `2U` and `CEB` join the enums? Keep or drop `pcie_x4_slots` (04 Q3/Q4, 05 F09/F11)?
6. **EAN as part number.** Should a 13-digit 1PC `מק"ט` barcode fill `part_numbers` (04 Q1)?
7. **Maker-page checks.** Is Aventurine a separate finish? Is A750BN PCIE5 III a separate part? Does ASUS print `90YV0L71-M0NA00` for both the 9070 and the 9070 XT (02 F-14, F-18, F-05)?
8. **Nano live checks.** Is `1pc:206013` really 5756? Do the 40 TMS `?product_id=` URLs resolve (06 Q4/Q5)?
9. **Extract file.** Extend the trust list or prune the 1,127 untrusted facts? What should happen to the 277 entries with a gone pid, and to the wrong PSU colour fact (08)?
10. **`vendor_count`.** Should it count offers or vendors (07 F3)?

### Owner answers (2026-11-10)

1. **Bundle price:** show the full price, with a small green chip on a conditional offer whose hover shows the conditional price. Bundle offers hold only the bundle price, so a bundle-only product shows that price with the chip (§3.2 H). TMS `1009115` at 70 is treated as a price with a PC.
2. **Second TMS crawl:** keep its data ("don't ignore important data"). The newest `scraped_at` row wins (§3.2 E).
3. **Box/Tray:** two versions are always two products, and a listing stays where its own label puts it. "Shared maker PN" meant the maker's own part number (Intel `BX…` Box, `CM…` Tray); it is now used only when a listing states no packaging (§3.2 D). The same principle settles Q7 and A's 5 ambiguous splits.
4. **Title vs attribute:** yes, when it is reliable. Reliable = two independent sources agree; one source alone is a QA flag (§3.2 F/G, measured).
5. **Schema:** the six chipsets are added and the E chipsets stay distinct. Left to my call: `80+`, `2U` and `CEB` join the enums, and `pcie_x4_slots` is kept (§3.2 M).
6. **1PC barcode as part number:** left open by the owner. My call: no. A 13-digit `מק"ט` barcode is stored as the EAN (used for matching under the strict-EAN rules) and is not shown as a part number.
7. **Maker pages:** the owner opened the pages. Antec Performance 1 M Black and Aventurine are one model in two colours, so they become two colour-variant products. MSI A750BN PCIE5 III (PCIe 5.1) and the original A750BN PCIE5 are two products. The three ASUS Prime RX 9070 offers are one card: the TMS "9070 XT" title is wrong, and the shared maker PN keeps them together (QA flag, no split) (§3.2 A2).
8. **Live checks:** two vendor pages to open in a browser (§3.2 V).
9. **Extract file:** my call: prune the 277 gone entries and the 16 that fail the verbatim check; keep the 1,127 untrusted facts for review (§3.2 K).
10. **`vendor_count`:** counts vendors, as today (§3.2 P).

Already answered (lane 03, recorded): `other` holds laptops, mini PCs and NAS for now; laptop SO-DIMM stays in `memory` (KSP's drop is a scraper scope issue); ROG Ryujin III Custom Loop is a water block (03 F13); when a generic title conflicts with an MPN another vendor files in a specific category, the MPN decides (03 F2).

## 8. decisions.md line (added 2026-11-10 at the owner's request, with the owner answers above)

> - TMS writes one crawl per UTC day: the night run honours the day's success marker and writes via `.part` + replace, and normalize keeps the newest `scraped_at` per listing key, never the lowest price (audit 2026-11-10: two 2026-11-09 crawls appended, 25 superseded prices, 11 shown as best offer).
