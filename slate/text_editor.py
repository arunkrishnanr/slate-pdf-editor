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
    ) -> EditResult:
        """Replace a span's text in place. Returns an EditResult describing what happened."""
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
        color = span.color_rgb
        fontsize = span.size

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
