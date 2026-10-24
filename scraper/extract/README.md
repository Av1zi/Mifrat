# `scraper/extract/` - verified AI extraction (tier 1.5, `extracted`)

The last source. It runs after the parsers, curated tables, maker pages, Open
Icecat and foreign retailers, and asks Claude only about the fields still empty
on products below the 90% target. It reads only that product's own listing
text: titles, descriptions and detail rows. That is where facts sit in prose or
under labels the parsers don't map.

```bash
python -m scraper.extract --dry-run        # products, fields, estimated cost; no requests
python -m scraper.extract --audit 300      # measure precision -> data/extract/trust.json
python -m scraper.extract                  # fill -> data/extract/products.json
python -m scraper.extract --offline        # re-verify cached answers, no requests
MIFRAT_NO_EXTRACT=1 python -m scraper.normalize_and_match   # build without the tier
```

The GitHub workflow `extract-specs` runs audit, then fill, and commits both files.
It needs the `ANTHROPIC_API_KEY` secret. The model is `MIFRAT_EXTRACT_MODEL`,
default `claude-haiku-5-5`. The Oct 2026 dry run estimated about $0.54 for
2,690 products and 17,963 fields.

## Why a model answer can be believed

A model answer is only a claim. `verify.verified()` keeps it only when all of
these hold:

1. **The quote is verbatim.** It must be a piece of the exact text sent, with
   whitespace, case and Hebrew direction marks ignored. An answer from general
   knowledge has nothing to quote.
2. **The value is typed.** It coerces through `values.coerce`, so canonical
   forms, enums and ranges all apply.
3. **The quote carries the value.** For a number, the number must be in the
   quote (GB/TB scaling allowed). For a word, the word must be in it. A Yes/No
   field needs a quote that itself re-parses to Yes/No. Every item of a list
   must be quoted.

Identity fields (`manufacturer`, `model`, `part_numbers`, `series`) are never
asked.

**At read time** (`store.py`), two more checks apply:

- **The field passed the audit.** `--audit` asks about fields a sourced tier
  already filled and compares the answers with `backtest_rules.agrees`. A field
  is used only with 10 or more measured overlaps and at most 3% disagreement.
  Fields over that limit are not asked again.
- **The quote is still in the current listing text.** A rewritten vendor page
  takes the value with it.

**Caveat.** The audit text contains the very rows the vendor parser already
read, so it measures how well the model reads tables more than how well it
reads prose. That is why the quote and re-parse checks, not the audit, are the
main guard. `scripts/check_extract.py` pins them offline in CI.

## Cache and cost

Every answer is cached under `data/extract/.cache/` (gitignored), keyed by
model, `PROMPT_VERSION`, category, fields and text. That includes refusals; a
response cut off by `max_tokens` is not cached.

A re-run pays only for listings whose text changed. Raising `PROMPT_VERSION`
re-asks everything and also invalidates `trust.json`.
