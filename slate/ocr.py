"""
OCR fallback for non-editable (scanned / outlined) text.

When a region has no extractable text, we rasterize it, run Tesseract, and rebuild
"virtual" spans (text + bbox + an estimated font size + a guessed family). Those spans
plug into exactly the same redact-and-reinsert editing path as real text, so a scanned
line can be removed and a corrected line dropped into the same spot.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Optional

import fitz

from .pdf_document import PdfDocument, TextSpan
from . import font_manager as fm

try:
    import pytesseract
    from PIL import Image
    import io
    _HAVE_PYTESSERACT = True
except Exception:
    _HAVE_PYTESSERACT = False


OCR_DPI = 300  # render resolution for recognition


def tesseract_available() -> bool:
    if not _HAVE_PYTESSERACT:
        return False
    return shutil.which("tesseract") is not None or _cmd_set()


def _cmd_set() -> bool:
    try:
        return bool(pytesseract.pytesseract.tesseract_cmd) and \
            shutil.which(pytesseract.pytesseract.tesseract_cmd) is not None
    except Exception:
        return False


def configure_tesseract(path: Optional[str]):
    """Point pytesseract at a specific tesseract binary (e.g. a bundled one)."""
    if path and _HAVE_PYTESSERACT:
        pytesseract.pytesseract.tesseract_cmd = path


@dataclass
class OcrWord:
    text: str
    bbox_pts: tuple[float, float, float, float]   # in PDF points
    conf: float
    est_size: float
    guessed_family: str


def _guess_family_serif(height_px: float) -> str:
    # We can't truly identify a typeface from a raster without a model; default to a
    # safe sans family. (Heuristics could be added; honesty over false precision.)
    return "Helvetica"


def ocr_page_region(
    document: PdfDocument,
    page_index: int,
    clip_pts: Optional[tuple[float, float, float, float]] = None,
    lang: str = "eng",
) -> list[OcrWord]:
    """Run OCR over a page (or a sub-rectangle) and return positioned words."""
    if not tesseract_available():
        raise RuntimeError("Tesseract OCR is not available.")
    page = document.doc[page_index]
    zoom = OCR_DPI / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    clip = fitz.Rect(clip_pts) if clip_pts else None
    pix = page.get_pixmap(matrix=matrix, clip=clip, alpha=False)
    img = Image.open(io.BytesIO(pix.tobytes("png")))

    data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)
    origin_x = clip.x0 if clip else 0.0
    origin_y = clip.y0 if clip else 0.0

    words: list[OcrWord] = []
    n = len(data["text"])
    for i in range(n):
        text = data["text"][i].strip()
        try:
            conf = float(data["conf"][i])
        except (ValueError, TypeError):
            conf = -1.0
        if not text or conf < 0:
            continue
        # Pixel box -> PDF points.
        x = data["left"][i] / zoom + origin_x
        y = data["top"][i] / zoom + origin_y
        w = data["width"][i] / zoom
        h = data["height"][i] / zoom
        est_size = round(h * 0.92, 1)  # cap height ≈ font size, rough but workable
        words.append(OcrWord(
            text=text,
            bbox_pts=(x, y, x + w, y + h),
            conf=conf,
            est_size=est_size,
            guessed_family=_guess_family_serif(h),
        ))
    return words


def words_to_spans(words: list[OcrWord], page_index: int) -> list[TextSpan]:
    """Adapt OCR words into TextSpan objects usable by the normal edit path."""
    spans = []
    for w in words:
        x0, y0, x1, y1 = w.bbox_pts
        baseline_y = y1 - (y1 - y0) * 0.18  # approximate baseline near the bottom
        spans.append(TextSpan(
            page_index=page_index,
            block=-1, line=-1, span=-1,
            text=w.text,
            bbox=(x0, y0, x1, y1),
            origin=(x0, baseline_y),
            font_name=w.guessed_family,
            size=w.est_size,
            color=0,
            flags=0,
            font_xref=0,
        ))
    return spans


def ocr_line_spans(
    document: PdfDocument,
    page_index: int,
    clip_pts: tuple[float, float, float, float],
    lang: str = "eng",
) -> list[TextSpan]:
    """Convenience: OCR a region and return ready-to-edit spans."""
    words = ocr_page_region(document, page_index, clip_pts, lang)
    return words_to_spans(words, page_index)
