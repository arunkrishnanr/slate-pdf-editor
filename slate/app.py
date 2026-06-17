"""Application entry point: builds the QApplication, applies styling, loads the icon."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import __app_name__
from .main_window import MainWindow


DARK_QSS = """
QMainWindow, QWidget { background: #2b2e35; color: #e6e8ec; }
QToolBar { background: #23262c; border: none; padding: 4px; spacing: 2px; }
QToolBar QToolButton { padding: 5px 9px; border-radius: 6px; color: #e6e8ec; }
QToolBar QToolButton:hover { background: #353a43; }
QToolBar QToolButton:checked { background: #2a82e6; color: white; }
QToolBar QToolButton:disabled { color: #6b7178; }
QMenuBar { background: #23262c; color: #e6e8ec; }
QMenuBar::item:selected { background: #353a43; }
QMenu { background: #2b2e35; color: #e6e8ec; border: 1px solid #3a3f48; }
QMenu::item:selected { background: #2a82e6; }
QStatusBar { background: #23262c; color: #cfd3da; }
QDockWidget { titlebar-close-icon: none; color: #e6e8ec; }
QDockWidget::title { background: #23262c; padding: 6px; }
QPushButton { background: #353a43; border: 1px solid #444a54; border-radius: 6px; padding: 6px 12px; }
QPushButton:hover { background: #3f4651; }
QPushButton:pressed { background: #2a82e6; }
QListWidget { background: #21242a; border: none; }
QListWidget::item { color: #cfd3da; border-radius: 6px; }
QListWidget::item:selected { background: #2a82e6; color: white; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {
    background: #20232a; border: 1px solid #444a54; border-radius: 5px; padding: 4px;
    color: #e6e8ec;
}
QLabel { color: #e6e8ec; }
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

    # Open a file passed on the command line.
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        try:
            win.document.open(sys.argv[1])
            win.current_page = 0
            win._after_document_changed()
        except Exception:
            pass

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
