"""
Option 9 - vertical text-distribution histogram.

For each sampled page, slice the page vertically into 10 bands of equal
height and count text lines per band. A real text page spreads lines
across the middle bands; a "header/footer only" page has text only in
the top and bottom bands with the middle empty. The latter is exactly
the SP-1133 second failure mode, regardless of whether the body is an
image, white space, or vector content.

Verdict per page:
  - if no text at all                                      -> OCR
  - if total >= MIN_LINES AND middle-60% bands are empty   -> OCR
  - otherwise                                              -> SEARCHABLE

Strength: pure geometry. No language, no spell-checker, no margin
assumption. Catches "body has no text" cases that Op1 can miss when the
body isn't a raster image (e.g. a blank-body letterhead).

Weakness: a very short document with only a few legitimate body lines
clustered at the top can look "header-only" to this check.

Engine: pdfminer.six (MIT) via shared cache.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Verdict, pdfminer_xml, parse_bbox, standalone_cli  # noqa: E402

NAME = "vertical-distribution"
N_BANDS = 10
MIDDLE_BANDS = range(2, 8)      # 0..9; middle 60% = bands 2..7
MIDDLE_EMPTY_THRESHOLD = 5      # fraction of middle bands that must be empty
TOP_BOTTOM_MIN_LINES = 1        # need text at top OR bottom to call this "hf-only"
MIN_LINES_FOR_VERDICT = 2       # need at least this many lines on the page to score


def _band_histogram(page_el) -> list[int]:
    pbbox = parse_bbox(page_el.attrib.get("bbox"))
    if pbbox is None:
        return [0] * N_BANDS
    _, py_bottom, _, py_top = pbbox
    height = py_top - py_bottom
    if height <= 0:
        return [0] * N_BANDS
    bands = [0] * N_BANDS
    for tl in page_el.iter("textline"):
        tbbox = parse_bbox(tl.attrib.get("bbox"))
        if tbbox is None:
            continue
        # check that the line has non-trivial text
        if not any(t.text and t.text.strip() for t in tl.iter("text")):
            continue
        _, ly_bottom, _, ly_top = tbbox
        cy = (ly_bottom + ly_top) / 2
        rel = (cy - py_bottom) / height          # 0..1
        idx = min(N_BANDS - 1, max(0, int(rel * N_BANDS)))
        bands[idx] += 1
    return bands


def _page_verdict(bands: list[int]) -> str:
    total = sum(bands)
    if total < MIN_LINES_FOR_VERDICT:
        return "OCR"  # no usable text on this page
    middle_empty = sum(1 for i in MIDDLE_BANDS if bands[i] == 0)
    top_lines = bands[-1] + bands[-2]
    bot_lines = bands[0] + bands[1]
    # SP-1133 pattern: text at BOTH top AND bottom, middle empty.
    if (
        middle_empty >= MIDDLE_EMPTY_THRESHOLD
        and top_lines >= TOP_BOTTOM_MIN_LINES
        and bot_lines >= TOP_BOTTOM_MIN_LINES
    ):
        return "OCR"
    return "SEARCHABLE"


def evaluate(pdf_bytes: bytes, sampled: list[int]) -> Verdict:
    xml = pdfminer_xml(pdf_bytes, sampled)
    root = etree.fromstring(xml.encode("utf-8"), parser=etree.XMLParser(recover=True))
    per_page: list[dict] = []
    for page_el, page_idx in zip(root.iter("page"), sampled):
        bands = _band_histogram(page_el)
        verdict = _page_verdict(bands)
        per_page.append({
            "page": page_idx,
            "bands": bands,
            "total_lines": sum(bands),
            "verdict": verdict,
        })

    if not per_page:
        return Verdict(NAME, "OCR", "no pages")
    threshold = math.floor(len(per_page) / 2) + 1
    bad = sum(1 for p in per_page if p["verdict"] == "OCR")
    v = "OCR" if bad >= threshold else "SEARCHABLE"
    return Verdict(
        option=NAME,
        verdict=v,
        rationale=f"{bad}/{len(per_page)} pages have empty middle and/or no text",
        per_page=per_page,
    )


if __name__ == "__main__":
    standalone_cli(evaluate, __doc__)
