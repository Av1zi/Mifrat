"""Shipped-text hygiene (audit 2026-11-10 J).

Vendor feeds hand over HTML entities (`&#34;`, `&#39;&#39;`, often without the
trailing `;`), bidi marks (U+200E/U+200F, embeddings and isolates) and NBSP
inside titles, SKUs and detail specs. They leak into product names, models and
part numbers, and an invisible mark inside a SKU breaks exact matching.
`clean_text` decodes and strips them once, where raw rows enter normalize;
`scripts/check_text_hygiene.py` holds every shipped file to the same patterns.
"""

from __future__ import annotations

import html
import re

ENTITY_RE = re.compile(r"&#\d+;?|&#x[0-9a-f]+;?|&(?:amp|quot|lt|gt|nbsp|apos);?", re.I)
BIDI_RE = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]")
NBSP_RE = re.compile(r"\u00a0")

# Links are left as they are: an `&lt` inside a query string is not an entity.
_SKIP_KEY_RE = re.compile(r"url|image|href", re.I)


def clean_text(value: str) -> str:
    """Decode entities (twice, for `&amp;#34;`), drop bidi marks, NBSP -> space."""
    if not (ENTITY_RE.search(value) or BIDI_RE.search(value) or NBSP_RE.search(value)):
        return value
    text = value
    for _ in range(2):
        if not ENTITY_RE.search(text):
            break
        text = html.unescape(text)
    text = NBSP_RE.sub(" ", BIDI_RE.sub("", text))
    return re.sub(r" {2,}", " ", text).strip()


def clean_tree(value, key: str = ""):
    """`clean_text` over every string in a JSON value, link fields excepted."""
    if isinstance(value, str):
        return value if _SKIP_KEY_RE.search(key) else clean_text(value)
    if isinstance(value, dict):
        return {k: clean_tree(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [clean_tree(v, key) for v in value]
    return value
