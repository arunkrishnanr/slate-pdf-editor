"""
International page-size standards, in PDF points (1 pt = 1/72 inch; 1 mm = 72/25.4 pt).

Covers ISO 216 (A/B/C), JIS B, North American, ANSI, and ARCH series.
Sizes are stored portrait (width <= height); callers can swap for landscape.
"""

from __future__ import annotations

MM = 72.0 / 25.4
IN = 72.0


def _mm(w_mm: float, h_mm: float) -> tuple[float, float]:
    return round(w_mm * MM, 2), round(h_mm * MM, 2)


def _in(w_in: float, h_in: float) -> tuple[float, float]:
    return round(w_in * IN, 2), round(h_in * IN, 2)


# name -> (width_pt, height_pt) portrait
PAGE_SIZES: dict[str, tuple[float, float]] = {
    # --- ISO 216 A series ---
    "A0": _mm(841, 1189), "A1": _mm(594, 841), "A2": _mm(420, 594),
    "A3": _mm(297, 420), "A4": _mm(210, 297), "A5": _mm(148, 210),
    "A6": _mm(105, 148), "A7": _mm(74, 105), "A8": _mm(52, 74),
    "A9": _mm(37, 52), "A10": _mm(26, 37),
    # --- ISO 216 B series ---
    "B0": _mm(1000, 1414), "B1": _mm(707, 1000), "B2": _mm(500, 707),
    "B3": _mm(353, 500), "B4": _mm(250, 353), "B5": _mm(176, 250),
    "B6": _mm(125, 176), "B7": _mm(88, 125), "B8": _mm(62, 88),
    "B9": _mm(44, 62), "B10": _mm(31, 44),
    # --- ISO 269 C series (envelopes) ---
    "C0": _mm(917, 1297), "C1": _mm(648, 917), "C2": _mm(458, 648),
    "C3": _mm(324, 458), "C4": _mm(229, 324), "C5": _mm(162, 229),
    "C6": _mm(114, 162), "C7": _mm(81, 114), "C8": _mm(57, 81),
    "C9": _mm(40, 57), "C10": _mm(28, 40),
    "DL Envelope": _mm(110, 220),
    # --- JIS B series (Japan) ---
    "JIS B0": _mm(1030, 1456), "JIS B1": _mm(728, 1030), "JIS B2": _mm(515, 728),
    "JIS B3": _mm(364, 515), "JIS B4": _mm(257, 364), "JIS B5": _mm(182, 257),
    "JIS B6": _mm(128, 182), "JIS B7": _mm(91, 128), "JIS B8": _mm(64, 91),
    # --- North American ---
    "Letter": _in(8.5, 11), "Legal": _in(8.5, 14), "Junior Legal": _in(5, 8),
    "Tabloid / Ledger": _in(11, 17), "Executive": _in(7.25, 10.5),
    "Statement": _in(5.5, 8.5), "Government Letter": _in(8, 10.5),
    # --- ANSI ---
    "ANSI A": _in(8.5, 11), "ANSI B": _in(11, 17), "ANSI C": _in(17, 22),
    "ANSI D": _in(22, 34), "ANSI E": _in(34, 44),
    # --- ARCH ---
    "ARCH A": _in(9, 12), "ARCH B": _in(12, 18), "ARCH C": _in(18, 24),
    "ARCH D": _in(24, 36), "ARCH E": _in(36, 48), "ARCH E1": _in(30, 42),
}

# Grouped for a tidy dropdown.
PAGE_SIZE_GROUPS: list[tuple[str, list[str]]] = [
    ("ISO A", ["A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10"]),
    ("ISO B", ["B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "B10"]),
    ("ISO C (envelopes)", ["C0", "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "DL Envelope"]),
    ("JIS B", ["JIS B0", "JIS B1", "JIS B2", "JIS B3", "JIS B4", "JIS B5", "JIS B6", "JIS B7", "JIS B8"]),
    ("North American", ["Letter", "Legal", "Junior Legal", "Tabloid / Ledger",
                        "Executive", "Statement", "Government Letter"]),
    ("ANSI", ["ANSI A", "ANSI B", "ANSI C", "ANSI D", "ANSI E"]),
    ("ARCH", ["ARCH A", "ARCH B", "ARCH C", "ARCH D", "ARCH E", "ARCH E1"]),
]


def size_label(name: str) -> str:
    w, h = PAGE_SIZES[name]
    return f"{name}  ({w/MM:.0f}×{h/MM:.0f} mm · {w/IN:.2f}×{h/IN:.2f} in)"


def nearest_standard(width_pt: float, height_pt: float, tol: float = 3.0) -> str | None:
    """Return the standard name matching these dimensions (either orientation), if any."""
    for name, (w, h) in PAGE_SIZES.items():
        if (abs(w - width_pt) < tol and abs(h - height_pt) < tol) or \
           (abs(h - width_pt) < tol and abs(w - height_pt) < tol):
            return name
    return None
