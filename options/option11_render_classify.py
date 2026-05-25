"""
Option 11 - render & visually classify.

Rasterise each sampled page to a small thumbnail and compute simple
bitmap statistics that distinguish "photo of a document" from "crisp
native PDF":

  - edge density          : Sobel-like gradient magnitude per pixel.
                            Scans have soft/anti-aliased glyph edges
                            spread over the page; native PDFs have a
                            small fraction of very sharp edges.
  - colour stdev          : standard deviation of (R+G+B)/3. Native
                            B&W pages are mostly white with thin black
                            text -> high variance, bimodal distribution.
                            Scans drift towards grey/sepia mid-tones.
  - mean brightness       : a sanity prior; scans tend to be dimmer
                            (paper colour cast).

The heuristic is intentionally crude -- the whole point of this option
is "what does the page *look* like" without needing OCR or text.

Strength: catches *anything* an extraction-based check misses, including
scans that already have an OCR layer (where Op6 would also fire) and
fully image-only docs (where Op1 fires).

Weakness: rendering is the slow path. ~50-200ms per sampled page.
Heuristics tuned for typical doc-scans; exotic colour layouts may fool
the colour stdev rule.

Engine: pypdfium2 (Apache-2.0) + PIL + numpy.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pypdfium2
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Verdict, standalone_cli  # noqa: E402

NAME = "render-classify"
RENDER_SCALE = 0.5
EDGE_THRESHOLD = 30          # gradient magnitude
SHARP_EDGE_FRACTION_MAX = 0.025   # scans: high; native: low... wait actually inverted
                                   # native B&W text has thin strokes -> small but very sharp
                                   # edges; scans have broader, softer transitions
                                   # We use it for documentation only here
COLOUR_STDEV_NATIVE_MIN = 50  # native B&W: high stdev (mostly white + bits of black)
EDGE_RATIO_NATIVE_MAX = 0.04  # native pages: few but very sharp edges
EDGE_RATIO_SCAN_MIN = 0.06    # scans: many soft-but-visible edges
                              # Anything between is UNKNOWN.


def _render_grey(page) -> np.ndarray:
    bitmap = page.render(scale=RENDER_SCALE, rotation=0, grayscale=True)
    img: Image.Image = bitmap.to_pil()
    return np.asarray(img, dtype=np.int16)


def _features(arr: np.ndarray) -> dict:
    # gradient via simple |dx|+|dy|
    dx = np.abs(np.diff(arr, axis=1))
    dy = np.abs(np.diff(arr, axis=0))
    grad = np.zeros_like(arr)
    grad[:, :-1] += dx
    grad[:-1, :] += dy
    edges = (grad >= EDGE_THRESHOLD).mean()
    return {
        "edge_ratio": float(round(edges, 4)),
        "stdev": float(round(arr.std(), 2)),
        "mean": float(round(arr.mean(), 2)),
    }


def _verdict_for_page(f: dict) -> str:
    # crisp B&W text page -> high stdev, low edge ratio
    if f["edge_ratio"] <= EDGE_RATIO_NATIVE_MAX and f["stdev"] >= COLOUR_STDEV_NATIVE_MIN:
        return "SEARCHABLE"
    # scan-like -> many soft edges spread across the page
    if f["edge_ratio"] >= EDGE_RATIO_SCAN_MIN:
        return "OCR"
    return "UNKNOWN"


def evaluate(pdf_bytes: bytes, sampled: list[int]) -> Verdict:
    per_page: list[dict] = []
    pdf = pypdfium2.PdfDocument(pdf_bytes)
    try:
        for i in sampled:
            arr = _render_grey(pdf[i])
            f = _features(arr)
            v = _verdict_for_page(f)
            per_page.append({"page": i, **f, "verdict": v})
    finally:
        pdf.close()

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
    return Verdict(
        option=NAME,
        verdict=v,
        rationale=f"per-page verdicts: OCR={ocr}, SEARCH={search}, ?={len(per_page) - ocr - search}",
        per_page=per_page,
    )


if __name__ == "__main__":
    standalone_cli(evaluate, __doc__)
