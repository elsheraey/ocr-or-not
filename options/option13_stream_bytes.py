"""
Option 13 - content-stream byte size per page.

The crudest possible "is this page image-heavy?" signal: how big is the
page's compressed content stream? Image-heavy pages have streams in the
hundreds-of-KB range; pure text pages are typically a few KB.

Verdict per page:
  - stream >= BIG_STREAM_KB           -> OCR    (likely image-heavy)
  - stream <= SMALL_STREAM_KB         -> SEARCHABLE (text-only sized)
  - in between                        -> UNKNOWN

Cheapest of all options after Op2 (metadata); useful as a fast prior
even though it's clearly imperfect (a page with thousands of vector
path operators can also be big without being a scan).

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

NAME = "stream-bytes"
BIG_STREAM_KB = 100
SMALL_STREAM_KB = 5


def _page_stream_kb(page) -> int:
    """Sum the *uncompressed* size of all content streams on the page."""
    contents = page.get("/Contents")
    if contents is None:
        return 0
    streams = contents if isinstance(contents, pikepdf.Array) else [contents]
    total = 0
    for s in streams:
        try:
            total += len(s.read_bytes())
        except Exception:
            pass
    return total // 1024


def _verdict_for_page(kb: int) -> str:
    if kb >= BIG_STREAM_KB:
        return "OCR"
    if 0 < kb <= SMALL_STREAM_KB:
        return "SEARCHABLE"
    return "UNKNOWN"


def evaluate(pdf_bytes: bytes, sampled: list[int]) -> Verdict:
    per_page: list[dict] = []
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        for i in sampled:
            kb = _page_stream_kb(pdf.pages[i])
            per_page.append({"page": i, "stream_kb": kb, "verdict": _verdict_for_page(kb)})

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
