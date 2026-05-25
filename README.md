# ocr-or-not

A research harness for evaluating different ways to answer one question about a PDF:

> *Should this go through a fast direct text extractor, or do we need to send it to OCR?*

The harness implements **20 independent classifiers** plus an orchestrator that runs all of them on the same documents and prints a side-by-side verdict table, so trade-offs can be compared empirically instead of argued about.

## Methodology

This repo demonstrates an approach to engineering. The 20 classifiers, the algorithm spec of [firecrawl/pdf-inspector](https://github.com/firecrawl/pdf-inspector), and most of the code here were produced in under an hour of collaboration with Claude, starting from one ticket review.

Twenty competing classifiers, plus a third-party algorithm reverse-engineered into a precise spec, used to be a multi-week research project. The same scope here was an hour. That changes which questions are cheap to answer. "Which approach should we ship?" stops being an opinion in a meeting and becomes a verdict matrix you can run on your own documents.

The pattern generalises far beyond PDFs. Anywhere there's a routing decision, a "which library should we pick?", or a "what's the cheapest signal that's good enough?", the cost of enumerating alternatives, implementing them in parallel, and letting real data pick the winner has dropped by roughly an order of magnitude. Empirical comparison becomes the default instead of the special case.

## What's here

```
ocr-or-not/
├── README.md                       ← this file
├── PDF_INSPECTOR_ALGORITHM.md      ← spec of firecrawl/pdf-inspector's classifier
├── check.py                        ← orchestrator: run all 20 options
├── make_samples.py                 ← generate synthetic test PDFs
├── options/
│   ├── common.py                   ← sampling, pdfminer cache, CLI wrapper
│   ├── option1_image_coverage.py
│   ├── option2_producer_metadata.py
│   ├── option3_text_quality.py
│   ├── option4_repeated_headers.py
│   ├── option5_measure.py
│   ├── option6_invisible_text.py
│   ├── option7_font_fingerprint.py
│   ├── option8_unicode_quality.py
│   ├── option9_vertical_distribution.py
│   ├── option10_operator_mix.py
│   ├── option11_render_classify.py
│   ├── option12_ocr_compare.py     ← stub (tesseract not installed)
│   ├── option13_stream_bytes.py
│   ├── option14_colour_palette.py
│   ├── option15_acroform.py
│   ├── option16_struct_tree.py
│   ├── option17_span_granularity.py
│   ├── option18_bigram_plausibility.py
│   ├── option19_skew_detection.py
│   └── option20_jbig2_jpx.py
└── samples/                        ← 6 synthetic PDFs + 2 real production PDFs
```

## The 20 options

| # | Module | Signal | Engine |
|---|---|---|---|
| 1 | `image_coverage` | fraction of each page covered by raster image bounding boxes | pypdfium2 |
| 2 | `producer_metadata` | `/Producer`, `/Creator` matched against known scanner / native / OCR signatures | pypdfium2 |
| 3 | `text_quality` | pdfminer XML extraction, 10% header/footer margin trim, digit-aware gibberish check | pdfminer + pyspellchecker |
| 4 | `repeated_headers` | identify recurring lines in top/bottom 10% band across pages, exclude them, then re-check body word count + gibberish | pdfminer + pyspellchecker |
| 5 | `measure` | crudest possible: at least 30 words extracted per page means searchable | pdfminer |
| 6 | `invisible_text` | detect Tesseract/OCRmyPDF-style OCR layer via render-mode-3 text | pikepdf |
| 7 | `font_fingerprint` | font subtypes, names, ToUnicode presence | pikepdf |
| 8 | `unicode_quality` | ratio of replacement chars, PUA glyphs, `(cid:NNN)` placeholders in extracted text | pdfminer |
| 9 | `vertical_distribution` | bin lines into 10 vertical bands; flag pages with text only at top *and* bottom | pdfminer |
| 10 | `operator_mix` | text-show vs image-draw vs path operators per page | pikepdf |
| 11 | `render_classify` | rasterise + compute edge density, colour stdev, mean brightness | pypdfium2 + PIL |
| 12 | `ocr_compare` | **stub** for an option that would render, run Tesseract, compare token counts vs pdfminer | (none) |
| 13 | `stream_bytes` | uncompressed content-stream byte size per page | pikepdf |
| 14 | `colour_palette` | render at low res + colour histogram statistics | pypdfium2 + numpy |
| 15 | `acroform` | `/AcroForm.Fields` non-empty means fillable form, treat as searchable | pikepdf |
| 16 | `struct_tree` | tagged PDF (`/StructTreeRoot`) or outline (`/Outlines`) is a searchable prior | pikepdf |
| 17 | `span_granularity` | chars per text-show operator: low means glyph-by-glyph (OCR-produced); high means native | pikepdf |
| 18 | `bigram_plausibility` | ratio of bigrams that appear in a tiny common-Latin-bigram list; no spell-checker, no language list | pdfminer |
| 19 | `skew_detection` | page rotation / skew via projection-variance over candidate angles | pypdfium2 + numpy |
| 20 | `jbig2_jpx` | image XObjects with `/JBIG2Decode` or `/JPXDecode` filters are almost certainly scans | pikepdf |

Each option returns one of `SEARCHABLE`, `OCR`, or `UNKNOWN` plus a per-page breakdown. Several options are deliberately one-sided: Op6, Op15, and Op16 only ever return `SEARCHABLE` or `UNKNOWN`; Op20 only ever returns `OCR` or `UNKNOWN`.

## Setup

Python 3.10+. From the repo root:

```bash
pip install --user pypdfium2 pdfminer.six pyspellchecker pikepdf reportlab Pillow numpy
```

Optional, for Op12 (currently a stub):

```bash
sudo apt install tesseract-ocr
pip install --user pytesseract
```

Generate the synthetic sample PDFs (one-off):

```bash
python3 make_samples.py
```

## Usage

### Run all 20 options on a set of PDFs

```bash
python3 check.py samples/*.pdf
```

Prints a per-file breakdown of every option's verdict and rationale, then a side-by-side verdict matrix. Sample output:

```
=== p83.pdf  (pages: 1, sampled: [0]) ===
  [image-coverage        ] OCR        1/1 sampled pages have >=60% image coverage
  [producer-metadata     ] UNKNOWN    no signature match  [creator='', producer='PyPDF2']
  [text-quality          ] OCR        1/1 pages flagged (<= 5 words or gibberish)
  [vertical-distribution ] OCR        1/1 pages have empty middle and/or no text
  ...
```

### Run a single option standalone

Every option script has a `__main__` block that takes PDF paths and prints its own per-file report:

```bash
python3 options/option1_image_coverage.py samples/*.pdf
python3 options/option9_vertical_distribution.py samples/p83.pdf
python3 options/option20_jbig2_jpx.py some_scan.pdf
```

This is handy when iterating on a single classifier without re-running the others.

### Add a new sample PDF

Drop it in `samples/` (or anywhere) and pass it to `check.py`. No registration needed.

### Add a new option

1. Copy any `option*.py` as a template.
2. Implement `evaluate(pdf_bytes, sampled) -> Verdict`. Use helpers in `common.py` (`sample_pages`, `pdfminer_xml`, `page_count_of`, `parse_bbox`) and the `standalone_cli` wrapper for the `__main__` block.
3. Import it in `check.py` and append to `MODULES`. Add a short label to `SHORT_NAMES`.

## Findings on the current sample set (8 PDFs)

| Option | Correct | Wrong | Inconclusive |
|---|---|---|---|
| Op3 text-quality | 8 | 0 | 0 |
| Op5 measure | 8 | 0 | 0 |
| Op9 vertical-distribution | 8 | 0 | 0 |
| Op1 image-coverage | 7 | 1 | 0 |
| Op4 repeated-headers | 7 | 1 | 0 |
| Op17 span-granularity | 3 | 0 | 5 |
| Op13 stream-bytes | 2 | 1 | 5 |
| Op11 render-classify | 2 | 4 | 2 |
| Op19 skew-detection | 2 | 6 | 0 |
| Op14 colour-palette | 4 | 4 | 0 |
| Op8 unicode-quality | 4 | 2 | 2 |
| Op18 bigram-plausibility | 3 | 1 | 4 |
| Op2 producer-metadata | 3 | 3 | 2 |
| Op7 font-fingerprint | 4 | 1 | 3 |
| Op10 operator-mix | 5 | 3 | 0 |
| Op6 invisible-text | 0 | 0 | 8 *(correctly silent, no OCR'd PDFs in set)* |
| Op12 ocr-compare | 0 | 0 | 8 *(stub)* |
| Op15 acroform | 0 | 0 | 8 *(correctly silent, no forms in set)* |
| Op16 struct-tree | 0 | 0 | 8 *(correctly silent, no tagged PDFs in set)* |
| Op20 jbig2-jpx | 0 | 0 | 8 *(correctly silent, no JBIG2/JPX in synthetic data)* |

Three options hit 8/8 on this set: **Op3** (a text-quality check with margin trim and digit-aware gibberish), **Op5** (just count words), and **Op9** (vertical text distribution). The visual / scan-shaped checks (Op11, Op14, Op19) need real scanned PDFs to be evaluated properly; synthetic ReportLab "fake scans" don't have the texture or skew of real scanner output.

The 8-document sample is too small to draw production conclusions from. Expand it with real documents from the target domain before picking a strategy to ship.

## See also

[`PDF_INSPECTOR_ALGORITHM.md`](./PDF_INSPECTOR_ALGORITHM.md) is the full algorithm spec of [firecrawl/pdf-inspector](https://github.com/firecrawl/pdf-inspector), a production Rust implementation of this same problem. Worth reading before extending this harness; many of the heuristic details there (decodability, template-image rules, newspaper detection) are well-calibrated against real data.
