"""
Text Properties panel (right dock).

Shows the style of the text you clicked — detected structure type, font family, size,
bold/italic, colour — and lets you override any of them. This is the manual font-selection
feature that complements automatic font detection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLabel, QFontComboBox, QSpinBox,
    QPushButton, QHBoxLayout, QToolButton, QCheckBox, QColorDialog, QComboBox,
)


@dataclass
class Selection:
    """What the canvas currently has selected, fed into the panel."""
    family: str
    size: float
    bold: bool
    italic: bool
    color: tuple[float, float, float]
    structure: str               # "Title"/"Heading"/"Paragraph"/"Line"/"New text"
    is_paragraph: bool
    align: int = 0


_ALIGN_LABELS = ["Left", "Center", "Right", "Justify"]


class PropertiesPanel(QWidget):
    # family, size, bold, italic, color(rgb 0..1), whole_paragraph, align
    styleApplied = Signal(str, float, bool, bool, tuple, bool, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._color = QColor(0, 0, 0)
        self._has_selection = False

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        title = QLabel("Text Properties")
        title.setStyleSheet("font-weight: 600;")
        root.addWidget(title)

        self.type_label = QLabel("Nothing selected")
        self.type_label.setStyleSheet("color: #8fd0ff; font-weight: 600;")
        root.addWidget(self.type_label)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        self.font_combo = QFontComboBox()
        self.font_combo.setCurrentFont(QFont("Helvetica"))
        form.addRow("Font", self.font_combo)

        self.size_spin = QSpinBox()
        self.size_spin.setRange(4, 400)
        self.size_spin.setValue(12)
        form.addRow("Size", self.size_spin)

        style_row = QHBoxLayout()
        self.bold_btn = QToolButton()
        self.bold_btn.setText("B")
        self.bold_btn.setCheckable(True)
        self.bold_btn.setStyleSheet("QToolButton { font-weight: 700; min-width: 30px; }")
        self.italic_btn = QToolButton()
        self.italic_btn.setText("I")
        self.italic_btn.setCheckable(True)
        self.italic_btn.setStyleSheet("QToolButton { font-style: italic; min-width: 30px; }")
        self.color_btn = QPushButton("Colour")
        self.color_btn.clicked.connect(self._pick_color)
        style_row.addWidget(self.bold_btn)
        style_row.addWidget(self.italic_btn)
        style_row.addWidget(self.color_btn)
        style_row.addStretch(1)
        form.addRow("Style", style_row)

        self.align_combo = QComboBox()
        self.align_combo.addItems(_ALIGN_LABELS)
        form.addRow("Align", self.align_combo)

        root.addLayout(form)

        self.whole_para = QCheckBox("Apply to whole paragraph")
        root.addWidget(self.whole_para)

        self.apply_btn = QPushButton("Apply to selection")
        self.apply_btn.clicked.connect(self._emit_apply)
        root.addWidget(self.apply_btn)

        hint = QLabel("Tip: click text on the page to load its style here, "
                      "then change font/size/colour and Apply.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #9aa0a8; font-size: 11px;")
        root.addWidget(hint)
        root.addStretch(1)

        self._set_enabled(False)

    # -- external API ------------------------------------------------------

    def show_selection(self, sel: Optional[Selection]):
        self._has_selection = sel is not None
        self._set_enabled(self._has_selection)
        if sel is None:
            self.type_label.setText("Nothing selected")
            return
        self.type_label.setText(f"{sel.structure}")
        self.font_combo.setCurrentFont(QFont(sel.family))
        self.size_spin.setValue(int(round(sel.size)))
        self.bold_btn.setChecked(sel.bold)
        self.italic_btn.setChecked(sel.italic)
        self._color = QColor.fromRgbF(*sel.color)
        self._refresh_color_btn()
        self.align_combo.setCurrentIndex(sel.align if 0 <= sel.align < 4 else 0)
        self._is_paragraph = sel.is_paragraph
        self.whole_para.setVisible(sel.is_paragraph)
        self.whole_para.setChecked(sel.is_paragraph)

    def current_color_rgb(self) -> tuple[float, float, float]:
        return (self._color.redF(), self._color.greenF(), self._color.blueF())

    # -- internals ---------------------------------------------------------

    def _set_enabled(self, on: bool):
        for w in (self.font_combo, self.size_spin, self.bold_btn, self.italic_btn,
                  self.color_btn, self.align_combo, self.whole_para, self.apply_btn):
            w.setEnabled(on)

    def _pick_color(self):
        c = QColorDialog.getColor(self._color, self, "Text colour")
        if c.isValid():
            self._color = c
            self._refresh_color_btn()

    def _refresh_color_btn(self):
        self.color_btn.setStyleSheet(
            f"QPushButton {{ background: {self._color.name()}; "
            f"color: {'#000' if self._color.lightnessF() > 0.5 else '#fff'}; "
            f"border: 1px solid #555; border-radius: 5px; padding: 6px 12px; }}")

    def _emit_apply(self):
        if not self._has_selection:
            return
        self.styleApplied.emit(
            self.font_combo.currentFont().family(),
            float(self.size_spin.value()),
            self.bold_btn.isChecked(),
            self.italic_btn.isChecked(),
            self.current_color_rgb(),
            getattr(self, "_is_paragraph", False) and self.whole_para.isChecked(),
            self.align_combo.currentIndex(),
        )
