"""
Option 18 - bigram plausibility (no spell-checker, no dictionary).

Replace Op3's spell-checker with a language-agnostic character bigram
check. Real-language text -- in any Latin-script language plus a lot of
others -- has a very non-uniform bigram distribution dominated by a
small set of common pairs ("th", "he", "in", "er", "an", "on", "re",
"at", "en", "es"). CID-broken extraction, random unicode noise, or
glyph-mapping failures produce near-uniform bigram distributions.

Per-page score = fraction of bigrams in the extracted text that appear
in a tiny built-in "common bigrams in Latin-script European languages"
list. Higher = more language-like.

Verdict per page:
  - score >= NATIVE_MIN     -> SEARCHABLE
  - score <= BROKEN_MAX     -> OCR  (text is unusable)
  - in between, or too few chars -> UNKNOWN

Strength: works for English / French / Spanish / German / Italian /
Portuguese / Dutch without changing anything; doesn't choke on numbers,
proper nouns, technical jargon.

Weakness: non-Latin scripts (Arabic, Chinese, Russian) will look
"broken" to this check. Production would extend the bigram list per
script. Also: false positives on heavily-numeric pages (no bigrams in
the common list because there are no letter pairs).

Engine: pdfminer.six (MIT) via shared cache.
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Verdict, pdfminer_xml, standalone_cli  # noqa: E402

NAME = "bigram-plausibility"
MIN_BIGRAMS = 80          # too little text -> can't judge
NATIVE_MIN = 0.18         # >=18% of bigrams are common Latin pairs -> language
BROKEN_MAX = 0.02         # <=2% -> almost certainly gibberish/cid

# Top ~80 bigrams pooled across English/French/Spanish/German/Italian/Portuguese/Dutch
COMMON_BIGRAMS = {
    "th", "he", "in", "er", "an", "re", "on", "at", "en", "nd", "ti", "es", "or",
    "te", "of", "ed", "is", "it", "al", "ar", "st", "to", "nt", "ng", "se", "ha",
    "as", "ou", "io", "le", "ve", "co", "me", "de", "hi", "ri", "ro", "ic", "ne",
    "ea", "ra", "ce", "li", "ch", "ll", "be", "ma", "si", "om", "ur", "ca", "el",
    "ta", "la", "ns", "di", "fo", "ho", "pe", "ec", "pr", "no", "ct", "us", "ac",
    "ot", "il", "tr", "ly", "nc", "et", "ut", "ss", "so", "rs", "un", "lo", "wa",
    "ge", "ie", "wh", "ee", "wi", "em", "ad", "ol", "rt", "po", "we", "na", "ul",
    "ni", "ts", "mo",
}
TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ]{2,}")  # letter sequences only


def _page_text(page_el) -> str:
    return "".join(t.text for t in page_el.iter("text") if t.text)


def _score(text: str) -> dict:
    bigrams = 0
    common = 0
    for tok in TOKEN_RE.findall(text.lower()):
        for i in range(len(tok) - 1):
            bg = tok[i:i + 2]
            bigrams += 1
            if bg in COMMON_BIGRAMS:
                common += 1
    ratio = (common / bigrams) if bigrams else 0.0
    return {"bigrams": bigrams, "common": common, "ratio": round(ratio, 4)}


def _verdict_for_page(s: dict) -> str:
    if s["bigrams"] < MIN_BIGRAMS:
        return "UNKNOWN"
    if s["ratio"] <= BROKEN_MAX:
        return "OCR"
    if s["ratio"] >= NATIVE_MIN:
        return "SEARCHABLE"
    return "UNKNOWN"


def evaluate(pdf_bytes: bytes, sampled: list[int]) -> Verdict:
    xml = pdfminer_xml(pdf_bytes, sampled)
    root = etree.fromstring(xml.encode("utf-8"), parser=etree.XMLParser(recover=True))
    per_page: list[dict] = []
    for page_el, page_idx in zip(root.iter("page"), sampled):
        s = _score(_page_text(page_el))
        per_page.append({"page": page_idx, **s, "verdict": _verdict_for_page(s)})

    if not per_page:
        return Verdict(NAME, "UNKNOWN", "no pages")
    threshold = math.floor(len(per_page) / 2) + 1
    ocr = sum(1 for p in per_page if p["verdict"] == "OCR")
    search = sum(1 for p in per_page if p["verdict"] == "SEARCHABLE")
    if ocr >= threshold:
        v = "OCR"
    elif search >= threshold:
        v = "SEARCHABLE"
    else:
        v = "UNKNOWN"
    return Verdict(NAME, v, f"OCR={ocr}, SEARCH={search}, ?={len(per_page)-ocr-search}", per_page)


if __name__ == "__main__":
    standalone_cli(evaluate, __doc__)
