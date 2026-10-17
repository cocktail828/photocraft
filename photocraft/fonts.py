"""Render system font families once on the GUI thread, then export with Pillow."""

import math

from PIL import ImageQt
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetricsF, QImage, QPainter


def default_font_family():
    families = set(QFontDatabase.families())
    for family in ("Noto Sans CJK SC", "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC"):
        if family in families:
            return family
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).family()


def render_text(text, family, size, color):
    font = QFont(family)
    font.setPixelSize(size)
    bounds = QFontMetricsF(font).boundingRect(text or " ")
    width, height = max(1, math.ceil(bounds.width()) + 8), max(1, math.ceil(bounds.height()) + 8)
    if width * height > 8_000_000:
        raise ValueError("水印尺寸过大，请减小字号或缩短文字。")
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setFont(font)
        painter.setPen(QColor(color))
        painter.drawText(QPointF(4 - bounds.left(), 4 - bounds.top()), text)
    finally:
        painter.end()
    return ImageQt.fromqimage(image).convert("RGBA")
