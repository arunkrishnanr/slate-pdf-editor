#!/usr/bin/env python3
"""
Generate the Slate app icon from the bundled SVG (slate/resources/icon.svg).

Rasterizes the SVG with Qt's SVG renderer, then writes:
  slate/resources/icon.png   (1024px master)
  slate/resources/icon.icns  (macOS, via iconutil if available)
  slate/resources/icon.ico   (Windows, multi-size)
"""

import os
import shutil
import subprocess

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "..", "slate", "resources")
SVG = os.path.join(RES, "icon.svg")
S = 1024


def render_svg(size: int) -> QImage:
    renderer = QSvgRenderer(SVG)
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    renderer.render(p)
    p.end()
    return img


def main():
    if not os.path.exists(SVG):
        raise SystemExit(f"SVG icon not found at {SVG}")
    # QImage/QPainter need a QApplication instance.
    app = QApplication.instance() or QApplication([])

    master = render_svg(S)
    png_path = os.path.join(RES, "icon.png")
    master.save(png_path, "PNG")
    print("wrote", png_path)

    # .ico (Windows) — multiple sizes in one container via Pillow.
    _write_ico(master)

    # .icns (macOS) via iconutil.
    if shutil.which("iconutil"):
        iconset = os.path.join(RES, "icon.iconset")
        if os.path.exists(iconset):
            shutil.rmtree(iconset)
        os.makedirs(iconset)
        specs = [
            (16, "16x16"), (32, "16x16@2x"), (32, "32x32"), (64, "32x32@2x"),
            (128, "128x128"), (256, "128x128@2x"), (256, "256x256"),
            (512, "256x256@2x"), (512, "512x512"), (1024, "512x512@2x"),
        ]
        for size, name in specs:
            render_svg(size).save(os.path.join(iconset, f"icon_{name}.png"), "PNG")
        icns_path = os.path.join(RES, "icon.icns")
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", icns_path], check=True)
        shutil.rmtree(iconset)
        print("wrote", icns_path)
    else:
        print("iconutil not found; skipped .icns (fine on non-mac build hosts)")


def _write_ico(master: QImage):
    """Write a multi-size .ico using Pillow from the Qt master image."""
    from PIL import Image
    ico_path = os.path.join(RES, "icon.ico")
    # Qt -> raw RGBA -> PIL
    img = master.convertToFormat(QImage.Format_RGBA8888)
    w, h = img.width(), img.height()
    ptr = img.constBits()
    pil = Image.frombytes("RGBA", (w, h), bytes(ptr))
    pil.save(ico_path, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print("wrote", ico_path)


if __name__ == "__main__":
    main()
