"""
Option 2 - PDF producer/creator metadata sniff.

Reads /Producer and /Creator from the PDF info dictionary and matches them
against three lists of known signatures:

  - NATIVE      : tools that emit text-based PDFs (Word, InDesign, LaTeX,
                  Chrome, ReportLab, etc.) -> very likely SEARCHABLE
  - OCR_LAYER   : tools that add an OCR text layer (ABBYY, Tesseract,
                  OCRmyPDF, Acrobat Capture) -> SEARCHABLE (already OCR'd)
  - SCANNER     : scanner/MFP firmware strings with no OCR mention
                  -> almost certainly needs OCR

Strength: cheapest possible signal (one metadata read). Strong PRIOR.

Weakness: only tells you who *made* the file, not what's *in* it. A PDF
made with ReportLab can still contain only images. So Option 2 is a tie-
breaker / fast-path, not a sole classifier.

Engine: pypdfium2 (Apache-2.0).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pypdfium2

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Verdict, standalone_cli  # noqa: E402

NAME = "producer-metadata"

# Substrings matched case-insensitively against `creator + " | " + producer`.
NATIVE_PRODUCERS = [
    "microsoft® word", "microsoft word", "word for",
    "adobe indesign", "adobe illustrator", "adobe acrobat pro",
    "powerpoint", "excel",
    "latex", "pdftex", "xetex", "luatex", "pdflatex",
    "pages",                            # Apple Pages
    "google docs", "google sheets",
    "reportlab",
    "skia/pdf",                         # Chrome / Chromium print
    "weasyprint", "wkhtmltopdf", "prince",
    "itext", "itextsharp",
    "fpdf", "tcpdf", "mpdf",
    "apache fop",
    "openoffice", "libreoffice",
    "scribus",
    "mozilla",                          # Firefox print to PDF
]

OCR_LAYER_PRODUCERS = [
    "abbyy", "finereader",
    "tesseract", "ocrmypdf",
    "acrobat capture", "adobe acrobat ocr",
    "readiris",
    "kofax",                             # often paired with OCR
]

SCANNER_PRODUCERS = [
    "canon ir", "canon scan", "canon mf",
    "xerox workcentre", "xerox altalink", "xerox versalink",
    "hp mfp", "hp laserjet mfp", "hp scanjet",
    "konica minolta", "bizhub",
    "ricoh mp", "ricoh im",
    "brother mfc", "brother dcp",
    "epson scan",
    "kodak scan", "i-series", "i series",
    "plustek", "fujitsu fi", "scansnap",
    "samsung scx",
    "sharp ar", "sharp mx",
]


def classify(signature: str) -> tuple[str, str]:
    s = signature.lower()
    for key in OCR_LAYER_PRODUCERS:
        if key in s:
            return "SEARCHABLE", f"OCR-layer producer matched: '{key}'"
    for key in SCANNER_PRODUCERS:
        if key in s:
            return "OCR", f"scanner producer matched: '{key}'"
    for key in NATIVE_PRODUCERS:
        if key in s:
            return "SEARCHABLE", f"native producer matched: '{key}'"
    return "UNKNOWN", "no signature match"


def evaluate(pdf_bytes: bytes, sampled: list[int]) -> Verdict:
    pdf = pypdfium2.PdfDocument(pdf_bytes)
    try:
        meta = pdf.get_metadata_dict()
    finally:
        pdf.close()
    creator = (meta.get("Creator") or "").strip()
    producer = (meta.get("Producer") or "").strip()
    signature = f"{creator} | {producer}"
    verdict, why = classify(signature)
    return Verdict(
        option=NAME,
        verdict=verdict,
        rationale=f"{why}  [creator={creator!r}, producer={producer!r}]",
        per_page=[],   # whole-document signal, no per-page rows
    )


if __name__ == "__main__":
    standalone_cli(evaluate, __doc__)
