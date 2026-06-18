"""Application entry point: builds the QApplication, applies styling, loads the icon."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import __app_name__
from .main_window import MainWindow


# Theme: dark grey #282828 + orange #ff8431.
DARK_QSS = """
QMainWindow, QWidget { background: #282828; color: #ededed; }
QToolBar { background: #1f1f1f; border: none; padding: 4px; spacing: 2px; }
QToolBar QToolButton { padding: 5px 9px; border-radius: 6px; color: #ededed; }
QToolBar QToolButton:hover { background: #3a3a3a; }
QToolBar QToolButton:checked { background: #ff8431; color: #282828; }
QToolBar QToolButton:disabled { color: #6f6f6f; }
QToolBar::separator { background: #3a3a3a; width: 1px; margin: 4px 4px; }
QMenuBar { background: #1f1f1f; color: #ededed; }
QMenuBar::item:selected { background: #3a3a3a; }
QMenu { background: #2e2e2e; color: #ededed; border: 1px solid #3a3a3a; }
QMenu::item:selected { background: #ff8431; color: #282828; }
QStatusBar { background: #1f1f1f; color: #d0d0d0; }
QStatusBar QLabel { color: #ff8431; }
QDockWidget { titlebar-close-icon: none; color: #ededed; }
QDockWidget::title { background: #1f1f1f; padding: 6px; }
QPushButton { background: #3a3a3a; border: 1px solid #4a4a4a; border-radius: 6px; padding: 6px 12px; color: #ededed; }
QPushButton:hover { background: #474747; border-color: #ff8431; }
QPushButton:pressed { background: #ff8431; color: #282828; }
QPushButton:default { border: 1px solid #ff8431; }
QListWidget { background: #222222; border: none; }
QListWidget::item { color: #d0d0d0; border-radius: 6px; }
QListWidget::item:selected { background: #ff8431; color: #282828; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {
    background: #1d1d1d; border: 1px solid #4a4a4a; border-radius: 5px; padding: 4px;
    color: #ededed; selection-background-color: #ff8431; selection-color: #282828;
}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #ff8431; }
QTabBar::tab {
    background: #1f1f1f; color: #c8c8c8; padding: 7px 16px; margin-right: 2px;
    border-top-left-radius: 6px; border-top-right-radius: 6px;
}
QTabBar::tab:selected { background: #282828; color: #ff8431; border-bottom: 2px solid #ff8431; }
QTabBar::tab:hover { background: #2e2e2e; }
QTabBar::close-button { subcontrol-position: right; }
QTabWidget::pane { border: none; }
QRadioButton, QCheckBox { color: #ededed; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked { background: #ff8431; border: 1px solid #ff8431; }
QToolButton:checked { background: #ff8431; color: #282828; border-radius: 6px; }
QScrollBar:vertical { background: #1f1f1f; width: 12px; }
QScrollBar::handle:vertical { background: #4a4a4a; border-radius: 6px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #ff8431; }
QScrollBar:horizontal { background: #1f1f1f; height: 12px; }
QScrollBar::handle:horizontal { background: #4a4a4a; border-radius: 6px; min-width: 24px; }
QScrollBar::handle:horizontal:hover { background: #ff8431; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QLabel { color: #ededed; }
"""


def icon_path() -> str:
    here = os.path.dirname(__file__)
    for name in ("icon.png", "icon.icns", "icon.ico"):
        p = os.path.join(here, "resources", name)
        if os.path.exists(p):
            return p
    return ""


def main():
    QApplication.setApplicationName(__app_name__)
    QApplication.setOrganizationName("Slate")
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_QSS)

    icon = QIcon(icon_path()) if icon_path() else QIcon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    win = MainWindow(icon=icon if not icon.isNull() else None)
    win.show()

    # Open any PDFs passed on the command line, each in its own tab.
    for arg in sys.argv[1:]:
        if os.path.isfile(arg) and arg.lower().endswith(".pdf"):
            try:
                win.open_path(arg)
            except Exception:
                pass

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
