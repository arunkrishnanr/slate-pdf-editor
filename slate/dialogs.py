"""Small dialogs: font resolution prompt, add-text, and OCR review."""

from __future__ import annotations

import os
import platform
import subprocess
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QDialogButtonBox, QSpinBox, QComboBox, QPlainTextEdit, QFormLayout,
    QRadioButton, QButtonGroup, QCheckBox, QTextBrowser, QGroupBox,
)

from . import font_manager as fm
from . import page_sizes as ps


class FontPromptDialog(QDialog):
    """Shown when a span's exact font isn't installed (and isn't embedded).

    Lets the user install the real font and retry, or accept a substitute.
    Returns one of: 'substitute', 'install', 'cancel'.
    """

    def __init__(self, resolution: fm.FontResolution, parent=None):
        super().__init__(parent)
        self.resolution = resolution
        self.choice = "cancel"
        self.setWindowTitle("Font not installed")
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        req = resolution.request
        msg = QLabel(
            f"<b>{req.display}</b> is used by this text but is <b>not installed</b> "
            f"on this computer."
        )
        msg.setWordWrap(True)
        layout.addWidget(msg)

        if resolution.substitute:
            sub = QLabel(
                f"You can install <b>{req.family}</b> and edit with the exact font, "
                f"or continue with the closest available match, "
                f"<b>{resolution.substitute.family}</b>."
            )
        else:
            sub = QLabel("No close substitute was found; a built-in font will be used.")
        sub.setWordWrap(True)
        layout.addWidget(sub)

        row = QHBoxLayout()
        btn_install = QPushButton("Install the font…")
        btn_sub = QPushButton(
            f"Use “{resolution.substitute.family}”" if resolution.substitute else "Use fallback"
        )
        btn_cancel = QPushButton("Cancel")
        btn_sub.setDefault(True)
        row.addWidget(btn_install)
        row.addStretch(1)
        row.addWidget(btn_cancel)
        row.addWidget(btn_sub)
        layout.addLayout(row)

        btn_install.clicked.connect(self._on_install)
        btn_sub.clicked.connect(lambda: self._finish("substitute"))
        btn_cancel.clicked.connect(lambda: self._finish("cancel"))

    def _on_install(self):
        _open_font_installer()
        self._finish("install")

    def _finish(self, choice: str):
        self.choice = choice
        self.accept()


def _open_font_installer():
    """Open the OS facility where the user installs fonts."""
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.Popen(["open", "-a", "Font Book"])
        elif system == "Windows":
            subprocess.Popen(["control", "fonts"], shell=True)
        else:
            user_fonts = os.path.expanduser("~/.fonts")
            os.makedirs(user_fonts, exist_ok=True)
            subprocess.Popen(["xdg-open", user_fonts])
    except Exception:
        pass


class AddTextDialog(QDialog):
    def __init__(self, families: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add text")
        self.setMinimumWidth(360)
        form = QFormLayout(self)

        self.text_edit = QLineEdit()
        self.text_edit.setPlaceholderText("Text to insert")
        form.addRow("Text", self.text_edit)

        self.font_combo = QComboBox()
        self.font_combo.setEditable(True)
        self.font_combo.addItems(families or ["Helvetica"])
        idx = self.font_combo.findText("Helvetica")
        if idx >= 0:
            self.font_combo.setCurrentIndex(idx)
        form.addRow("Font", self.font_combo)

        self.size_spin = QSpinBox()
        self.size_spin.setRange(4, 400)
        self.size_spin.setValue(12)
        form.addRow("Size", self.size_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self):
        return (
            self.text_edit.text(),
            self.font_combo.currentText().strip() or "Helvetica",
            self.size_spin.value(),
        )


class OcrReviewDialog(QDialog):
    """Show OCR-recognized text for a region and let the user correct it before
    it replaces the original (non-editable) content in place."""

    def __init__(self, recognized: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit recognized text (OCR)")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "This region wasn't editable, so it was read with OCR. Correct the text below; "
            "the original will be removed and replaced in the same place."
        ))
        self.edit = QPlainTextEdit()
        self.edit.setPlainText(recognized)
        layout.addWidget(self.edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def text(self) -> str:
        return self.edit.toPlainText()


class PageSizeDialog(QDialog):
    """Choose a standard page size (or custom), orientation, scope and resize behaviour."""

    def __init__(self, current_label: str | None, page_count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Page size")
        self.setMinimumWidth(420)
        form = QFormLayout(self)

        # Two-level picker: Category -> Size (keeps each list short).
        self.cat_combo = QComboBox()
        for group_name, _names in ps.PAGE_SIZE_GROUPS:
            self.cat_combo.addItem(group_name)
        self.cat_combo.addItem("Custom")
        self.cat_combo.currentIndexChanged.connect(self._on_category_changed)
        form.addRow("Category", self.cat_combo)

        self.size_combo = QComboBox()
        form.addRow("Size", self.size_combo)

        # Preselect the category + size that matches the current page, if known.
        start_cat = 0
        if current_label:
            for gi, (_g, names) in enumerate(ps.PAGE_SIZE_GROUPS):
                if current_label in names:
                    start_cat = gi
                    break
        self.cat_combo.setCurrentIndex(start_cat)
        self._on_category_changed(start_cat)
        if current_label:
            j = self.size_combo.findData(current_label)
            if j >= 0:
                self.size_combo.setCurrentIndex(j)

        # Custom dimensions (mm)
        custom_row = QHBoxLayout()
        self.cw = QSpinBox(); self.cw.setRange(10, 5000); self.cw.setValue(210); self.cw.setSuffix(" mm")
        self.ch = QSpinBox(); self.ch.setRange(10, 5000); self.ch.setValue(297); self.ch.setSuffix(" mm")
        custom_row.addWidget(QLabel("W")); custom_row.addWidget(self.cw)
        custom_row.addWidget(QLabel("H")); custom_row.addWidget(self.ch)
        form.addRow("Custom size", custom_row)
        self._on_category_changed(self.cat_combo.currentIndex())  # now that cw/ch exist

        # Orientation
        orient_row = QHBoxLayout()
        self.portrait = QRadioButton("Portrait")
        self.landscape = QRadioButton("Landscape")
        self.portrait.setChecked(True)
        og = QButtonGroup(self); og.addButton(self.portrait); og.addButton(self.landscape)
        orient_row.addWidget(self.portrait); orient_row.addWidget(self.landscape); orient_row.addStretch(1)
        form.addRow("Orientation", orient_row)

        # Scope
        scope_row = QHBoxLayout()
        self.scope_current = QRadioButton("This page")
        self.scope_all = QRadioButton(f"All {page_count} pages")
        self.scope_current.setChecked(True)
        sg = QButtonGroup(self); sg.addButton(self.scope_current); sg.addButton(self.scope_all)
        scope_row.addWidget(self.scope_current); scope_row.addWidget(self.scope_all); scope_row.addStretch(1)
        form.addRow("Apply to", scope_row)

        # Content behaviour (offered every time, per the chosen design)
        behav_row = QVBoxLayout()
        self.scale_content = QRadioButton("Scale content to fit the new size")
        self.keep_content = QRadioButton("Keep content as-is (change page dimensions only)")
        self.scale_content.setChecked(True)
        bg = QButtonGroup(self); bg.addButton(self.scale_content); bg.addButton(self.keep_content)
        behav_row.addWidget(self.scale_content)
        behav_row.addWidget(self.keep_content)
        note = QLabel("Both keep text fully editable afterwards.")
        note.setStyleSheet("color: #9aa0a8; font-size: 11px;")
        behav_row.addWidget(note)
        form.addRow("Content", behav_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _on_category_changed(self, idx: int):
        is_custom = self.cat_combo.currentText() == "Custom"
        self.size_combo.blockSignals(True)
        self.size_combo.clear()
        if not is_custom and 0 <= idx < len(ps.PAGE_SIZE_GROUPS):
            for n in ps.PAGE_SIZE_GROUPS[idx][1]:
                self.size_combo.addItem(ps.size_label(n), n)
        self.size_combo.blockSignals(False)
        self.size_combo.setEnabled(not is_custom)
        if hasattr(self, "cw"):
            self.cw.setEnabled(is_custom)
            self.ch.setEnabled(is_custom)

    def result_values(self):
        """Return (width_pt, height_pt, apply_all, scale_content)."""
        if self.cat_combo.currentText() == "Custom":
            w = self.cw.value() * ps.MM
            h = self.ch.value() * ps.MM
        else:
            data = self.size_combo.currentData()
            w, h = ps.PAGE_SIZES[data]
        if self.landscape.isChecked():
            w, h = max(w, h), min(w, h)
        else:
            w, h = min(w, h), max(w, h)
        return w, h, self.scope_all.isChecked(), self.scale_content.isChecked()


HELP_HTML = """
<h2>Tirut PDF — User Guide</h2>
<p>Tirut PDF edits the <b>real content</b> of a PDF (original glyphs are removed and replaced),
not a layer stamped on top.</p>

<h3>Opening &amp; saving</h3>
<ul>
<li><b>File ▸ Open</b> (⌘/Ctrl+O) — open a PDF. <b>Save</b> (⌘/Ctrl+S), <b>Save As</b>,
or <b>Export Copy</b>.</li>
<li><b>File ▸ Print</b> (⌘/Ctrl+P) — print, or use <b>Print Preview</b> first.</li>
</ul>

<h3>Edit Mode vs View Only</h3>
<ul>
<li>Tirut PDF opens in <b>View Only</b> (read-only). Flip the <b>Edit Mode</b> switch in the
toolbar to make changes. Other switches: <b>Paragraphs</b>, <b>Tables</b>, <b>Properties</b>
(show/hide the panel).</li>
</ul>

<h3>Recognize Text (OCR) — make a scan searchable</h3>
<ul>
<li><b>Tools ▸ Recognize Text</b> reads a scanned page with cloud AI OCR (Tesseract
offline fallback) and adds an <b>invisible, selectable/searchable</b> text layer over the
image — the page looks identical but you can now select, copy and search the text
(Adobe-style "Searchable Image").</li>
</ul>

<h3>Tables</h3>
<ul>
<li>Turn on the <b>Tables</b> switch to detect and outline tables. Drag the row/column
<b>dividers</b> to resize, use <b>＋ Row</b> / <b>＋ Column</b> to add lines, then
<b>Apply Table</b> to draw the gridlines onto the page.</li>
</ul>

<h3>Editing text</h3>
<ul>
<li>With <b>Edit Mode</b> on: click a line to edit it inline — press <b>Enter</b> to commit,
<b>Esc</b> to cancel.</li>
<li>Click a <b>paragraph</b> and the whole paragraph opens; it re-wraps within its area.
Press <b>Ctrl/⌘+Enter</b> to commit, <b>Esc</b> to cancel.</li>
<li>The <b>Properties</b> panel (right) shows the detected structure (Title / Heading /
Paragraph / Line) and the font. Change <b>font, size, bold/italic, colour, alignment</b>
and click <b>Apply</b> — to the line or the whole paragraph.</li>
</ul>

<h3>Fonts</h3>
<ul>
<li>Tirut PDF detects the font of the text you click. If it isn't installed, you're asked to
<b>install</b> it (opens Font Book / Windows Fonts) or to use the closest <b>substitute</b>.</li>
<li>Pick any installed font manually from the Properties panel.</li>
</ul>

<h3>Adding text</h3>
<ul>
<li><b>Add Text</b>: click where you want new text.</li>
<li><b>Text Box</b>: drag a box, then type wrapping multi-line text.</li>
</ul>

<h3>Scanned / non-editable text (OCR)</h3>
<ul>
<li><b>OCR Region</b>: drag a box over text that isn't selectable. Tirut PDF reads it with
Tesseract, lets you correct it, then removes the original and places your text in the
same spot.</li>
</ul>

<h3>Markup &amp; redaction (Markup menu)</h3>
<ul>
<li><b>Highlight / Underline / Strikethrough</b>: drag over text.</li>
<li><b>Sticky Note</b>: click to drop a note; <b>Rectangle / Line / Freehand</b>: drag to draw.</li>
<li><b>Redact</b>: drag over content to <b>permanently remove</b> it (black-out).</li>
</ul>

<h3>Insert (Insert menu)</h3>
<ul>
<li><b>Image</b>: pick a file, then drag a box to place it.</li>
<li><b>Pages from PDF</b>: merge another PDF in after the current page.
<b>Blank Page</b>, <b>Duplicate Current Page</b>.</li>
</ul>

<h3>Undo, find, crop</h3>
<ul>
<li><b>Edit ▸ Undo / Redo</b> (⌘/Ctrl+Z, ⇧⌘/Ctrl+Y) covers every change.</li>
<li><b>Edit ▸ Find &amp; Replace</b> (⌘/Ctrl+F): search, navigate matches, replace all.</li>
<li><b>Tools ▸ Crop Page</b>: drag the area to keep.</li>
<li><b>View ▸ Paragraph Detection</b>: toggle whole-paragraph editing on/off.</li>
</ul>

<h3>Export &amp; security (File menu)</h3>
<ul>
<li><b>Export ▸ Pages as Images / Text</b>.</li>
<li><b>Security ▸ Set Password</b> (encrypt a copy); <b>Remove Password / Restrictions</b>
(on a document you've opened). Protected files prompt for the password on open.</li>
</ul>

<h3>Organize pages</h3>
<ul>
<li>Left panel: drag thumbnails to reorder; <b>Delete</b>, <b>Rotate</b>,
<b>Split off</b> selected pages to a new PDF, or split the document in two
(right-click a thumbnail).</li>
</ul>

<h3>Page size</h3>
<ul>
<li><b>Page ▸ Page Size</b>: choose a <b>Category</b> (ISO A/B/C, JIS B, US, ANSI, ARCH)
then a <b>Size</b>, or set a custom size. Apply to this page or all pages, portrait or
landscape. Choose <b>scale-to-fit</b> or <b>keep-canvas</b> — both keep text editable.</li>
</ul>

<h3>View</h3>
<ul>
<li>Zoom with the toolbar or <b>Ctrl/⌘ + mouse wheel</b>. Navigate pages with ◀ ▶.</li>
</ul>
"""


class DocumentSetupDialog(QDialog):
    """File ▸ Document Setup — document properties (metadata) plus optional page setup."""

    def __init__(self, metadata: dict, current_label: str | None, page_count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Document Setup")
        self.setMinimumWidth(480)
        root = QVBoxLayout(self)

        # --- Document properties (metadata) ---
        props = QGroupBox("Document Properties")
        pf = QFormLayout(props)
        self.title_edit = QLineEdit(metadata.get("title", ""))
        self.author_edit = QLineEdit(metadata.get("author", ""))
        self.subject_edit = QLineEdit(metadata.get("subject", ""))
        self.keywords_edit = QLineEdit(metadata.get("keywords", ""))
        pf.addRow("Title", self.title_edit)
        pf.addRow("Author", self.author_edit)
        pf.addRow("Subject", self.subject_edit)
        pf.addRow("Keywords", self.keywords_edit)
        root.addWidget(props)

        # --- Page setup (only applied if the group is checked) ---
        self.page_group = QGroupBox("Resize pages")
        self.page_group.setCheckable(True)
        self.page_group.setChecked(False)
        gf = QFormLayout(self.page_group)

        self.cat_combo = QComboBox()
        for gname, _names in ps.PAGE_SIZE_GROUPS:
            self.cat_combo.addItem(gname)
        self.cat_combo.addItem("Custom")
        gf.addRow("Category", self.cat_combo)

        self.size_combo = QComboBox()
        gf.addRow("Size", self.size_combo)

        crow = QHBoxLayout()
        self.cw = QSpinBox(); self.cw.setRange(10, 5000); self.cw.setValue(210); self.cw.setSuffix(" mm")
        self.ch = QSpinBox(); self.ch.setRange(10, 5000); self.ch.setValue(297); self.ch.setSuffix(" mm")
        crow.addWidget(QLabel("W")); crow.addWidget(self.cw)
        crow.addWidget(QLabel("H")); crow.addWidget(self.ch)
        gf.addRow("Custom size", crow)

        orow = QHBoxLayout()
        self.portrait = QRadioButton("Portrait"); self.landscape = QRadioButton("Landscape")
        self.portrait.setChecked(True)
        og = QButtonGroup(self); og.addButton(self.portrait); og.addButton(self.landscape)
        orow.addWidget(self.portrait); orow.addWidget(self.landscape); orow.addStretch(1)
        gf.addRow("Orientation", orow)

        srow = QHBoxLayout()
        self.scope_current = QRadioButton("This page"); self.scope_all = QRadioButton(f"All {page_count} pages")
        self.scope_current.setChecked(True)
        sg = QButtonGroup(self); sg.addButton(self.scope_current); sg.addButton(self.scope_all)
        srow.addWidget(self.scope_current); srow.addWidget(self.scope_all); srow.addStretch(1)
        gf.addRow("Apply to", srow)

        cvrow = QVBoxLayout()
        self.scale_content = QRadioButton("Scale content to fit the new size")
        self.keep_content = QRadioButton("Keep content as-is (change dimensions only)")
        self.scale_content.setChecked(True)
        bg = QButtonGroup(self); bg.addButton(self.scale_content); bg.addButton(self.keep_content)
        cvrow.addWidget(self.scale_content); cvrow.addWidget(self.keep_content)
        gf.addRow("Content", cvrow)
        root.addWidget(self.page_group)

        self.cat_combo.currentIndexChanged.connect(self._on_cat)
        start = 0
        if current_label:
            for gi, (_g, names) in enumerate(ps.PAGE_SIZE_GROUPS):
                if current_label in names:
                    start = gi
                    break
        self.cat_combo.setCurrentIndex(start)
        self._on_cat(start)
        if current_label:
            j = self.size_combo.findData(current_label)
            if j >= 0:
                self.size_combo.setCurrentIndex(j)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _on_cat(self, idx: int):
        is_custom = self.cat_combo.currentText() == "Custom"
        self.size_combo.blockSignals(True)
        self.size_combo.clear()
        if not is_custom and 0 <= idx < len(ps.PAGE_SIZE_GROUPS):
            for n in ps.PAGE_SIZE_GROUPS[idx][1]:
                self.size_combo.addItem(ps.size_label(n), n)
        self.size_combo.blockSignals(False)
        self.size_combo.setEnabled(not is_custom)
        if hasattr(self, "cw"):
            self.cw.setEnabled(is_custom)
            self.ch.setEnabled(is_custom)

    def metadata(self) -> dict:
        return {"title": self.title_edit.text(), "author": self.author_edit.text(),
                "subject": self.subject_edit.text(), "keywords": self.keywords_edit.text()}

    def page_resize(self):
        """Return (w, h, apply_all, scale) if pages should be resized, else None."""
        if not self.page_group.isChecked():
            return None
        if self.cat_combo.currentText() == "Custom":
            w, h = self.cw.value() * ps.MM, self.ch.value() * ps.MM
        else:
            w, h = ps.PAGE_SIZES[self.size_combo.currentData()]
        if self.landscape.isChecked():
            w, h = max(w, h), min(w, h)
        else:
            w, h = min(w, h), max(w, h)
        return w, h, self.scope_all.isChecked(), self.scale_content.isChecked()


class FindReplaceDialog(QDialog):
    """Non-modal find & replace. Emits signals the main window acts on."""
    findNext = Signal(str, bool)            # query, match_case
    replaceAll = Signal(str, str, bool)     # query, replacement, match_case

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Find & Replace")
        self.setMinimumWidth(380)
        form = QFormLayout(self)

        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Find…")
        form.addRow("Find", self.find_edit)

        self.replace_edit = QLineEdit()
        self.replace_edit.setPlaceholderText("Replace with…")
        form.addRow("Replace", self.replace_edit)

        self.match_case = QCheckBox("Match case")
        form.addRow("", self.match_case)

        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color: #9aa0a8; font-size: 11px;")
        form.addRow("", self.count_label)

        row = QHBoxLayout()
        btn_find = QPushButton("Find Next")
        btn_replace = QPushButton("Replace All")
        btn_close = QPushButton("Close")
        row.addWidget(btn_find)
        row.addWidget(btn_replace)
        row.addStretch(1)
        row.addWidget(btn_close)
        form.addRow(row)

        btn_find.clicked.connect(lambda: self.findNext.emit(self.find_edit.text(), self.match_case.isChecked()))
        self.find_edit.returnPressed.connect(btn_find.click)
        btn_replace.clicked.connect(lambda: self.replaceAll.emit(
            self.find_edit.text(), self.replace_edit.text(), self.match_case.isChecked()))
        btn_close.clicked.connect(self.close)

    def set_status(self, text: str):
        self.count_label.setText(text)


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tirut PDF — Help")
        self.resize(620, 640)
        layout = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(HELP_HTML)
        layout.addWidget(browser)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        buttons.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        layout.addWidget(buttons)
