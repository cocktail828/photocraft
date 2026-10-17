"""Render the original vector mark into platform app icons; no network required."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QRectF
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[1]


def generate():
    app = QGuiApplication.instance() or QGuiApplication([])
    assets = ROOT / "photocraft/assets"
    renderer = QSvgRenderer(str(assets / "logo.svg"))
    for size in (16, 32, 48, 64, 128, 256, 512):
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        image.save(str(assets / f"icon-{size}.png"))
    with Image.open(assets / "icon-256.png") as image:
        image.save(assets / "photocraft.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    return app  # Keep the Qt application alive until all painter objects have been destroyed.


if __name__ == "__main__":
    generate()
