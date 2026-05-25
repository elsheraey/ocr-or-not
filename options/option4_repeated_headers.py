"""
Option 4 - header/footer detection by repetition + position.

Instead of "exclude the top/bottom 10% of every page" (Option 3's brittle
margin trick), identify headers and footers as text lines that BOTH:

  (a) sit near the top or bottom of the page  (positional gate), AND
  (b) recur on most sampled pages with the same normalised signature.

Excluding only those lines avoids the failure mode of "repeating body
content" (e.g. boilerplate paragraphs) being misclassified as a header.

Algorithm:
  1. Extract pdfminer XML for the sampled pages.
  2. For each text line, record:
        - text signature (lowercase, collapsed whitespace, digit-runs -> '#')
        - y position relative to page height (0 = bottom, 1 = top)
  3. Consider a line a header/footer candidate iff
        y_top >= 0.80  OR  y_bottom <= 0.20
  4. Among CANDIDATES, count signatures across pages. Signatures appearing
     on >= REPEAT_RATIO * N pages are confirmed header/footer.
  5. Re-tally each page using only non-(header/footer) lines, then apply
     the same word-count + gibberish check as Option 3.

Strength: adapts to whatever header/footer the document actually has;
positional gate prevents false positives on repeating body content.

Weakness: still needs >= 2 sampled pages for repetition. Single-page docs
keep all lines (degenerate case, falls back to a pure text-quality check).

Engine: pdfminer.six (MIT) + pyspellchecker (MIT).
"""
from __future__ import annotations

import math
import re
import sys
from collections import Counter
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Verdict, pdfminer_xml, parse_bbox, standalone_cli  # noqa: E402
from option3_text_quality import is_gibberish  # reuse  # noqa: E402

NAME = "repeated-headers"
REPEAT_RATIO = 0.5
TOP_BAND = 0.90     # y_top  >= 0.90  -> in top 10% of page
BOTTOM_BAND = 0.10  # y_bottom <= 0.10 -> in bottom 10% of page
MIN_WORDS_PER_PAGE = 5

DIGIT_RE = re.compile(r"\d+")
WS_RE = re.compile(r"\s+")


def signature(text: str) -> str:
    s = WS_RE.sub(" ", text.strip().lower())
    return DIGIT_RE.sub("#", s)


def _line_text(textline_el) -> str:
    chars = []
    for letter in textline_el.iter("text"):
        if letter.text is None:
            continue
        size = float(letter.attrib.get("size", "0") or 0)
        if size <= 1.0 and letter.text.strip():
            continue
        chars.append(letter.text)
    return "".join(chars).strip()


def _extract_page_lines(page_el) -> list[dict]:
    """Return [{text, sig, in_band}] for every non-empty text line on the page."""
    pbbox = parse_bbox(page_el.attrib.get("bbox"))
    if pbbox is None:
        return []
    _, py_bottom, _, py_top = pbbox
    height = py_top - py_bottom if py_top > py_bottom else 1.0

    lines: list[dict] = []
    for tl in page_el.iter("textline"):
        text = _line_text(tl)
        if not text:
            continue
        tbbox = parse_bbox(tl.attrib.get("bbox"))
        if tbbox is None:
            continue
        _, ly_bottom, _, ly_top = tbbox
        rel_top = (ly_top - py_bottom) / height
        rel_bottom = (ly_bottom - py_bottom) / height
        in_band = rel_top >= TOP_BAND or rel_bottom <= BOTTOM_BAND
        lines.append({"text": text, "sig": signature(text), "in_band": in_band})
    return lines


def _confirm_header_footer_sigs(pages_lines: list[tuple[int, list[dict]]]) -> set[str]:
    """Signatures of band lines that recur on >= REPEAT_RATIO of the sampled pages."""
    n_pages = len(pages_lines)
    if n_pages < 2:
        return set()
    repeat_cut = max(2, math.ceil(REPEAT_RATIO * n_pages))
    counts: Counter[str] = Counter()
    for _, lines in pages_lines:
        for sig in {ln["sig"] for ln in lines if ln["in_band"] and ln["sig"]}:
            counts[sig] += 1
    return {s for s, c in counts.items() if c >= repeat_cut}


def _score_page(page_idx: int, lines: list[dict], hf_sigs: set[str]) -> dict:
    kept = [ln["text"] for ln in lines if ln["sig"] not in hf_sigs]
    excluded_count = len(lines) - len(kept)
    body = " ".join(kept)
    wc = sum(len(t.split()) for t in kept)
    gib = is_gibberish(body)
    return {
        "page": page_idx,
        "hf_lines_excluded": excluded_count,
        "body_word_count": wc,
        "gibberish": gib,
        "flagged": wc <= MIN_WORDS_PER_PAGE or gib,
    }


def evaluate(pdf_bytes: bytes, sampled: list[int]) -> Verdict:
    xml = pdfminer_xml(pdf_bytes, sampled)
    root = etree.fromstring(xml.encode("utf-8"), parser=etree.XMLParser(recover=True))

    pages_lines = [
        (idx, _extract_page_lines(el))
        for el, idx in zip(root.iter("page"), sampled)
    ]
    hf_sigs = _confirm_header_footer_sigs(pages_lines)
    per_page = [_score_page(idx, lines, hf_sigs) for idx, lines in pages_lines]

    if not per_page:
        return Verdict(NAME, "OCR", "no pages")
    threshold = math.floor(len(per_page) / 2) + 1
    bad = sum(1 for p in per_page if p["flagged"])
    verdict = "OCR" if bad >= threshold else "SEARCHABLE"
    return Verdict(
        option=NAME,
        verdict=verdict,
        rationale=(
            f"{bad}/{len(per_page)} pages flagged; "
            f"{len(hf_sigs)} header/footer signature(s) confirmed "
            f"(repeating in top/bottom 10% band)"
        ),
        per_page=per_page,
    )


if __name__ == "__main__":
    standalone_cli(evaluate, __doc__)
