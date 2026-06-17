"""The main application window — wires the document, page view, and panels together."""

from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QKeySequence, QIcon
from PySide6.QtWidgets import (
    QMainWindow, QFileDialog, QMessageBox, QDockWidget, QToolBar, QLabel,
    QStatusBar, QApplication, QComboBox, QWidget, QSizePolicy,
)

from . import __app_name__, __version__
from . import font_manager as fm
from . import ocr as ocr_mod
from .pdf_document import PdfDocument, TextSpan
from .text_editor import TextEditor, EditResult
from .canvas import PageView, Mode
from .pages_panel import PagesPanel
from .dialogs import FontPromptDialog, AddTextDialog, OcrReviewDialog


class MainWindow(QMainWindow):
    def __init__(self, icon: Optional[QIcon] = None):
        super().__init__()
        self.setWindowTitle(__app_name__)
        if icon:
            self.setWindowIcon(icon)
        self.resize(1280, 860)

        self.document = PdfDocument()
        self.editor = TextEditor(self.document)
        self.current_page = 0
        self.zoom = 1.5

        # Central page view
        self.view = PageView()
        self.setCentralWidget(self.view)
        self.view.commitEdit.connect(self._on_commit_edit)
        self.view.spanActivated.connect(self._on_span_activated)
        self.view.addTextRequested.connect(self._on_add_text)
        self.view.ocrRegionRequested.connect(self._on_ocr_region)
        self.view.zoomRequested.connect(self._on_zoom_factor)

        # Pages dock
        self.pages = PagesPanel()
        dock = QDockWidget("Pages", self)
        dock.setWidget(self.pages)
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        self.pages_dock = dock
        self.pages.pageSelected.connect(self.goto_page)
        self.pages.deleteRequested.connect(self._on_delete_pages)
        self.pages.splitOffRequested.connect(self._on_split_off)
        self.pages.splitAtRequested.connect(self._on_split_at)
        self.pages.rotateRequested.connect(self._on_rotate)
        self.pages.reordered.connect(self._on_reordered)

        self._build_actions()
        self._build_toolbar()
        self._build_menu()
        self.setStatusBar(QStatusBar())
        self._set_open_state(False)
        self.status("Open a PDF to begin — File ▸ Open  (⌘O)")

        # Point pytesseract at a bundled binary if present.
        self._configure_ocr()

    # -- UI construction ---------------------------------------------------

    def _build_actions(self):
        self.act_open = QAction("Open…", self, shortcut=QKeySequence.Open, triggered=self.open_file)
        self.act_new = QAction("New", self, shortcut=QKeySequence.New, triggered=self.new_file)
        self.act_save = QAction("Save", self, shortcut=QKeySequence.Save, triggered=self.save_file)
        self.act_save_as = QAction("Save As…", self, shortcut=QKeySequence.SaveAs, triggered=self.save_file_as)
        self.act_export = QAction("Export Copy…", self, triggered=self.export_copy)
        self.act_quit = QAction("Quit", self, shortcut=QKeySequence.Quit, triggered=self.close)

        self.act_mode_select = QAction("Edit Text", self, checkable=True, triggered=lambda: self.set_mode(Mode.SELECT))
        self.act_mode_add = QAction("Add Text", self, checkable=True, triggered=lambda: self.set_mode(Mode.ADD_TEXT))
        self.act_mode_ocr = QAction("OCR Region", self, checkable=True, triggered=lambda: self.set_mode(Mode.OCR_REGION))
        self.act_mode_select.setChecked(True)

        self.act_prev = QAction("◀", self, triggered=self.prev_page)
        self.act_next = QAction("▶", self, triggered=self.next_page)
        self.act_zoom_in = QAction("Zoom +", self, shortcut=QKeySequence.ZoomIn, triggered=lambda: self._on_zoom_factor(1.15))
        self.act_zoom_out = QAction("Zoom −", self, shortcut=QKeySequence.ZoomOut, triggered=lambda: self._on_zoom_factor(1/1.15))

        self.act_about = QAction("About", self, triggered=self.about)

    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setIconSize(QSize(18, 18))
        tb.setMovable(False)
        self.addToolBar(tb)
        tb.addAction(self.act_open)
        tb.addAction(self.act_save)
        tb.addSeparator()
        tb.addAction(self.act_mode_select)
        tb.addAction(self.act_mode_add)
        tb.addAction(self.act_mode_ocr)
        tb.addSeparator()
        tb.addAction(self.act_prev)
        self.page_label = QLabel("  —  ")
        tb.addWidget(self.page_label)
        tb.addAction(self.act_next)
        tb.addSeparator()
        tb.addAction(self.act_zoom_out)
        tb.addAction(self.act_zoom_in)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        self.font_status = QLabel("")
        self.font_status.setStyleSheet("color: #cfd3da; padding-right: 8px;")
        tb.addWidget(self.font_status)

    def _build_menu(self):
        bar = self.menuBar()
        m_file = bar.addMenu("File")
        for a in (self.act_new, self.act_open, self.act_save, self.act_save_as, self.act_export):
            m_file.addAction(a)
        m_file.addSeparator()
        m_file.addAction(self.act_quit)

        m_tools = bar.addMenu("Tools")
        for a in (self.act_mode_select, self.act_mode_add, self.act_mode_ocr):
            m_tools.addAction(a)

        m_view = bar.addMenu("View")
        for a in (self.act_zoom_in, self.act_zoom_out, self.act_prev, self.act_next):
            m_view.addAction(a)
        m_view.addAction(self.pages_dock.toggleViewAction())

        m_help = bar.addMenu("Help")
        m_help.addAction(self.act_about)

    def _configure_ocr(self):
        # Prefer a tesseract bundled under vendor/ (works inside a frozen one-file exe,
        # where data is unpacked next to this module); otherwise fall back to PATH.
        import sys
        import shutil
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(__file__)))
        names = ("tesseract.exe", "tesseract") if sys.platform.startswith("win") else ("tesseract",)
        for name in names:
            candidate = os.path.join(base, "vendor", name)
            if os.path.exists(candidate):
                ocr_mod.configure_tesseract(candidate)
                return
        found = shutil.which("tesseract")
        if found:
            ocr_mod.configure_tesseract(found)

    # -- state -------------------------------------------------------------

    def _set_open_state(self, is_open: bool):
        for a in (self.act_save, self.act_save_as, self.act_export,
                  self.act_mode_select, self.act_mode_add, self.act_mode_ocr,
                  self.act_prev, self.act_next, self.act_zoom_in, self.act_zoom_out):
            a.setEnabled(is_open)

    def status(self, msg: str, timeout: int = 0):
        self.statusBar().showMessage(msg, timeout)

    def set_mode(self, mode: Mode):
        self.view.set_mode(mode)
        self.act_mode_select.setChecked(mode == Mode.SELECT)
        self.act_mode_add.setChecked(mode == Mode.ADD_TEXT)
        self.act_mode_ocr.setChecked(mode == Mode.OCR_REGION)
        names = {Mode.SELECT: "Edit Text — click any text to change it",
                 Mode.ADD_TEXT: "Add Text — click where you want new text",
                 Mode.OCR_REGION: "OCR Region — drag a box over non-editable text"}
        self.status(names[mode])

    # -- file ops ----------------------------------------------------------

    def new_file(self):
        if not self._confirm_discard():
            return
        self.document.new_blank()
        self.current_page = 0
        self._after_document_changed()
        self.status("New blank document.")

    def open_file(self):
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open PDF", "", "PDF files (*.pdf)")
        if not path:
            return
        try:
            self.document.open(path)
        except Exception as e:
            QMessageBox.critical(self, "Could not open", str(e))
            return
        self.current_page = 0
        self._after_document_changed()
        self.status(f"Opened {os.path.basename(path)} — {self.document.page_count} pages")

    def save_file(self):
        if not self.document.is_open:
            return
        if not self.document.path:
            return self.save_file_as()
        try:
            self.document.save()
            self.status(f"Saved {os.path.basename(self.document.path)}")
            self._update_title()
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))

    def save_file_as(self):
        if not self.document.is_open:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save PDF As", self.document.path or "untitled.pdf",
                                              "PDF files (*.pdf)")
        if not path:
            return
        try:
            self.document.save(path)
            self.status(f"Saved {os.path.basename(path)}")
            self._update_title()
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))

    def export_copy(self):
        if not self.document.is_open:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export a Copy", "copy.pdf", "PDF files (*.pdf)")
        if not path:
            return
        try:
            self.document.doc.save(path, garbage=4, deflate=True, clean=True)
            self.status(f"Exported copy to {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))

    # -- rendering ---------------------------------------------------------

    def _after_document_changed(self):
        self._set_open_state(self.document.is_open)
        self.pages.refresh(self.document, self.current_page)
        self.render_current_page()
        self._update_title()

    def render_current_page(self):
        if not self.document.is_open:
            return
        self.current_page = max(0, min(self.current_page, self.document.page_count - 1))
        png = self.document.render_page_png(self.current_page, self.zoom)
        spans = self.document.spans_on_page(self.current_page)
        self.view.set_page(png, self.zoom, self.current_page, spans)
        self.page_label.setText(f"  {self.current_page + 1} / {self.document.page_count}  ")
        if not self.document.has_extractable_text(self.current_page):
            self.status("This page has no selectable text — use the OCR Region tool to edit it.")

    def _refresh_thumbnail(self, index: int):
        # Cheap: just rebuild the panel (page count is usually modest).
        self.pages.refresh(self.document, self.current_page)

    def goto_page(self, index: int):
        if index != self.current_page:
            self.current_page = index
            self.render_current_page()

    def prev_page(self):
        self.goto_page(max(0, self.current_page - 1))

    def next_page(self):
        self.goto_page(min(self.document.page_count - 1, self.current_page + 1))

    def _on_zoom_factor(self, factor: float):
        self.zoom = max(0.3, min(6.0, self.zoom * factor))
        self.render_current_page()

    # -- editing -----------------------------------------------------------

    def _on_span_activated(self, span: TextSpan):
        res = self.editor.resolve_font(span)
        self.font_status.setText("🅵 " + res.status_text)

    def _on_commit_edit(self, span: TextSpan, new_text: str):
        res = self.editor.resolve_font(span)
        force_substitute = False
        # Prompt only when the font is genuinely missing (not installed, not embedded).
        if not res.is_exact:
            dlg = FontPromptDialog(res, self)
            dlg.exec()
            if dlg.choice == "cancel":
                self.status("Edit cancelled.")
                self.render_current_page()
                return
            if dlg.choice == "install":
                self.status("Install the font, then click the text again to edit with it.")
                self.render_current_page()
                return
            force_substitute = True  # user chose to proceed with substitute

        result = self.editor.replace_span_text(span, new_text, res, force_substitute=force_substitute)
        self.status(result.message)
        self.render_current_page()
        self._refresh_thumbnail(span.page_index)
        self._update_title()

    def _on_add_text(self, x: float, y: float):
        dlg = AddTextDialog(fm.index().families(), self)
        if dlg.exec() != dlg.Accepted:
            return
        text, family, size = dlg.values()
        if not text.strip():
            return
        req = fm.parse_pdf_fontname(family)
        # y is the click point; nudge the baseline down by the font size.
        result = self.editor.add_text(self.current_page, (x, y + size), text, req, size=size)
        self.status(result.message)
        self.render_current_page()
        self._refresh_thumbnail(self.current_page)
        self._update_title()

    def _on_ocr_region(self, rect_pts: tuple):
        if not ocr_mod.tesseract_available():
            QMessageBox.warning(self, "OCR unavailable",
                                "Tesseract OCR isn't available. Install it to edit non-editable text.")
            return
        self.status("Running OCR…")
        QApplication.processEvents()
        try:
            spans = ocr_mod.ocr_line_spans(self.document, self.current_page, rect_pts)
        except Exception as e:
            QMessageBox.critical(self, "OCR failed", str(e))
            return
        if not spans:
            self.status("OCR found no text in that region.")
            return
        recognized = " ".join(s.text for s in spans)
        sizes = sorted(s.size for s in spans)
        median_size = sizes[len(sizes) // 2]

        dlg = OcrReviewDialog(recognized, self)
        if dlg.exec() != dlg.Accepted:
            return
        corrected = dlg.text().strip()

        # Build a synthetic span covering the whole region and replace it in place.
        x0, y0, x1, y1 = rect_pts
        baseline_y = y1 - (y1 - y0) * 0.18
        region_span = TextSpan(
            page_index=self.current_page, block=-1, line=-1, span=-1,
            text=recognized, bbox=rect_pts, origin=(x0, baseline_y),
            font_name="Helvetica", size=median_size, color=0, flags=0, font_xref=0,
        )
        res = self.editor.resolve_font(region_span)
        result = self.editor.replace_span_text(region_span, corrected, res)
        self.status("Replaced OCR'd text in place. " + result.message)
        self.render_current_page()
        self._refresh_thumbnail(self.current_page)
        self._update_title()

    # -- page organization -------------------------------------------------

    def _on_delete_pages(self, rows: list[int]):
        if not rows:
            return
        if self.document.page_count - len(rows) < 1:
            QMessageBox.warning(self, "Cannot delete", "A PDF must keep at least one page.")
            return
        if QMessageBox.question(self, "Delete pages",
                                f"Delete {len(rows)} page(s)?") != QMessageBox.Yes:
            return
        for i in sorted(rows, reverse=True):
            self.document.delete_page(i)
        self.current_page = min(self.current_page, self.document.page_count - 1)
        self._after_document_changed()
        self.status(f"Deleted {len(rows)} page(s).")

    def _on_split_off(self, rows: list[int]):
        if not rows:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Split selected pages into…", "split.pdf",
                                              "PDF files (*.pdf)")
        if not path:
            return
        self.document.split_off(rows, path)
        self.status(f"Wrote {len(rows)} page(s) to {os.path.basename(path)}")

    def _on_split_at(self, after_index: int):
        base = QFileDialog.getExistingDirectory(self, "Choose a folder for the two split files")
        if not base:
            return
        a = os.path.join(base, "part1.pdf")
        b = os.path.join(base, "part2.pdf")
        self.document.split_at(after_index, a, b)
        self.status(f"Split after page {after_index + 1} → part1.pdf, part2.pdf")

    def _on_rotate(self, rows: list[int], degrees: int):
        for i in rows:
            self.document.rotate_page(i, degrees)
        self._after_document_changed()
        self.status(f"Rotated {len(rows)} page(s) by {degrees}°.")

    def _on_reordered(self, src: int, dst: int):
        self.document.move_page(src, dst)
        self.current_page = dst
        self.pages.refresh(self.document, self.current_page)
        self.render_current_page()
        self.status(f"Moved page {src + 1} → position {dst + 1}.")

    # -- misc --------------------------------------------------------------

    def _update_title(self):
        name = os.path.basename(self.document.path) if self.document.path else "Untitled"
        dirty = "•" if self.document.dirty else ""
        self.setWindowTitle(f"{dirty}{name} — {__app_name__}")

    def _confirm_discard(self) -> bool:
        if self.document.is_open and self.document.dirty:
            r = QMessageBox.question(
                self, "Unsaved changes",
                "You have unsaved changes. Save before continuing?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if r == QMessageBox.Cancel:
                return False
            if r == QMessageBox.Save:
                self.save_file()
        return True

    def closeEvent(self, event):
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()

    def about(self):
        QMessageBox.about(
            self, "About " + __app_name__,
            f"<h3>{__app_name__} {__version__}</h3>"
            "<p>A desktop PDF editor with true in-place text editing, font detection, "
            "page organization, and OCR for scanned text.</p>"
            "<p>Built with PySide6 and PyMuPDF.</p>")
