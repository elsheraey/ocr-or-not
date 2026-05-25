"""
Option 5 - measure, don't predict.

The simplest possible heuristic: extract text with pdfminer (no margin
trim, no spell-checker, no language assumptions) and decide based on the
*amount* of extractable text per page.

  - page is "thin" if it yields fewer than MIN_WORDS_PER_PAGE words
  - document needs OCR if >= half + 1 of sampled pages are thin

We use a higher word bar than file-processor's current 5: a real document
page has dozens of words, so 30 catches the "only header/footer was
searchable" case without needing margin tricks.

Strength: no assumptions about layout, language, or font. The most
reliable proxy for "we actually got something useful out of this PDF."

Weakness: a fixed word bar is still a threshold. A genuinely sparse page
(title slide, chapter heading) will look thin and be misrouted to OCR.
The real form of this option in production is "try both pipelines and
keep whichever output is denser" -- but that costs more compute. This
script implements the cheap measurement form.

Engine: pdfminer.six (MIT).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Verdict, pdfminer_xml, standalone_cli  # noqa: E402

NAME = "measure"
MIN_WORDS_PER_PAGE = 30


def _page_word_count(page_el) -> int:
    chars = []
    for letter in page_el.iter("text"):
        if letter.text is None:
            continue
        size = float(letter.attrib.get("size", "0") or 0)
        if size <= 1.0 and letter.text.strip():
            continue
        chars.append(letter.text)
    text = "".join(chars)
    return len(text.split())


def evaluate(pdf_bytes: bytes, sampled: list[int]) -> Verdict:
    xml = pdfminer_xml(pdf_bytes, sampled)
    root = etree.fromstring(xml.encode("utf-8"), parser=etree.XMLParser(recover=True))
    per_page: list[dict] = []
    for page_el, page_idx in zip(root.iter("page"), sampled):
        wc = _page_word_count(page_el)
        per_page.append({
            "page": page_idx,
            "word_count": wc,
            "thin": wc < MIN_WORDS_PER_PAGE,
        })

    if not per_page:
        return Verdict(NAME, "OCR", "no pages")
    threshold = math.floor(len(per_page) / 2) + 1
    bad = sum(1 for p in per_page if p["thin"])
    verdict = "OCR" if bad >= threshold else "SEARCHABLE"
    return Verdict(
        option=NAME,
        verdict=verdict,
        rationale=f"{bad}/{len(per_page)} pages have <{MIN_WORDS_PER_PAGE} words",
        per_page=per_page,
    )


if __name__ == "__main__":
    standalone_cli(evaluate, __doc__)
