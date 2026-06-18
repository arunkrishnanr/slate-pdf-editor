"""
True in-place text editing.

This does NOT stamp new text over old text behind a white box. The flow is:

  1. Redact the original span's rectangle. PyMuPDF's `apply_redactions` physically
     deletes the text-drawing operators from the page content stream — after this the
     original glyphs are *gone* (you can verify: extracting text from that rect returns
     nothing). The rectangle is repainted with the sampled background colour so it
     blends in, rather than always white.
  2. Re-insert the replacement text at the original baseline, using the original font:
       - first choice: the font embedded in the PDF (perfect glyph match)
       - second choice: the same family installed on this system
       - last resort: a metrically-close substitute (and we flag it)

The net effect is that the real content of the PDF changes — same mechanism real
editors use — not a visual patch on top.
"""

from __future__ import annotations

import os
import hashlib
from dataclasses import dataclass
from typing import Optional

import fitz

from . import font_manager as fm
from .pdf_document import PdfDocument, TextSpan


# Base-14 fallback names PyMuPDF understands without a font file.
_BUILTIN_FALLBACK = {
    ("sans", False, False): "helv",
    ("sans", True, False): "hebo",
    ("sans", False, True): "heit",
    ("sans", True, True): "hebi",
    ("serif", False, False): "tiro",
    ("serif", True, False): "tibo",
    ("serif", False, True): "tiit",
    ("serif", True, True): "tibi",
}


@dataclass
class EditResult:
    ok: bool
    message: str
    resolution: Optional[fm.FontResolution] = None
    substituted: bool = False


def _ci_replace(text: str, query: str, replacement: str, match_case: bool) -> str:
    """Replace occurrences of query in text, optionally case-insensitively."""
    if match_case:
        return text.replace(query, replacement)
    out = []
    low = text.lower()
    qlow = query.lower()
    i = 0
    while True:
        j = low.find(qlow, i)
        if j < 0:
            out.append(text[i:])
            break
        out.append(text[i:j])
        out.append(replacement)
        i = j + len(query)
    return "".join(out)


def _fontname_for_file(path: str) -> str:
    """A stable, unique PyMuPDF font alias derived from a font file path.

    PyMuPDF won't let two different font files share one alias on a page, so we key
    the alias on the file's path.
    """
    h = hashlib.md5(path.encode("utf-8")).hexdigest()[:8]
    stem = "".join(c for c in os.path.splitext(os.path.basename(path))[0] if c.isalnum())[:12]
    return f"sf_{stem}_{h}"


def _builtin_for(req: fm.FontRequest) -> str:
    fam = req.family.lower()
    kind = "serif" if any(s in fam for s in ("times", "serif", "georgia", "garamond", "roman")) else "sans"
    return _BUILTIN_FALLBACK[(kind, req.bold, req.italic)]


def _sample_background(page: fitz.Page, rect: fitz.Rect) -> tuple[float, float, float]:
    """Sample the page just outside a span to guess its background colour."""
    pad = max(2.0, rect.height * 0.4)
    probe = fitz.Rect(rect.x0, rect.y0 - pad, rect.x1, rect.y0 - 0.5)
    probe = probe & page.rect
    if probe.is_empty or probe.height < 0.5:
        return (1.0, 1.0, 1.0)
    try:
        pix = page.get_pixmap(clip=probe, alpha=False)
        if pix.width == 0 or pix.height == 0:
            return (1.0, 1.0, 1.0)
        # Average a thin strip; good enough for solid backgrounds.
        n = pix.width * pix.height
        r = g = b = 0
        samples = pix.samples
        stride = pix.n
        for i in range(0, len(samples), stride):
            r += samples[i]
            g += samples[i + 1]
            b += samples[i + 2]
        return (r / n / 255.0, g / n / 255.0, b / n / 255.0)
    except Exception:
        return (1.0, 1.0, 1.0)


class TextEditor:
    def __init__(self, document: PdfDocument):
        self.doc = document

    def resolve_font(self, span: TextSpan) -> fm.FontResolution:
        """Work out which concrete font we'll use to rewrite a span."""
        req = span.font_request()
        embedded = None
        if span.font_xref:
            embedded = self.doc.extract_embedded_font(span.font_xref)
        return fm.resolve(req, embedded_path=embedded)

    def replace_span_text(
        self,
        span: TextSpan,
        new_text: str,
        resolution: Optional[fm.FontResolution] = None,
        force_substitute: bool = False,
        size_override: Optional[float] = None,
        color_override: Optional[tuple[float, float, float]] = None,
    ) -> EditResult:
        """Replace a span's text in place. Returns an EditResult describing what happened.

        `size_override`/`color_override` let the properties panel restyle a span (change
        font, size or colour) while keeping it a true in-place edit.
        """
        page = self.doc.doc[span.page_index]
        if resolution is None:
            resolution = self.resolve_font(span)

        rect = span.rect
        # 1. Remove the original glyphs from the content stream.
        bg = _sample_background(page, rect)
        page.add_redact_annot(rect, fill=bg)
        # cross_out=False so we don't draw the strike line; we only want removal.
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

        # 2. Re-insert at the original baseline.
        point = fitz.Point(span.origin[0], span.origin[1])
        color = color_override if color_override is not None else span.color_rgb
        fontsize = size_override if size_override is not None else span.size

        substituted = (not resolution.is_exact) or force_substitute
        font_file = None if force_substitute else resolution.file_for_embedding
        if force_substitute and resolution.substitute:
            font_file = resolution.substitute.path

        inserted = False
        if font_file:
            try:
                page.insert_text(
                    point, new_text,
                    fontfile=font_file,
                    fontname=_fontname_for_file(font_file),
                    fontsize=fontsize,
                    color=color,
                    render_mode=0,
                )
                inserted = True
            except Exception:
                inserted = False

        if not inserted:
            # Last-resort built-in font so the edit never silently fails.
            builtin = _builtin_for(resolution.request)
            page.insert_text(
                point, new_text,
                fontname=builtin,
                fontsize=fontsize,
                color=color,
                render_mode=0,
            )
            substituted = True

        self.doc.dirty = True
        msg = resolution.status_text
        if substituted and not resolution.substitute and not resolution.is_exact:
            msg = (f"'{resolution.request.display}' is not installed and could not be "
                   f"matched; used a built-in fallback font.")
        return EditResult(ok=True, message=msg, resolution=resolution, substituted=substituted)

    def add_text(
        self,
        page_index: int,
        point: tuple[float, float],
        text: str,
        font_request: fm.FontRequest,
        size: float = 12.0,
        color: tuple[float, float, float] = (0, 0, 0),
    ) -> EditResult:
        """Insert brand-new text (not replacing anything)."""
        page = self.doc.doc[page_index]
        resolution = fm.resolve(font_request)
        font_file = resolution.file_for_embedding
        try:
            if font_file:
                page.insert_text(fitz.Point(*point), text, fontfile=font_file,
                                 fontname=_fontname_for_file(font_file), fontsize=size, color=color)
            else:
                page.insert_text(fitz.Point(*point), text,
                                 fontname=_builtin_for(font_request), fontsize=size, color=color)
        except Exception as e:
            return EditResult(ok=False, message=f"Could not add text: {e}")
        self.doc.dirty = True
        return EditResult(ok=True, message="Text added.", resolution=resolution)

    # ------------------------------------------------------------------
    # Block / paragraph editing (reflow within the block's own area)
    # ------------------------------------------------------------------

    def replace_block_text(
        self,
        block,
        new_text: str,
        resolution: fm.FontResolution,
        size: float,
        color: tuple[float, float, float],
        align: int = 0,
    ) -> EditResult:
        """Replace a whole paragraph/heading, re-wrapping the new text inside its region.

        The text re-wraps within the block width and grows downward; if it overflows the
        available space the font size is reduced until it fits (so nothing is lost).
        """
        page = self.doc.doc[block.page_index]
        rect = fitz.Rect(block.bbox)

        bg = _sample_background(page, rect)
        page.add_redact_annot(rect, fill=bg)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

        # Box can grow down to near the page bottom.
        grow = fitz.Rect(rect.x0, rect.y0, rect.x1, page.rect.y1 - 12)
        font_file = resolution.file_for_embedding
        fontname = _fontname_for_file(font_file) if font_file else _builtin_for(resolution.request)

        cur = size
        rc = -1
        for _ in range(24):  # shrink-to-fit
            try:
                if font_file:
                    rc = page.insert_textbox(grow, new_text, fontfile=font_file,
                                             fontname=fontname, fontsize=cur, color=color, align=align)
                else:
                    rc = page.insert_textbox(grow, new_text, fontname=_builtin_for(resolution.request),
                                             fontsize=cur, color=color, align=align)
            except Exception:
                rc = -1
            if rc >= 0:
                break
            cur = round(cur * 0.94, 2)
            if cur < 4:
                break

        self.doc.dirty = True
        if rc < 0:
            return EditResult(ok=False, message="Paragraph too long to fit even at minimum size.",
                              resolution=resolution)
        note = "" if abs(cur - size) < 0.1 else f" (font scaled to {cur:.1f}pt to fit)"
        return EditResult(ok=True, message=resolution.status_text + note, resolution=resolution,
                          substituted=not resolution.is_exact)

    def replace_all(self, query: str, replacement: str, match_case: bool = False) -> int:
        """Replace every occurrence of `query` with `replacement` across the document.

        Works span-by-span on real text (so it's a true in-place edit). Returns the
        number of occurrences replaced.
        """
        if not query:
            return 0
        total = 0
        for i in range(self.doc.page_count):
            for span in self.doc.spans_on_page(i):
                text = span.text
                hay = text if match_case else text.lower()
                ndl = query if match_case else query.lower()
                n = hay.count(ndl)
                if n == 0:
                    continue
                new_text = _ci_replace(text, query, replacement, match_case)
                res = self.replace_span_text(span, new_text)
                if res.ok:
                    total += n
        return total

    def recognize_text_searchable(self, page_index: int) -> tuple:
        """Acrobat-style 'Recognize Text': OCR the page and overlay an INVISIBLE text
        layer so the scanned content becomes selectable & searchable, while the original
        image appearance is preserved. Returns (word_count, engine_name)."""
        from . import ocr as _ocr
        page = self.doc.doc[page_index]
        r = page.rect
        words, engine = _ocr.recognize_region(self.doc, page_index, (r.x0, r.y0, r.x1, r.y1))
        count = 0
        for w in words:
            if not w.text.strip():
                continue
            x0, y0, x1, y1 = w.bbox_pts
            fs = max(4.0, (y1 - y0) * 0.9)
            try:
                page.insert_text(fitz.Point(x0, y1 - (y1 - y0) * 0.18), w.text,
                                 fontsize=fs, render_mode=3)  # render_mode 3 = invisible
                count += 1
            except Exception:
                continue
        self.doc.dirty = True
        return count, engine

    def replace_region_inpaint(
        self,
        page_index: int,
        rect_pts: tuple,
        new_text: str,
        size: float,
        color: tuple = (0, 0, 0),
        align: int = 0,
    ) -> EditResult:
        """Remove scanned text from a region and rebuild the background, then place new text.

        Uses OpenCV inpainting: the original glyph pixels are masked out and the background
        (including textures/patterns) is reconstructed, so it looks like the original text
        was never there. Falls back to a solid-colour fill if OpenCV isn't available.
        """
        page = self.doc.doc[page_index]
        rect = fitz.Rect(rect_pts)
        try:
            import cv2
            import numpy as np
        except Exception:
            return self._replace_region_flat(page, rect, new_text, size, color, align)

        DPI = 200
        zoom = DPI / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect, alpha=False)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:
            bgr = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
        elif pix.n == 1:
            bgr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
        else:
            bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        # Text tends to be darker than its local background; adaptive threshold isolates it.
        th = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY_INV, 31, 15)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        mask = cv2.dilate(th, kernel, iterations=2)
        inpainted = cv2.inpaint(bgr, mask, 3, cv2.INPAINT_TELEA)
        ok, buf = cv2.imencode(".png", inpainted)
        if not ok:
            return self._replace_region_flat(page, rect, new_text, size, color, align)

        # Cover the original with the cleaned background, then lay down the new editable text.
        page.insert_image(rect, stream=buf.tobytes())
        self._insert_textbox_fitted(page, rect, new_text, size, color, align,
                                    fm.parse_pdf_fontname("Helvetica"))
        self.doc.dirty = True
        return EditResult(ok=True, message="Scanned text removed (background reconstructed) and replaced.")

    def _replace_region_flat(self, page, rect, new_text, size, color, align):
        """Fallback when OpenCV is unavailable: sample background, fill, reinsert."""
        bg = _sample_background(page, rect)
        page.add_redact_annot(rect, fill=bg)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        self._insert_textbox_fitted(page, rect, new_text, size, color, align,
                                    fm.parse_pdf_fontname("Helvetica"))
        self.doc.dirty = True
        return EditResult(ok=True, message="Replaced (solid background fill).")

    def _insert_textbox_fitted(self, page, rect, text, size, color, align, req):
        resolution = fm.resolve(req)
        font_file = resolution.file_for_embedding
        cur = size
        for _ in range(24):
            try:
                if font_file:
                    rc = page.insert_textbox(rect, text, fontfile=font_file,
                                             fontname=_fontname_for_file(font_file),
                                             fontsize=cur, color=color, align=align)
                else:
                    rc = page.insert_textbox(rect, text, fontname=_builtin_for(req),
                                             fontsize=cur, color=color, align=align)
            except Exception:
                rc = -1
            if rc >= 0:
                return
            cur = round(cur * 0.94, 2)
            if cur < 4:
                return

    def add_text_box(
        self,
        page_index: int,
        rect_pts: tuple[float, float, float, float],
        text: str,
        font_request: fm.FontRequest,
        size: float = 12.0,
        color: tuple[float, float, float] = (0, 0, 0),
        align: int = 0,
    ) -> EditResult:
        """Insert a wrapping text box within the given rectangle."""
        page = self.doc.doc[page_index]
        resolution = fm.resolve(font_request)
        rect = fitz.Rect(rect_pts)
        font_file = resolution.file_for_embedding
        cur = size
        rc = -1
        for _ in range(24):
            try:
                if font_file:
                    rc = page.insert_textbox(rect, text, fontfile=font_file,
                                             fontname=_fontname_for_file(font_file),
                                             fontsize=cur, color=color, align=align)
                else:
                    rc = page.insert_textbox(rect, text, fontname=_builtin_for(font_request),
                                             fontsize=cur, color=color, align=align)
            except Exception:
                rc = -1
            if rc >= 0:
                break
            cur = round(cur * 0.94, 2)
            if cur < 4:
                break
        if rc < 0:
            return EditResult(ok=False, message="Text doesn't fit in that box.")
        self.doc.dirty = True
        return EditResult(ok=True, message="Text box added.", resolution=resolution)
