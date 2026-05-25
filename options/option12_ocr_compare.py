"""
Option 12 - OCR vs extraction comparison (STUB).

The "real" measure-don't-predict approach: render each sampled page,
run our OCR pipeline against it, then compare token counts to
pdfminer's extraction. If OCR yields substantially more text than
extraction, the searchable text layer is incomplete -> use OCR. Else
-> use extraction.

This is intentionally a stub in the ocr-test harness because the local
environment doesn't have a tesseract binary (and apt requires sudo).
Install:

    sudo apt install tesseract-ocr
    pip install pytesseract

then replace `evaluate` with the real implementation -- roughly:

    import pytesseract
    from PIL import Image

    pdf = pypdfium2.PdfDocument(pdf_bytes)
    for i in sampled:
        img = pdf[i].render(scale=2.0).to_pil()
        ocr_text = pytesseract.image_to_string(img)
        # vs pdfminer extraction (use common.pdfminer_xml + page text)
        # ratio of token counts -> verdict

The stub returns UNKNOWN so the orchestrator column stays informative.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Verdict, standalone_cli  # noqa: E402

NAME = "ocr-compare"


def evaluate(pdf_bytes: bytes, sampled: list[int]) -> Verdict:
    return Verdict(
        option=NAME,
        verdict="UNKNOWN",
        rationale="stub: tesseract not installed in this environment",
        per_page=[],
    )


if __name__ == "__main__":
    standalone_cli(evaluate, __doc__)
