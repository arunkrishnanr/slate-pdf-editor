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
    QInputDialog, QLineEdit, QTabWidget, QVBoxLayout, QSlider, QToolButton,
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
from .widgets import SwitchButton
from .dialogs import (
    FontPromptDialog, AddTextDialog, OcrReviewDialog, PageSizeDialog, HelpDialog,
    FindReplaceDialog, DocumentSetupDialog,
)

DEVELOPER = "Aaron Krrish"


class DocumentTab(QWidget):
    """One open PDF: owns its document, editor, page view, and per-document state.

    The main window keeps the toolbar/menus/docks global and proxies its handlers to
    whichever tab is current, so each PDF carries its own undo history, zoom, page, etc.
    """

    def __init__(self, main: "MainWindow"):
        super().__init__()
        self.document = PdfDocument()
        self.editor = TextEditor(self.document)
        self.view = PageView()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

        # Per-document state
        self.current_page = 0
        self.zoom = 1.5
        self.blocks: list = []
        self.sel_span = None
        self.sel_block = None
        self.undo_stack: list[bytes] = []
        self.redo_stack: list[bytes] = []
        self.find_hits: list = []
        self.find_idx = -1
        self.find_query = ""
        self.pending_image = None

        # Route this view's interactions to the main window's handlers.
        v = self.view
        v.commitEdit.connect(main._on_commit_edit)
        v.commitBlockEdit.connect(main._on_commit_block_edit)
        v.selected.connect(main._on_selection)
        v.spanActivated.connect(main._on_span_activated)
        v.addTextRequested.connect(main._on_add_text)
        v.textBoxCommit.connect(main._on_textbox_commit)
        v.ocrRegionRequested.connect(main._on_ocr_region)
        v.rectToolFinished.connect(main._on_rect_tool)
        v.pointToolClicked.connect(main._on_point_tool)
        v.inkFinished.connect(main._on_ink)
        v.zoomRequested.connect(main._on_zoom_factor)


class MainWindow(QMainWindow):
    def __init__(self, icon: Optional[QIcon] = None):
        super().__init__()
        self.setWindowTitle(__app_name__)
        if icon:
            self.setWindowIcon(icon)
        self.resize(1280, 860)

        self._para_detect = False      # off by default; toggle applies to all tabs
        self._table_detect = False     # table overlay/editor toggle, off by default
        self._view_only = True         # app starts read-only; Edit Mode switch turns it on
        self._UNDO_CAP = 25
        self._find_dialog: FindReplaceDialog | None = None
        self._null_doc = PdfDocument()  # stand-in when no tab is open

        # Central: one tab per open PDF
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.setElideMode(Qt.ElideRight)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.tabs.tabCloseRequested.connect(self._on_tab_close)
        self.setCentralWidget(self.tabs)

        # Pages dock
        self.pages = PagesPanel()
        dock = QDockWidget("Pages", self)
        dock.setWidget(self.pages)
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
                         | QDockWidget.DockWidgetClosable)
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
        pdock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
                          | QDockWidget.DockWidgetClosable)
        self.addDockWidget(Qt.RightDockWidgetArea, pdock)
        self.props_dock = pdock
        self.props.styleApplied.connect(self._on_style_applied)

        self._build_actions()
        self._build_toolbar()
        self._build_menu()
        self._build_zoom_bar()
        self.setStatusBar(QStatusBar())
        self._set_open_state(False)
        self.status("Open a PDF to begin — File ▸ Open  (⌘O)")

        # Point pytesseract at a bundled binary if present.
        self._configure_ocr()

    # -- tab proxying ------------------------------------------------------
    # Handlers were written against self.document / self.view / self.current_page etc.
    # These properties forward to whichever tab is current, so each PDF keeps its own
    # document, view, undo history and view state.

    def tab(self) -> Optional[DocumentTab]:
        w = self.tabs.currentWidget()
        return w if isinstance(w, DocumentTab) else None

    @property
    def document(self) -> PdfDocument:
        t = self.tab()
        return t.document if t else self._null_doc

    @property
    def editor(self) -> TextEditor:
        t = self.tab()
        return t.editor if t else TextEditor(self._null_doc)

    @property
    def view(self) -> PageView:
        return self.tab().view  # only called when a tab exists

    def _tab_attr(self, name, default=None):
        t = self.tab()
        return getattr(t, name) if t else default

    def _set_tab_attr(self, name, value):
        t = self.tab()
        if t:
            setattr(t, name, value)

    # current_page / zoom / blocks / selection / find / image / undo proxies
    current_page = property(lambda s: s._tab_attr("current_page", 0),
                            lambda s, v: s._set_tab_attr("current_page", v))
    zoom = property(lambda s: s._tab_attr("zoom", 1.5),
                    lambda s, v: s._set_tab_attr("zoom", v))
    _blocks = property(lambda s: s._tab_attr("blocks", []),
                       lambda s, v: s._set_tab_attr("blocks", v))
    _sel_span = property(lambda s: s._tab_attr("sel_span"),
                         lambda s, v: s._set_tab_attr("sel_span", v))
    _sel_block = property(lambda s: s._tab_attr("sel_block"),
                          lambda s, v: s._set_tab_attr("sel_block", v))
    _undo_stack = property(lambda s: s._tab_attr("undo_stack", []))
    _redo_stack = property(lambda s: s._tab_attr("redo_stack", []))
    _find_hits = property(lambda s: s._tab_attr("find_hits", []),
                          lambda s, v: s._set_tab_attr("find_hits", v))
    _find_idx = property(lambda s: s._tab_attr("find_idx", -1),
                         lambda s, v: s._set_tab_attr("find_idx", v))
    _find_query = property(lambda s: s._tab_attr("find_query", ""),
                           lambda s, v: s._set_tab_attr("find_query", v))
    _pending_image = property(lambda s: s._tab_attr("pending_image"),
                              lambda s, v: s._set_tab_attr("pending_image", v))

    # -- tab management ----------------------------------------------------

    def _new_tab(self) -> DocumentTab:
        t = DocumentTab(self)
        t.view.set_paragraph_detection(self._para_detect)
        if self._view_only:
            t.view.set_mode(Mode.VIEW)
        idx = self.tabs.addTab(t, "Untitled")
        self.tabs.setCurrentIndex(idx)
        return t

    def _tab_title(self, t: DocumentTab) -> str:
        name = os.path.basename(t.document.path) if t.document.path else "Untitled"
        return ("• " if t.document.dirty else "") + name

    def _refresh_tab_title(self):
        t = self.tab()
        if t:
            self.tabs.setTabText(self.tabs.currentIndex(), self._tab_title(t))

    def _on_tab_changed(self, index: int):
        if self.tab() is None:
            # No documents left — clear every view so nothing stale lingers.
            self._set_open_state(False)
            self.pages.refresh(self._null_doc, 0)   # clear the thumbnails
            self.props.show_selection(None)
            self.font_status.setText("")
            self.page_label.setText("  —  ")
            self.status("No document open — File ▸ Open  (⌘O)")
            self.setWindowTitle(__app_name__)
            return
        self._set_open_state(True)
        self.pages.refresh(self.document, self.current_page)
        self.render_current_page()
        self._update_undo_actions()
        self._update_title()
        self._sync_zoom_ui()
        # Keep the canvas mode and toolbar tool-checkmarks consistent on the new tab.
        self.set_mode(Mode.VIEW if self._view_only else Mode.SELECT)

    def _on_tab_close(self, index: int):
        t = self.tabs.widget(index)
        if isinstance(t, DocumentTab) and t.document.is_open and t.document.dirty:
            self.tabs.setCurrentIndex(index)
            r = QMessageBox.question(
                self, "Unsaved changes",
                f"Save changes to {self._tab_title(t).lstrip('• ')} before closing?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if r == QMessageBox.Cancel:
                return
            if r == QMessageBox.Save and not self.save_file():
                return  # save failed — keep the tab open so work isn't lost
        if isinstance(t, DocumentTab):
            t.document.close()
        self.tabs.removeTab(index)
        t.deleteLater()

    # -- UI construction ---------------------------------------------------

    def _build_actions(self):
        self.act_open = QAction("Open…", self, shortcut=QKeySequence.Open, triggered=self.open_file)
        self.act_new = QAction("New", self, shortcut=QKeySequence.New, triggered=self.new_file)
        self.act_close = QAction("Close Document", self, shortcut=QKeySequence.Close,
                                 triggered=self.close_current_document)
        self.act_save = QAction("Save", self, shortcut=QKeySequence.Save, triggered=self.save_file)
        self.act_save_as = QAction("Save As…", self, shortcut=QKeySequence.SaveAs, triggered=self.save_file_as)
        self.act_export = QAction("Export Copy…", self, triggered=self.export_copy)
        self.act_doc_setup = QAction("Document Setup…", self, triggered=self.document_setup)
        self.act_print = QAction("Print…", self, shortcut=QKeySequence.Print, triggered=self.print_document)
        self.act_print_preview = QAction("Print Preview…", self, triggered=self.print_preview)
        self.act_quit = QAction("Quit", self, shortcut=QKeySequence.Quit, triggered=self.close)

        self.act_undo = QAction("Undo", self, shortcut=QKeySequence.Undo, triggered=self.undo)
        self.act_redo = QAction("Redo", self, shortcut=QKeySequence.Redo, triggered=self.redo)
        self.act_undo.setEnabled(False)
        self.act_redo.setEnabled(False)
        self.act_find = QAction("Find & Replace…", self, shortcut=QKeySequence.Find, triggered=self.show_find)

        self.act_para_detect = QAction("Paragraph Detection", self, checkable=True)
        self.act_para_detect.setChecked(False)
        self.act_para_detect.toggled.connect(self._toggle_paragraph_detection)

        self.act_table_detect = QAction("Table Detection", self, checkable=True)
        self.act_table_detect.setChecked(False)
        self.act_table_detect.toggled.connect(self._toggle_table_detection)

        # Edit ⇄ View-only swap (checked = Edit mode); app starts in view-only
        self.act_edit_mode = QAction("Edit Mode", self, checkable=True)
        self.act_edit_mode.setChecked(False)
        self.act_edit_mode.toggled.connect(self._toggle_edit_mode)

        # Interactive table editing (shown only while Table Detection is on)
        self.act_table_add_row = QAction("＋ Row", self, triggered=self._table_add_row)
        self.act_table_add_col = QAction("＋ Column", self, triggered=self._table_add_col)
        self.act_table_apply = QAction("Apply Table", self, triggered=self._table_apply)
        for a in (self.act_table_add_row, self.act_table_add_col, self.act_table_apply):
            a.setVisible(False)

        # Acrobat-style "Recognize Text" — make a scanned page searchable/selectable
        self.act_recognize_page = QAction("Recognize Text — This Page", self, triggered=lambda: self.recognize_text(False))
        self.act_recognize_all = QAction("Recognize Text — All Pages", self, triggered=lambda: self.recognize_text(True))

        self.act_mode_select = QAction("Select", self, checkable=True, triggered=lambda: self.set_mode(Mode.SELECT))
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
        self.act_zoom_in = QAction("Zoom In", self, shortcut=QKeySequence.ZoomIn, triggered=lambda: self._on_zoom_factor(1.15))
        self.act_zoom_out = QAction("Zoom Out", self, shortcut=QKeySequence.ZoomOut, triggered=lambda: self._on_zoom_factor(1/1.15))
        self.act_fit_window = QAction("Fit to Window", self, triggered=self.zoom_fit_window)

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
        # Edit/View as a labelled switch (off = view-only, the app's start state)
        self.sw_edit = SwitchButton("Edit Mode", checked=False)
        self.sw_edit.toggled.connect(self._toggle_edit_mode)
        tb.addWidget(self.sw_edit)
        tb.addSeparator()
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
        # Detection + panel switches
        self.sw_para = SwitchButton("Paragraphs", checked=False)
        self.sw_para.toggled.connect(self._toggle_paragraph_detection)
        tb.addWidget(self.sw_para)
        self.sw_table = SwitchButton("Tables", checked=False)
        self.sw_table.toggled.connect(self._toggle_table_detection)
        tb.addWidget(self.sw_table)
        tb.addAction(self.act_table_add_row)
        tb.addAction(self.act_table_add_col)
        tb.addAction(self.act_table_apply)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        self.font_status = QLabel("")
        self.font_status.setStyleSheet("color: #cfd3da; padding-right: 8px;")
        tb.addWidget(self.font_status)

    ZOOM_PRESETS = [25, 50, 75, 100, 125, 150, 175, 200]

    def _build_zoom_bar(self):
        """A bottom bar with: − [slider] +  and a Fit/percentage selector."""
        bar = QToolBar("Zoom")
        bar.setMovable(False)
        self.addToolBar(Qt.BottomToolBarArea, bar)

        self.btn_zoom_minus = QToolButton()
        self.btn_zoom_minus.setText("−")
        self.btn_zoom_minus.setToolTip("Zoom out")
        self.btn_zoom_minus.clicked.connect(lambda: self._on_zoom_factor(1 / 1.15))
        bar.addWidget(self.btn_zoom_minus)

        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(25, 300)      # 25% .. 300%
        self.zoom_slider.setValue(150)
        self.zoom_slider.setFixedWidth(220)
        self.zoom_slider.valueChanged.connect(self._on_zoom_slider)
        bar.addWidget(self.zoom_slider)

        self.btn_zoom_plus = QToolButton()
        self.btn_zoom_plus.setText("+")
        self.btn_zoom_plus.setToolTip("Zoom in")
        self.btn_zoom_plus.clicked.connect(lambda: self._on_zoom_factor(1.15))
        bar.addWidget(self.btn_zoom_plus)

        self.zoom_combo = QComboBox()
        self.zoom_combo.setEditable(True)
        self.zoom_combo.setInsertPolicy(QComboBox.NoInsert)
        self.zoom_combo.setFixedWidth(130)
        self.zoom_combo.addItem("Fit to Window", "fit")
        for p in self.ZOOM_PRESETS:
            self.zoom_combo.addItem(f"{p}%", p)
        self.zoom_combo.setCurrentText("150%")
        self.zoom_combo.activated.connect(self._on_zoom_combo)
        self.zoom_combo.lineEdit().editingFinished.connect(self._on_zoom_typed)
        bar.addWidget(self.zoom_combo)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(spacer)
        self.mode_status = QLabel("View Only")
        self.mode_status.setStyleSheet("color: #ff8431; padding-right: 10px; font-weight: 600;")
        bar.addWidget(self.mode_status)
        self._zoom_bar = bar

    def _build_menu(self):
        bar = self.menuBar()
        m_file = bar.addMenu("File")
        for a in (self.act_new, self.act_open, self.act_save, self.act_save_as, self.act_export):
            m_file.addAction(a)
        m_file.addSeparator()
        m_file.addAction(self.act_close)
        m_file.addSeparator()
        m_file.addAction(self.act_doc_setup)
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
        m_tools.addAction(self.act_edit_mode)
        m_tools.addSeparator()
        for a in (self.act_mode_add, self.act_mode_box, self.act_mode_ocr):
            m_tools.addAction(a)
        m_tools.addSeparator()
        m_ocr = m_tools.addMenu("Recognize Text (OCR)")
        m_ocr.addAction(self.act_recognize_page)
        m_ocr.addAction(self.act_recognize_all)
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

        m_view = bar.addMenu("View")
        m_view.addAction(self.act_edit_mode)
        m_view.addSeparator()
        for a in (self.act_zoom_in, self.act_zoom_out, self.act_fit_window):
            m_view.addAction(a)
        m_view.addSeparator()
        m_view.addAction(self.act_para_detect)
        m_view.addAction(self.act_table_detect)
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
        for a in (self.act_save, self.act_save_as, self.act_export, self.act_doc_setup,
                  self.act_close,
                  self.act_print, self.act_print_preview, self.act_find,
                  self.act_mode_select, self.act_mode_add, self.act_mode_box, self.act_mode_ocr,
                  self.act_page_size, self.act_crop, self.act_edit_mode,
                  self.act_para_detect, self.act_table_detect,
                  self.act_insert_image, self.act_insert_pdf, self.act_insert_blank,
                  self.act_duplicate_page,
                  self.act_mk_highlight, self.act_mk_underline, self.act_mk_strike,
                  self.act_mk_note, self.act_mk_rect, self.act_mk_line, self.act_mk_ink,
                  self.act_redact,
                  self.act_export_images, self.act_export_text,
                  self.act_encrypt, self.act_remove_pw,
                  self.act_recognize_page, self.act_recognize_all,
                  self.act_table_add_row, self.act_table_add_col, self.act_table_apply,
                  self.act_prev, self.act_next, self.act_zoom_in, self.act_zoom_out,
                  self.act_fit_window):
            a.setEnabled(is_open)
        # In View-Only mode, keep editing tools disabled even with a document open.
        if is_open and self._view_only:
            for a in self._editing_actions():
                a.setEnabled(False)

    def status(self, msg: str, timeout: int = 0):
        self.statusBar().showMessage(msg, timeout)

    def set_mode(self, mode: Mode):
        if self.tab() is None:
            return
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
        self._new_tab()
        self.document.new_blank()
        self.current_page = 0
        self._after_document_changed()
        self.status("New blank document.")

    def open_file(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Open PDF(s)", "", "PDF files (*.pdf)")
        for path in paths:
            self.open_path(path)

    def close_current_document(self):
        """Close the current tab (same as its ✕), honoring unsaved-changes prompts."""
        if self.tabs.count() > 0:
            self._on_tab_close(self.tabs.currentIndex())

    def open_path(self, path: str):
        """Open one PDF in a new tab (skips if already open: focuses that tab)."""
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, DocumentTab) and w.document.path == path:
                self.tabs.setCurrentIndex(i)
                return
        t = self._new_tab()
        try:
            t.document.open(path)
        except Exception as e:
            self._discard_tab(t)
            QMessageBox.critical(self, "Could not open", str(e))
            return
        if t.document.needs_password and not self._prompt_password():
            self._discard_tab(t)
            self.status("Open cancelled — password required.")
            return
        self.current_page = 0
        self._after_document_changed()
        self.status(f"Opened {os.path.basename(path)} — {self.document.page_count} pages")

    def _discard_tab(self, t: DocumentTab):
        idx = self.tabs.indexOf(t)
        if idx >= 0:
            self.tabs.removeTab(idx)
        t.document.close()
        t.deleteLater()

    def save_file(self) -> bool:
        """Returns True on success, False on failure/cancel (so callers can abort)."""
        if not self.document.is_open:
            return False
        if not self.document.path:
            return self.save_file_as()
        try:
            self.document.save()
            self.status(f"Saved {os.path.basename(self.document.path)}")
            self._update_title()
            return True
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))
            return False

    def save_file_as(self) -> bool:
        if not self.document.is_open:
            return False
        path, _ = QFileDialog.getSaveFileName(self, "Save PDF As", self.document.path or "untitled.pdf",
                                              "PDF files (*.pdf)")
        if not path:
            return False
        try:
            self.document.save(path)
            self.status(f"Saved {os.path.basename(path)}")
            self._update_title()
            return True
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))
            return False

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
        # Cached find hits reference pre-edit page rects/indices; drop them so a later
        # Find Next never points at stale coordinates or a deleted page.
        self._find_query = ""
        self._find_hits = []
        self._find_idx = -1
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
        notes = self.document.note_annotations(self.current_page)
        grids = self.document.detect_table_grids(self.current_page) if self._table_detect else []
        self.view.set_overlays(notes, grids)
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

    def _set_zoom(self, zoom: float, sync: bool = True):
        if self.tab() is None:
            return
        self.zoom = max(0.25, min(3.0, zoom))
        self.render_current_page()
        if sync:
            self._sync_zoom_ui()

    def _on_zoom_factor(self, factor: float):
        self._set_zoom(self.zoom * factor)

    def _on_zoom_slider(self, value: int):
        self._set_zoom(value / 100.0, sync=False)
        self._update_zoom_text()

    def _on_zoom_combo(self, index: int):
        data = self.zoom_combo.itemData(index)
        if data == "fit":
            self.zoom_fit_window()
        elif data is not None:
            self._set_zoom(int(data) / 100.0)

    def _on_zoom_typed(self):
        txt = self.zoom_combo.currentText().strip().rstrip("%")
        try:
            self._set_zoom(float(txt) / 100.0)
        except ValueError:
            self._sync_zoom_ui()

    def zoom_fit_window(self):
        if self.tab() is None:
            return
        w, h = self.document.page_size(self.current_page)
        vp = self.view.viewport().size()
        if w <= 0 or h <= 0:
            return
        z = min((vp.width() - 24) / w, (vp.height() - 24) / h)
        self._set_zoom(z, sync=False)
        self._sync_zoom_ui(fit=True)

    def _sync_zoom_ui(self, fit: bool = False):
        pct = int(round(self.zoom * 100))
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(max(25, min(300, pct)))
        self.zoom_slider.blockSignals(False)
        self.zoom_combo.blockSignals(True)
        self.zoom_combo.lineEdit().blockSignals(True)
        self.zoom_combo.setCurrentText("Fit to Window" if fit else f"{pct}%")
        self.zoom_combo.lineEdit().blockSignals(False)
        self.zoom_combo.blockSignals(False)

    def _update_zoom_text(self):
        pct = int(round(self.zoom * 100))
        self.zoom_combo.blockSignals(True)
        self.zoom_combo.lineEdit().blockSignals(True)
        self.zoom_combo.setCurrentText(f"{pct}%")
        self.zoom_combo.lineEdit().blockSignals(False)
        self.zoom_combo.blockSignals(False)

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
        try:
            result = self.editor.replace_span_text(span, new_text, res, force_substitute=force_substitute)
        except Exception as e:
            if self._undo_stack:
                self._undo_stack.pop()
            self._update_undo_actions()
            QMessageBox.warning(self, "Edit failed", str(e))
            self.render_current_page()
            return
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

    def document_setup(self):
        if not self.document.is_open:
            return
        meta = self.document.get_metadata()
        w, h = self.document.page_size(self.current_page)
        current = ps.nearest_standard(w, h)
        dlg = DocumentSetupDialog(meta, current, self.document.page_count, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._snapshot()
        self.document.set_metadata(dlg.metadata())
        pr = dlg.page_resize()
        if pr:
            width, height, apply_all, scale = pr
            indices = list(range(self.document.page_count)) if apply_all else [self.current_page]
            self.document.set_page_size(indices, width, height, scale)
        self._after_document_changed()
        self.status("Document setup applied." + (" Pages resized." if pr else ""))

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

    def _on_textbox_commit(self, rect_pts, text, size):
        """A live text box was typed on the canvas — place it as a wrapping text box."""
        if not text.strip():
            return
        self._snapshot()
        req = fm.parse_pdf_fontname("Helvetica")
        result = self.editor.add_text_box(self.current_page, rect_pts, text, req, size=size)
        self.status(result.message)
        self.render_current_page()
        self._refresh_thumbnail(self.current_page)
        self._update_title()

    def _on_ocr_region(self, rect_pts: tuple):
        self.status("Running OCR…")
        QApplication.processEvents()
        try:
            words, engine = ocr_mod.recognize_region(self.document, self.current_page, rect_pts)
        except Exception as e:
            from .preflight import tesseract_install_hint
            QMessageBox.warning(
                self, "OCR unavailable",
                f"Couldn't read this region.\n\n{e}\n\n"
                f"Cloud OCR needs internet; the offline engine (Tesseract) can be installed from:\n"
                f"{tesseract_install_hint()}")
            return
        if not words:
            self.status("OCR found no text in that region.")
            return
        recognized = " ".join(w.text for w in words)
        sizes = sorted(w.est_size for w in words)
        median_size = sizes[len(sizes) // 2] if sizes else 12.0

        dlg = OcrReviewDialog(recognized, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        corrected = dlg.text().strip()

        # Remove the original scanned text + reconstruct the background, then place the
        # corrected text in the same spot.
        self._snapshot()
        result = self.editor.replace_region_inpaint(
            self.current_page, rect_pts, corrected, size=median_size, color=(0, 0, 0))
        self.status(f"OCR via {engine}. {result.message}")
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
        t = self.tab()
        if t is None:
            self.setWindowTitle(__app_name__)
            return
        name = os.path.basename(t.document.path) if t.document.path else "Untitled"
        dirty = "•" if t.document.dirty else ""
        self.setWindowTitle(f"{dirty}{name} — {__app_name__}")
        self._refresh_tab_title()

    def closeEvent(self, event):
        """On quit, offer to save every tab with unsaved changes."""
        for i in range(self.tabs.count()):
            t = self.tabs.widget(i)
            if isinstance(t, DocumentTab) and t.document.is_open and t.document.dirty:
                self.tabs.setCurrentIndex(i)
                r = QMessageBox.question(
                    self, "Unsaved changes",
                    f"Save changes to {self._tab_title(t).lstrip('• ')} before quitting?",
                    QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
                if r == QMessageBox.Cancel:
                    event.ignore()
                    return
                if r == QMessageBox.Save and not self.save_file():
                    event.ignore()   # save failed — don't lose the work by quitting
                    return
        event.accept()

    # -- printing ----------------------------------------------------------

    def print_document(self):
        if not self.document.is_open:
            return
        printer = QPrinter(QPrinter.HighResolution)
        printer.setDocName(os.path.basename(self.document.path or "document.pdf"))
        printer.setFromTo(1, self.document.page_count)
        dlg = QPrintDialog(printer, self)
        dlg.setWindowTitle("Print")
        if dlg.exec() != QDialog.DialogCode.Accepted:
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
        if mode == M.IMAGE and not self._pending_image:
            return  # nothing to place; don't leave a junk undo snapshot
        self._snapshot()
        try:
            if mode == M.IMAGE:
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
        if not query or self.tab() is None:
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

    def _sync_toggle(self, switch, action, on):
        """Keep a toolbar switch and its menu action in sync without re-firing handlers."""
        if switch is not None:
            switch.blockSignals(True); switch.setChecked(on); switch.blockSignals(False)
        if action is not None:
            action.blockSignals(True); action.setChecked(on); action.blockSignals(False)

    def _toggle_paragraph_detection(self, on: bool):
        self._para_detect = on
        self._sync_toggle(self.sw_para, self.act_para_detect, on)
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, DocumentTab):
                w.view.set_paragraph_detection(on)
        if self.tab() is not None:
            self.render_current_page()
        self.status(f"Paragraph detection {'on' if on else 'off'} — "
                    f"{'paragraphs edit as a block' if on else 'every click edits a single line'}.")

    def _toggle_table_detection(self, on: bool):
        self._table_detect = on
        self._sync_toggle(self.sw_table, self.act_table_detect, on)
        self.act_table_add_row.setVisible(on)
        self.act_table_add_col.setVisible(on)
        self.act_table_apply.setVisible(on)
        if self.tab() is not None:
            self.render_current_page()
        self.status("Table detection on — drag dividers to resize; use Add Row/Column, then Apply."
                    if on else "Table detection off.")

    # -- interactive table editing -----------------------------------------

    def _table_add_row(self):
        if self.tab() is None:
            return
        self.view.add_table_row()
        self.status("Row divider added — drag it to position, then Apply.")

    def _table_add_col(self):
        if self.tab() is None:
            return
        self.view.add_table_col()
        self.status("Column divider added — drag it to position, then Apply.")

    def _table_apply(self):
        if self.tab() is None:
            return
        grids = self.view.table_grids()
        if not grids:
            self.status("No table to apply. Turn on Tables over a page with a table.")
            return
        self._snapshot()
        self.document.draw_table_grids(self.current_page, grids)
        self.render_current_page()
        self._refresh_thumbnail(self.current_page)
        self._update_title()
        self.status("Table gridlines applied to the page.")

    # -- Acrobat-style Recognize Text (searchable layer) -------------------

    def recognize_text(self, all_pages: bool):
        if self.tab() is None:
            return
        pages = range(self.document.page_count) if all_pages else [self.current_page]
        self.status("Recognizing text…")
        QApplication.processEvents()
        self._snapshot()
        total = 0
        engine_used = ""
        try:
            for i in pages:
                n, engine_used = self.editor.recognize_text_searchable(i)
                total += n
        except Exception as e:
            if self._undo_stack:
                self._undo_stack.pop()
            self._update_undo_actions()
            from .preflight import tesseract_install_hint
            QMessageBox.warning(self, "OCR unavailable",
                                f"Couldn't recognize text.\n\n{e}\n\nOffline engine: {tesseract_install_hint()}")
            return
        self.render_current_page()
        self._update_title()
        scope = "all pages" if all_pages else f"page {self.current_page + 1}"
        self.status(f"Recognized {total} words on {scope} via {engine_used}. "
                    f"Text is now selectable & searchable.")

    def _editing_actions(self):
        return [
            self.act_mode_add, self.act_mode_box, self.act_mode_ocr, self.act_crop,
            self.act_page_size, self.act_undo, self.act_redo,
            self.act_insert_image, self.act_insert_pdf, self.act_insert_blank, self.act_duplicate_page,
            self.act_mk_highlight, self.act_mk_underline, self.act_mk_strike, self.act_mk_note,
            self.act_mk_rect, self.act_mk_line, self.act_mk_ink, self.act_redact,
        ]

    def _toggle_edit_mode(self, on: bool):
        self._view_only = not on
        self._sync_toggle(self.sw_edit, self.act_edit_mode, on)
        self.mode_status.setText("Edit Mode" if on else "View Only")
        for a in self._editing_actions():
            a.setEnabled(on and self.document.is_open)
        if on:
            self._update_undo_actions()
        if self.tab() is not None:
            if on:
                self.set_mode(Mode.SELECT)
            else:
                self.view.set_mode(Mode.VIEW)
        self.status("Edit mode — full editing enabled." if on
                    else "View Only — read-only; turn on Edit Mode to make changes.")

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
