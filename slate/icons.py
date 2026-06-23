"""
Minimal line-art tool icons + matching cursors, drawn as SVG and rendered to QIcon/QCursor.

Each icon is a 24×24 outline glyph. `icon(name)` returns a two-state QIcon: a light stroke
for the normal (Off) state and a dark stroke for the checked (On) state, so an active tool
reads cleanly against the orange highlight. `cursor(name)` builds a QCursor from the same
glyph so the pointer represents the active tool.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QByteArray
from PySide6.QtGui import QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer

LIGHT = "#e6e6e6"   # normal stroke on the dark theme
DARK = "#282828"    # checked stroke (sits on the orange highlight)

# Each entry is an SVG body using {c} for stroke colour. fill is none unless the glyph
# is meant to be solid (redact). viewBox is 0 0 24 24.
_GLYPHS = {
    # pointer / arrow (Select)
    "select": '<path d="M5 3 L5 18 L9.2 14 L12 20.5 L14.2 19.5 L11.4 13.2 L17 13.2 Z" '
              'fill="{c}" stroke="{c}" stroke-width="1.2" stroke-linejoin="round"/>',
    # four-way move
    "move": '<g fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" '
            'stroke-linejoin="round"><path d="M12 3 V21 M3 12 H21"/>'
            '<path d="M9 6 L12 3 L15 6 M9 18 L12 21 L15 18 M6 9 L3 12 L6 15 M18 9 L21 12 L18 15"/></g>',
    # capital A (Add Text)
    "text": '<path d="M5 20 L12 4 L19 20 M8.2 14 H15.8" fill="none" stroke="{c}" '
            'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    # box with a T (Text Box)
    "textbox": '<g fill="none" stroke="{c}" stroke-width="2" stroke-linejoin="round" '
               'stroke-linecap="round"><rect x="3" y="5" width="18" height="14" rx="1.5"/>'
               '<path d="M8.5 9.5 H15.5 M12 9.5 V15"/></g>',
    # magnifier over text lines (OCR)
    "ocr": '<g fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" '
           'stroke-linejoin="round"><path d="M4 6 H13 M4 10 H11 M4 14 H8"/>'
           '<circle cx="15.5" cy="14.5" r="4"/><path d="M18.4 17.4 L21 20"/></g>',
    # crop marks
    "crop": '<g fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" '
            'stroke-linejoin="round"><path d="M7 2 V17 H22 M2 7 H17 V22"/></g>',
    # highlighter nib
    "highlight": '<g fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" '
                 'stroke-linejoin="round"><path d="M5 19 H11"/>'
                 '<path d="M14 4 L20 10 L11 19 L6 19 L6 14 Z"/></g>',
    # underline U
    "underline": '<g fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" '
                 'stroke-linejoin="round"><path d="M7 4 V10 A5 5 0 0 0 17 10 V4 M5 20 H19"/></g>',
    # strikethrough
    "strike": '<g fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round">'
              '<path d="M7 7 H17 M9 17 H15 M4 12 H20"/></g>',
    # sticky note / comment
    "note": '<path d="M4 5 H20 V15 H11 L6.5 19.5 V15 H4 Z" fill="none" stroke="{c}" '
            'stroke-width="2" stroke-linejoin="round"/>',
    # rectangle
    "rect": '<rect x="4" y="6" width="16" height="12" rx="1" fill="none" stroke="{c}" '
            'stroke-width="2"/>',
    # diagonal line
    "line": '<path d="M5 19 L19 5" fill="none" stroke="{c}" stroke-width="2" '
            'stroke-linecap="round"/>',
    # pencil (freehand ink)
    "ink": '<g fill="none" stroke="{c}" stroke-width="2" stroke-linejoin="round" '
           'stroke-linecap="round"><path d="M5 19 L5.5 15 L15.5 5 L19 8.5 L9 18.5 Z"/>'
           '<path d="M14 6.5 L17.5 10"/></g>',
    # redact (solid block)
    "redact": '<rect x="4" y="8" width="16" height="8" rx="1" fill="{c}" stroke="{c}" '
              'stroke-width="1"/>',
    # picture (insert image)
    "image": '<g fill="none" stroke="{c}" stroke-width="2" stroke-linejoin="round" '
             'stroke-linecap="round"><rect x="3" y="5" width="18" height="14" rx="1.5"/>'
             '<path d="M3 16 L9 10 L13 14 L16 11 L21 16"/><circle cx="15.5" cy="8.5" r="1.3"/></g>',
    # magnet (snap)
    "snap": '<g fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" '
            'stroke-linejoin="round"><path d="M6 4 V12 A6 6 0 0 0 18 12 V4"/>'
            '<path d="M6 4 H10 M14 4 H18 M10 4 V12 A2 2 0 0 0 14 12 V4"/></g>',
    # expand to fullscreen (present)
    "present": '<path d="M4 9 V4 H9 M15 4 H20 V9 M20 15 V20 H15 M9 20 H4 V15" fill="none" '
               'stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    # file ops (top bar)
    "open": '<path d="M3 6 H9 L11 8 H21 V19 H3 Z" fill="none" stroke="{c}" stroke-width="2" '
            'stroke-linejoin="round"/>',
    "save": '<g fill="none" stroke="{c}" stroke-width="2" stroke-linejoin="round">'
            '<path d="M5 4 H16 L20 8 V20 H5 Z"/><path d="M8 4 V9 H15 V4 M8 20 V14 H16 V20"/></g>',
    "undo": '<path d="M8 8 H15 A4.5 4.5 0 1 1 10.5 16 M8 8 L11 5 M8 8 L11 11" fill="none" '
            'stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    "redo": '<path d="M16 8 H9 A4.5 4.5 0 1 0 13.5 16 M16 8 L13 5 M16 8 L13 11" fill="none" '
            'stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    "find": '<g fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round">'
            '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15 L20 20"/></g>',
    "prev": '<path d="M15 4 L8 12 L15 20" fill="none" stroke="{c}" stroke-width="2.2" '
            'stroke-linecap="round" stroke-linejoin="round"/>',
    "next": '<path d="M9 4 L16 12 L9 20" fill="none" stroke="{c}" stroke-width="2.2" '
            'stroke-linecap="round" stroke-linejoin="round"/>',
    "pagesize": '<g fill="none" stroke="{c}" stroke-width="2" stroke-linejoin="round" '
                'stroke-linecap="round"><rect x="5" y="3" width="14" height="18" rx="1.5"/>'
                '<path d="M9 15 L15 9 M15 9 H11.5 M15 9 V12.5"/></g>',
    "tablerow": '<g fill="none" stroke="{c}" stroke-width="2" stroke-linejoin="round" '
                'stroke-linecap="round"><rect x="3" y="5" width="18" height="9" rx="1"/>'
                '<path d="M3 9.5 H21 M12 17 V21 M10 19 H14"/></g>',
    "tablecol": '<g fill="none" stroke="{c}" stroke-width="2" stroke-linejoin="round" '
                'stroke-linecap="round"><rect x="3" y="3" width="14" height="18" rx="1"/>'
                '<path d="M10 3 V21 M19 10 V14 M17 12 H21"/></g>',
    "tableapply": '<g fill="none" stroke="{c}" stroke-width="2" stroke-linejoin="round" '
                  'stroke-linecap="round"><rect x="3" y="4" width="18" height="16" rx="1"/>'
                  '<path d="M3 10 H21 M9 4 V20"/></g>',
}

def _svg_bytes(name: str, color: str) -> QByteArray:
    body = _GLYPHS[name].replace("{c}", color)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
           f'width="24" height="24">{body}</svg>')
    return QByteArray(svg.encode("utf-8"))


def _pixmap(name: str, color: str, size: int) -> QPixmap:
    ren = QSvgRenderer(_svg_bytes(name, color))
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    ren.render(p)
    p.end()
    return pm


def icon(name: str, size: int = 22) -> QIcon:
    """Two-state icon: light stroke normally, dark stroke when the action is checked
    (so an active tool reads on the orange highlight)."""
    ic = QIcon()
    ic.addPixmap(_pixmap(name, LIGHT, size), QIcon.Normal, QIcon.Off)
    ic.addPixmap(_pixmap(name, DARK, size), QIcon.Normal, QIcon.On)
    ic.addPixmap(_pixmap(name, DARK, size), QIcon.Active, QIcon.On)
    return ic
