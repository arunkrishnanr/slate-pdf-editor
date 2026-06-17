"""
Organize Pages panel: thumbnail grid with delete, drag-to-reorder, rotate and split.

Emits high-level intents; the main window performs them against the document and asks
for a refresh. Thumbnails are rendered lazily at a small zoom.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QPixmap, QImage, QIcon, QAction
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton,
    QLabel, QListView, QMenu, QAbstractItemView,
)

from .pdf_document import PdfDocument


THUMB_ZOOM = 0.28


class PagesPanel(QWidget):
    pageSelected = Signal(int)            # user clicked a thumbnail (current index)
    deleteRequested = Signal(list)        # page indices to delete
    splitOffRequested = Signal(list)      # page indices to export to a new PDF
    splitAtRequested = Signal(int)        # split into two after this index
    rotateRequested = Signal(list, int)   # (indices, degrees)
    reordered = Signal(int, int)          # (from_index, to_index)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        header = QLabel("Organize Pages")
        header.setStyleSheet("font-weight: 600; padding: 2px;")
        layout.addWidget(header)

        self.list = QListWidget()
        self.list.setViewMode(QListView.IconMode)
        self.list.setIconSize(QSize(140, 180))
        self.list.setResizeMode(QListView.Adjust)
        self.list.setMovement(QListView.Snap)
        self.list.setSpacing(8)
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        self.list.currentRowChanged.connect(self._on_current_changed)
        self.list.model().rowsMoved.connect(self._on_rows_moved)
        layout.addWidget(self.list, 1)

        btn_row = QHBoxLayout()
        self.btn_delete = QPushButton("Delete")
        self.btn_split_off = QPushButton("Split off →")
        self.btn_rotate = QPushButton("Rotate")
        for b in (self.btn_delete, self.btn_split_off, self.btn_rotate):
            btn_row.addWidget(b)
        layout.addLayout(btn_row)

        self.btn_delete.clicked.connect(lambda: self.deleteRequested.emit(self.selected_rows()))
        self.btn_split_off.clicked.connect(lambda: self.splitOffRequested.emit(self.selected_rows()))
        self.btn_rotate.clicked.connect(lambda: self.rotateRequested.emit(self.selected_rows(), 90))

        self._suppress_move_signal = False

    # -- population --------------------------------------------------------

    def refresh(self, document: PdfDocument, current: int = 0):
        self.list.blockSignals(True)
        self.list.clear()
        for i in range(document.page_count):
            png = document.render_page_png(i, THUMB_ZOOM)
            img = QImage.fromData(png, "PNG")
            pix = QPixmap.fromImage(img)
            item = QListWidgetItem(QIcon(pix), f"Page {i + 1}")
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignBottom)
            item.setData(Qt.UserRole, i)
            self.list.addItem(item)
        self.list.blockSignals(False)
        if 0 <= current < self.list.count():
            self.list.setCurrentRow(current)

    def selected_rows(self) -> list[int]:
        rows = sorted(self.list.row(i) for i in self.list.selectedItems())
        if not rows and self.list.currentRow() >= 0:
            rows = [self.list.currentRow()]
        return rows

    # -- events ------------------------------------------------------------

    def _on_current_changed(self, row: int):
        if row >= 0:
            self.pageSelected.emit(row)

    def _on_rows_moved(self, parent, start, end, dest, dest_row):
        if self._suppress_move_signal:
            return
        to = dest_row if dest_row < start else dest_row - 1
        self.reordered.emit(start, to)

    def _context_menu(self, pos):
        rows = self.selected_rows()
        if not rows:
            return
        menu = QMenu(self)
        act_delete = menu.addAction("Delete page(s)")
        act_split_off = menu.addAction("Split selected into new PDF…")
        act_split_at = menu.addAction(f"Split document after page {rows[-1] + 1}…")
        menu.addSeparator()
        act_rot_cw = menu.addAction("Rotate 90° clockwise")
        act_rot_ccw = menu.addAction("Rotate 90° counter-clockwise")
        chosen = menu.exec(self.list.mapToGlobal(pos))
        if chosen == act_delete:
            self.deleteRequested.emit(rows)
        elif chosen == act_split_off:
            self.splitOffRequested.emit(rows)
        elif chosen == act_split_at:
            self.splitAtRequested.emit(rows[-1])
        elif chosen == act_rot_cw:
            self.rotateRequested.emit(rows, 90)
        elif chosen == act_rot_ccw:
            self.rotateRequested.emit(rows, -90)
