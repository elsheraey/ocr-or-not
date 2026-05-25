"""
Comparison driver: runs every options/option*.py module against the PDFs
given on the command line and prints a side-by-side verdict matrix.

Usage:
    python3 check.py samples/*.pdf p83.pdf table_two_pages.pdf
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "options"))

import common  # noqa: E402
import option1_image_coverage as op1   # noqa: E402
import option2_producer_metadata as op2  # noqa: E402
import option3_text_quality as op3     # noqa: E402
import option4_repeated_headers as op4  # noqa: E402
import option5_measure as op5          # noqa: E402
import option6_invisible_text as op6   # noqa: E402
import option7_font_fingerprint as op7  # noqa: E402
import option8_unicode_quality as op8  # noqa: E402
import option9_vertical_distribution as op9  # noqa: E402
import option10_operator_mix as op10   # noqa: E402
import option11_render_classify as op11  # noqa: E402
import option12_ocr_compare as op12    # noqa: E402
import option13_stream_bytes as op13   # noqa: E402
import option14_colour_palette as op14  # noqa: E402
import option15_acroform as op15       # noqa: E402
import option16_struct_tree as op16    # noqa: E402
import option17_span_granularity as op17  # noqa: E402
import option18_bigram_plausibility as op18  # noqa: E402
import option19_skew_detection as op19  # noqa: E402
import option20_jbig2_jpx as op20      # noqa: E402

MODULES = [op1, op2, op3, op4, op5, op6, op7, op8, op9, op10,
           op11, op12, op13, op14, op15, op16, op17, op18, op19, op20]

SHORT_NAMES = {
    "image-coverage":         "img-cov",
    "producer-metadata":      "meta",
    "text-quality":           "text-qual",
    "repeated-headers":       "rep-hdr",
    "measure":                "measure",
    "invisible-text":         "invis-txt",
    "font-fingerprint":       "font-fp",
    "unicode-quality":        "unicode",
    "vertical-distribution":  "vdist",
    "operator-mix":           "ops-mix",
    "render-classify":        "rend-cls",
    "ocr-compare":            "ocr-cmp",
    "stream-bytes":           "strm-kb",
    "colour-palette":         "colour",
    "acroform":               "acroform",
    "struct-tree":            "struct",
    "span-granularity":       "span-gr",
    "bigram-plausibility":    "bigram",
    "skew-detect":            "skew",
    "jbig2-jpx":              "jbig2",
}


def short(verdict: str) -> str:
    return {"SEARCHABLE": "SEARCH", "OCR": "OCR", "UNKNOWN": "?"}.get(verdict, verdict)


def run_file(path: Path) -> tuple[str, list[common.Verdict]]:
    pdf_bytes = path.read_bytes()
    total = common.page_count_of(pdf_bytes)
    sampled = common.sample_pages(total)
    results = [m.evaluate(pdf_bytes, sampled) for m in MODULES]
    print(f"\n=== {path.name}  (pages: {total}, sampled: {sampled}) ===")
    for v in results:
        print(f"  [{v.option:<22}] {v.verdict:<10} {v.rationale}")
    return path.name, results


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    args = ap.parse_args(argv)

    summary: list[tuple[str, list[common.Verdict]]] = []
    for p in args.paths:
        path = Path(p)
        if not path.exists():
            print(f"!! missing: {path}", file=sys.stderr)
            continue
        summary.append(run_file(path))

    col_w = 9
    file_w = 32
    headers = ["file"] + [SHORT_NAMES.get(m.NAME, m.NAME) for m in MODULES]
    widths = [file_w] + [col_w] * len(MODULES)
    total_w = sum(widths) + len(widths)
    print("\n" + "=" * total_w)
    print(" ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print("-" * total_w)
    for fname, results in summary:
        row = [fname[:file_w].ljust(file_w)]
        row += [short(r.verdict).ljust(col_w) for r in results]
        print(" ".join(row))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
