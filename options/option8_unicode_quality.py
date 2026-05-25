"""
Option 8 - Unicode/character validity check.

Skips the spell-checker entirely. After extracting text, classify each
char as either "valid" (letters, digits, normal punctuation, whitespace)
or "broken" (replacement chars, private-use-area, stray control chars,
or `(cid:NNN)` placeholders from a missing ToUnicode map).

Verdict:
  OCR         : >= BROKEN_RATIO of the extracted chars are broken
  SEARCHABLE  : extracted text is substantial and clean
  UNKNOWN     : no extractable text at all (defer to other options;
                a text-quality-only check shouldn't decide "is it
                image-only?" -- Op1, Op9, Op10 are better for that)

Language-agnostic and dictionary-free. Catches the failure modes that
break Op3's spell-checker approach: CID-encoded glyphs, character
substitution noise, encoding corruption.

Engine: pdfminer.six (MIT) via shared cache.
"""
from __future__ import annotations

import math
import re
import sys
import unicodedata
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Verdict, pdfminer_xml, standalone_cli  # noqa: E402

NAME = "unicode-quality"
BROKEN_RATIO = 0.05      # >5% broken chars -> text encoding is busted
MIN_CHARS_PER_PAGE = 30  # below this we don't have enough text to judge
CID_RE = re.compile(r"\(cid:\+?\d+\)")
REPLACEMENT = "�"


def _is_broken_char(c: str) -> bool:
    if c == REPLACEMENT:
        return True
    cp = ord(c)
    # private use area (BMP)
    if 0xE000 <= cp <= 0xF8FF:
        return True
    # control chars except tab / newline / carriage return / space
    if unicodedata.category(c).startswith("C") and c not in ("\t", "\n", "\r"):
        return True
    return False


def _page_text(page_el) -> str:
    chars = []
    for letter in page_el.iter("text"):
        if letter.text:
            chars.append(letter.text)
    return "".join(chars)


def _score(text: str) -> dict:
    if not text:
        return {"chars": 0, "broken": 0, "cid_placeholders": 0, "broken_ratio": 0.0}
    cid_hits = len(CID_RE.findall(text))
    # treat each `(cid:NNN)` as 1 broken "char" for ratio purposes
    text_no_cid = CID_RE.sub("", text)
    broken_chars = sum(1 for c in text_no_cid if _is_broken_char(c))
    total = len(text_no_cid) + cid_hits  # cid placeholders count
    return {
        "chars": total,
        "broken": broken_chars + cid_hits,
        "cid_placeholders": cid_hits,
        "broken_ratio": ((broken_chars + cid_hits) / total) if total else 0.0,
    }


def evaluate(pdf_bytes: bytes, sampled: list[int]) -> Verdict:
    xml = pdfminer_xml(pdf_bytes, sampled)
    root = etree.fromstring(xml.encode("utf-8"), parser=etree.XMLParser(recover=True))
    per_page: list[dict] = []
    for page_el, page_idx in zip(root.iter("page"), sampled):
        text = _page_text(page_el)
        s = _score(text)
        if s["chars"] < MIN_CHARS_PER_PAGE:
            verdict = "UNKNOWN"
        elif s["broken_ratio"] >= BROKEN_RATIO:
            verdict = "OCR"
        else:
            verdict = "SEARCHABLE"
        per_page.append({"page": page_idx, **s, "verdict": verdict})

    if not per_page:
        return Verdict(NAME, "UNKNOWN", "no pages")
    threshold = math.floor(len(per_page) / 2) + 1
    ocr_pages = sum(1 for p in per_page if p["verdict"] == "OCR")
    search_pages = sum(1 for p in per_page if p["verdict"] == "SEARCHABLE")
    if ocr_pages >= threshold:
        v = "OCR"
    elif search_pages >= threshold:
        v = "SEARCHABLE"
    else:
        v = "UNKNOWN"
    return Verdict(
        option=NAME,
        verdict=v,
        rationale=f"per-page verdicts: OCR={ocr_pages}, SEARCH={search_pages}, ?={len(per_page) - ocr_pages - search_pages}",
        per_page=per_page,
    )


if __name__ == "__main__":
    standalone_cli(evaluate, __doc__)
