"""
Generate synthetic PDFs that exercise the two SP-1133 failure modes plus a few
sanity cases. Output: samples/*.pdf
"""
from pathlib import Path
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.utils import ImageReader

SAMPLES = Path(__file__).parent / "samples"
SAMPLES.mkdir(exist_ok=True)

W, H = LETTER  # 612 x 792 points


def gray_image(w_px=1700, h_px=2200, label="SCANNED BODY"):
    """A page-sized raster image that LOOKS like a scan."""
    img = Image.new("RGB", (w_px, h_px), (235, 235, 235))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 60)
    except Exception:
        font = ImageFont.load_default()
    for i, line in enumerate([label, "(this is pixels, not selectable text)"]):
        d.text((100, 200 + i * 90), line, fill=(50, 50, 50), font=font)
    # add some "noise" so it visually looks like a scan
    for x in range(0, w_px, 40):
        d.line([(x, 0), (x, h_px)], fill=(220, 220, 220), width=1)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)


def write_text_page(c, lines, y_start=720, leading=14, font_size=11):
    c.setFont("Helvetica", font_size)
    y = y_start
    for line in lines:
        c.drawString(72, y, line)
        y -= leading


# ---------------------------------------------------------------------------
# 1. searchable-text-only.pdf
#    Plain text document. Should be SEARCHABLE.
# ---------------------------------------------------------------------------
def make_searchable_text():
    out = SAMPLES / "1_searchable_text.pdf"
    c = canvas.Canvas(str(out), pagesize=LETTER)
    body = (
        "The quick brown fox jumps over the lazy dog. " * 4
    ).split(". ")
    for _ in range(3):
        write_text_page(c, [
            "Quarterly Report",
            "",
            *body,
            "",
            "This document contains only selectable text and no images.",
            "It should be classified as searchable by both methods.",
        ])
        c.showPage()
    c.save()
    print(f"wrote {out}")


# ---------------------------------------------------------------------------
# 2. searchable-numbers-heavy.pdf
#    The first SP-1133 case: searchable but mostly numbers, which the old
#    spell-checker would call gibberish.
# ---------------------------------------------------------------------------
def make_numbers_heavy():
    out = SAMPLES / "2_searchable_numbers_heavy.pdf"
    c = canvas.Canvas(str(out), pagesize=LETTER)
    for _ in range(3):
        write_text_page(c, [
            "Financial Statement",
            "",
            "Account      Q1         Q2         Q3         Q4",
            *[
                f"{1000+i:<10}  {1234.56+i:>9.2f}  {2345.67+i:>9.2f}  "
                f"{3456.78+i:>9.2f}  {4567.89+i:>9.2f}"
                for i in range(25)
            ],
        ])
        c.showPage()
    c.save()
    print(f"wrote {out}")


# ---------------------------------------------------------------------------
# 3. scanned-image-only.pdf
#    Page-sized raster image, no text. Clearly needs OCR.
# ---------------------------------------------------------------------------
def make_scanned_only():
    out = SAMPLES / "3_scanned_image_only.pdf"
    c = canvas.Canvas(str(out), pagesize=LETTER)
    for i in range(3):
        c.drawImage(gray_image(label=f"SCANNED PAGE {i+1}"), 0, 0, W, H)
        c.showPage()
    c.save()
    print(f"wrote {out}")


# ---------------------------------------------------------------------------
# 4. header_footer_image_body.pdf
#    The second SP-1133 case: searchable header + footer, body is one big
#    raster image. Should be OCR, but the old check + the new margin trick
#    both have edge cases here.
# ---------------------------------------------------------------------------
def make_header_footer_image_body():
    out = SAMPLES / "4_header_footer_image_body.pdf"
    c = canvas.Canvas(str(out), pagesize=LETTER)
    for i in range(3):
        # header
        c.setFont("Helvetica-Bold", 12)
        c.drawString(72, H - 40, "Acme Corp.   Confidential Memorandum")
        c.setFont("Helvetica", 9)
        c.drawString(72, H - 55, f"Document reference: ACME-2026-{i+1:03d}")
        # body image (occupies most of the page)
        body_top = H - 90
        body_bottom = 60
        c.drawImage(
            gray_image(label=f"BODY IMAGE PAGE {i+1}"),
            36, body_bottom,
            W - 72, body_top - body_bottom,
        )
        # footer
        c.setFont("Helvetica", 9)
        c.drawString(72, 40, f"Page {i+1} of 3   |   acme.example.com   |   strictly private")
        c.showPage()
    c.save()
    print(f"wrote {out}")


# ---------------------------------------------------------------------------
# 5. searchable_with_logo.pdf
#    Real text body with a small logo image. Should be SEARCHABLE -- the
#    image-coverage check needs to not over-trigger on incidental images.
# ---------------------------------------------------------------------------
def make_text_with_logo():
    out = SAMPLES / "5_searchable_with_logo.pdf"
    c = canvas.Canvas(str(out), pagesize=LETTER)
    body_lines = [
        "Project Plan",
        "",
        "This document outlines the deliverables for the upcoming quarter.",
        "Each section corresponds to one workstream and has an owner.",
        "",
        "1. Discovery and scoping",
        "2. Architecture and design",
        "3. Implementation",
        "4. Acceptance testing",
        "5. Rollout and training",
        "",
        "Refer to the appendix for the full risk register and timeline.",
    ] * 4
    for _ in range(3):
        # small logo top-right
        c.drawImage(gray_image(w_px=300, h_px=200, label="LOGO"),
                    W - 180, H - 100, 120, 60)
        write_text_page(c, body_lines)
        c.showPage()
    c.save()
    print(f"wrote {out}")


# ---------------------------------------------------------------------------
# 6. text_as_curves.pdf  (the case that defeats Option 1)
#    Text rendered as vector outlines: no selectable text AND no image
#    XObjects. Image-coverage will say 0% -> "searchable" wrongly. The
#    text-quality check should catch it (page has 0 extractable words).
# ---------------------------------------------------------------------------
def make_text_as_curves():
    """
    Simulate a text-as-vector-curves PDF. reportlab's drawPath with
    textObject(...).setTextRenderMode(3) makes glyphs invisible. To produce
    truly outlined-only text we use PIL to draw text onto a transparent
    canvas, then convert to vectors via reportlab's drawPath -- but the
    simplest reliable proxy is: a PDF with NO text objects and NO image
    XObjects, just stroked paths.
    """
    out = SAMPLES / "6_text_as_curves.pdf"
    c = canvas.Canvas(str(out), pagesize=LETTER)
    for _ in range(3):
        # draw a bunch of small line segments that visually resemble text
        for row in range(40):
            y = H - 80 - row * 15
            for col in range(50):
                x = 72 + col * 9
                c.line(x, y, x + 6, y)
                c.line(x + 3, y, x + 3, y + 7)
        c.showPage()
    c.save()
    print(f"wrote {out}")


if __name__ == "__main__":
    make_searchable_text()
    make_numbers_heavy()
    make_scanned_only()
    make_header_footer_image_body()
    make_text_with_logo()
    make_text_as_curves()
    print(f"\nGenerated {len(list(SAMPLES.glob('*.pdf')))} sample PDFs in {SAMPLES}")
