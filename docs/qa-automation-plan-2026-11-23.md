# Evidence-backed QA automation plan

**Date: 2026-11-23**

**Status: First staged implementation verified (owner-authorized Nov 23); publication authorized Nov 24.** Later stages remain proposed.

**Evidence baseline: `541cc6d65ee2f71f7cf00eaa775ceb791d4663be`.** Recheck current code before implementation.

## Recommendation: automate proof, not dismissal

The pipeline should automatically **correct bad facts, recognize already-correct answers, and keep genuinely uncertain cases open**. It should not learn “this case ID was dismissed, so hide it forever.”

This plan is based on **203 append-only evidence records**, including **115 dismissals and 80 specification corrections**:

- [QA resolution report and remaining work](qa-resolution/2026-11-22.md).
- [Evidence and applied decisions](qa-resolution/2026-11-22.jsonl).
- [Current-input exceptions and preservation proof](qa-resolution/2026-11-23-publish-verification.json).

The evidence reveals three distinct problems:

1. **Parsing or source-selection errors** — wrong RAM arithmetic, mixed CPU clock metrics, incorrect reference matches.
2. **False conflicts** — the chosen answer is correct, but another source abbreviates it or describes a different metric.
3. **Identity mistakes** — different editions merged together, or the same manufacturer code split across products.

These need separate solutions. The existing QA fixes were published at the baseline commit; the first rollout below is implemented locally. The remaining automation is still proposed.

### First rollout scope

- Blocking offline regression corpus: `scripts/check_qa_automation.py`, including pinned BL122 evidence through real normalization, matching, final specs and QA without human overrides or dismissals.
- Strict boolean/vector/model comparisons; qualified sources retain precedence over model-digit and GPU-title shortcuts.
- Unsupported CPU platform-memory inference is quarantined; its rejected candidate remains visible in rule-health backtests.
- Additive cached-sheet match proof; ambiguous fan manufacturer keys/names or multiple different matching fan sheets are refused rather than using the last entry. Other categories retain existing source selection in this rollout; broader duplicate-cache handling needs separate fixtures and diff review.
- Recomputed exact-manufacturer fan-performance resolution only, with off/shadow/enabled modes in `scraper/specs/resolution.py`. Final identity uncertainty, changed/unknown answers, validation issues and equally qualified contradictions veto resolution. Public QA, local workbench and operations distinguish it from human decisions; history does not consume open-case caps.

This is **not** the full plan: Intel adapters, broader semantic parsing, general authoritative closure, identifier annotations and assignment-changing identity automation remain future stages. No new collection, ledger cleanup or publication is authorized by this implementation.

**Nov 23 offline verification:** the enabled fan rule proves 18 distinct product/field decisions, including 15 previously open decisions and three already human-dismissed ones. Repeated fixed-clock builds under multiple hash seeds preserve all 7,031 listings, offers, assignments and aliases across 4,230 products. The only selected-spec changes are 106 unsupported inferred CPU memory limits becoming unknown and eight model names taking manufacturer evidence. Regression corpus, code checks, type checks, site tests/lint/build and publish integrity pass. The publish suite reports 51 passes, three quality warnings and zero blockers; ledger, quarantined-rule health and reduced CPU coverage warnings remain visible with unchanged thresholds. No live source behaviour was verified.

## 1. Establish the regression corpus first

Turn the evidence into fixtures that exercise the **real normalization → matching → specification → QA pipeline**, not just isolated helpers.

Each fixture should retain:

- Original vendor listings and relevant manufacturer evidence.
- Exact manufacturer identifiers and physical variant.
- Expected specifications and grouping.
- Why the competing answer was wrong.
- Whether the decision requires manual evidence.

For cases intended to become automatic, test them **without their specification overrides or dismissal entries**. Otherwise, the existing manual correction could conceal a broken implementation. Keep separate tests proving that human overrides and grouping constraints remain respected.

Include nearby counterexamples:

- `245K` versus `245KF`.
- RX 9070 versus RX 9070 XT.
- Threadripper 7980X versus 7960X.
- Box versus Tray.
- FT versus FT ARGB.
- Glass versus metal editions.
- `96GB (2×24GB)` as contradictory evidence — not an invitation to guess.

Pin historical snapshots for historical tests. A listing disappearing from today's feed must not make the script resurrect an old offer or falsely declare its specification resolved.

**Completion criterion:** every proposed automatic rule has real-pipeline positive fixtures and negative counterexamples; manual entries do not supply the answer being tested.

## 2. Tighten comparison rules before adding automatic closure

This is a prerequisite, not an optional cleanup.

Read-only probes against the baseline confirmed that helpers can:

- Treat `False` and unknown as equal.
- Treat reordered dimension vectors as equal.
- Treat `XT` or `redux` as wording-only additions.

Other guards may catch those cases, but those comparisons are **unsafe foundations for broader automation**. These probes do not establish that every such input reaches an incorrect published result.

Change `scraper/specs/merge.py` and `scraper/specs/report.py` to use **field-aware comparison**:

| Field type | Safe comparison |
|---|---|
| Boolean | Unknown, explicit No, and Yes remain distinct |
| Supported sockets | Compare normalized unordered sets |
| Dimensions/timings | Preserve order, or normalize explicitly labelled axes |
| Model names | Preserve meaningful suffixes, editions and numbers |
| Lighting | Presence is not RGB/ARGB protocol |
| Numeric measurements | Normalize units, not arbitrary “close enough” differences |

For example, **158mm and 160mm must not become equivalent merely because they are close**. An exact manufacturer specification can establish which is correct; rounding tolerance cannot.

Also review existing ranking shortcuts: “more digits in the model” and “GPU title always wins” should not outrank qualified evidence.

**Completion criterion:** the counterexamples above remain distinct, legitimate representation changes compare correctly, and unrelated selected specifications are unchanged.

## 3. Make every fact carry its evidence quality

A source tier does not fully describe **how confidently that source was joined to this SKU**.

Extend the existing fact/merge interface with optional evidence metadata:

- Exact manufacturer key, approved alias, or name/family fallback.
- Source URL and cached-document fingerprint.
- Selected SKU/variant.
- Measurement meaning and units.
- Complete specification versus partial description.
- Evidence origin, so copied supplier information is not counted twice.

Then qualify facts **before ranking them**.

Examples:

- A family-level fan reference must not supply SKU-specific RPM, airflow or noise over an exact manufacturer sheet.
- An exact-name reference should still be checked against trustworthy physical anchors. A poorly parsed vendor value is not automatically a trustworthy anchor.
- Multiple manufacturer entries matching different SKUs must not silently become “last entry wins.”
- Two vendors copying a supplier code are not proof that it is a manufacturer ordering code.

Implement this behind the existing merge module's interface, with `scraper/specs/build.py`, `scraper/specs/resolvers/reference.py` and `scraper/mfr/store.py` supplying the evidence. Do not build a second, competing merge engine.

Additive metadata should be backward-compatible. Missing proof means a fact cannot authorize automatic closure, not that old input must crash. Any breaking schema change needs the existing migration and frontend-export checks.

**Completion criterion:** every automatic decision can explain its identity match, field meaning and source support; ambiguous matches cannot acquire automatic authority.

## 4. Expand authoritative enrichment and semantic parsing

This is the highest-return route for replacing repetitive manual overrides.

### CPU evidence

Add manufacturer adapters for the approved, cached Intel ordering/specification evidence and extend relevant existing adapters under `scraper/mfr/`.

Extract labelled facts separately:

- Total cores versus performance cores.
- Total threads versus partial core-cluster counts.
- P-core base versus E-core base.
- Overall maximum turbo versus a separately labelled P-core turbo.
- Exact GPU name.
- Explicit ECC capability.
- Exact-model memory limits.
- Ordering code, spec code and shipping media.

**Do not infer these from generic family names when the manufacturer states them per model.**

### RAM evidence

Reuse one shared kit parser across vendor cells, title parsing, quote verification and arithmetic:

```text
2×24GB → 2 modules, 24GB each, 48GB total
```

Distinguish:

- Kit capacity from module capacity.
- Tested/XMP voltage from SPD voltage.
- Tested data rate from another operating profile.

Contradictory inputs remain unresolved unless independent, exact-SKU evidence establishes the answer. Arithmetic must respect source priority and must not silently overwrite a human correction.

### Other specifications

Separate easily confused meanings:

- Included fans versus supported fan capacity.
- Product dimensions versus packaging dimensions.
- Compatible sockets versus included mounting hardware.
- Lighting already included versus lighting merely supported.

Some of this parsing is already corrected in the published fixes. The goal is to **generalize and consolidate it**, not redo it.

Use cached evidence first. Any future collection must follow the [manufacturer source rules](../scraper/mfr/README.md) and [root scraping rules](../README.md#scraping-rules); this plan does not authorize new crawls or paused-source requests.

**Completion criterion:** eligible reviewed answers are produced natively without their manual specification overrides, with exact-SKU evidence and correctly labelled metrics.

## 5. Normalize authoritative identifiers before grouping

The duplicate 14600KF Tray groups demonstrate why changing `specs.part_numbers` **after matching** is insufficient.

Add a category-aware identifier pass before grouping in `scraper/identity.py` and `scraper/normalize_and_match.py`. For the verified Intel example, it should preserve:

```text
Ordering code: CM8071504821014
Spec code:     SRN42
Original text: CM8071504821014S RN42
```

Recognize that separation **only when the manufacturer ordering evidence supports it**.

Do not generically strip suffixes: they can encode colour, profile, packaging or revision.

Keep separate identifier kinds:

- Manufacturer ordering/part number.
- Spec/revision code.
- Barcode.
- Retailer catalogue code.

Start this pass in annotation-only mode. Enable grouping changes later, after tests prove that it:

- Joins genuinely identical SKUs.
- Preserves Box/Tray and edition distinctions.
- Respects blocked pairs and curated products.
- Preserves stable IDs, or creates only unambiguous aliases.
- Leaves every vendor price, stock observation and URL intact.

Automatic splits are appropriate for **uncurated groups with proven distinct physical SKUs**. Repartitioning a human-curated group should remain a proposed change requiring approval.

**Completion criterion:** approved identity changes pass I1–I6, surviving-evidence connectivity, alias/history checks and full assignment-delta review; unrelated groups do not move.

## 6. Compute QA resolution from the final answer

Many dismissals did not require another specification change — the pipeline had already selected the correct value.

Add a computed resolution decision **after final specification validation and normalization**. Keep the resulting decision consistent across `scraper/specs/report.py`, `scraper/site_data.py`, `scraper/qa_tool.py` and operations reporting.

A case can become automatically resolved only when:

- The sold SKU and variant are sufficiently established.
- The selected value answers the correct metric.
- Qualified evidence supports the actual shipped value.
- All relevant competing claims have been considered.
- No equally qualified contradiction or identity uncertainty remains.

Return a reason such as:

- `exact_manufacturer_spec`
- `representation_equivalent`
- `partial_description_compatible`
- `wrong_metric_rejected`

Keep **open, auto-resolved, human-fixed, human-dismissed and inactive** distinct.

Automatic resolution must not write permanent entries into `data/matching/qa_dismissed.json`. Recompute it each build; changed evidence must be able to reopen a case. The reappeared 7980X split case demonstrates why this matters.

Evaluate the **uncapped decision set**, then apply public-display caps. Preserve raw disagreements for audit and provide an explanation showing the rule and evidence used. Keep detailed proof out of public payloads where a compact reference suffices; existing payload limits still apply.

**Completion criterion:** every automatic resolution has a current proof, genuine disagreements remain open, and resolution history cannot consume the open-case cap or conceal reappearing cases.

## 7. Quarantine unsafe inference rather than expanding guesses

At the evidence baseline, the CPU maximum-memory fallback disagreed with **13 of 60 sourced overlaps**.

Do not “fix” that by replacing every platform limit with 256GB.

Instead:

- Disable or narrow that specific unsupported fallback.
- Retain exact-model, manufacturer-backed answers.
- Leave unsupported answers unknown.
- Keep rule-health warnings visible.

Use the same principle for future rules: failing trusted counterexamples should stop that rule's automatic decisions — not erase authoritative facts, widen budgets, or silence warnings.

**Completion criterion:** trusted counterexamples cannot produce the disproven inferred answer, supported sourced values are retained, and the script handles the remaining unknowns normally.

## Safety gates and rollout

Enable **one rule family at a time**:

1. **Off:** existing behavior remains unchanged.
2. **Shadow:** record proposed changes without applying them.
3. **Enabled:** promote only after reviewing the complete diff.

Every promotion must pass:

- Reviewed positive fixtures and adversarial negative fixtures.
- Native-resolution tests without the targeted manual overrides/dismissals.
- Full-catalog comparison: **zero unrelated specification or assignment changes**.
- Exact preservation of vendor observations.
- Identity I1–I6, aliases and history checks.
- Repeated builds and multiple hash seeds.
- Existing code, QA, schema, site and publish-integrity checks.
- Runtime, memory and payload checks.

Missing evidence or an unsupported source layout should produce **unknown/open**, not a guess. Genuine code or integrity failures must still block publication; recoverable source-data gaps are not permission to publish an incoherent output set.

### Recommended implementation order

**Regression corpus → strict comparisons and inference safeguards → evidence provenance and manufacturer enrichment → computed QA resolution → higher-risk identity automation.**

Identifier annotations may be developed earlier, but assignment-changing identity rules stay disabled until their dedicated gates pass.

No plan can guarantee zero bugs on unseen data. This plan makes uncertainty explicit and limits the impact of mistakes.

**The success metric is correct answers without manual intervention — not simply a smaller QA queue.**
