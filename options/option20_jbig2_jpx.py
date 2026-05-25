"""
Option 20 - JBIG2 / JPEG2000 image-stream filter detection.

JBIG2 (filter /JBIG2Decode) is used almost exclusively for the binary
"text mask" in scanned documents. JPEG2000 (/JPXDecode) is the colour-
photo companion. Encountering either as a filter on an Image XObject
is overwhelmingly evidence that the page is a scan or a re-saved scan.

Verdict per page:
  OCR         : page has at least one image XObject with JBIG2 or JPX
                (or one of the other scan-only filters)
  UNKNOWN     : no scan-typical filters present (defer to other options)

Single highest-information cheap signal: O(1) per page, ~15 lines.

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

NAME = "jbig2-jpx"

# Filters commonly emitted by scan-to-PDF / OCR-PDF tools
SCAN_FILTERS = {"/JBIG2Decode", "/JPXDecode", "/CCITTFaxDecode"}


def _filters_of(stream_obj) -> set[str]:
    try:
        f = stream_obj.Filter
    except (AttributeError, KeyError):
        return set()
    if isinstance(f, pikepdf.Array):
        return {str(x) for x in f}
    return {str(f)}


def _scan_filter_hits(page) -> dict:
    hits: dict[str, int] = {k: 0 for k in SCAN_FILTERS}
    try:
        xobjects = page.Resources.XObject
    except (AttributeError, KeyError):
        return {"hits": hits, "total": 0}
    for _, obj in xobjects.items():
        try:
            if str(obj.Subtype) != "/Image":
                continue
        except (AttributeError, KeyError):
            continue
        for f in _filters_of(obj):
            if f in SCAN_FILTERS:
                hits[f] += 1
    return {"hits": hits, "total": sum(hits.values())}


def _verdict_for_page(s: dict) -> str:
    return "OCR" if s["total"] > 0 else "UNKNOWN"


def evaluate(pdf_bytes: bytes, sampled: list[int]) -> Verdict:
    per_page: list[dict] = []
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        for i in sampled:
            s = _scan_filter_hits(pdf.pages[i])
            per_page.append({"page": i, **s, "verdict": _verdict_for_page(s)})

    if not per_page:
        return Verdict(NAME, "UNKNOWN", "no pages")
    threshold = math.floor(len(per_page) / 2) + 1
    ocr = sum(1 for p in per_page if p["verdict"] == "OCR")
    if ocr >= threshold:
        return Verdict(NAME, "OCR", f"{ocr}/{len(per_page)} pages have JBIG2/JPX/CCITT image streams", per_page)
    return Verdict(NAME, "UNKNOWN", "no scan-typical image filters found", per_page)


if __name__ == "__main__":
    standalone_cli(evaluate, __doc__)
