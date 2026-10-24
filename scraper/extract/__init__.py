"""
scraper/extract - verified AI extraction of spec facts from listing text (tier 1.5).

Last in the source order: only fields still empty after the parsers, the
curated tables, the makers' pages, Open Icecat and the foreign retailers are
asked about. A model answer is a claim, not a value: it is kept only when its
quote is a verbatim piece of the text we sent AND the value re-parses from that
quote (verify.py). See README.md.
"""
