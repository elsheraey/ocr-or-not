"""
Shared utilities used by every option-script: sampling, dataclasses, the
standalone CLI runner, and the pdfminer XML cache (re-extracting per option
would otherwise dominate runtime).
"""
from __future__ import annotations

import argparse
import functools
import io
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pdfminer.high_level
import pdfminer.layout
import pdfminer.settings
import pypdfium2

pdfminer.settings.STRICT = False

# Sampling defaults mirror file-processor/miner/utils.py
SAMPLE_PERCENTAGE = 0.25
SAMPLE_UPPER = 20
SAMPLE_LOWER = 3
RANDOM_SEED = 43


@dataclass
class Verdict:
    """The output every option module returns."""
    option: str                      # short label e.g. "image-coverage"
    verdict: str                     # "OCR" | "SEARCHABLE" | "UNKNOWN"
    rationale: str                   # one-line explanation
    per_page: list[dict] = field(default_factory=list)


def sample_pages(page_count: int) -> list[int]:
    if page_count <= 0:
        return []
    n = min(SAMPLE_UPPER, max(SAMPLE_LOWER, int(page_count * SAMPLE_PERCENTAGE)))
    n = min(n, page_count)
    random.seed(RANDOM_SEED)
    return sorted(random.sample(range(page_count), n))


def page_count_of(pdf_bytes: bytes) -> int:
    pdf = pypdfium2.PdfDocument(pdf_bytes)
    try:
        return len(pdf)
    finally:
        pdf.close()


@functools.lru_cache(maxsize=8)
def _cached_pdfminer_xml(pdf_bytes: bytes, page_numbers_key: tuple[int, ...]) -> str:
    """Internal cache so multiple options re-use the same pdfminer extraction."""
    out = io.BytesIO()
    pdfminer.high_level.extract_text_to_fp(
        io.BytesIO(pdf_bytes),
        outfp=out,
        output_type="xml",
        laparams=pdfminer.layout.LAParams(),
        page_numbers=list(page_numbers_key),
    )
    return out.getvalue().decode("utf-8", errors="replace")


def pdfminer_xml(pdf_bytes: bytes, page_numbers: list[int]) -> str:
    return _cached_pdfminer_xml(pdf_bytes, tuple(page_numbers))


def parse_bbox(value: str | None) -> tuple[float, float, float, float] | None:
    if not value:
        return None
    parts = value.split(",")
    if len(parts) != 4:
        return None
    try:
        x_left, y_bottom, x_right, y_top = [float(p) for p in parts]
    except ValueError:
        return None
    return x_left, y_bottom, x_right, y_top


def standalone_cli(evaluate_fn, doc: str) -> None:
    """
    Drop-in `if __name__ == '__main__'` runner for every option module.
    Lets you do `python3 options/option2_producer_metadata.py *.pdf` and
    get a per-file verdict without going through the orchestrator.
    """
    ap = argparse.ArgumentParser(description=doc)
    ap.add_argument("paths", nargs="+")
    args = ap.parse_args()
    for p in args.paths:
        path = Path(p)
        if not path.exists():
            print(f"!! missing: {path}", file=sys.stderr)
            continue
        pdf_bytes = path.read_bytes()
        total = page_count_of(pdf_bytes)
        sampled = sample_pages(total)
        v: Verdict = evaluate_fn(pdf_bytes, sampled)
        print(f"\n=== {path.name}  (pages: {total}, sampled: {sampled}) ===")
        print(f"  verdict   : {v.verdict}")
        print(f"  rationale : {v.rationale}")
        if v.per_page:
            for row in v.per_page:
                print(f"    {row}")
