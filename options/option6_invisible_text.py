"""
Option 6 - invisible OCR layer detection.

OCR engines (ABBYY, Tesseract, OCRmyPDF, Acrobat Capture, ...) typically
write the recognised text as a hidden layer behind the page image, using
text render mode 3 (Tr 3 in the content stream). If most of a page's text
chars are drawn in mode 3, the PDF already has a usable OCR layer and we
should treat it as SEARCHABLE rather than re-OCR.

This option is intentionally conservative: if there's no invisible text
at all, it returns UNKNOWN -- it's not designed to decide visible-text
cases, only to short-circuit "already OCR'd" documents.

Engine: pikepdf (MPL-2.0).
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pikepdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Verdict, standalone_cli  # noqa: E402

NAME = "invisible-text"
INVISIBLE_MODE = 3
DOMINANCE_THRESHOLD = 0.5  # invisible_chars / (visible+invisible) >= this -> OCR layer


def _count_text_chars(operands, mode_stack: list[int], counts: list[int]) -> None:
    """counts is [visible, invisible]; mutate in place."""
    mode = mode_stack[-1]
    bucket = 1 if mode == INVISIBLE_MODE else 0
    for operand in operands:
        if isinstance(operand, pikepdf.String):
            counts[bucket] += len(bytes(operand))
        elif isinstance(operand, pikepdf.Array):
            for item in operand:
                if isinstance(item, pikepdf.String):
                    counts[bucket] += len(bytes(item))


def _analyse_page(page) -> tuple[int, int]:
    """Returns (visible_chars, invisible_chars) for one page."""
    mode_stack = [0]
    counts = [0, 0]
    try:
        stream = pikepdf.parse_content_stream(page)
    except Exception:
        return 0, 0
    for operands, operator in stream:
        op = str(operator)
        if op == "q":
            mode_stack.append(mode_stack[-1])
        elif op == "Q" and len(mode_stack) > 1:
            mode_stack.pop()
        elif op == "Tr" and operands:
            try:
                mode_stack[-1] = int(operands[0])
            except (TypeError, ValueError):
                pass
        elif op in ("Tj", "'", '"', "TJ"):
            _count_text_chars(operands, mode_stack, counts)
    return counts[0], counts[1]


def evaluate(pdf_bytes: bytes, sampled: list[int]) -> Verdict:
    per_page: list[dict] = []
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        for i in sampled:
            visible, invisible = _analyse_page(pdf.pages[i])
            total = visible + invisible
            ratio = (invisible / total) if total else 0.0
            per_page.append({
                "page": i,
                "visible_chars": visible,
                "invisible_chars": invisible,
                "invisible_ratio": round(ratio, 3),
                "has_ocr_layer": ratio >= DOMINANCE_THRESHOLD and invisible > 0,
            })

    if not per_page:
        return Verdict(NAME, "UNKNOWN", "no pages")
    any_invisible = sum(p["invisible_chars"] for p in per_page)
    if any_invisible == 0:
        return Verdict(NAME, "UNKNOWN", "no invisible text found on any sampled page", per_page)

    layered = sum(1 for p in per_page if p["has_ocr_layer"])
    rationale = f"{layered}/{len(per_page)} pages have a dominant invisible text layer"
    verdict = "SEARCHABLE" if layered >= 1 else "UNKNOWN"
    return Verdict(NAME, verdict, rationale, per_page)


if __name__ == "__main__":
    standalone_cli(evaluate, __doc__)
