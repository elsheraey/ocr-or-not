# pdf-inspector: Full Algorithm Spec

A self-contained spec for [firecrawl/pdf-inspector](https://github.com/firecrawl/pdf-inspector)'s PDF classification algorithm, written from a careful read of `src/detector.rs` (3536 lines) and the key functions of `src/tounicode.rs` (3004 lines). Every threshold and conditional is verified against the source.

Caveat: extraction, table detection, Markdown conversion, and CJK character-collection tables (`extractor/`, `markdown/`, `tables/`, `structure_tree.rs`, `adobe_korea1.rs`) are out of scope; those modules don't influence the detector's output.

---

## 0. Input / output

**Input:** PDF bytes or a path. Parsed once into a PDF object model (lopdf in Rust; `pikepdf` or `pypdf` in Python both work).

**Output:**

```text
PdfTypeResult {
    pdf_type:           TextBased | Scanned | ImageBased | Mixed
    page_count:         total pages (from /Pages tree)
    pages_sampled:      pages actually analysed
    pages_with_text:    sampled pages that passed the page-level text test
    confidence:         f32 in [0.5, 0.95]; see §4
    title:              from /Info /Title (handles UTF-16BE BOM)
    ocr_recommended:    bool; may be true even when pages_needing_ocr is empty
                        (newspaper-layout case, §5)
    pages_needing_ocr:  sorted, deduped list of 1-indexed page numbers
}
```

## 1. Defaults

```text
DetectionConfig {
    strategy:                  Sample(8)        # 8 evenly distributed pages
    min_text_ops_per_page:     3
    text_page_ratio_threshold: 0.6
}
```

`EarlyExit` is **not** the default. It misclassifies annual reports with image covers.

### Page sampling (`distribute_pages(n, total)`)

```text
if n == 0:                 return []
if n >= total:             return [1..=total]
indices = [1]
if n > 1:                  indices.push(total)
remaining = n - 2
if remaining > 0 and total > 2:
    step = (total - 2) // (remaining + 1)
    for i in 1..=remaining:
        idx = 1 + step*i
        if 1 < idx < total and idx not in indices:
            indices.push(idx)
return sorted(unique(indices))
```

Always includes page 1 and page `total`; intermediate pages evenly spaced.

## 2. Stage 1: per-page analysis (`analyze_page_content`)

For each sampled page, produce:

```text
PageAnalysis {
    text_operator_count          # Tj + TJ + ' + "   (Form XObjects included)
    image_count                  # count of /Subtype /Image XObjects reachable
                                 # from page Resources, recursively through Forms.
                                 # NOT a count of Do operators.
    path_op_count                # m,l,c,h,f,re,S,s,B,b,F,f* with word boundaries
    font_change_count            # count of Tf operators
    unique_text_chars            # |set of unique non-WS bytes in text-show
                                 # operands (Tj/TJ/'/" strings + TJ-array strings)|
    unique_alphanum_chars        # subset of above that are ASCII alnum
    has_images                   # image_count > 0  OR  analyze_page_images found one
    has_template_image           # see §2b
    total_image_area             # sum of W*H over all image XObjects (raw pixels)
    has_vector_text              # see §2c
    has_identity_h_no_tounicode  # see §2d
    has_only_type3_fonts         # see §2d
    has_decodable_text_fonts     # see §2d
}
```

### 2a. Content-stream walk

For each content stream on the page (and for each Form XObject reachable through page Resources/XObject, depth-first, with a visited-set for cycle prevention):

- Tokenise raw bytes (no full PDF-op parser). Operators are detected as byte sequences with word boundaries.
- For `Tj` / `TJ` / `'` / `"`: increment `text_operator_count` and harvest text bytes by **scanning backward** from the operator position for the operand:
  - `)` indicates a literal string; balanced parens; `\` before a paren disables nesting.
  - `>` indicates a hex string; decode hex pairs, skip whitespace, drop zero bytes and ASCII whitespace codepoints.
  - `]` indicates a TJ array; walk forward inside `[...]` collecting both `(...)` literals and `<...>` hex strings.
- For `Tf`: increment `font_change_count` and extract the font name by scanning backward: skip whitespace, skip the size token, skip whitespace, read backward to `/` collecting the name. The Tf detector accepts trailing `[`, `(`, `<`, `/` as valid post-Tf delimiters (some PDFs omit whitespace).
- For path operators (single-byte: `m l c h f S s B b F`; two-byte: `re f*`): increment `path_op_count`. Word boundaries required.
- `Do` is **not** counted by the content-stream walker.

For Form XObjects, the recursion uses the **Form's own /Resources** for font-name resolution (not the page's). Font definitions found in each scope are added to a global `font_map: ObjectId -> FontInfo`.

### 2b. Image-area computation (`analyze_page_images`)

Constants:

```text
TEMPLATE_IMAGE_THRESHOLD = 500_000  # raw pixels
```

Walk the page's Resources, then its XObject subdictionary, then any /Pattern dictionary (Chrome-style screenshot pastes), recursing through Form XObjects:

- For each `/Subtype /Image`:
  - `area = Width * Height` (raw image pixels, **not** page-space coverage; transforms ignored).
  - `total_image_area += area`.
  - If `area >= TEMPLATE_IMAGE_THRESHOLD`: `has_template_image = true`.
- After walking, if `not has_template_image` but `total_image_area >= 4 * TEMPLATE_IMAGE_THRESHOLD` (≥ 2,000,000 px): `has_template_image = true`. This is the "tiled scan" rule for JBIG2 strips and scanner row tiles.

`has_template_image` is the central "this page is a single big scan" signal, but it's measured in image pixels, not page coverage. A 5000×6500 px image displayed thumbnail-sized still counts.

### 2c. Vector-outlined-text rule

```text
has_vector_text = (path_op_count >= 1000
                   AND path_op_count > text_operator_count * 200
                   AND unique_alphanum_chars < 30)
```

The 200× ratio plus the low-alnum requirement separates "decorative paths beside real text" (column rules, dividers) from "text drawn as outlines" (no real text-show ops, glyph paths everywhere).

### 2d. Font flags

Build `used_font_ids: set[ObjectId]` = font ObjectIds actually referenced by Tf operators, resolved through **PDF resource inheritance with shadowing** (ISO 32000-1, §7.7.3.4):

1. Look up the font name in the page's own inline `/Resources` if present (most-specific scope wins).
2. Else walk `/Resources` of ancestor `/Pages` nodes, most-specific to root; first dictionary that defines the name wins.
3. Form XObjects resolve names against their **own** `/Resources` (collected during the XObject recursion).

For each font in `used_font_ids`, look up its `FontInfo` (subtype, encoding name, has /ToUnicode, raw font dict) in `font_map`:

```text
has_identity_h_no_tounicode:
    needs text_operator_count > 0
    has_undecodable, has_other = false, false
    for font in used_font_ids:
        match font.subtype:
            Type0:
                if font.encoding not in {Identity-H, Identity-V}:
                    has_other = true   # named CMap, decodable
                elif font.has_tounicode:
                    has_other = true
                elif identity_h_font_has_fallback(font.dict):  # see §8
                    has_other = true
                else:
                    has_undecodable = true
            Type3:
                pass                    # handled by has_only_type3_fonts
            _ (Type1, TrueType, MMType1, ...):
                has_other = true        # decodable via standard encoding
    return has_undecodable AND NOT has_other

has_only_type3_fonts:
    needs text_operator_count > 0
    if used_font_ids empty: return false
    has_type3 = false
    for font in used_font_ids:
        if font.subtype == Type3:
            if font.has_tounicode: return false
            has_type3 = true
        else:
            return false
    return has_type3

has_decodable_text_fonts:
    needs text_operator_count > 0
    for font in used_font_ids:
        if font.has_tounicode:                          return true
        if font.subtype in {Type1, TrueType, MMType1}:  return true
        if font.subtype == Type0 and identity_h_font_has_fallback(font.dict):
                                                        return true
    return false
```

The P1+P2 source comments mean: pre-fix, the check looked at *any* font in Resources/Font, which false-flagged unused fonts and missed fonts inside Form XObjects. The production check is **usage-based** (only fonts actually selected by Tf) **and includes Form XObject fonts**.

## 3. Stage 2: per-page text-presence

For each sampled page:

```text
is_image_dominated = (image_count > 10 AND image_count > text_operator_count * 3)
effective_min_ops  = max(min_text_ops_per_page, 10) if has_images or image_count > 0
                     else min_text_ops_per_page              # 3
page_has_text = (text_operator_count >= effective_min_ops
                 AND NOT is_image_dominated
                 AND unique_text_chars >= 5
                 AND NOT has_vector_text
                 AND NOT has_only_type3_fonts)
```

Increment `pages_with_text` when `page_has_text` is true. `effective_min_ops` quietly bumps from 3 to 10 whenever the page touches any image XObject.

Classify "template-image scan" status separately:

```text
alphanum_ok = (unique_alphanum_chars < 10
               AND NOT (has_decodable_text_fonts AND text_operator_count >= 10))
page_is_template_scan = (has_template_image
                         AND image_count <= 1
                         AND text_operator_count < 50
                         AND alphanum_ok)
```

Increment `pages_with_template_images` when true. The combined condition matters: a page with several smaller images plus real text is "doc with figures", not "scan". `alphanum_ok` carves out CID-encoded text (low raw-byte diversity) when fonts are decodable.

Also: increment `pages_with_images` if `has_images`, `pages_with_vector_text` if `has_vector_text`, accumulate `total_text_ops`.

If `strategy == EarlyExit`, break out of the loop as soon as a page has insufficient text AND (`has_images` or `has_template_image`).

## 4. Stage 3: document-level classification

```text
text_ratio     = pages_with_text / pages_sampled   if pages_sampled > 0 else 0.0
template_ratio = pages_with_template_images / pages_sampled

# Rules evaluated in order; first match wins.

if pages_with_template_images > 0 AND pages_with_text > 0:
    pdf_type   = Mixed
    confidence = 0.5 + 0.3 * (1.0 - template_ratio)   # in [0.5, 0.8]
    ocr_recommended = true

elif text_ratio >= text_page_ratio_threshold (0.6):
    pdf_type   = TextBased
    confidence = text_ratio
    ocr_recommended = false

elif pages_with_text == 0 AND (pages_with_images > 0 OR pages_with_vector_text > 0):
    if total_text_ops == 0 AND pages_with_vector_text == 0:
        pdf_type = Scanned;     confidence = 0.95
    else:
        pdf_type = ImageBased;  confidence = 0.80
    ocr_recommended = true

elif pages_with_text > 0 AND (pages_with_images > 0 OR pages_with_vector_text > 0):
    pdf_type   = Mixed
    confidence = 0.70
    ocr_recommended = true

elif total_text_ops == 0:
    pdf_type   = Scanned
    confidence = 0.90
    ocr_recommended = true

else:
    pdf_type   = TextBased
    confidence = max(text_ratio, 0.5)
    ocr_recommended = false
```

## 5. Stage 3b: newspaper-layout override

Only runs if `pdf_type == TextBased AND pages_sampled >= 3`. For each cached page analysis:

```text
ratio = font_change_count / text_operator_count   if text_operator_count > 0 else 1.0
if text_operator_count >= 1500 AND font_change_count >= 50 AND ratio < 0.15:
    newspaper_pages += 1

if newspaper_pages / pages_sampled >= 0.5:
    ocr_recommended = true   # extraction works but layout is hopeless
```

Calibration notes from the source:

- WSJ-style newspapers: 1500 to 3800 text_ops/page, 50 to 194 font_changes, ratio 0.02 to 0.06.
- Styled contracts and DPAs: 1300 to 2260 text_ops, 327 to 630 font_changes, ratio 0.25 to 0.32.
- SEC filings: 1 to 1800 text_ops, 1 to 65 font_changes (only 1 or 2 dense pages, won't hit ≥50%).
- Normal docs: text_ops < 700, font_changes < 55 (won't trigger).

The `< 0.15` ratio is the key separator: newspapers have dense prose with occasional font changes; contracts have per-character font styling.

## 6. Stage 4: per-page OCR list

```text
match pdf_type:
    TextBased:
        pages_needing_ocr = []

    Scanned | ImageBased:
        pages_needing_ocr = [1..=page_count]

    Mixed:
        pages_needing_ocr = []
        for page_num in 1..=page_count:
            a = cached_analysis(page_num) OR analyze_page_content(page_num)
            alphanum_low = (a.unique_alphanum_chars < 10
                            AND NOT (a.has_decodable_text_fonts
                                     AND a.text_operator_count >= 10))
            looks_like_scan = (a.image_count <= 1
                               AND a.text_operator_count < 50
                               AND alphanum_low)
            if (a.has_template_image AND looks_like_scan)
               OR a.has_vector_text
               OR (a.text_operator_count < min_text_ops_per_page AND a.has_images):
                pages_needing_ocr.append(page_num)
        sort + dedup
```

Pages outside the sample get analysed on demand here.

## 7. Stage 5: broken-encoding pass (independent)

After Stage 4, regardless of `pdf_type`:

```text
for page_num, a in analysis_cache:
    if (a.has_identity_h_no_tounicode OR a.has_only_type3_fonts)
       and page_num not in pages_needing_ocr:
        pages_needing_ocr.append(page_num)

if pages_needing_ocr is shorter than total_pages:
    for page_num in 1..=page_count:
        if page_num in cache or in pages_needing_ocr: continue
        a = analyze_page_content(page_num)
        if a.has_identity_h_no_tounicode OR a.has_only_type3_fonts:
            pages_needing_ocr.append(page_num)

sort + dedup
```

A page can be `TextBased` overall but still flagged here because its specific font encoding is broken.

## 8. The decodability check (`identity_h_font_has_fallback`)

This is the single most subtle piece of the algorithm. A Type0 font with Identity-H/V encoding and no /ToUnicode is decodable iff **either**:

### Fallback 1: W-array CIDs look like Unicode passthrough

```text
function cid_values_look_like_unicode(cid_font_dict):
    W = cid_font_dict["W"]   # required to be an Array
    if W absent or empty:
        return false
    cids = []
    i = 0
    while i < len(W):
        cid = parse_i64(W[i])
        cids.append(cid)
        if i+1 < len(W):
            if W[i+1] is Array:           # [cid [w1 w2 ...]] form
                for j in 1..len(widths):
                    cids.append(cid + j)  # u16 wrapping add
                i += 2
            else:                          # [cid_start cid_end w] range form
                if i+2 < len(W):
                    cid_end = parse_i64(W[i+1])
                    for c in cid..=cid_end: cids.append(c)
                    i += 3
                else: i += 1
        else: i += 1
    if cids empty: return false
    sort cids
    median = cids[len(cids)//2]
    return median >= 0x41
```

The 0x41 cutoff (ASCII `'A'`) separates "Unicode-encoded CIDs" (Chromium, wkhtmltopdf, where CID literally equals the Unicode codepoint) from "GID-based subsets" (which use low CID values 0..255).

### Fallback 2: embedded TrueType has a usable cmap

Locate the descendant CIDFont's FontDescriptor `/FontFile2` (TrueType) or `/FontFile3` (OpenType), decompress the stream, parse with `ttf_parser`. The font has a usable cmap if **either**:

- Any `is_unicode()` subtable contains at least one codepoint-to-glyph mapping, **or**
- The Windows Symbol subtable `(platform=3, encoding=0)` contains mappings (after stripping `0xF000` to `0xF0FF` PUA offsets).

If neither fallback applies, the font is genuinely undecodable.

## 9. Things easy to miss

1. **`image_count` is not a count of Do operators.** It's the count of `/Subtype /Image` XObjects reachable from page Resources (recursively through Forms and Patterns). A page that declares 20 image XObjects but draws 1 still has `image_count == 20`. This matters for `is_image_dominated`.

2. **`total_image_area` is in raw image pixels**, not page-space coverage. A 5000×6500 px image displayed thumbnail-sized still triggers `has_template_image`. Their model is "this is a big scanned image" rather than "this image dominates the page visually."

3. **Tiled scans:** if no single image hits 500 K pixels but the sum is ≥ 2 M pixels, `has_template_image` still fires. Catches JBIG2 strips and per-row scanner output.

4. **`effective_min_ops = max(3, 10) = 10` whenever any image is present**, not just for template images. So a page with one tiny logo and 5 words of text fails the page-text check.

5. **`alphanum_ok` exemption for CID text.** The "looks like a scan" rule has a deliberate carve-out: if the page has decodable fonts AND ≥10 text ops, low raw-byte alnum diversity is allowed (CID-encoded text is fine even though raw bytes are non-ASCII).

6. **Font tracking is by ObjectId, not name.** Two different resource dicts can both define `/F1` pointing to different fonts. Resolving by name globally would conflate them. The detector resolves names per-scope and stores by ObjectId.

7. **Form XObject recursion is unbounded but cycle-safe** via a `visited: HashSet<ObjectId>`. Same XObject referenced twice is processed once.

8. **`get_page_resources` returns ancestor resource dicts in most-specific-first order.** First dictionary that defines a font name wins; PDF resource shadowing per ISO 32000-1 §7.7.3.4.

9. **TrueType cmap acceptance is permissive.** They accept any Unicode subtable, plus Windows Symbol `(3,0)` with PUA stripping, plus glyph-name fallback via Adobe Glyph List for fonts without any cmap. This is what rescues many "broken" PDFs from being misclassified as scans.

10. **Adobe-Korea1 CIDSystemInfo decoding.** A separate decodability path covers Korean CJK fonts. Marked "extendable to Adobe-Japan1, Adobe-GB1, Adobe-CNS1." Only Korean is wired in.

11. **Document title extraction** handles UTF-16BE with BOM (`0xFE 0xFF`); common for non-ASCII titles produced by Word or Acrobat.

12. **There is no separate "OCR layer detected" check.** Unlike Op6 in this harness, pdf-inspector does not look for invisible text (`Tr 3`). A PDF already OCR'd by Tesseract/OCRmyPDF classifies as `TextBased` if its OCR layer is good enough; they don't distinguish "originally text" from "previously OCR'd."

13. **No visual or rendered checks.** pdf-inspector is explicitly "no rendering, no ML." That's a design choice.

---

## Reading-order summary

Walk every page's content stream (and Form XObject sub-streams) counting Tj/TJ/'/", Tf, and path operators; recursively measure image XObject pixel area; resolve which fonts the text ops actually used and check those fonts for ToUnicode / standard-encoding / W-array-passthrough / embedded-TrueType-cmap decodability; classify each page from those counters into "has text" and "looks like a scan"; combine into a four-way document verdict with confidence; apply a newspaper-layout override; emit per-page OCR list from the verdict; then a final independent pass adds any page with undecodable fonts to the OCR list.

---

## License note

pdf-inspector is MIT-licensed, so its source can be directly translated. This spec describes the algorithm in language-neutral terms and matches the source line-by-line for everything that affects classification. Implement it in any language without worrying about licensing.
