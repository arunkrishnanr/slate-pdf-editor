"""
Font detection & matching.

Two jobs:
  1. Given a font name pulled out of a PDF (often a subset like "ABCDEF+Helvetica-Bold"),
     figure out the real family + style and whether that font is installed on this machine.
  2. Hand back an actual font *file* so we can re-embed it when we rewrite text, so the
     replacement glyphs match the originals.

We index the OS font directories with fontTools so we get real file paths (QFontDatabase
can tell us a family exists but won't give us a path to embed).
"""

from __future__ import annotations

import os
import sys
import platform
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

from fontTools.ttLib import TTFont, TTLibError
from fontTools.ttLib.ttCollection import TTCollection


# ---------------------------------------------------------------------------
# PDF font name parsing
# ---------------------------------------------------------------------------

_STYLE_TOKENS = {
    "bold": {"bold", "bd", "black", "heavy", "semibold", "demibold", "medium"},
    "italic": {"italic", "oblique", "it", "ital"},
}


@dataclass
class FontRequest:
    """A normalized description of the font a PDF span wants."""
    raw_name: str
    family: str
    bold: bool = False
    italic: bool = False

    @property
    def display(self) -> str:
        bits = [self.family]
        if self.bold:
            bits.append("Bold")
        if self.italic:
            bits.append("Italic")
        return " ".join(bits)


def parse_pdf_fontname(name: str, flags: int = 0) -> FontRequest:
    """Turn a raw PDF BaseFont name into a clean family + style request.

    `flags` is the PyMuPDF span flag bitfield (bit 1 = italic, bit 4 = bold).
    """
    raw = name or "Helvetica"
    # Strip subset prefix:  "ABCDEF+RealName"
    if "+" in raw:
        raw = raw.split("+", 1)[1]

    base = raw
    bold = bool(flags & (1 << 4))
    italic = bool(flags & (1 << 1))

    # Split the family from style descriptors that follow a '-' or ','.
    family_part = base
    for sep in ("-", ","):
        if sep in family_part:
            family_part, _, style_part = family_part.partition(sep)
            sp = style_part.lower()
            if any(t in sp for t in _STYLE_TOKENS["bold"]):
                bold = True
            if any(t in sp for t in _STYLE_TOKENS["italic"]):
                italic = True

    # Also catch styles glued to the family name with no separator, e.g. "ArialBold".
    low = family_part.lower()
    for t in _STYLE_TOKENS["bold"]:
        if low.endswith(t) and len(low) > len(t):
            bold = True
    for t in _STYLE_TOKENS["italic"]:
        if low.endswith(t) and len(low) > len(t):
            italic = True

    # Tidy up camel-case family names a little for display.
    family = family_part.replace("MT", "").strip() or "Helvetica"
    return FontRequest(raw_name=name, family=family, bold=bold, italic=italic)


# ---------------------------------------------------------------------------
# System font index
# ---------------------------------------------------------------------------

@dataclass
class InstalledFont:
    path: str
    family: str
    subfamily: str
    collection_index: int = 0  # for .ttc files

    @property
    def bold(self) -> bool:
        return "bold" in self.subfamily.lower() or "black" in self.subfamily.lower()

    @property
    def italic(self) -> bool:
        s = self.subfamily.lower()
        return "italic" in s or "oblique" in s


def _font_dirs() -> list[str]:
    sysname = platform.system()
    home = os.path.expanduser("~")
    if sysname == "Darwin":
        adobe = os.path.join(home, "Library/Application Support/Adobe/CoreSync/plugins/livetype")
        return [
            "/System/Library/Fonts",
            "/Library/Fonts",
            os.path.join(home, "Library/Fonts"),
            # Adobe Fonts (Creative Cloud activated) — obfuscated .otf/.ttf files
            os.path.join(adobe, ".r"),
            os.path.join(adobe, "r"),
        ]
    if sysname == "Windows":
        dirs = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")]
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(os.path.join(local, r"Microsoft\Windows\Fonts"))
        for env in ("APPDATA", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if base:
                adobe = os.path.join(base, r"Adobe\CoreSync\plugins\livetype")
                dirs.append(os.path.join(adobe, "r"))
                dirs.append(os.path.join(adobe, ".r"))
        return dirs
    # Linux / other
    return [
        "/usr/share/fonts",
        "/usr/local/share/fonts",
        os.path.join(home, ".fonts"),
        os.path.join(home, ".local/share/fonts"),
    ]


def _names_from_ttfont(tt: TTFont) -> tuple[str, str]:
    """Return (family, subfamily) from a TTFont name table."""
    family = subfamily = ""
    try:
        name_table = tt["name"]
    except Exception:
        return family, subfamily
    # nameID 16/17 = typographic family/subfamily; 1/2 = legacy.
    for fam_id in (16, 1):
        rec = name_table.getDebugName(fam_id)
        if rec:
            family = rec
            break
    for sub_id in (17, 2):
        rec = name_table.getDebugName(sub_id)
        if rec:
            subfamily = rec
            break
    return family.strip(), subfamily.strip()


class FontIndex:
    """Lazily-built index of installed fonts: family name -> InstalledFont list."""

    def __init__(self):
        self._by_family: dict[str, list[InstalledFont]] = {}
        self._built = False

    def build(self):
        if self._built:
            return
        exts = (".ttf", ".otf", ".ttc", ".otc")
        for d in _font_dirs():
            if not os.path.isdir(d):
                continue
            for root, _dirs, files in os.walk(d):
                for fn in files:
                    if not fn.lower().endswith(exts):
                        continue
                    path = os.path.join(root, fn)
                    try:
                        self._index_file(path)
                    except (TTLibError, OSError, Exception):
                        continue
        self._built = True

    def _index_file(self, path: str):
        low = path.lower()
        if low.endswith((".ttc", ".otc")):
            coll = TTCollection(path, lazy=True)
            for i, tt in enumerate(coll.fonts):
                fam, sub = _names_from_ttfont(tt)
                if fam:
                    self._add(InstalledFont(path, fam, sub, i))
            coll.close()
        else:
            tt = TTFont(path, lazy=True, fontNumber=0)
            fam, sub = _names_from_ttfont(tt)
            if fam:
                self._add(InstalledFont(path, fam, sub, 0))
            tt.close()

    def _add(self, font: InstalledFont):
        key = font.family.lower()
        self._by_family.setdefault(key, []).append(font)

    # -- queries -----------------------------------------------------------

    def has_family(self, family: str) -> bool:
        self.build()
        return family.lower() in self._by_family

    def families(self) -> list[str]:
        self.build()
        return sorted({f.family for fams in self._by_family.values() for f in fams})

    def find(self, req: FontRequest) -> Optional[InstalledFont]:
        """Best installed match for a request, or None if the family is absent."""
        self.build()
        candidates = self._by_family.get(req.family.lower())
        if not candidates:
            # Try a looser contains-match on family (handles "ArialMT" vs "Arial").
            fam = req.family.lower()
            for key, fonts in self._by_family.items():
                if key in fam or fam in key:
                    candidates = fonts
                    break
        if not candidates:
            return None
        # Score on style agreement.
        best, best_score = None, -1
        for f in candidates:
            score = 0
            if f.bold == req.bold:
                score += 2
            if f.italic == req.italic:
                score += 2
            if not f.bold and not f.italic and not req.bold and not req.italic:
                score += 1  # prefer plain regular when nothing requested
            if score > best_score:
                best, best_score = f, score
        return best

    def closest_substitute(self, req: FontRequest) -> Optional[InstalledFont]:
        """A sane fallback when the exact family isn't installed.

        Prefers common sans/serif families that almost certainly exist.
        """
        self.build()
        prefs = [
            "Helvetica Neue", "Helvetica", "Arial", "Liberation Sans",
            "Times New Roman", "Times", "Liberation Serif",
            "DejaVu Sans", "Verdana", "Tahoma",
        ]
        for name in prefs:
            f = self.find(FontRequest(name, name, req.bold, req.italic))
            if f:
                return f
        # Anything at all.
        for fonts in self._by_family.values():
            if fonts:
                return fonts[0]
        return None


# Singleton index used across the app.
_INDEX: Optional[FontIndex] = None


def index() -> FontIndex:
    global _INDEX
    if _INDEX is None:
        _INDEX = FontIndex()
    return _INDEX


@dataclass
class FontResolution:
    """Outcome of resolving a PDF span's font to something we can render with."""
    request: FontRequest
    installed: Optional[InstalledFont]      # exact family match, if any
    substitute: Optional[InstalledFont]     # fallback used if not installed
    embedded_path: Optional[str] = None     # font extracted from the PDF itself

    @property
    def is_exact(self) -> bool:
        return self.installed is not None or self.embedded_path is not None

    @property
    def file_for_embedding(self) -> Optional[str]:
        """Path to the font file we should embed when rewriting text."""
        if self.embedded_path:
            return self.embedded_path
        if self.installed:
            return self.installed.path
        if self.substitute:
            return self.substitute.path
        return None

    @property
    def status_text(self) -> str:
        if self.embedded_path:
            return f"Using the font embedded in the PDF ({self.request.display})."
        if self.installed:
            return f"'{self.request.display}' is installed — using it directly."
        if self.substitute:
            return (f"'{self.request.display}' is not installed. "
                    f"Substituting '{self.substitute.family}'.")
        return f"Could not resolve a font for '{self.request.display}'."


def resolve(req: FontRequest, embedded_path: Optional[str] = None) -> FontResolution:
    idx = index()
    installed = idx.find(req)
    substitute = None if installed else idx.closest_substitute(req)
    return FontResolution(req, installed, substitute, embedded_path)
