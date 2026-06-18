"""Small custom widgets — currently an iOS-style on/off switch with a label."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QRectF, QSize
from PySide6.QtGui import QPainter, QColor, QFont
from PySide6.QtWidgets import QWidget


ORANGE = QColor(0xFF, 0x84, 0x31)
TRACK_OFF = QColor(0x55, 0x55, 0x55)
KNOB = QColor(0xF2, 0xF2, 0xF2)
TEXT = QColor(0xE6, 0xE6, 0xE6)


class SwitchButton(QWidget):
    """A labelled on/off switch. Drop-in toggle: isChecked/setChecked/toggled."""

    toggled = Signal(bool)

    TRACK_W = 38
    TRACK_H = 20
    KNOB_M = 2  # margin between knob and track edge

    def __init__(self, label: str, checked: bool = False, parent=None):
        super().__init__(parent)
        self._label = label
        self._checked = checked
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(26)
        self._font = QFont()
        self._font.setPointSize(11)

    # -- API ---------------------------------------------------------------

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, value: bool):
        value = bool(value)
        if value != self._checked:
            self._checked = value
            self.update()

    def setText(self, text: str):
        self._label = text
        self.updateGeometry()
        self.update()

    def text(self) -> str:
        return self._label

    # -- sizing ------------------------------------------------------------

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        text_w = fm.horizontalAdvance(self._label)
        return QSize(self.TRACK_W + 8 + text_w + 10, 26)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    # -- interaction -------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._checked = not self._checked
            self.update()
            self.toggled.emit(self._checked)

    # -- painting ----------------------------------------------------------

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cy = self.height() / 2
        track = QRectF(2, cy - self.TRACK_H / 2, self.TRACK_W, self.TRACK_H)
        p.setPen(Qt.NoPen)
        p.setBrush(ORANGE if self._checked else TRACK_OFF)
        p.drawRoundedRect(track, self.TRACK_H / 2, self.TRACK_H / 2)

        knob_d = self.TRACK_H - 2 * self.KNOB_M
        knob_x = (track.right() - knob_d - self.KNOB_M) if self._checked else (track.left() + self.KNOB_M)
        p.setBrush(KNOB)
        p.drawEllipse(QRectF(knob_x, cy - knob_d / 2, knob_d, knob_d))

        p.setFont(self._font)
        p.setPen(ORANGE if self._checked else TEXT)
        text_x = self.TRACK_W + 10
        p.drawText(QRectF(text_x, 0, self.width() - text_x, self.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, self._label)
        p.end()
