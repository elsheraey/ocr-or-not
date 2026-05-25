"""
Option 10 - content-stream operator mix.

Look at the raw PDF drawing operators on each page and classify by which
class dominates:

  - text-show ops   (Tj, TJ, ', ")        -> real text content
  - image-draw ops  (Do referencing an    -> raster image content
                     Image XObject)
  - path ops        (l, c, m, re, f, S,   -> vector / "text as curves"
                     b, ...)

Verdict per page:
  - if image-draw ops cover most of the page area      -> OCR
  - if path ops dominate AND text chars are sparse     -> OCR (text-as-curves)
  - if text chars dominate                             -> SEARCHABLE
  - else                                               -> UNKNOWN

Distinctive feature: this is the only check that can call out the
text-as-curves case from a *positive* signal (lots of path ops) rather
than the absence of text. That makes it a useful sibling to Op1.

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

NAME = "operator-mix"

TEXT_OPS = {"Tj", "TJ", "'", '"'}
PATH_OPS = {"l", "c", "v", "y", "re", "f", "F", "f*", "S", "s", "B", "b", "B*", "b*"}
IMAGE_OP = "Do"  # only counts when name resolves to an Image XObject

PATH_DOMINATES_RATIO = 50    # path ops per text char above this -> path-heavy
MIN_TEXT_CHARS = 30
MIN_IMAGE_DRAWS = 1


def _is_image_xobject(resources, name) -> bool:
    try:
        xobj = resources.XObject[name]
        return str(xobj.Subtype) == "/Image"
    except Exception:
        return False


def _analyse_page(page) -> dict:
    text_chars = 0
    image_draws = 0
    path_ops = 0
    text_show_ops = 0
    try:
        resources = page.Resources
    except (AttributeError, KeyError):
        resources = None
    try:
        stream = pikepdf.parse_content_stream(page)
    except Exception:
        return {"text_chars": 0, "image_draws": 0, "path_ops": 0, "text_show_ops": 0}
    for operands, operator in stream:
        op = str(operator)
        if op in TEXT_OPS:
            text_show_ops += 1
            for operand in operands:
                if isinstance(operand, pikepdf.String):
                    text_chars += len(bytes(operand))
                elif isinstance(operand, pikepdf.Array):
                    for item in operand:
                        if isinstance(item, pikepdf.String):
                            text_chars += len(bytes(item))
        elif op == IMAGE_OP and operands and resources is not None:
            if _is_image_xobject(resources, operands[0]):
                image_draws += 1
        elif op in PATH_OPS:
            path_ops += 1
    return {
        "text_chars": text_chars,
        "image_draws": image_draws,
        "path_ops": path_ops,
        "text_show_ops": text_show_ops,
    }


def _verdict_for_page(stats: dict) -> str:
    if stats["image_draws"] >= MIN_IMAGE_DRAWS and stats["text_chars"] < MIN_TEXT_CHARS:
        return "OCR"
    if stats["text_chars"] >= MIN_TEXT_CHARS:
        return "SEARCHABLE"
    path_per_char = (stats["path_ops"] / stats["text_chars"]) if stats["text_chars"] else float("inf")
    if stats["path_ops"] > 0 and path_per_char >= PATH_DOMINATES_RATIO:
        return "OCR"
    if stats["text_chars"] == 0 and stats["image_draws"] == 0 and stats["path_ops"] == 0:
        return "UNKNOWN"
    return "UNKNOWN"


def evaluate(pdf_bytes: bytes, sampled: list[int]) -> Verdict:
    per_page: list[dict] = []
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        for i in sampled:
            stats = _analyse_page(pdf.pages[i])
            verdict = _verdict_for_page(stats)
            per_page.append({"page": i, **stats, "verdict": verdict})

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
