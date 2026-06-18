"""
Document structure recognition.

PyMuPDF already segments a page into text *blocks* (≈ paragraphs) and *lines*. We build on
that: group the spans of a block, find the block's dominant font/size/colour and alignment,
then classify the block as TITLE / HEADING / PARAGRAPH / LINE using the body text size as a
yardstick. This lets the editor treat a paragraph as a paragraph (reflowed as a whole) and a
title as a title (kept on its own).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from enum import Enum

import fitz

from .pdf_document import TextSpan


class BlockType(str, Enum):
    TITLE = "Title"
    HEADING = "Heading"
    PARAGRAPH = "Paragraph"
    LINE = "Line"


# PDF text alignment constants mirror fitz: 0 left, 1 center, 2 right, 3 justify.
ALIGN_LEFT, ALIGN_CENTER, ALIGN_RIGHT, ALIGN_JUSTIFY = 0, 1, 2, 3


@dataclass
class Block:
    page_index: int
    block_no: int
    bbox: tuple[float, float, float, float]
    type: BlockType
    text: str
    lines: list[list[TextSpan]]          # spans grouped per line
    font_name: str
    size: float
    color: int
    flags: int
    align: int

    @property
    def rect(self) -> fitz.Rect:
        return fitz.Rect(self.bbox)

    @property
    def line_count(self) -> int:
        return len(self.lines)

    @property
    def all_spans(self) -> list[TextSpan]:
        return [s for line in self.lines for s in line]

    @property
    def flow_text(self) -> str:
        """The paragraph as one flowing string — soft line-wraps joined with spaces and
        de-hyphenated, so editing/re-wrapping doesn't reproduce the original hard breaks."""
        parts = []
        line_texts = [" ".join(s.text for s in line).strip() for line in self.lines]
        for i, lt in enumerate(line_texts):
            if not lt:
                continue
            if parts and parts[-1].endswith("-") and lt[:1].islower():
                parts[-1] = parts[-1][:-1] + lt   # join hyphenated word split across lines
            elif parts:
                parts.append(" " + lt)
            else:
                parts.append(lt)
        return "".join(parts)

    @property
    def first_origin(self) -> tuple[float, float]:
        spans = self.lines[0] if self.lines else []
        return spans[0].origin if spans else (self.bbox[0], self.bbox[3])


def _dominant_span(spans: list[TextSpan]) -> TextSpan:
    """The span carrying the most characters — represents the block's main style."""
    return max(spans, key=lambda s: len(s.text))


def _detect_align(block_bbox, lines: list[list[TextSpan]]) -> int:
    if len(lines) < 1:
        return ALIGN_LEFT
    bx0, _, bx1, _ = block_bbox
    bw = bx1 - bx0
    if bw <= 1:
        return ALIGN_LEFT
    left_gaps, right_gaps = [], []
    for line in lines:
        if not line:
            continue
        lx0 = min(s.bbox[0] for s in line)
        lx1 = max(s.bbox[2] for s in line)
        left_gaps.append(lx0 - bx0)
        right_gaps.append(bx1 - lx1)
    if not left_gaps:
        return ALIGN_LEFT
    avg_l = statistics.mean(left_gaps)
    avg_r = statistics.mean(right_gaps)
    # centered: comparable left/right margins, both clearly > 0
    if abs(avg_l - avg_r) < 0.1 * bw and avg_l > 0.05 * bw:
        return ALIGN_CENTER
    if avg_r < avg_l and avg_r < 0.05 * bw and avg_l > 0.1 * bw:
        return ALIGN_RIGHT
    return ALIGN_LEFT


def analyze_page(document, page_index: int) -> list[Block]:
    """Return classified blocks for a page (uses the same dict extraction as spans)."""
    page = document.doc[page_index]
    data = page.get_text("dict")
    font_xrefs = document._page_font_xrefs(page_index)

    raw_blocks = []
    all_sizes = []
    for bi, block in enumerate(data.get("blocks", [])):
        if block.get("type", 0) != 0:
            continue
        lines: list[list[TextSpan]] = []
        for li, line in enumerate(block.get("lines", [])):
            line_spans = []
            for si, span in enumerate(line.get("spans", [])):
                if span.get("text", "") == "":
                    continue
                ts = TextSpan(
                    page_index=page_index, block=bi, line=li, span=si,
                    text=span["text"], bbox=tuple(span["bbox"]),
                    origin=tuple(span.get("origin", (span["bbox"][0], span["bbox"][3]))),
                    font_name=span.get("font", ""), size=span.get("size", 11.0),
                    color=span.get("color", 0), flags=span.get("flags", 0),
                    font_xref=font_xrefs.get(span.get("font", ""), 0),
                )
                line_spans.append(ts)
                all_sizes.append(ts.size)
            if line_spans:
                lines.append(line_spans)
        if lines:
            raw_blocks.append((bi, tuple(block["bbox"]), lines))

    body_size = statistics.median(all_sizes) if all_sizes else 11.0
    page_top = page.rect.y0

    blocks: list[Block] = []
    for bi, bbox, lines in raw_blocks:
        spans = [s for line in lines for s in line]
        dom = _dominant_span(spans)
        max_size = max(s.size for s in spans)
        n_lines = len(lines)
        text = "\n".join(" ".join(s.text for s in line) for line in lines)
        is_bold = bool(dom.flags & (1 << 4))
        near_top = (bbox[1] - page_top) < (page.rect.height * 0.22)

        btype = _classify(max_size, body_size, n_lines, is_bold, near_top,
                          len(text.strip()))
        blocks.append(Block(
            page_index=page_index, block_no=bi, bbox=bbox, type=btype, text=text,
            lines=lines, font_name=dom.font_name, size=round(dom.size, 1),
            color=dom.color, flags=dom.flags, align=_detect_align(bbox, lines),
        ))
    return blocks


def _classify(max_size, body_size, n_lines, is_bold, near_top, char_len) -> BlockType:
    ratio = max_size / body_size if body_size else 1.0
    if n_lines <= 2 and ratio >= 1.5 and char_len < 120:
        return BlockType.TITLE
    if n_lines <= 2 and (ratio >= 1.2 or (is_bold and ratio >= 1.05)) and char_len < 160:
        return BlockType.HEADING
    if n_lines >= 2:
        return BlockType.PARAGRAPH
    return BlockType.LINE


def block_at(blocks: list[Block], x: float, y: float) -> Block | None:
    """Find the smallest block containing a point (PDF coordinates)."""
    best = None
    for b in blocks:
        x0, y0, x1, y1 = b.bbox
        if x0 <= x <= x1 and y0 <= y <= y1:
            area = (x1 - x0) * (y1 - y0)
            if best is None or area < best[1]:
                best = (b, area)
    return best[0] if best else None
