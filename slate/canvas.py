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
    QGraphicsRectItem,
)

from .pdf_document import TextSpan


class Mode(Enum):
    SELECT = auto()
    ADD_TEXT = auto()
    OCR_REGION = auto()


class PageView(QGraphicsView):
    spanActivated = Signal(object)          # TextSpan to edit
    commitEdit = Signal(object, str)        # (TextSpan, new_text)
    addTextRequested = Signal(float, float) # PDF point x, y
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
        self._hover_item: Optional[QGraphicsRectItem] = None
        self._mode = Mode.SELECT

        self._editor: Optional[QLineEdit] = None
        self._editing_span: Optional[TextSpan] = None

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

    def set_page(self, png_bytes: bytes, zoom: float, page_index: int, spans: list[TextSpan]):
        self._cancel_inline_edit()
        self._zoom = zoom
        self._page_index = page_index
        self._spans = spans
        img = QImage.fromData(png_bytes, "PNG")
        pix = QPixmap.fromImage(img)
        self._scene.clear()
        self._hover_item = None
        self._pixmap_item = self._scene.addPixmap(pix)
        self._scene.setSceneRect(QRectF(pix.rect()))

    def set_zoom(self, zoom: float):
        self._zoom = zoom

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

    # -- mouse -------------------------------------------------------------

    def mouseMoveEvent(self, event):
        scene_pt = self.mapToScene(event.position().toPoint())
        if self._mode == Mode.SELECT:
            span = self._span_at(scene_pt)
            self._show_hover(span)
        elif self._mode == Mode.OCR_REGION and self._rubber is not None:
            rect = QRect(self._rubber_origin.toPoint(), event.position().toPoint()).normalized()
            self._rubber.setGeometry(rect)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        scene_pt = self.mapToScene(event.position().toPoint())

        if self._mode == Mode.SELECT:
            span = self._span_at(scene_pt)
            if span is not None:
                self._begin_inline_edit(span)
            else:
                self._cancel_inline_edit()
        elif self._mode == Mode.ADD_TEXT:
            self.addTextRequested.emit(scene_pt.x() / self._zoom, scene_pt.y() / self._zoom)
        elif self._mode == Mode.OCR_REGION:
            self._rubber_origin = event.position()
            if self._rubber is None:
                self._rubber = QRubberBand(QRubberBand.Rectangle, self.viewport())
            self._rubber.setGeometry(QRect(self._rubber_origin.toPoint(), self._rubber_origin.toPoint()))
            self._rubber.show()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._mode == Mode.OCR_REGION and self._rubber is not None and self._rubber.isVisible():
            geo = self._rubber.geometry()
            self._rubber.hide()
            p0 = self.mapToScene(geo.topLeft())
            p1 = self.mapToScene(geo.bottomRight())
            rect_pts = (min(p0.x(), p1.x()) / self._zoom, min(p0.y(), p1.y()) / self._zoom,
                        max(p0.x(), p1.x()) / self._zoom, max(p0.y(), p1.y()) / self._zoom)
            if (rect_pts[2] - rect_pts[0]) > 3 and (rect_pts[3] - rect_pts[1]) > 3:
                self.ocrRegionRequested.emit(rect_pts)
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

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._cancel_inline_edit()
        super().keyPressEvent(event)
