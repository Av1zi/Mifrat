"""
specs/resolvers — one module per source tier. Each resolver answers a single
question: "what does THIS source know about this listing/product?" and emits
`{field: [Fact]}` using schema field names only.

Tiers (see specs/merge.py):
  reference.py     Tier 0 — PCPartPicker/docyx dataset + data/specs/overrides.json
  vendor_struct.py Tier 1 — vendor structured payloads + post-match fields
  title_parse.py   Tier 2 — typed regex over the listing title/SKU
  weak_vendor.py   Tier 3 — prose fragments (Plonter tree/dash-dumps, 1PC prose)

Resolvers never merge, never overwrite and never guess: the merge engine
decides what wins and logs what lost.
"""
