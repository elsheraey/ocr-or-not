"""
Option 3 - text-quality check (status quo in file-processor + PR #61 fixes).

Mirrors `miner/searchable_pdf_checker.py::check_noocr_output` and
`miner/utils.py::is_gibberish_text` after PR #61:

  - extract pdfminer XML for the sampled pages
  - exclude a 10% margin band (header/footer) on each page
  - count words with letter-height > 1.0
  - page is "non-searchable" if word_count <= 5 OR text looks gibberish
  - gibberish = ratio of valid words (spell-checker OR digit-only) below 0.7
  - document needs OCR if >= half + 1 of sampled pages are non-searchable

Strength: catches documents whose extracted text is unusable, regardless of
whether images are present (e.g. text-as-vector-curves, CID-broken fonts).

Weakness: heuristic on top of heuristic. Spell-checker doesn't know proper
nouns / domain jargon; 10% margin is arbitrary; thresholds are guesses.

Engine: pdfminer.six (MIT) + pyspellchecker (MIT).
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

from lxml import etree
from spellchecker import SpellChecker

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Verdict, pdfminer_xml, parse_bbox, standalone_cli  # noqa: E402

NAME = "text-quality"
MARGIN_PERCENTAGE = 0.10
MIN_WORDS_PER_PAGE = 5
GIBBERISH_RATIO = 0.7

SPELL_CHECKER = SpellChecker(language="en")


def _clean(word: str) -> str:
    return re.sub(r"[^\w\s]", "", word)


def is_gibberish(text: str, threshold: float = GIBBERISH_RATIO) -> bool:
    if not text:
        return True
    words = text.split(" ")
    valid = 0
    non_empty = len(words)
    for w in words:
        w = _clean(w)
        if not w:
            non_empty -= 1
            continue
        if w.isdigit() or SPELL_CHECKER.known([w]):
            valid += 1
        if non_empty > 0 and valid / non_empty > threshold:
            return False
    return True


def evaluate(pdf_bytes: bytes, sampled: list[int]) -> Verdict:
    xml = pdfminer_xml(pdf_bytes, sampled)
    root = etree.fromstring(xml.encode("utf-8"), parser=etree.XMLParser(recover=True))
    per_page: list[dict] = []
    for page_el, page_idx in zip(root.iter("page"), sampled):
        bbox = parse_bbox(page_el.attrib.get("bbox"))
        if bbox is None:
            per_page.append({"page": page_idx, "word_count": 0, "gibberish": True, "flagged": True})
            continue
        _, y_bottom, _, y_top = bbox
        if y_top > y_bottom:
            margin = MARGIN_PERCENTAGE * (y_top - y_bottom)
            body_min, body_max = y_bottom + margin, y_top - margin
        else:
            body_min, body_max = float("-inf"), float("inf")

        parts, word_count = [], 0
        for textline in page_el.iter("textline"):
            tbbox = parse_bbox(textline.attrib.get("bbox"))
            if tbbox is None:
                continue
            _, ly_bottom, _, ly_top = tbbox
            if ly_bottom < body_min or ly_top > body_max:
                continue
            chars = []
            for letter in textline.iter("text"):
                if letter.text is None:
                    continue
                size = float(letter.attrib.get("size", "0") or 0)
                if size <= 1.0 and letter.text.strip():
                    continue
                chars.append(letter.text)
            line_text = "".join(chars).strip()
            if line_text:
                parts.append(line_text)
                word_count += len(line_text.split())
        page_text = " ".join(parts)
        gib = is_gibberish(page_text)
        flagged = word_count <= MIN_WORDS_PER_PAGE or gib
        per_page.append({
            "page": page_idx,
            "word_count": word_count,
            "gibberish": gib,
            "flagged": flagged,
            "sample_text": page_text[:60].replace("\n", " "),
        })

    if not per_page:
        return Verdict(NAME, "OCR", "no pages")
    threshold = math.floor(len(per_page) / 2) + 1
    bad = sum(1 for p in per_page if p["flagged"])
    verdict = "OCR" if bad >= threshold else "SEARCHABLE"
    return Verdict(
        option=NAME,
        verdict=verdict,
        rationale=f"{bad}/{len(per_page)} pages flagged (<= {MIN_WORDS_PER_PAGE} words or gibberish)",
        per_page=per_page,
    )


if __name__ == "__main__":
    standalone_cli(evaluate, __doc__)
