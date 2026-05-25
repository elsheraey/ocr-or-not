"""
Option 7 - font embedding & font-name fingerprints.

Different PDF producers leak themselves through their font usage:

  - OCR layers              : "GlyphlessFont", "Tesseract*", "OcrA",
                              Type 3 fonts with no ToUnicode map
  - Native digital PDFs     : embedded subset fonts named with a 6-char
                              prefix ("ABCDEE+Helvetica"), standard 14
                              PDF base fonts (Helvetica, Times-Roman ...)
  - Image-only / scanned    : page has no /Font resource at all
  - Encoding-broken PDFs    : embedded font with missing ToUnicode ->
                              extracted text will be CID gibberish

The option returns:
  SEARCHABLE  : page uses native or OCR-layer fonts (text is real)
  OCR         : page has text-bearing operators but no usable fonts,
                or page has zero fonts at all
  UNKNOWN     : mixed / inconclusive

Engine: pikepdf (MPL-2.0).
"""
from __future__ import annotations

import io
import math
import sys
from pathlib import Path

import pikepdf
from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Verdict, pdfminer_xml, standalone_cli  # noqa: E402

NAME = "font-fingerprint"

OCR_FONT_HINTS = ("glyphless", "tesseract", "ocra", "ocrb")
SUBSET_PREFIX_LEN = 7  # "ABCDEE+Name" -> prefix length, 6 caps + '+'


def _classify_font(name: str, font_dict: pikepdf.Object) -> str:
    n = name.lower()
    if any(h in n for h in OCR_FONT_HINTS):
        return "ocr_layer"
    # subset-embedded font prefix: 6 uppercase letters + '+'
    if len(name) > SUBSET_PREFIX_LEN and name[6] == "+" and name[:6].isupper():
        return "native_embedded"
    # standard 14 PDF base fonts (treated as native)
    standard_14 = {
        "Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique",
        "Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic",
        "Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique",
        "Symbol", "ZapfDingbats",
    }
    if name in standard_14:
        return "native_standard"
    # Type 3 fonts are user-defined glyphs - common in OCR or weird PDFs
    try:
        if font_dict.Subtype == "/Type3":
            return "type3_suspicious"
    except (AttributeError, KeyError):
        pass
    # Embedded font without ToUnicode -> extraction will be broken
    try:
        has_tounicode = "/ToUnicode" in font_dict.keys()
    except Exception:
        has_tounicode = False
    if not has_tounicode:
        return "no_tounicode"
    return "native_other"


def _page_font_summary(page) -> dict:
    cats = {"ocr_layer": 0, "native_embedded": 0, "native_standard": 0,
            "type3_suspicious": 0, "no_tounicode": 0, "native_other": 0}
    try:
        fonts = page.Resources.Font
    except (AttributeError, KeyError):
        return {"total": 0, **cats}
    for _, font_dict in fonts.items():
        try:
            base = str(font_dict.BaseFont).lstrip("/")
        except (AttributeError, KeyError):
            base = ""
        cat = _classify_font(base, font_dict)
        cats[cat] += 1
    return {"total": sum(cats.values()), **cats}


def _text_char_counts(pdf_bytes: bytes, sampled: list[int]) -> dict[int, int]:
    """Per-page extractable char count (used to disambiguate 'fonts declared but unused')."""
    xml = pdfminer_xml(pdf_bytes, sampled)
    root = etree.fromstring(xml.encode("utf-8"), parser=etree.XMLParser(recover=True))
    counts: dict[int, int] = {}
    for page_el, idx in zip(root.iter("page"), sampled):
        n = sum(len(t.text) for t in page_el.iter("text") if t.text)
        counts[idx] = n
    return counts


def evaluate(pdf_bytes: bytes, sampled: list[int]) -> Verdict:
    per_page: list[dict] = []
    text_counts = _text_char_counts(pdf_bytes, sampled)
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        for i in sampled:
            summary = _page_font_summary(pdf.pages[i])
            summary["text_chars"] = text_counts.get(i, 0)
            verdict = _verdict_for_page(summary)
            per_page.append({"page": i, **summary, "verdict": verdict})

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


def _verdict_for_page(s: dict) -> str:
    no_text = s.get("text_chars", 0) == 0
    if s["total"] == 0:
        return "OCR"   # no fonts AT ALL -> image-only or vector
    if no_text:
        # fonts are declared in /Resources but no text actually drawn on the
        # page (common with reportlab on image-only pages); can't decide
        return "UNKNOWN"
    if s["ocr_layer"] > 0:
        return "SEARCHABLE"
    if s["no_tounicode"] > 0 and s["native_embedded"] + s["native_standard"] == 0:
        return "OCR"   # only fonts present have broken extraction
    if s["native_embedded"] + s["native_standard"] + s["native_other"] > 0:
        return "SEARCHABLE"
    return "UNKNOWN"


if __name__ == "__main__":
    standalone_cli(evaluate, __doc__)
