"""
Startup dependency preflight.

Before the GUI loads, verify the runtime tools Slate needs are present. If a *hard*
requirement is missing, show a clear error (with official download links) and terminate.
Optional tools (Tesseract OCR) are reported as soft notes — the app still runs without them.

This must not assume any third-party package is importable: the error display falls back
from Qt → native OS dialog → stderr so it works even when PySide6 itself is missing.
"""

from __future__ import annotations

import os
import sys
import shutil
import platform

APP_NAME = "Slate PDF Editor"
MIN_PYTHON = (3, 9)

# (import name, display name, install hint, official URL)
HARD_REQUIREMENTS = [
    ("PySide6", "PySide6 (Qt for Python)", "pip install PySide6", "https://pypi.org/project/PySide6/"),
    ("fitz", "PyMuPDF", "pip install PyMuPDF", "https://pypi.org/project/PyMuPDF/"),
    ("PIL", "Pillow", "pip install Pillow", "https://pypi.org/project/Pillow/"),
]

PYTHON_URL = "https://www.python.org/downloads/"


def tesseract_install_hint() -> str:
    system = platform.system()
    if system == "Darwin":
        url = "https://formulae.brew.sh/formula/tesseract  (run: brew install tesseract)"
    elif system == "Windows":
        url = "https://github.com/UB-Mannheim/tesseract/wiki"
    else:
        url = "https://tesseract-ocr.github.io/tessdoc/Installation.html"
    return url


def _check() -> list[str]:
    """Return a list of human-readable problem descriptions (empty == all good)."""
    problems: list[str] = []

    if sys.version_info < MIN_PYTHON:
        have = ".".join(map(str, sys.version_info[:3]))
        need = ".".join(map(str, MIN_PYTHON))
        problems.append(
            f"• Python {need}+ is required (you have {have}).\n"
            f"    Download Python:  {PYTHON_URL}")

    # Skip the import checks inside a frozen build — everything is bundled, and a
    # transient import quirk shouldn't block a self-contained app.
    if not getattr(sys, "frozen", False):
        for mod, name, pip_cmd, url in HARD_REQUIREMENTS:
            try:
                __import__(mod)
            except Exception:
                problems.append(
                    f"• {name} is not installed.\n"
                    f"    Install:  {pip_cmd}\n"
                    f"    Details:  {url}")
    return problems


def _show_error(title: str, message: str):
    """Best-effort error display that degrades gracefully."""
    # 1) Qt dialog, if PySide6 is available.
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance() or QApplication(sys.argv)
        box = QMessageBox()
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle(title)
        box.setText(message)
        box.exec()
        return
    except Exception:
        pass
    # 2) Native OS dialog.
    try:
        if platform.system() == "Darwin":
            import subprocess
            safe = message.replace('"', "'")
            subprocess.run(["osascript", "-e",
                            f'display dialog "{safe}" with title "{title}" buttons {{"Quit"}} with icon stop'])
            return
        if platform.system() == "Windows":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
            return
    except Exception:
        pass
    # 3) Plain stderr.
    print(f"\n{title}\n{'=' * len(title)}\n{message}\n", file=sys.stderr)


def run_or_exit():
    """Run the preflight check; on failure, display an error and terminate."""
    problems = _check()
    if problems:
        message = (
            f"{APP_NAME} can't start because a required runtime tool is missing:\n\n"
            + "\n\n".join(problems)
            + "\n\nPlease install the item(s) above and launch the app again."
        )
        _show_error(f"{APP_NAME} — Missing requirement", message)
        sys.exit(1)
