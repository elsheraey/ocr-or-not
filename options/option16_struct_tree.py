"""
Option 16 - structure tree / tagged-PDF prior.

PDFs with a /StructTreeRoot (tagged for accessibility / PDF/UA / PDF/A)
were authored as PDFs by tools that emit semantic structure -- they're
essentially never scans. Same goes for documents with a logical outline
(/Outlines): scanned PDFs almost never have one.

Verdict:
  SEARCHABLE  : /StructTreeRoot OR a non-trivial /Outlines tree
  UNKNOWN     : neither -- this option doesn't apply

One-sided like Op15: it never returns OCR. It's a fast SEARCHABLE
prior, not a routing decision on its own.

Engine: pikepdf (MPL-2.0).
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pikepdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Verdict, standalone_cli  # noqa: E402

NAME = "struct-tree"


def evaluate(pdf_bytes: bytes, sampled: list[int]) -> Verdict:
    has_struct = False
    has_outline = False
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        try:
            _ = pdf.Root.StructTreeRoot
            has_struct = True
        except (AttributeError, KeyError):
            pass
        try:
            outlines = pdf.Root.Outlines
            has_outline = "/First" in outlines.keys()
        except (AttributeError, KeyError):
            pass

    if has_struct and has_outline:
        return Verdict(NAME, "SEARCHABLE", "tagged PDF with outline")
    if has_struct:
        return Verdict(NAME, "SEARCHABLE", "tagged PDF (StructTreeRoot present)")
    if has_outline:
        return Verdict(NAME, "SEARCHABLE", "has logical outline")
    return Verdict(NAME, "UNKNOWN", "no structure tree, no outline")


if __name__ == "__main__":
    standalone_cli(evaluate, __doc__)
