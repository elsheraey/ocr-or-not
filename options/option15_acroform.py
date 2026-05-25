"""
Option 15 - AcroForm / fillable-fields short-circuit.

If the PDF has an /AcroForm dictionary with /Fields, it's almost
certainly a fillable digital form (tax filing, application, contract).
Forms require form-element semantics that scans don't have. A strong
*whole-document* SEARCHABLE short-circuit.

Verdict:
  SEARCHABLE  : /AcroForm.Fields is non-empty
  UNKNOWN     : no /AcroForm at all (this option doesn't apply)

This is intentionally one-sided -- it never returns OCR. It exists to
let the orchestrator skip everything else for fillable PDFs.

Engine: pikepdf (MPL-2.0).
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pikepdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Verdict, standalone_cli  # noqa: E402

NAME = "acroform"


def evaluate(pdf_bytes: bytes, sampled: list[int]) -> Verdict:
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        try:
            acroform = pdf.Root.AcroForm
            fields = acroform.get("/Fields", pikepdf.Array())
            n = len(fields)
        except (AttributeError, KeyError):
            n = 0
            acroform = None

    if acroform is not None and n > 0:
        return Verdict(NAME, "SEARCHABLE", f"AcroForm with {n} fillable field(s)")
    return Verdict(NAME, "UNKNOWN", "no AcroForm / no fillable fields")


if __name__ == "__main__":
    standalone_cli(evaluate, __doc__)
