"""
Option 14 - colour palette analysis.

Render each sampled page at low resolution and look at the colour
histogram. Distinguishes:

  - native B&W document  : near-bimodal (mostly white, some black),
                           very limited colour palette, high stdev
  - native colour design : multiple distinct colours, often saturated
  - scanned page         : a wide band of mid-tones (paper colour
                           cast, JPEG artefacts), low saturation,
                           continuous histogram instead of spikes

Verdict per page:
  - palette spread is broad AND saturation low      -> OCR (scan)
  - palette is sparse / bimodal                     -> SEARCHABLE (native)
  - otherwise                                       -> UNKNOWN

Complements Op11 (Op11 looks at edge density; Op14 looks at colour
distribution). Two visual signals that disagree mean the page is weird.

Engine: pypdfium2 (Apache-2.0) + PIL + numpy.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pypdfium2

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Verdict, standalone_cli  # noqa: E402

NAME = "colour-palette"
RENDER_SCALE = 0.4
DISTINCT_BUCKETS_NATIVE_MAX = 12     # # of populated luminance buckets out of 16
MID_TONE_FRACTION_SCAN_MIN = 0.10    # fraction of pixels in mid-tone band (80..200)
SATURATION_NATIVE_MAX = 0.10         # native designs may be colour; scans rarely saturated


def _render_rgb(page) -> np.ndarray:
    bitmap = page.render(scale=RENDER_SCALE, rotation=0)
    return np.asarray(bitmap.to_pil().convert("RGB"), dtype=np.int16)


def _features(arr: np.ndarray) -> dict:
    grey = arr.mean(axis=2)
    hist, _ = np.histogram(grey, bins=16, range=(0, 256))
    distinct_buckets = int((hist > grey.size * 0.005).sum())
    mid_tone = float(((grey > 80) & (grey < 200)).mean())
    rng = arr.max(axis=2) - arr.min(axis=2)
    saturation = float((rng > 30).mean())
    return {
        "distinct_buckets": distinct_buckets,
        "mid_tone_frac": round(mid_tone, 4),
        "saturation_frac": round(saturation, 4),
    }


def _verdict_for_page(f: dict) -> str:
    if (
        f["mid_tone_frac"] >= MID_TONE_FRACTION_SCAN_MIN
        and f["saturation_frac"] <= SATURATION_NATIVE_MAX
    ):
        return "OCR"
    if f["distinct_buckets"] <= DISTINCT_BUCKETS_NATIVE_MAX:
        return "SEARCHABLE"
    return "UNKNOWN"


def evaluate(pdf_bytes: bytes, sampled: list[int]) -> Verdict:
    per_page: list[dict] = []
    pdf = pypdfium2.PdfDocument(pdf_bytes)
    try:
        for i in sampled:
            f = _features(_render_rgb(pdf[i]))
            per_page.append({"page": i, **f, "verdict": _verdict_for_page(f)})
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
    return Verdict(NAME, v, f"OCR={ocr}, SEARCH={search}, ?={len(per_page)-ocr-search}", per_page)


if __name__ == "__main__":
    standalone_cli(evaluate, __doc__)
