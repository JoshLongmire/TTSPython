"""Draw the app mark in the default theme colors and save TTSPython.ico and TTSPython.png."""
from __future__ import annotations

import os
import struct
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ttspython.core.theme import DEFAULT_THEME, THEME_PRESETS, derive_tokens  # noqa: E402
from ttspython.ui.widgets import ICON_SIZES as SIZES, paint_mark  # noqa: E402


def render_png(size, accent, fg):
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    paint_mark(p, QRectF(0, 0, size, size), accent, fg)
    p.end()
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)


def write_ico(path, images):
    """images: [(size, png bytes)]. ICO files may hold PNG data directly (Vista and later)."""
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, blobs = b"", b""
    for size, png in images:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    with open(path, "wb") as f:
        f.write(header + entries + blobs)


def main(out_dir):
    QApplication.instance() or QApplication([])
    tokens = derive_tokens(THEME_PRESETS[DEFAULT_THEME])
    images = [(size, render_png(size, tokens["accent_fill"], tokens["on_accent"])) for size in SIZES]
    os.makedirs(out_dir, exist_ok=True)
    ico = os.path.join(out_dir, "TTSPython.ico")
    png = os.path.join(out_dir, "TTSPython.png")
    write_ico(ico, images)
    with open(png, "wb") as f:
        f.write(images[-1][1])
    return ico, png


if __name__ == "__main__":
    for path in main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "build", "icon")):
        print(path)
