#!/usr/bin/env python3
"""
Generate the Slate app icon: a modern rounded-square with a document + edit nib.

Produces:
  slate/resources/icon.png   (1024px master)
  slate/resources/icon.icns  (macOS, via iconutil if available)
  slate/resources/icon.ico   (Windows, multi-size)
"""

import os
import math
import shutil
import subprocess

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "..", "slate", "resources")
os.makedirs(RES, exist_ok=True)

S = 1024


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def rounded_rect_mask(size, radius):
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return mask


def make_master() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # Vertical gradient background (indigo -> blue).
    top = (60, 80, 220)
    bot = (30, 130, 240)
    grad = Image.new("RGBA", (S, S))
    gp = grad.load()
    for y in range(S):
        c = lerp(top, bot, y / S)
        for x in range(S):
            gp[x, y] = (c[0], c[1], c[2], 255)

    mask = rounded_rect_mask(S, int(S * 0.225))
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)

    # Document sheet
    doc_w, doc_h = int(S * 0.42), int(S * 0.52)
    dx = (S - doc_w) // 2 - int(S * 0.03)
    dy = (S - doc_h) // 2 - int(S * 0.02)
    fold = int(doc_w * 0.28)

    # Soft shadow
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle([dx + 14, dy + 22, dx + doc_w + 14, dy + doc_h + 22],
                         radius=int(S * 0.03), fill=(10, 20, 60, 90))
    img.alpha_composite(shadow)

    # Page body with a folded corner
    page = (245, 247, 252, 255)
    d.rounded_rectangle([dx, dy, dx + doc_w, dy + doc_h], radius=int(S * 0.03), fill=page)
    # fold triangle
    d.polygon([(dx + doc_w - fold, dy), (dx + doc_w, dy + fold), (dx + doc_w - fold, dy + fold)],
              fill=(210, 218, 232, 255))

    # Text lines
    line_color = (150, 160, 180, 255)
    lx = dx + int(doc_w * 0.16)
    lw = int(doc_w * 0.62)
    for i in range(4):
        ly = dy + int(doc_h * (0.34 + i * 0.13))
        ww = lw if i < 3 else int(lw * 0.6)
        d.rounded_rectangle([lx, ly, lx + ww, ly + int(S * 0.018)],
                            radius=int(S * 0.009), fill=line_color)

    # Edit nib / pen crossing the lower-right
    nib_len = int(S * 0.40)
    nx, ny = dx + doc_w + int(S * 0.02), dy + doc_h - int(S * 0.02)
    angle = math.radians(-45)
    ex = int(nx - nib_len * math.cos(angle))
    ey = int(ny - nib_len * math.sin(angle))
    # pen body
    d.line([(nx, ny), (ex, ey)], fill=(255, 196, 60, 255), width=int(S * 0.055))
    # nib tip
    tip = int(S * 0.05)
    d.polygon([
        (nx, ny),
        (nx - tip, ny - int(tip * 0.4)),
        (nx - int(tip * 0.4), ny - tip),
    ], fill=(40, 44, 56, 255))

    return img


def main():
    master = make_master()
    png_path = os.path.join(RES, "icon.png")
    master.save(png_path)
    print("wrote", png_path)

    # .ico for Windows
    ico_path = os.path.join(RES, "icon.ico")
    master.save(ico_path, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print("wrote", ico_path)

    # .icns for macOS via iconutil
    if shutil.which("iconutil"):
        iconset = os.path.join(RES, "icon.iconset")
        if os.path.exists(iconset):
            shutil.rmtree(iconset)
        os.makedirs(iconset)
        specs = [
            (16, "16x16"), (32, "16x16@2x"),
            (32, "32x32"), (64, "32x32@2x"),
            (128, "128x128"), (256, "128x128@2x"),
            (256, "256x256"), (512, "256x256@2x"),
            (512, "512x512"), (1024, "512x512@2x"),
        ]
        for size, name in specs:
            master.resize((size, size), Image.LANCZOS).save(
                os.path.join(iconset, f"icon_{name}.png"))
        icns_path = os.path.join(RES, "icon.icns")
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", icns_path], check=True)
        shutil.rmtree(iconset)
        print("wrote", icns_path)
    else:
        print("iconutil not found; skipped .icns (fine on non-mac build hosts)")


if __name__ == "__main__":
    main()
