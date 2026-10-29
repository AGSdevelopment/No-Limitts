"""No Limitts logo on generated PDFs: the logo sits in the top-left header and page content starts below it."""
from pathlib import Path

LOGO = Path(__file__).resolve().parent / "assets" / "no-limitts-logo.png"
LOGO_RECT = (36, 22, 156, 112)  # 120 x 90 pt, same 4:3 shape as the logo
FIRST_TOP = 122  # first page content starts under the logo


def add_logo(pdf: bytes) -> bytes:
    import pymupdf
    doc = pymupdf.open("pdf", pdf)
    doc[0].insert_image(pymupdf.Rect(*LOGO_RECT), filename=str(LOGO), keep_proportion=True)
    return doc.tobytes(deflate=True)
