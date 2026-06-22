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


def write_unlocked(doc: "fitz.Document", path: str):
    """Write an unlocked (no encryption, no permission restrictions) copy of an *already
    authenticated* document, and VERIFY the result.

    MuPDF can very rarely glitch while decrypting content streams during save ("aes padding
    out of range"), silently producing a page with no content. Since this feature's whole
    job is unlocking, we never hand back a corrupted file: we verify page count + text, fall
    back to rebuilding the document from scratch, and raise if neither yields a valid copy.
    """
    src_pages = doc.page_count
    src_len = sum(len(doc[i].get_text("text")) for i in range(src_pages))  # also forces decrypt

    def _valid(p: str) -> bool:
        try:
            c = fitz.open(p)
            ok = (not c.needs_pass and c.page_count == src_pages and
                  sum(len(c[i].get_text("text")) for i in range(c.page_count)) >= src_len * 0.6)
            c.close()
            return ok
        except Exception:
            return False

    # 1) Direct re-save without encryption.
    try:
        doc.save(path, encryption=fitz.PDF_ENCRYPT_NONE, garbage=4, deflate=True)
        if _valid(path):
            return
    except Exception:
        pass
    # 2) Rebuild into a fresh, unencrypted document (forces a full decrypt on copy).
    try:
        rebuilt = fitz.open()
        rebuilt.insert_pdf(doc)
        rebuilt.save(path, garbage=4, deflate=True)
        rebuilt.close()
        if _valid(path):
            return
    except Exception:
        pass
    raise RuntimeError("Couldn't produce a valid unlocked copy (decryption glitch). "
                       "Please try again.")


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
        # Remove the per-document temp font dir so it doesn't leak for the process life.
        try:
            import shutil
            shutil.rmtree(self._tempdir, ignore_errors=True)
        except Exception:
            pass
        self._tempdir = tempfile.mkdtemp(prefix="slate_fonts_")

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

    def get_metadata(self) -> dict:
        return dict(self.doc.metadata) if self.doc else {}

    def set_metadata(self, meta: dict):
        """Merge the given fields into the document metadata."""
        current = dict(self.doc.metadata or {})
        current.update({k: v for k, v in meta.items() if v is not None})
        self.doc.set_metadata(current)
        self.dirty = True

    def set_page_size(self, indices: list[int], width: float, height: float,
                      scale_content: bool):
        """Resize pages to width×height points, keeping text live & editable.

        We transform the page content via a `cm` matrix in the content stream (rather
        than rasterizing), so text stays selectable and editable afterwards.
          * scale_content=True  -> content scaled uniformly to fit and centred
          * scale_content=False -> content kept at its size, anchored to the top
        """
        for i in indices:
            page = self.doc[i]
            old = page.rect
            oldw, oldh = old.width, old.height
            if oldw > 1 and oldh > 1:
                s = min(width / oldw, height / oldh) if scale_content else 1.0
                tx = (width - oldw * s) / 2 if scale_content else 0.0
                ty = height - oldh * s  # PDF origin is bottom-left; anchor content to top
                try:
                    page.clean_contents()
                    contents = page.get_contents()
                    if contents:
                        xref = contents[0]
                        stream = self.doc.xref_stream(xref)
                        prefix = ("q %.6f 0 0 %.6f %.6f %.6f cm\n" % (s, s, tx, ty)).encode()
                        self.doc.update_stream(xref, prefix + stream + b"\nQ")
                except Exception:
                    pass
            page.set_mediabox(fitz.Rect(0, 0, width, height))
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

    # -- page insertion / merge / export ----------------------------------

    def insert_pdf(self, other_path: str, at_index: int) -> int:
        """Insert all pages of another PDF after `at_index`. Returns pages added."""
        other = fitz.open(other_path)
        n = other.page_count
        self.doc.insert_pdf(other, start_at=at_index + 1)
        other.close()
        self.dirty = True
        return n

    def insert_blank_page(self, at_index: int, width: float, height: float):
        self.doc.new_page(pno=at_index + 1, width=width, height=height)
        self.dirty = True

    def duplicate_page(self, index: int):
        to = index + 1
        if to >= self.doc.page_count:
            to = -1  # append (immediately after the last page)
        self.doc.fullcopy_page(index, to)
        self.dirty = True

    def export_images(self, folder: str, dpi: int = 150) -> int:
        """Render every page to a PNG in `folder`. Returns count."""
        zoom = dpi / 72.0
        for i in range(self.page_count):
            png = self.render_page_png(i, zoom)
            with open(os.path.join(folder, f"page_{i + 1:03d}.png"), "wb") as fh:
                fh.write(png)
        return self.page_count

    def export_text(self, path: str):
        parts = []
        for i in range(self.page_count):
            parts.append(self.doc[i].get_text("text"))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\f".join(parts))  # form-feed between pages

    def crop_page(self, index: int, rect_pts: tuple[float, float, float, float]):
        """Crop a page to the given rectangle (in points)."""
        page = self.doc[index]
        r = fitz.Rect(rect_pts) & page.rect
        if not r.is_empty:
            page.set_cropbox(r)
            self.dirty = True

    # -- images ------------------------------------------------------------

    def insert_image(self, page_index: int, rect_pts: tuple, image_path: str):
        page = self.doc[page_index]
        page.insert_image(fitz.Rect(rect_pts), filename=image_path)
        self.dirty = True

    # -- redaction (true, permanent removal) ------------------------------

    def redact(self, page_index: int, rect_pts: tuple, fill=(0, 0, 0)):
        """Permanently remove content under a rectangle (black-out by default)."""
        page = self.doc[page_index]
        page.add_redact_annot(fitz.Rect(rect_pts), fill=fill)
        page.apply_redactions()
        self.dirty = True

    # -- annotations -------------------------------------------------------

    def annotate_text_markup(self, page_index: int, rect_pts: tuple, kind: str,
                             color=(1, 0.85, 0)):
        """Highlight / underline / strikeout the text within a rectangle."""
        page = self.doc[page_index]
        rect = fitz.Rect(rect_pts)
        if kind == "highlight":
            annot = page.add_highlight_annot(rect)
        elif kind == "underline":
            annot = page.add_underline_annot(rect)
        elif kind == "strikeout":
            annot = page.add_strikeout_annot(rect)
        else:
            return
        if kind == "highlight":
            annot.set_colors(stroke=color)
        annot.update()
        self.dirty = True

    def add_note(self, page_index: int, point: tuple, text: str):
        page = self.doc[page_index]
        annot = page.add_text_annot(fitz.Point(*point), text, icon="Note")
        annot.set_colors(stroke=(1.0, 0.52, 0.19))  # theme orange, so it's easy to spot
        annot.set_info(content=text)
        annot.update()
        self.dirty = True

    def detect_table_grids(self, page_index: int) -> list[dict]:
        """Return editable grid structures for tables: {bbox, cols:[x...], rows:[y...]}."""
        out = []
        page = self.doc[page_index]
        finder = None
        try:
            finder = page.find_tables()
            if not finder.tables:               # lines-only tables (forms) need the lines strategy
                finder = page.find_tables(strategy="lines")
        except Exception:
            finder = None
        if finder is not None:
            for t in finder.tables:
                xs, ys = set(), set()
                for c in t.cells:
                    if not c:
                        continue
                    xs.add(round(c[0], 1)); xs.add(round(c[2], 1))
                    ys.add(round(c[1], 1)); ys.add(round(c[3], 1))
                if xs and ys:
                    cols, rows = sorted(xs), sorted(ys)
                    out.append({"bbox": (cols[0], rows[0], cols[-1], rows[-1]),
                                "cols": cols, "rows": rows})
                else:
                    bx = tuple(t.bbox)
                    out.append({"bbox": bx, "cols": [bx[0], bx[2]], "rows": [bx[1], bx[3]]})
        return out

    def draw_table_grids(self, page_index: int, grids: list, color=(0, 0, 0), width: float = 0.8):
        """Draw the (possibly edited) gridlines of tables onto the page."""
        page = self.doc[page_index]
        shape = page.new_shape()
        for g in grids:
            x0, y0, x1, y1 = g["bbox"]
            for cx in g["cols"]:
                shape.draw_line(fitz.Point(cx, y0), fitz.Point(cx, y1))
            for ry in g["rows"]:
                shape.draw_line(fitz.Point(x0, ry), fitz.Point(x1, ry))
        shape.finish(color=color, width=width)
        shape.commit()
        self.dirty = True

    def note_annotations(self, page_index: int) -> list[tuple]:
        """Return [(bbox, text), ...] for sticky-note annotations on a page."""
        out = []
        try:
            for annot in self.doc[page_index].annots(types=(fitz.PDF_ANNOT_TEXT,)):
                info = annot.info
                out.append((tuple(annot.rect), info.get("content", "")))
        except Exception:
            pass
        return out

    def add_shape(self, page_index: int, rect_pts: tuple, kind: str,
                  color=(0.85, 0.1, 0.1), width: float = 1.5):
        page = self.doc[page_index]
        r = fitz.Rect(rect_pts)
        if kind == "rect":
            annot = page.add_rect_annot(r)
        elif kind == "line":
            annot = page.add_line_annot(r.tl, r.br)
        else:
            return
        annot.set_colors(stroke=color)
        annot.set_border(width=width)
        annot.update()
        self.dirty = True

    def add_ink(self, page_index: int, points_pts: list, color=(0.1, 0.1, 0.9), width: float = 1.5):
        if len(points_pts) < 2:
            return
        page = self.doc[page_index]
        stroke = [(float(p[0]), float(p[1])) for p in points_pts]
        annot = page.add_ink_annot([stroke])
        annot.set_colors(stroke=color)
        annot.set_border(width=width)
        annot.update()
        self.dirty = True

    # -- encryption / password --------------------------------------------

    @property
    def needs_password(self) -> bool:
        return bool(self.doc and self.doc.needs_pass)

    @property
    def is_encrypted(self) -> bool:
        return bool(self.doc and self.doc.is_encrypted)

    @property
    def is_locked(self) -> bool:
        """True if the document is password-protected or has owner/permission restrictions.
        (is_encrypted alone is unreliable — it goes False after an auto-decrypt.)"""
        if not self.doc:
            return False
        return bool(self.doc.needs_pass) or bool((self.doc.metadata or {}).get("encryption"))

    def authenticate(self, password: str) -> bool:
        return bool(self.doc.authenticate(password))

    def save_encrypted(self, path: str, user_pw: str, owner_pw: str):
        perm = int(
            fitz.PDF_PERM_ACCESSIBILITY | fitz.PDF_PERM_PRINT | fitz.PDF_PERM_COPY |
            fitz.PDF_PERM_ANNOTATE
        )
        self.doc.save(path, encryption=fitz.PDF_ENCRYPT_AES_256,
                      owner_pw=owner_pw or user_pw, user_pw=user_pw,
                      permissions=perm, garbage=4, deflate=True)

    def save_decrypted(self, path: str):
        """Write a verified, fully-unlocked copy (no encryption / no restrictions)."""
        write_unlocked(self.doc, path)

    def save(self, path: Optional[str] = None):
        target = path or self.path
        if not target:
            raise ValueError("No path to save to.")
        if target == self.path:
            # Incremental save in place when possible; fall back to full rewrite.
            try:
                self.doc.save(target, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
            except Exception:
                # Incremental can fail (cleaned/encrypted/grown docs) — full rewrite.
                self.doc.save(target, garbage=4, deflate=True, clean=True)
                self._reopen(target)
        else:
            self.doc.save(target, garbage=4, deflate=True, clean=True)
        self.path = target
        self.dirty = False

    def _reopen(self, path: str):
        self.doc.close()
        self.doc = fitz.open(path)
        self._embedded_font_cache.clear()  # xref-keyed cache is invalid after a reopen

    # -- undo/redo snapshots ----------------------------------------------

    def snapshot(self) -> bytes:
        """Serialize the current document to bytes (for the undo stack)."""
        return self.doc.tobytes(deflate=True, garbage=0)

    def restore(self, data: bytes):
        """Replace the in-memory document with a previously taken snapshot."""
        self.doc.close()
        self.doc = fitz.open(stream=data, filetype="pdf")
        self._embedded_font_cache.clear()
        self.dirty = True

    # -- text search -------------------------------------------------------

    def search(self, query: str) -> list[tuple[int, fitz.Rect]]:
        """Find a string across all pages -> list of (page_index, rect)."""
        hits: list[tuple[int, fitz.Rect]] = []
        if not query:
            return hits
        for i in range(self.page_count):
            for r in self.doc[i].search_for(query):
                hits.append((i, r))
        return hits
