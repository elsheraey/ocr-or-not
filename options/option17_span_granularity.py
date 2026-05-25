"""
Option 17 - text-span granularity (chars per text-show op).

OCR engines often emit one text-show operator *per glyph* (one Tj per
recognised character). Native PDFs lay text out as runs -- typically one
TJ with an array of dozens of characters at a time. So:

  chars_per_text_op  ratio
  ----------------------------------------------------------
    < 3              text was emitted glyph-by-glyph (OCR-produced)
    > 10             native text layout (Word, InDesign, LaTeX, ...)
    in between       inconclusive

This is a *positive* signal for "this is OCR-produced text" rather than
"this is missing text". Pairs naturally with Op6: Op6 says "there is an
invisible text layer", Op17 says "the visible text looks OCR'd".

Important nuance: a page where the OCR'd text layer looks usable should
still be classified as SEARCHABLE (we'd use the existing layer, not
re-OCR). So this option returns SEARCHABLE for OCR-granularity text --
not OCR. It's an "already-OCR'd, can be extracted" detector.

Engine: pikepdf (MPL-2.0).
"""
from __future__ import annotations

import io
import math
import sys
from pathlib import Path

import pikepdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Verdict, standalone_cli  # noqa: E402

NAME = "span-granularity"
GLYPH_BY_GLYPH_MAX_RATIO = 3.0
NATIVE_MIN_RATIO = 10.0
MIN_OPS_FOR_SIGNAL = 20


def _stats(page) -> dict:
    text_ops = 0
    text_chars = 0
    try:
        stream = pikepdf.parse_content_stream(page)
    except Exception:
        return {"text_ops": 0, "text_chars": 0, "chars_per_op": 0.0}
    for operands, operator in stream:
        op = str(operator)
        if op not in ("Tj", "TJ", "'", '"'):
            continue
        text_ops += 1
        for operand in operands:
            if isinstance(operand, pikepdf.String):
                text_chars += len(bytes(operand))
            elif isinstance(operand, pikepdf.Array):
                for item in operand:
                    if isinstance(item, pikepdf.String):
                        text_chars += len(bytes(item))
    ratio = (text_chars / text_ops) if text_ops else 0.0
    return {"text_ops": text_ops, "text_chars": text_chars, "chars_per_op": round(ratio, 2)}


def _verdict_for_page(s: dict) -> str:
    if s["text_ops"] < MIN_OPS_FOR_SIGNAL:
        return "UNKNOWN"
    r = s["chars_per_op"]
    if r <= GLYPH_BY_GLYPH_MAX_RATIO:
        return "SEARCHABLE"   # OCR-produced layer; usable as text
    if r >= NATIVE_MIN_RATIO:
        return "SEARCHABLE"   # native layout
    return "UNKNOWN"


def evaluate(pdf_bytes: bytes, sampled: list[int]) -> Verdict:
    per_page: list[dict] = []
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        for i in sampled:
            stats = _stats(pdf.pages[i])
            per_page.append({"page": i, **stats, "verdict": _verdict_for_page(stats)})

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
