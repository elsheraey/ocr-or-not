"""
Option 1 - image-coverage check.

For each sampled page, sum the bounding boxes of raster image XObjects
(clipped to the page bbox) and divide by page area. If most sampled pages
are mostly raster, the body is dominated by images and the document needs OCR.

Strength: directly answers "is the body a picture?". Catches the SP-1133
header/footer-with-image-body case without any margin trick.

Weakness: blind to documents that contain neither images nor extractable
text -- e.g. text rendered as vector outlines, or broken CID fonts.

Engine: pypdfium2 (Apache-2.0).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pypdfium2
import pypdfium2.raw as pdfium_c

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Verdict, standalone_cli  # noqa: E402

NAME = "image-coverage"
COVERAGE_THRESHOLD = 0.60  # >=60% of page is raster -> page is "image-dominated"


def evaluate(pdf_bytes: bytes, sampled: list[int]) -> Verdict:
    per_page: list[dict] = []
    pdf = pypdfium2.PdfDocument(pdf_bytes)
    try:
        for i in sampled:
            page = pdf[i]
            pw, ph = page.get_size()
            page_area = pw * ph
            covered = 0.0
            n_images = 0
            for obj in page.get_objects(
                filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE], max_depth=2,
            ):
                left, bottom, right, top = obj.get_bounds()
                cl = max(left, 0.0)
                cb = max(bottom, 0.0)
                cr = min(right, pw)
                ct = min(top, ph)
                if cr > cl and ct > cb:
                    covered += (cr - cl) * (ct - cb)
                    n_images += 1
            cov = (covered / page_area) if page_area > 0 else 0.0
            per_page.append({
                "page": i,
                "image_count": n_images,
                "coverage": round(cov, 4),
                "image_dominated": cov >= COVERAGE_THRESHOLD,
            })
    finally:
        pdf.close()

    if not per_page:
        return Verdict(NAME, "OCR", "no pages")
    threshold = math.floor(len(per_page) / 2) + 1
    bad = sum(1 for p in per_page if p["image_dominated"])
    verdict = "OCR" if bad >= threshold else "SEARCHABLE"
    return Verdict(
        option=NAME,
        verdict=verdict,
        rationale=f"{bad}/{len(per_page)} sampled pages have >={int(COVERAGE_THRESHOLD*100)}% image coverage",
        per_page=per_page,
    )


if __name__ == "__main__":
    standalone_cli(evaluate, __doc__)
