"""The main application window — wires the document, page view, and panels together."""

from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QKeySequence, QIcon, QImage, QPainter
from PySide6.QtPrintSupport import QPrinter, QPrintDialog, QPrintPreviewDialog
from PySide6.QtWidgets import (
    QMainWindow, QFileDialog, QMessageBox, QDockWidget, QToolBar, QLabel,
    QStatusBar, QApplication, QComboBox, QWidget, QSizePolicy, QDialog,
    QInputDialog, QLineEdit,
)

from . import __app_name__, __version__
from . import font_manager as fm
from . import ocr as ocr_mod
from . import structure as struct
from . import page_sizes as ps
from .pdf_document import PdfDocument, TextSpan, _int_to_rgb
from .text_editor import TextEditor, EditResult
from .canvas import PageView, Mode
from .pages_panel import PagesPanel
from .properties_panel import PropertiesPanel, Selection
from .dialogs import (
    FontPromptDialog, AddTextDialog, OcrReviewDialog, PageSizeDialog, HelpDialog,
    FindReplaceDialog,
)

DEVELOPER = "Aaron Krrish"


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
        self._blocks: list = []
        self._sel_span: TextSpan | None = None
        self._sel_block = None
        self._para_detect = True
        self._undo_stack: list[bytes] = []
        self._redo_stack: list[bytes] = []
        self._UNDO_CAP = 25
        self._find_dialog: FindReplaceDialog | None = None
        self._find_hits: list = []
        self._find_idx = -1
        self._find_query = ""

        # Central page view
        self.view = PageView()
        self.setCentralWidget(self.view)
        self.view.commitEdit.connect(self._on_commit_edit)
        self.view.commitBlockEdit.connect(self._on_commit_block_edit)
        self.view.selected.connect(self._on_selection)
        self.view.spanActivated.connect(self._on_span_activated)
        self.view.addTextRequested.connect(self._on_add_text)
        self.view.textBoxRequested.connect(self._on_text_box)
        self.view.ocrRegionRequested.connect(self._on_ocr_region)
        self.view.rectToolFinished.connect(self._on_rect_tool)
        self.view.pointToolClicked.connect(self._on_point_tool)
        self.view.inkFinished.connect(self._on_ink)
        self.view.zoomRequested.connect(self._on_zoom_factor)
        self._pending_image: str | None = None

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

        # Properties dock (right): manual font selection + structure type
        self.props = PropertiesPanel()
        pdock = QDockWidget("Properties", self)
        pdock.setWidget(self.props)
        pdock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        self.addDockWidget(Qt.RightDockWidgetArea, pdock)
        self.props_dock = pdock
        self.props.styleApplied.connect(self._on_style_applied)

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
        self.act_print = QAction("Print…", self, shortcut=QKeySequence.Print, triggered=self.print_document)
        self.act_print_preview = QAction("Print Preview…", self, triggered=self.print_preview)
        self.act_quit = QAction("Quit", self, shortcut=QKeySequence.Quit, triggered=self.close)

        self.act_undo = QAction("Undo", self, shortcut=QKeySequence.Undo, triggered=self.undo)
        self.act_redo = QAction("Redo", self, shortcut=QKeySequence.Redo, triggered=self.redo)
        self.act_undo.setEnabled(False)
        self.act_redo.setEnabled(False)
        self.act_find = QAction("Find & Replace…", self, shortcut=QKeySequence.Find, triggered=self.show_find)

        self.act_para_detect = QAction("Paragraph Detection", self, checkable=True)
        self.act_para_detect.setChecked(True)
        self.act_para_detect.toggled.connect(self._toggle_paragraph_detection)

        self.act_mode_select = QAction("Edit Text", self, checkable=True, triggered=lambda: self.set_mode(Mode.SELECT))
        self.act_mode_add = QAction("Add Text", self, checkable=True, triggered=lambda: self.set_mode(Mode.ADD_TEXT))
        self.act_mode_box = QAction("Text Box", self, checkable=True, triggered=lambda: self.set_mode(Mode.TEXT_BOX))
        self.act_mode_ocr = QAction("OCR Region", self, checkable=True, triggered=lambda: self.set_mode(Mode.OCR_REGION))
        self.act_mode_select.setChecked(True)

        self.act_page_size = QAction("Page Size…", self, triggered=self.change_page_size)
        self.act_crop = QAction("Crop Page", self, checkable=True, triggered=lambda: self.set_mode(Mode.CROP))

        # Insert
        self.act_insert_image = QAction("Image…", self, triggered=self.insert_image)
        self.act_insert_pdf = QAction("Pages from PDF…", self, triggered=self.insert_pdf_pages)
        self.act_insert_blank = QAction("Blank Page", self, triggered=self.insert_blank_page)
        self.act_duplicate_page = QAction("Duplicate Current Page", self, triggered=self.duplicate_page)

        # Markup tools (checkable, share the tool-mode group)
        self.act_mk_highlight = QAction("Highlight", self, checkable=True, triggered=lambda: self.set_mode(Mode.HIGHLIGHT))
        self.act_mk_underline = QAction("Underline", self, checkable=True, triggered=lambda: self.set_mode(Mode.UNDERLINE))
        self.act_mk_strike = QAction("Strikethrough", self, checkable=True, triggered=lambda: self.set_mode(Mode.STRIKE))
        self.act_mk_note = QAction("Sticky Note", self, checkable=True, triggered=lambda: self.set_mode(Mode.NOTE))
        self.act_mk_rect = QAction("Rectangle", self, checkable=True, triggered=lambda: self.set_mode(Mode.SHAPE_RECT))
        self.act_mk_line = QAction("Line", self, checkable=True, triggered=lambda: self.set_mode(Mode.SHAPE_LINE))
        self.act_mk_ink = QAction("Freehand", self, checkable=True, triggered=lambda: self.set_mode(Mode.INK))
        self.act_redact = QAction("Redact (black out)", self, checkable=True, triggered=lambda: self.set_mode(Mode.REDACT))

        # Export & security
        self.act_export_images = QAction("Export Pages as Images…", self, triggered=self.export_images)
        self.act_export_text = QAction("Export Text…", self, triggered=self.export_text)
        self.act_encrypt = QAction("Set Password…", self, triggered=self.set_password)
        self.act_remove_pw = QAction("Remove Password / Restrictions…", self, triggered=self.remove_password)

        self.act_prev = QAction("◀", self, triggered=self.prev_page)
        self.act_next = QAction("▶", self, triggered=self.next_page)
        self.act_zoom_in = QAction("Zoom +", self, shortcut=QKeySequence.ZoomIn, triggered=lambda: self._on_zoom_factor(1.15))
        self.act_zoom_out = QAction("Zoom −", self, shortcut=QKeySequence.ZoomOut, triggered=lambda: self._on_zoom_factor(1/1.15))

        self.act_user_guide = QAction("User Guide", self, shortcut=QKeySequence.HelpContents,
                                      triggered=self.show_help)
        self.act_user_guide.setMenuRole(QAction.MenuRole.ApplicationSpecificRole)
        self.act_about = QAction("About Slate PDF Editor", self, triggered=self.about)
        self.act_about.setMenuRole(QAction.MenuRole.AboutRole)  # -> app menu on macOS
        self.act_about_dev = QAction("About the Developer", self, triggered=self.about_developer)
        # Keep the developer credit in the Help menu (don't let macOS merge it with About).
        self.act_about_dev.setMenuRole(QAction.MenuRole.ApplicationSpecificRole)

    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setIconSize(QSize(18, 18))
        tb.setMovable(False)
        self.addToolBar(tb)
        tb.addAction(self.act_open)
        tb.addAction(self.act_save)
        tb.addSeparator()
        tb.addAction(self.act_undo)
        tb.addAction(self.act_redo)
        tb.addAction(self.act_find)
        tb.addSeparator()
        tb.addAction(self.act_mode_select)
        tb.addAction(self.act_mode_add)
        tb.addAction(self.act_mode_box)
        tb.addAction(self.act_mode_ocr)
        tb.addSeparator()
        tb.addAction(self.act_page_size)
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
        m_export = m_file.addMenu("Export")
        m_export.addAction(self.act_export_images)
        m_export.addAction(self.act_export_text)
        m_security = m_file.addMenu("Security")
        m_security.addAction(self.act_encrypt)
        m_security.addAction(self.act_remove_pw)
        m_file.addSeparator()
        m_file.addAction(self.act_print)
        m_file.addAction(self.act_print_preview)
        m_file.addSeparator()
        m_file.addAction(self.act_quit)

        m_edit = bar.addMenu("Edit")
        m_edit.addAction(self.act_undo)
        m_edit.addAction(self.act_redo)
        m_edit.addSeparator()
        m_edit.addAction(self.act_find)

        m_tools = bar.addMenu("Tools")
        for a in (self.act_mode_select, self.act_mode_add, self.act_mode_box, self.act_mode_ocr):
            m_tools.addAction(a)
        m_tools.addSeparator()
        m_tools.addAction(self.act_crop)

        m_insert = bar.addMenu("Insert")
        for a in (self.act_insert_image, self.act_insert_pdf, self.act_insert_blank,
                  self.act_duplicate_page):
            m_insert.addAction(a)

        m_markup = bar.addMenu("Markup")
        for a in (self.act_mk_highlight, self.act_mk_underline, self.act_mk_strike,
                  self.act_mk_note, self.act_mk_rect, self.act_mk_line, self.act_mk_ink):
            m_markup.addAction(a)
        m_markup.addSeparator()
        m_markup.addAction(self.act_redact)

        m_page = bar.addMenu("Page")
        m_page.addAction(self.act_page_size)

        m_view = bar.addMenu("View")
        for a in (self.act_zoom_in, self.act_zoom_out, self.act_prev, self.act_next):
            m_view.addAction(a)
        m_view.addSeparator()
        m_view.addAction(self.act_para_detect)
        m_view.addSeparator()
        m_view.addAction(self.pages_dock.toggleViewAction())
        m_view.addAction(self.props_dock.toggleViewAction())

        m_help = bar.addMenu("Help")
        m_help.addAction(self.act_user_guide)
        m_help.addSeparator()
        m_help.addAction(self.act_about)
        m_help.addAction(self.act_about_dev)

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
                  self.act_print, self.act_print_preview, self.act_find,
                  self.act_mode_select, self.act_mode_add, self.act_mode_box, self.act_mode_ocr,
                  self.act_page_size, self.act_crop,
                  self.act_insert_image, self.act_insert_pdf, self.act_insert_blank,
                  self.act_duplicate_page,
                  self.act_mk_highlight, self.act_mk_underline, self.act_mk_strike,
                  self.act_mk_note, self.act_mk_rect, self.act_mk_line, self.act_mk_ink,
                  self.act_redact,
                  self.act_export_images, self.act_export_text,
                  self.act_encrypt, self.act_remove_pw,
                  self.act_prev, self.act_next, self.act_zoom_in, self.act_zoom_out):
            a.setEnabled(is_open)

    def status(self, msg: str, timeout: int = 0):
        self.statusBar().showMessage(msg, timeout)

    def set_mode(self, mode: Mode):
        self.view.set_mode(mode)
        mode_actions = {
            Mode.SELECT: self.act_mode_select, Mode.ADD_TEXT: self.act_mode_add,
            Mode.TEXT_BOX: self.act_mode_box, Mode.OCR_REGION: self.act_mode_ocr,
            Mode.CROP: self.act_crop, Mode.HIGHLIGHT: self.act_mk_highlight,
            Mode.UNDERLINE: self.act_mk_underline, Mode.STRIKE: self.act_mk_strike,
            Mode.NOTE: self.act_mk_note, Mode.SHAPE_RECT: self.act_mk_rect,
            Mode.SHAPE_LINE: self.act_mk_line, Mode.INK: self.act_mk_ink,
            Mode.REDACT: self.act_redact,
        }
        for m, act in mode_actions.items():
            act.setChecked(m == mode)
        names = {
            Mode.SELECT: "Edit Text — click a line, or a paragraph to reflow it",
            Mode.ADD_TEXT: "Add Text — click where you want new text",
            Mode.TEXT_BOX: "Text Box — drag a box, then type wrapping text",
            Mode.OCR_REGION: "OCR Region — drag a box over non-editable text",
            Mode.IMAGE: "Insert Image — drag a box to place the image",
            Mode.REDACT: "Redact — drag over content to permanently black it out",
            Mode.CROP: "Crop — drag the area to keep",
            Mode.HIGHLIGHT: "Highlight — drag over text",
            Mode.UNDERLINE: "Underline — drag over text",
            Mode.STRIKE: "Strikethrough — drag over text",
            Mode.NOTE: "Sticky Note — click to place a note",
            Mode.SHAPE_RECT: "Rectangle — drag to draw",
            Mode.SHAPE_LINE: "Line — drag to draw",
            Mode.INK: "Freehand — drag to draw",
        }
        self.status(names.get(mode, ""))

    # -- file ops ----------------------------------------------------------

    def new_file(self):
        if not self._confirm_discard():
            return
        self.document.new_blank()
        self.current_page = 0
        self._reset_history()
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
        if self.document.needs_password and not self._prompt_password():
            self.document.close()
            self.status("Open cancelled — password required.")
            self._after_document_changed()
            return
        self.current_page = 0
        self._reset_history()
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

    def _reset_history(self):
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._find_query = ""
        self._find_hits = []
        self._find_idx = -1
        self._update_undo_actions()

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
        self._blocks = struct.analyze_page(self.document, self.current_page) if self._para_detect else []
        self.view.set_page(png, self.zoom, self.current_page, spans, self._blocks)
        self.props.show_selection(None)
        self._sel_span = self._sel_block = None
        w, h = self.document.page_size(self.current_page)
        std = ps.nearest_standard(w, h)
        size_txt = f" · {std}" if std else f" · {w/ps.MM:.0f}×{h/ps.MM:.0f}mm"
        self.page_label.setText(f"  {self.current_page + 1} / {self.document.page_count}{size_txt}  ")
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

    def _on_span_activated(self, obj):
        # obj may be a TextSpan or a Block; both expose font_name + flags.
        req = fm.parse_pdf_fontname(getattr(obj, "font_name", "Helvetica"),
                                    getattr(obj, "flags", 0))
        res = fm.resolve(req)
        self.font_status.setText("🅵 " + res.status_text)

    def _on_selection(self, span, block):
        """Populate the Properties panel from whatever was clicked."""
        self._sel_span = span
        self._sel_block = block
        source = span if span is not None else block
        if source is None:
            self.props.show_selection(None)
            return
        req = fm.parse_pdf_fontname(source.font_name, source.flags)
        installed = fm.index().find(req)
        family = installed.family if installed else req.family
        is_para = block is not None and getattr(block, "line_count", 1) >= 2
        structure = block.type.value if block is not None else "Line"
        align = getattr(block, "align", 0) if block is not None else 0
        color = source.color_rgb if span is not None else _int_to_rgb(source.color)
        self.props.show_selection(Selection(
            family=family, size=source.size, bold=req.bold, italic=req.italic,
            color=color, structure=structure, is_paragraph=is_para, align=align,
        ))

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

        self._snapshot()
        result = self.editor.replace_span_text(span, new_text, res, force_substitute=force_substitute)
        self.status(result.message)
        self.render_current_page()
        self._refresh_thumbnail(span.page_index)
        self._update_title()

    def _on_add_text(self, x: float, y: float):
        dlg = AddTextDialog(fm.index().families(), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        text, family, size = dlg.values()
        if not text.strip():
            return
        req = fm.parse_pdf_fontname(family)
        # y is the click point; nudge the baseline down by the font size.
        self._snapshot()
        result = self.editor.add_text(self.current_page, (x, y + size), text, req, size=size)
        self.status(result.message)
        self.render_current_page()
        self._refresh_thumbnail(self.current_page)
        self._update_title()

    def _on_commit_block_edit(self, block, new_text: str):
        """A whole paragraph was edited — reflow it within its area."""
        req = fm.parse_pdf_fontname(block.font_name, block.flags)
        res = fm.resolve(req)
        force_substitute = False
        if not res.is_exact:
            dlg = FontPromptDialog(res, self)
            dlg.exec()
            if dlg.choice == "cancel":
                self.render_current_page()
                return
            if dlg.choice == "install":
                self.status("Install the font, then click the paragraph again to edit it.")
                self.render_current_page()
                return
            force_substitute = True
        if force_substitute and res.substitute:
            res = fm.FontResolution(res.request, None, res.substitute, None)
        self._snapshot()
        result = self.editor.replace_block_text(
            block, new_text, res, size=block.size, color=_int_to_rgb(block.color), align=block.align)
        self.status(result.message)
        self.render_current_page()
        self._refresh_thumbnail(block.page_index)
        self._update_title()

    def _on_text_box(self, rect_pts: tuple):
        dlg = AddTextDialog(fm.index().families(), self)
        dlg.setWindowTitle("Text box")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        text, family, size = dlg.values()
        if not text.strip():
            return
        req = fm.parse_pdf_fontname(family)
        self._snapshot()
        result = self.editor.add_text_box(self.current_page, rect_pts, text, req, size=size)
        self.status(result.message)
        self.render_current_page()
        self._refresh_thumbnail(self.current_page)
        self._update_title()

    def _on_style_applied(self, family, size, bold, italic, color, whole_paragraph, align):
        """Properties-panel Apply: restyle the current selection with a chosen font."""
        req = fm.FontRequest(family, family, bold, italic)
        res = fm.resolve(req)
        if whole_paragraph and self._sel_block is not None:
            self._snapshot()
            result = self.editor.replace_block_text(
                self._sel_block, self._sel_block.text, res, size=size, color=color, align=align)
        elif self._sel_span is not None:
            self._snapshot()
            span = self._sel_span
            result = self.editor.replace_span_text(
                span, span.text, res, size_override=size, color_override=color)
        else:
            self.status("Click some text first, then Apply.")
            return
        self.status("Applied: " + result.message)
        self.render_current_page()
        self._refresh_thumbnail(self.current_page)
        self._update_title()

    def change_page_size(self):
        if not self.document.is_open:
            return
        w, h = self.document.page_size(self.current_page)
        current = ps.nearest_standard(w, h)
        dlg = PageSizeDialog(current, self.document.page_count, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        width, height, apply_all, scale = dlg.result_values()
        indices = list(range(self.document.page_count)) if apply_all else [self.current_page]
        self._snapshot()
        self.document.set_page_size(indices, width, height, scale)
        self._after_document_changed()
        scope = f"all {len(indices)} pages" if apply_all else f"page {self.current_page + 1}"
        mode = "scaled content" if scale else "kept content"
        self.status(f"Resized {scope} to {width/ps.MM:.0f}×{height/ps.MM:.0f} mm ({mode}).")

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
        if dlg.exec() != QDialog.DialogCode.Accepted:
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
        self._snapshot()
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
        self._snapshot()
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
        self._snapshot()
        for i in rows:
            self.document.rotate_page(i, degrees)
        self._after_document_changed()
        self.status(f"Rotated {len(rows)} page(s) by {degrees}°.")

    def _on_reordered(self, src: int, dst: int):
        self._snapshot()
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

    # -- printing ----------------------------------------------------------

    def print_document(self):
        if not self.document.is_open:
            return
        printer = QPrinter(QPrinter.HighResolution)
        printer.setDocName(os.path.basename(self.document.path or "document.pdf"))
        printer.setFromTo(1, self.document.page_count)
        dlg = QPrintDialog(printer, self)
        dlg.setWindowTitle("Print")
        if dlg.exec() != QDialog.Accepted:
            return
        self.status("Printing…")
        QApplication.processEvents()
        self._render_to_printer(printer)
        self.status("Sent to printer.")

    def print_preview(self):
        if not self.document.is_open:
            return
        printer = QPrinter(QPrinter.HighResolution)
        printer.setDocName(os.path.basename(self.document.path or "document.pdf"))
        dlg = QPrintPreviewDialog(printer, self)
        dlg.paintRequested.connect(self._render_to_printer)
        dlg.exec()

    def _render_to_printer(self, printer: QPrinter):
        """Paint each page onto the printer, scaled to the sheet and centred."""
        painter = QPainter(printer)
        try:
            first = max(1, printer.fromPage() or 1)
            last = printer.toPage() or self.document.page_count
            last = min(last, self.document.page_count)
            # Render around 150 dpi for crisp output without huge memory use.
            dpi = min(printer.resolution(), 150)
            zoom = dpi / 72.0
            for n, i in enumerate(range(first - 1, last)):
                if n > 0:
                    printer.newPage()
                img = QImage.fromData(self.document.render_page_png(i, zoom), "PNG")
                page_rect = painter.viewport()
                size = img.size()
                size.scale(page_rect.size(), Qt.KeepAspectRatio)
                x = page_rect.x() + (page_rect.width() - size.width()) // 2
                y = page_rect.y() + (page_rect.height() - size.height()) // 2
                painter.setViewport(x, y, size.width(), size.height())
                painter.setWindow(img.rect())
                painter.drawImage(0, 0, img)
        finally:
            painter.end()

    # -- markup / images / redaction tools ---------------------------------

    def _on_rect_tool(self, mode, rect):
        from .canvas import Mode as M
        self._snapshot()
        try:
            if mode == M.IMAGE:
                if not self._pending_image:
                    return
                self.document.insert_image(self.current_page, rect, self._pending_image)
                self._pending_image = None
                self.set_mode(M.SELECT)
                self.status("Image inserted.")
            elif mode == M.REDACT:
                self.document.redact(self.current_page, rect, fill=(0, 0, 0))
                self.status("Redacted — content permanently removed.")
            elif mode == M.CROP:
                self.document.crop_page(self.current_page, rect)
                self.status("Page cropped.")
            elif mode in (M.HIGHLIGHT, M.UNDERLINE, M.STRIKE):
                kind = {M.HIGHLIGHT: "highlight", M.UNDERLINE: "underline", M.STRIKE: "strikeout"}[mode]
                self.document.annotate_text_markup(self.current_page, rect, kind)
                self.status(f"{kind.capitalize()} added.")
            elif mode in (M.SHAPE_RECT, M.SHAPE_LINE):
                kind = "rect" if mode == M.SHAPE_RECT else "line"
                self.document.add_shape(self.current_page, rect, kind)
                self.status(f"{kind.capitalize()} drawn.")
        except Exception as e:
            if self._undo_stack:
                self._undo_stack.pop()  # the operation failed; drop its snapshot
            self._update_undo_actions()
            QMessageBox.warning(self, "Action failed", str(e))
            return
        self.render_current_page()
        self._refresh_thumbnail(self.current_page)
        self._update_title()

    def _on_point_tool(self, mode, x, y):
        from .canvas import Mode as M
        if mode == M.NOTE:
            text, ok = QInputDialog.getMultiLineText(self, "Sticky note", "Note text:")
            if not ok or not text.strip():
                return
            self._snapshot()
            self.document.add_note(self.current_page, (x, y), text)
            self.render_current_page()
            self._refresh_thumbnail(self.current_page)
            self.status("Note added.")

    def _on_ink(self, points):
        self._snapshot()
        self.document.add_ink(self.current_page, points)
        self.render_current_page()
        self._refresh_thumbnail(self.current_page)
        self.status("Freehand drawing added.")

    # -- insert / duplicate ------------------------------------------------

    def insert_image(self):
        if not self.document.is_open:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Choose an image", "",
                                              "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tiff)")
        if not path:
            return
        self._pending_image = path
        self.set_mode(Mode.IMAGE)

    def insert_pdf_pages(self):
        if not self.document.is_open:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Insert pages from PDF", "", "PDF files (*.pdf)")
        if not path:
            return
        self._snapshot()
        try:
            n = self.document.insert_pdf(path, self.current_page)
        except Exception as e:
            QMessageBox.critical(self, "Insert failed", str(e))
            return
        self._after_document_changed()
        self.status(f"Inserted {n} page(s) after page {self.current_page + 1}.")

    def insert_blank_page(self):
        if not self.document.is_open:
            return
        w, h = self.document.page_size(self.current_page)
        self._snapshot()
        self.document.insert_blank_page(self.current_page, w, h)
        self.current_page += 1
        self._after_document_changed()
        self.status("Blank page inserted.")

    def duplicate_page(self):
        if not self.document.is_open:
            return
        self._snapshot()
        self.document.duplicate_page(self.current_page)
        self._after_document_changed()
        self.status("Page duplicated.")

    # -- export ------------------------------------------------------------

    def export_images(self):
        if not self.document.is_open:
            return
        folder = QFileDialog.getExistingDirectory(self, "Export pages as PNG images to…")
        if not folder:
            return
        n = self.document.export_images(folder, dpi=150)
        self.status(f"Exported {n} page image(s) to {os.path.basename(folder)}.")

    def export_text(self):
        if not self.document.is_open:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export text", "document.txt", "Text (*.txt)")
        if not path:
            return
        self.document.export_text(path)
        self.status(f"Exported text to {os.path.basename(path)}.")

    # -- password / security ----------------------------------------------

    def set_password(self):
        if not self.document.is_open:
            return
        pw, ok = QInputDialog.getText(self, "Set password",
                                      "Open password (leave blank to cancel):",
                                      QLineEdit.Password)
        if not ok or not pw:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save encrypted PDF as",
                                              self.document.path or "protected.pdf", "PDF files (*.pdf)")
        if not path:
            return
        try:
            self.document.save_encrypted(path, user_pw=pw, owner_pw=pw)
            self.status(f"Saved password-protected copy: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "Encryption failed", str(e))

    def _prompt_password(self) -> bool:
        """Prompt for the open password (up to 3 tries). Returns True if authenticated."""
        for _ in range(3):
            pw, ok = QInputDialog.getText(self, "Password required",
                                          "This PDF is protected. Enter its password:",
                                          QLineEdit.Password)
            if not ok:
                return False
            if self.document.authenticate(pw):
                return True
            QMessageBox.warning(self, "Wrong password", "That password didn't work. Try again.")
        return False

    def remove_password(self):
        """Remove encryption/owner-restrictions. Requires the document to already be open
        (i.e. you provided the password on open, or it was owner-restricted only)."""
        if not self.document.is_open:
            return
        if not self.document.is_encrypted:
            QMessageBox.information(self, "Not protected", "This PDF has no password or restrictions.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save unprotected copy as",
                                              "unprotected.pdf", "PDF files (*.pdf)")
        if not path:
            return
        try:
            self.document.save_decrypted(path)
            self.status(f"Saved unprotected copy: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "Failed", str(e))

    # -- undo / redo -------------------------------------------------------

    def _snapshot(self):
        """Record the document state before a mutation, for undo."""
        try:
            self._undo_stack.append(self.document.snapshot())
            if len(self._undo_stack) > self._UNDO_CAP:
                self._undo_stack.pop(0)
            self._redo_stack.clear()
        except Exception:
            pass
        self._update_undo_actions()

    def _update_undo_actions(self):
        self.act_undo.setEnabled(bool(self._undo_stack))
        self.act_redo.setEnabled(bool(self._redo_stack))

    def undo(self):
        if not self._undo_stack:
            return
        try:
            self._redo_stack.append(self.document.snapshot())
            self.document.restore(self._undo_stack.pop())
        except Exception as e:
            self.status(f"Undo failed: {e}")
            return
        self._after_document_changed()
        self._update_undo_actions()
        self.status("Undid last change.")

    def redo(self):
        if not self._redo_stack:
            return
        try:
            self._undo_stack.append(self.document.snapshot())
            self.document.restore(self._redo_stack.pop())
        except Exception as e:
            self.status(f"Redo failed: {e}")
            return
        self._after_document_changed()
        self._update_undo_actions()
        self.status("Redid change.")

    # -- find & replace ----------------------------------------------------

    def show_find(self):
        if not self.document.is_open:
            return
        if self._find_dialog is None:
            self._find_dialog = FindReplaceDialog(self)
            self._find_dialog.findNext.connect(self._on_find_next)
            self._find_dialog.replaceAll.connect(self._on_replace_all)
        self._find_dialog.show()
        self._find_dialog.raise_()
        self._find_dialog.activateWindow()

    def _on_find_next(self, query: str, match_case: bool):
        if not query:
            return
        # Recompute hits if the query changed.
        if query != self._find_query:
            self._find_query = query
            self._find_hits = self.document.search(query)
            self._find_idx = -1
        if not self._find_hits:
            if self._find_dialog:
                self._find_dialog.set_status("No matches.")
            return
        self._find_idx = (self._find_idx + 1) % len(self._find_hits)
        page_index, rect = self._find_hits[self._find_idx]
        if page_index != self.current_page:
            self.current_page = page_index
            self.render_current_page()
        self.view.show_search_highlight((rect.x0, rect.y0, rect.x1, rect.y1))
        self.view.centerOn(rect.x0 * self.zoom, rect.y0 * self.zoom)
        if self._find_dialog:
            self._find_dialog.set_status(f"Match {self._find_idx + 1} of {len(self._find_hits)} "
                                         f"(page {page_index + 1})")

    def _on_replace_all(self, query: str, replacement: str, match_case: bool):
        if not query:
            return
        self._snapshot()
        count = self.editor.replace_all(query, replacement, match_case)
        self._find_query = ""  # force re-search next Find
        self.render_current_page()
        self.pages.refresh(self.document, self.current_page)
        self._update_title()
        msg = f"Replaced {count} occurrence(s)."
        self.status(msg)
        if self._find_dialog:
            self._find_dialog.set_status(msg)

    def _toggle_paragraph_detection(self, on: bool):
        self._para_detect = on
        self.view.set_paragraph_detection(on)
        self.render_current_page()
        self.status(f"Paragraph detection {'on' if on else 'off'} — "
                    f"{'paragraphs edit as a block' if on else 'every click edits a single line'}.")

    # -- help / about ------------------------------------------------------

    def show_help(self):
        HelpDialog(self).exec()

    def about(self):
        QMessageBox.about(
            self, "About " + __app_name__,
            f"<h3>{__app_name__} {__version__}</h3>"
            "<p>A desktop PDF editor with true in-place text editing, structure recognition, "
            "font detection &amp; selection, page organization, international page sizes, "
            "and OCR for scanned text.</p>"
            "<p>Built with PySide6 and PyMuPDF.</p>"
            f"<p>Developed by: <b>{DEVELOPER}</b></p>")

    def about_developer(self):
        QMessageBox.about(
            self, "About the Developer",
            f"<h3>Developed by: {DEVELOPER}</h3>"
            f"<p>{__app_name__} {__version__}</p>")
