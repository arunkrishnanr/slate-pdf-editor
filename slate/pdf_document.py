"""
PyMuPDF wrapper — the document model the whole app talks to.

Responsibilities:
  * open / save / export
  * render a page to a QImage at an arbitrary zoom
  * extract text as structured spans (with font, size, colour, bbox, baseline)
  * extract embedded fonts (so replacements can reuse the original glyphs)
  * page operations: delete, move, split, rotate
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from typing import Optional

import fitz  # PyMuPDF

from . import font_manager as fm


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class TextSpan:
    """One run of same-styled text on a page, in PDF (point) coordinates."""
    page_index: int
    block: int
    line: int
    span: int
    text: str
    bbox: tuple[float, float, float, float]   # x0, y0, x1, y1
    origin: tuple[float, float]               # baseline start (x, y)
    font_name: str                            # raw PDF BaseFont
    size: float
    color: int                                # packed sRGB int
    flags: int                                # PyMuPDF span flags (bold/italic/...)
    font_xref: int = 0                        # xref of embedded font, 0 if none

    @property
    def rect(self) -> fitz.Rect:
        return fitz.Rect(self.bbox)

    @property
    def color_rgb(self) -> tuple[float, float, float]:
        return _int_to_rgb(self.color)

    def font_request(self) -> fm.FontRequest:
        return fm.parse_pdf_fontname(self.font_name, self.flags)


def _int_to_rgb(c: int) -> tuple[float, float, float]:
    return ((c >> 16) & 255) / 255.0, ((c >> 8) & 255) / 255.0, (c & 255) / 255.0


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------

class PdfDocument:
    def __init__(self):
        self.doc: Optional[fitz.Document] = None
        self.path: Optional[str] = None
        self.dirty: bool = False
        self._embedded_font_cache: dict[int, Optional[str]] = {}
        self._tempdir = tempfile.mkdtemp(prefix="slate_fonts_")

    # -- lifecycle ---------------------------------------------------------

    def open(self, path: str):
        self.close()
        self.doc = fitz.open(path)
        self.path = path
        self.dirty = False

    def new_blank(self):
        self.close()
        self.doc = fitz.open()
        self.doc.new_page()
        self.path = None
        self.dirty = True

    def close(self):
        if self.doc is not None:
            self.doc.close()
        self.doc = None
        self.path = None
        self.dirty = False
        self._embedded_font_cache.clear()

    @property
    def is_open(self) -> bool:
        return self.doc is not None

    @property
    def page_count(self) -> int:
        return self.doc.page_count if self.doc else 0

    # -- rendering ---------------------------------------------------------

    def render_page_png(self, index: int, zoom: float = 1.0) -> bytes:
        """Render a page to PNG bytes at the given zoom (1.0 == 72 dpi)."""
        page = self.doc[index]
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        return pix.tobytes("png")

    def page_size(self, index: int) -> tuple[float, float]:
        r = self.doc[index].rect
        return r.width, r.height

    # -- text extraction ---------------------------------------------------

    def spans_on_page(self, index: int) -> list[TextSpan]:
        page = self.doc[index]
        data = page.get_text("dict")
        spans: list[TextSpan] = []
        # Build a quick lookup of font name -> xref for embedded font extraction.
        font_xrefs = self._page_font_xrefs(index)
        for bi, block in enumerate(data.get("blocks", [])):
            if block.get("type", 0) != 0:  # 0 == text block
                continue
            for li, line in enumerate(block.get("lines", [])):
                for si, span in enumerate(line.get("spans", [])):
                    text = span.get("text", "")
                    if text == "":
                        continue
                    fname = span.get("font", "")
                    spans.append(TextSpan(
                        page_index=index,
                        block=bi, line=li, span=si,
                        text=text,
                        bbox=tuple(span["bbox"]),
                        origin=tuple(span.get("origin", (span["bbox"][0], span["bbox"][3]))),
                        font_name=fname,
                        size=span.get("size", 11.0),
                        color=span.get("color", 0),
                        flags=span.get("flags", 0),
                        font_xref=font_xrefs.get(fname, 0),
                    ))
        return spans

    def has_extractable_text(self, index: int) -> bool:
        return bool(self.doc[index].get_text("text").strip())

    # -- embedded fonts ----------------------------------------------------

    def _page_font_xrefs(self, index: int) -> dict[str, int]:
        """Map the font BaseFont name -> xref for fonts used on a page."""
        out: dict[str, int] = {}
        try:
            for f in self.doc.get_page_fonts(index, full=True):
                # f = (xref, ext, type, basefont, refname, encoding)
                xref, _ext, _type, basefont = f[0], f[1], f[2], f[3]
                if basefont:
                    out[basefont] = xref
        except Exception:
            pass
        return out

    def extract_embedded_font(self, xref: int) -> Optional[str]:
        """Extract an embedded font to a temp file and return its path (or None)."""
        if xref in self._embedded_font_cache:
            return self._embedded_font_cache[xref]
        result = None
        try:
            name, ext, _ftype, buffer = self.doc.extract_font(xref)
            if buffer and ext in ("ttf", "otf", "cff", "pfa"):
                safe = "".join(c for c in (name or "font") if c.isalnum()) or "font"
                out = os.path.join(self._tempdir, f"{safe}_{xref}.{ext}")
                with open(out, "wb") as fh:
                    fh.write(buffer)
                result = out
        except Exception:
            result = None
        self._embedded_font_cache[xref] = result
        return result

    # -- page operations ---------------------------------------------------

    def delete_page(self, index: int):
        self.doc.delete_page(index)
        self.dirty = True

    def move_page(self, src: int, dst: int):
        self.doc.move_page(src, dst)
        self.dirty = True

    def rotate_page(self, index: int, degrees: int):
        page = self.doc[index]
        page.set_rotation((page.rotation + degrees) % 360)
        self.dirty = True

    def split_off(self, indices: list[int], out_path: str):
        """Write the given pages into a brand-new PDF file (non-destructive)."""
        new = fitz.open()
        for i in sorted(indices):
            new.insert_pdf(self.doc, from_page=i, to_page=i)
        new.save(out_path)
        new.close()

    def split_at(self, after_index: int, out_path_a: str, out_path_b: str):
        """Split the document into two files: [0..after] and [after+1..end]."""
        a = fitz.open()
        a.insert_pdf(self.doc, from_page=0, to_page=after_index)
        a.save(out_path_a)
        a.close()
        b = fitz.open()
        b.insert_pdf(self.doc, from_page=after_index + 1, to_page=self.page_count - 1)
        b.save(out_path_b)
        b.close()

    # -- saving ------------------------------------------------------------

    def save(self, path: Optional[str] = None):
        target = path or self.path
        if not target:
            raise ValueError("No path to save to.")
        if target == self.path:
            # Incremental save in place when possible; fall back to full rewrite.
            try:
                self.doc.save(target, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
            except (ValueError, RuntimeError):
                self.doc.save(target, garbage=4, deflate=True, clean=True)
                self._reopen(target)
        else:
            self.doc.save(target, garbage=4, deflate=True, clean=True)
        self.path = target
        self.dirty = False

    def _reopen(self, path: str):
        self.doc.close()
        self.doc = fitz.open(path)
