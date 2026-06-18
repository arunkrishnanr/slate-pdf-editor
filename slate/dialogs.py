"""Small dialogs: font resolution prompt, add-text, and OCR review."""

from __future__ import annotations

import os
import platform
import subprocess
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QDialogButtonBox, QSpinBox, QComboBox, QPlainTextEdit, QFormLayout,
    QRadioButton, QButtonGroup, QCheckBox,
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

        # Size picker, grouped by standard family.
        self.size_combo = QComboBox()
        for group_name, names in ps.PAGE_SIZE_GROUPS:
            self.size_combo.addItem(f"— {group_name} —")
            idx = self.size_combo.count() - 1
            self.size_combo.model().item(idx).setEnabled(False)
            for n in names:
                self.size_combo.addItem(ps.size_label(n), n)
        self.size_combo.addItem("Custom…", "__custom__")
        if current_label:
            i = self.size_combo.findData(current_label)
            if i >= 0:
                self.size_combo.setCurrentIndex(i)
        form.addRow("Standard", self.size_combo)

        # Custom dimensions (mm)
        custom_row = QHBoxLayout()
        self.cw = QSpinBox(); self.cw.setRange(10, 5000); self.cw.setValue(210); self.cw.setSuffix(" mm")
        self.ch = QSpinBox(); self.ch.setRange(10, 5000); self.ch.setValue(297); self.ch.setSuffix(" mm")
        custom_row.addWidget(QLabel("W")); custom_row.addWidget(self.cw)
        custom_row.addWidget(QLabel("H")); custom_row.addWidget(self.ch)
        form.addRow("Custom size", custom_row)

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

    def result_values(self):
        """Return (width_pt, height_pt, apply_all, scale_content)."""
        data = self.size_combo.currentData()
        if data == "__custom__" or data is None:
            w = self.cw.value() * ps.MM
            h = self.ch.value() * ps.MM
        else:
            w, h = ps.PAGE_SIZES[data]
        if self.landscape.isChecked():
            w, h = max(w, h), min(w, h)
        else:
            w, h = min(w, h), max(w, h)
        return w, h, self.scope_all.isChecked(), self.scale_content.isChecked()
