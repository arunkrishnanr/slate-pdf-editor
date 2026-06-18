"""
The page view: renders a page and lets the user edit text directly on it.

Interaction model:
  * SELECT mode  — click a text span to edit it inline (a box appears right over the
    text, pre-filled with the current content; Enter commits, Esc cancels).
  * ADD_TEXT     — click anywhere to drop a new text box.
  * OCR_REGION   — drag a rectangle over non-editable text to OCR + edit it.

Coordinates: we render at `zoom`, so 1 PDF point == `zoom` device pixels. The scene is
in pixels; dividing by zoom gives PDF points (PyMuPDF and Qt both use a top-left origin).
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Optional

from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QRect
from PySide6.QtGui import QPixmap, QImage, QPainter, QColor, QPen, QBrush
from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QLineEdit, QRubberBand,
    QGraphicsRectItem, QPlainTextEdit,
)

from .pdf_document import TextSpan


class Mode(Enum):
    SELECT = auto()
    ADD_TEXT = auto()
    TEXT_BOX = auto()
    OCR_REGION = auto()


class _ParagraphEdit(QPlainTextEdit):
    """Multi-line editor overlay for paragraphs. Commits on Ctrl/Cmd+Enter or focus-out."""
    committed = Signal()
    cancelled = Signal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.cancelled.emit()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and \
                (event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier)):
            self.committed.emit()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.committed.emit()


class PageView(QGraphicsView):
    spanActivated = Signal(object)          # TextSpan to edit
    commitEdit = Signal(object, str)        # (TextSpan, new_text)
    commitBlockEdit = Signal(object, str)   # (Block, new_text) — paragraph reflow
    selected = Signal(object, object)       # (TextSpan|None, Block|None) for properties panel
    addTextRequested = Signal(float, float) # PDF point x, y
    textBoxRequested = Signal(tuple)        # (x0, y0, x1, y1) for a new text box
    ocrRegionRequested = Signal(tuple)      # (x0, y0, x1, y1) in PDF points
    zoomRequested = Signal(float)           # zoom factor delta

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor(60, 63, 70))
        self.setDragMode(QGraphicsView.NoDrag)

        self._pixmap_item: Optional[QGraphicsPixmapItem] = None
        self._zoom = 1.5
        self._page_index = 0
        self._spans: list[TextSpan] = []
        self._blocks: list = []
        self._hover_item: Optional[QGraphicsRectItem] = None
        self._search_item: Optional[QGraphicsRectItem] = None
        self._mode = Mode.SELECT
        self._para_detect = True

        self._editor: Optional[QLineEdit] = None
        self._editing_span: Optional[TextSpan] = None
        self._block_editor: Optional[QPlainTextEdit] = None
        self._editing_block = None

        self._rubber: Optional[QRubberBand] = None
        self._rubber_origin = QPointF()

        self.setMouseTracking(True)

    # -- public API --------------------------------------------------------

    @property
    def zoom(self) -> float:
        return self._zoom

    def set_mode(self, mode: Mode):
        self._mode = mode
        self._cancel_inline_edit()
        if mode == Mode.SELECT:
            self.viewport().setCursor(Qt.ArrowCursor)
        elif mode == Mode.ADD_TEXT:
            self.viewport().setCursor(Qt.IBeamCursor)
        else:
            self.viewport().setCursor(Qt.CrossCursor)

    def set_page(self, png_bytes: bytes, zoom: float, page_index: int,
                 spans: list[TextSpan], blocks: list | None = None):
        self._cancel_inline_edit()
        self._zoom = zoom
        self._page_index = page_index
        self._spans = spans
        self._blocks = blocks or []
        img = QImage.fromData(png_bytes, "PNG")
        pix = QPixmap.fromImage(img)
        self._scene.clear()
        self._hover_item = None
        self._search_item = None
        self._pixmap_item = self._scene.addPixmap(pix)
        self._scene.setSceneRect(QRectF(pix.rect()))

    def set_zoom(self, zoom: float):
        self._zoom = zoom

    def set_paragraph_detection(self, on: bool):
        self._para_detect = on

    def show_search_highlight(self, bbox):
        """Draw a temporary highlight over a search hit (cleared on next page set)."""
        if self._search_item is not None:
            try:
                self._scene.removeItem(self._search_item)
            except Exception:
                pass
            self._search_item = None
        if bbox is None:
            return
        item = QGraphicsRectItem(self._bbox_scene_rect(bbox))
        item.setPen(QPen(QColor(240, 180, 20), 1.5))
        item.setBrush(QBrush(QColor(255, 220, 0, 80)))
        item.setZValue(9)
        self._scene.addItem(item)
        self._search_item = item

    # -- hit testing -------------------------------------------------------

    def _span_at(self, scene_pt: QPointF) -> Optional[TextSpan]:
        x = scene_pt.x() / self._zoom
        y = scene_pt.y() / self._zoom
        best = None
        for s in self._spans:
            x0, y0, x1, y1 = s.bbox
            if x0 <= x <= x1 and y0 <= y <= y1:
                # Prefer the smallest matching span (most specific).
                area = (x1 - x0) * (y1 - y0)
                if best is None or area < best[1]:
                    best = (s, area)
        return best[0] if best else None

    def _span_scene_rect(self, span: TextSpan) -> QRectF:
        x0, y0, x1, y1 = span.bbox
        return QRectF(x0 * self._zoom, y0 * self._zoom,
                      (x1 - x0) * self._zoom, (y1 - y0) * self._zoom)

    def _bbox_scene_rect(self, bbox) -> QRectF:
        x0, y0, x1, y1 = bbox
        return QRectF(x0 * self._zoom, y0 * self._zoom,
                      (x1 - x0) * self._zoom, (y1 - y0) * self._zoom)

    def _block_at(self, scene_pt: QPointF):
        x = scene_pt.x() / self._zoom
        y = scene_pt.y() / self._zoom
        best = None
        for b in self._blocks:
            x0, y0, x1, y1 = b.bbox
            if x0 <= x <= x1 and y0 <= y <= y1:
                area = (x1 - x0) * (y1 - y0)
                if best is None or area < best[1]:
                    best = (b, area)
        return best[0] if best else None

    # -- mouse -------------------------------------------------------------

    def mouseMoveEvent(self, event):
        scene_pt = self.mapToScene(event.position().toPoint())
        if self._mode == Mode.SELECT:
            span = self._span_at(scene_pt)
            self._show_hover(span)
        elif self._mode in (Mode.OCR_REGION, Mode.TEXT_BOX) and self._rubber is not None \
                and self._rubber.isVisible():
            rect = QRect(self._rubber_origin.toPoint(), event.position().toPoint()).normalized()
            self._rubber.setGeometry(rect)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        scene_pt = self.mapToScene(event.position().toPoint())

        if self._mode == Mode.SELECT:
            span = self._span_at(scene_pt)
            block = self._block_at(scene_pt)
            # Populate the properties panel for whatever was clicked.
            self.selected.emit(span, block)
            if self._para_detect and block is not None and getattr(block, "line_count", 1) >= 2 \
                    and span is not None:
                # Multi-line block -> edit the whole paragraph and reflow.
                self._begin_block_edit(block)
            elif span is not None:
                self._begin_inline_edit(span)
            else:
                self._cancel_inline_edit()
        elif self._mode == Mode.ADD_TEXT:
            self.addTextRequested.emit(scene_pt.x() / self._zoom, scene_pt.y() / self._zoom)
        elif self._mode in (Mode.OCR_REGION, Mode.TEXT_BOX):
            self._rubber_origin = event.position()
            if self._rubber is None:
                self._rubber = QRubberBand(QRubberBand.Rectangle, self.viewport())
            self._rubber.setGeometry(QRect(self._rubber_origin.toPoint(), self._rubber_origin.toPoint()))
            self._rubber.show()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._mode in (Mode.OCR_REGION, Mode.TEXT_BOX) and self._rubber is not None \
                and self._rubber.isVisible():
            geo = self._rubber.geometry()
            self._rubber.hide()
            p0 = self.mapToScene(geo.topLeft())
            p1 = self.mapToScene(geo.bottomRight())
            rect_pts = (min(p0.x(), p1.x()) / self._zoom, min(p0.y(), p1.y()) / self._zoom,
                        max(p0.x(), p1.x()) / self._zoom, max(p0.y(), p1.y()) / self._zoom)
            if (rect_pts[2] - rect_pts[0]) > 3 and (rect_pts[3] - rect_pts[1]) > 3:
                if self._mode == Mode.OCR_REGION:
                    self.ocrRegionRequested.emit(rect_pts)
                else:
                    self.textBoxRequested.emit(rect_pts)
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        # Ctrl+wheel zooms; otherwise let the scroll area scroll.
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            factor = 1.15 if delta > 0 else 1 / 1.15
            self.parent_zoom(factor)
            event.accept()
        else:
            super().wheelEvent(event)

    def parent_zoom(self, factor: float):
        # Re-render at a new zoom by asking the owner; the owner connects this.
        self.zoomRequested.emit(factor)

    # -- hover highlight ---------------------------------------------------

    def _show_hover(self, span: Optional[TextSpan]):
        if self._hover_item is not None:
            self._scene.removeItem(self._hover_item)
            self._hover_item = None
        if span is None:
            return
        rect = self._span_scene_rect(span)
        item = QGraphicsRectItem(rect)
        item.setPen(QPen(QColor(40, 130, 230), 1.2))
        item.setBrush(QBrush(QColor(40, 130, 230, 40)))
        item.setZValue(10)
        self._scene.addItem(item)
        self._hover_item = item

    # -- inline editing ----------------------------------------------------

    def _begin_inline_edit(self, span: TextSpan):
        self._cancel_inline_edit()
        self._editing_span = span
        rect = self._span_scene_rect(span)
        view_tl = self.mapFromScene(rect.topLeft())
        view_br = self.mapFromScene(rect.bottomRight())
        geo = QRect(view_tl, view_br).normalized()
        geo.adjust(-3, -3, 60, 6)  # a little breathing room + room to type more

        editor = QLineEdit(self.viewport())
        editor.setText(span.text)
        editor.setGeometry(geo)
        px = max(9, int(span.size * self._zoom * 0.85))
        editor.setStyleSheet(
            f"QLineEdit {{ font-size: {px}px; padding: 1px 3px; "
            f"border: 2px solid #2a82e6; background: #fffef5; color: #111; }}"
        )
        editor.selectAll()
        editor.returnPressed.connect(self._commit_inline_edit)
        editor.editingFinished.connect(self._on_editing_finished)
        editor.show()
        editor.setFocus()
        self._editor = editor
        self.spanActivated.emit(span)

    def _on_editing_finished(self):
        # editingFinished fires on focus-out too; commit if text changed.
        if self._editor is not None and self._editing_span is not None:
            if self._editor.text() != self._editing_span.text:
                self._commit_inline_edit()
            else:
                self._cancel_inline_edit()

    def _commit_inline_edit(self):
        if self._editor is None or self._editing_span is None:
            return
        new_text = self._editor.text()
        span = self._editing_span
        # Clear references before emitting so re-render doesn't fight the widget.
        self._editor.blockSignals(True)
        self._editor.deleteLater()
        self._editor = None
        self._editing_span = None
        if new_text != span.text:
            self.commitEdit.emit(span, new_text)

    def _cancel_inline_edit(self):
        if self._editor is not None:
            self._editor.blockSignals(True)
            self._editor.deleteLater()
            self._editor = None
        self._editing_span = None
        if self._block_editor is not None:
            self._block_editor.blockSignals(True)
            self._block_editor.deleteLater()
            self._block_editor = None
        self._editing_block = None

    # -- paragraph (multi-line block) editing ------------------------------

    def _begin_block_edit(self, block):
        self._cancel_inline_edit()
        self._editing_block = block
        rect = self._bbox_scene_rect(block.bbox)
        view_tl = self.mapFromScene(rect.topLeft())
        view_br = self.mapFromScene(rect.bottomRight())
        geo = QRect(view_tl, view_br).normalized()
        geo.adjust(-4, -4, 8, 40)  # room to grow downward as the paragraph reflows

        editor = _ParagraphEdit(self.viewport())
        editor.setPlainText(block.text)
        editor.setGeometry(geo)
        px = max(9, int(block.size * self._zoom * 0.85))
        editor.setStyleSheet(
            f"QPlainTextEdit {{ font-size: {px}px; padding: 2px 4px; "
            f"border: 2px solid #f5a623; background: #fffdf3; color: #111; }}"
        )
        editor.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        editor.selectAll()
        editor.committed.connect(self._commit_block_edit)
        editor.cancelled.connect(self._cancel_inline_edit)
        editor.show()
        editor.setFocus()
        self._block_editor = editor
        self.spanActivated.emit(block)

    def _commit_block_edit(self):
        if self._block_editor is None or self._editing_block is None:
            return
        new_text = self._block_editor.toPlainText()
        block = self._editing_block
        self._block_editor.blockSignals(True)
        self._block_editor.deleteLater()
        self._block_editor = None
        self._editing_block = None
        if new_text != block.text:
            self.commitBlockEdit.emit(block, new_text)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._cancel_inline_edit()
            return
        super().keyPressEvent(event)
