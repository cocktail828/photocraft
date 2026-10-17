from __future__ import annotations

import math

from PIL import ImageQt
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QGraphicsView


def pixmap(image):
    return QPixmap.fromImage(ImageQt.ImageQt(image))


class Canvas(QGraphicsView):
    cropChanged = Signal(QRectF)
    cropApplied = Signal()
    strokeFinished = Signal(list)
    strokePreview = Signal(list)
    markMoved = Signal(int, float, float)
    zoomChanged = Signal(float)
    fileDropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("canvas")
        self.scene_ = QGraphicsScene(self)
        self.setScene(self.scene_)
        self.photo = QGraphicsPixmapItem()
        self.scene_.addItem(self.photo)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.bounds = QRectF()
        self.crop = QRectF()
        self.ratio = None
        self.crop_fixed_size = False
        self.tool = "hand"
        self.marks = []
        self.drag = None
        self.start = QPointF()
        self.start_crop = QRectF()
        self.points = []
        self.brush_size = 24
        self.brush_color = "#437aff"
        self.brush_opacity = 0.8
        self.cursor_position = None
        self.space = False
        self.portrait_guides = False
        self.checker = True
        self.stroke_timer = QTimer(self)
        self.stroke_timer.setInterval(50)
        self.stroke_timer.timeout.connect(lambda: self.strokePreview.emit(list(self.points)))

    def set_image(self, image, watermarks=(), fit=False, logical_size=None):
        self.photo.setPixmap(pixmap(image))
        width, height = logical_size or image.size
        self.photo.setTransform(QTransform.fromScale(width / image.width, height / image.height))
        self.bounds = QRectF(0, 0, width, height)
        self.setSceneRect(self.bounds.adjusted(-40, -40, 40, 40))
        self.clear_watermarks()
        for mark in watermarks:
            if mark.tile:
                from PIL import Image

                from .core import compose

                layer = compose(Image.new("RGBA", image.size), [mark])
                item = QGraphicsPixmapItem(pixmap(layer))
            else:
                item = QGraphicsPixmapItem(pixmap(mark.bitmap()))
                item.setPos(mark.x, mark.y)
            item.setZValue(2)
            item.setData(0, mark.tile)
            self.scene_.addItem(item)
            self.marks.append(item)
        if self.crop.isEmpty() or not self.bounds.contains(self.crop):
            self.reset_crop()
        else:
            self.cropChanged.emit(self.crop)
        if fit:
            self.fit()
        self.viewport().update()

    def clear_watermarks(self):
        for item in self.marks:
            self.scene_.removeItem(item)
        self.marks = []

    def set_watermark_preview(self, image, scale):
        self.clear_watermarks()
        item = QGraphicsPixmapItem(pixmap(image))
        item.setScale(1 / scale)
        item.setZValue(2)
        item.setData(0, True)
        self.scene_.addItem(item)
        self.marks.append(item)

    def fit(self):
        if not self.bounds.isEmpty():
            self.fitInView(self.bounds.adjusted(-15, -15, 15, 15), Qt.AspectRatioMode.KeepAspectRatio)
            self.zoomChanged.emit(self.transform().m11())

    def actual_size(self):
        self.resetTransform()
        self.zoomChanged.emit(1)

    def set_zoom(self, value):
        factor = max(0.01, min(32, value)) / self.transform().m11()
        self.scale(factor, factor)
        self.zoomChanged.emit(self.transform().m11())

    def set_tool(self, name):
        self.tool = name
        self.setCursor(Qt.CursorShape.OpenHandCursor if name == "hand" else Qt.CursorShape.CrossCursor)
        self.viewport().update()

    def reset_crop(self, ratio=None):
        self.ratio = ratio
        if self.bounds.isEmpty():
            return
        width, height = self.bounds.width() * 0.88, self.bounds.height() * 0.88
        if ratio:
            width, height = min(width, height * ratio), min(height, width / ratio)
        else:
            width, height = round(width), round(height)
        left, top = (self.bounds.width() - width) / 2, (self.bounds.height() - height) / 2
        if ratio is None:
            left, top = round(left), round(top)
        self.crop = QRectF(left, top, width, height)
        self.cropChanged.emit(self.crop)
        self.viewport().update()

    def set_crop_pixels(self, width, height):
        width, height = min(width, self.bounds.width()), min(height, self.bounds.height())
        if width <= 0 or height <= 0:
            return
        self.crop = QRectF(
            round(self.crop.center().x() - width / 2),
            round(self.crop.center().y() - height / 2),
            width,
            height,
        )
        self._clamp_crop()
        self.cropChanged.emit(self.crop)
        self.viewport().update()

    def _clamp_crop(self):
        self.crop.moveLeft(max(0, min(self.crop.left(), self.bounds.width() - self.crop.width())))
        self.crop.moveTop(max(0, min(self.crop.top(), self.bounds.height() - self.crop.height())))

    def handles(self):
        r = self.crop
        return [
            r.topLeft(),
            QPointF(r.center().x(), r.top()),
            r.topRight(),
            QPointF(r.right(), r.center().y()),
            r.bottomRight(),
            QPointF(r.center().x(), r.bottom()),
            r.bottomLeft(),
            QPointF(r.left(), r.center().y()),
        ]

    def drawBackground(self, painter, rect):
        painter.fillRect(rect, QColor("#202736"))
        if self.checker and not self.bounds.isEmpty():
            tile = QPixmap(24, 24)
            tile.fill(QColor("#ecedf0"))
            p = QPainter(tile)
            p.fillRect(0, 0, 12, 12, QColor("#dce0e6"))
            p.fillRect(12, 12, 12, 12, QColor("#dce0e6"))
            p.end()
            painter.fillRect(self.bounds, QBrush(tile))

    def drawForeground(self, painter, rect):
        scale = self.transform().m11()
        if self.tool in ("crop", "id") and not self.bounds.isEmpty():
            shade = QPainterPath()
            shade.addRect(self.bounds)
            inner = QPainterPath()
            inner.addRect(self.crop)
            painter.fillPath(shade.subtracted(inner), QColor(12, 18, 31, 155))
            painter.setPen(QPen(QColor("#ffffff"), 1.3 / scale))
            painter.drawRect(self.crop)
            painter.setPen(QPen(QColor(255, 255, 255, 115), 0.7 / scale))
            for i in (1, 2):
                x = self.crop.x() + self.crop.width() * i / 3
                y = self.crop.y() + self.crop.height() * i / 3
                painter.drawLine(QPointF(x, self.crop.top()), QPointF(x, self.crop.bottom()))
                painter.drawLine(QPointF(self.crop.left(), y), QPointF(self.crop.right(), y))
            if self.portrait_guides:
                painter.setPen(QPen(QColor("#8ee8d6"), 1 / scale, Qt.PenStyle.DashLine))
                center = self.crop.center()
                painter.drawLine(
                    QPointF(center.x(), self.crop.top()), QPointF(center.x(), self.crop.bottom())
                )
                painter.drawEllipse(
                    QRectF(
                        center.x() - self.crop.width() * 0.27,
                        self.crop.top() + self.crop.height() * 0.10,
                        self.crop.width() * 0.54,
                        self.crop.height() * 0.49,
                    )
                )
            painter.setBrush(QColor("#ffffff"))
            painter.setPen(QPen(QColor("#4275f5"), 1 / scale))
            for point in () if self.crop_fixed_size else self.handles():
                painter.drawRoundedRect(
                    QRectF(point.x() - 3.5 / scale, point.y() - 3.5 / scale, 7 / scale, 7 / scale),
                    1 / scale,
                    1 / scale,
                )
        if self.cursor_position is not None and self.tool in ("brush", "mosaic", "blur", "erase"):
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#ffffff"), 1 / scale))
            painter.drawEllipse(self.cursor_position, self.brush_size / 2, self.brush_size / 2)

    def wheelEvent(self, event):
        self.set_zoom(self.transform().m11() * (1.15 if event.angleDelta().y() > 0 else 1 / 1.15))
        event.accept()

    def mousePressEvent(self, event):
        self.setFocus()
        point = self.mapToScene(event.position().toPoint())
        self.start = point
        if event.button() == Qt.MouseButton.MiddleButton or self.space or self.tool == "hand":
            self.drag = "pan"
            self.pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif self.tool in ("crop", "id"):
            tolerance = 12 / self.transform().m11()
            distances = [math.hypot(point.x() - p.x(), point.y() - p.y()) for p in self.handles()]
            handle = min(range(8), key=lambda i: distances[i])
            self.drag = handle if not self.crop_fixed_size and distances[handle] < tolerance else "move"
            self.start_crop = QRectF(self.crop)
        elif self.tool in ("brush", "mosaic", "blur", "erase") and self.bounds.contains(point):
            self.drag = "paint"
            self.points = [(point.x(), point.y())]
            self.strokePreview.emit(list(self.points))
            self.stroke_timer.start()
        elif self.tool == "watermark":
            for index in reversed(range(len(self.marks))):
                item = self.marks[index]
                if not item.data(0) and item.sceneBoundingRect().contains(point):
                    self.drag = ("mark", index, item.pos())
                    break
        self.viewport().update()

    def mouseMoveEvent(self, event):
        point = self.mapToScene(event.position().toPoint())
        self.cursor_position = point
        if self.drag == "pan":
            delta = event.position() - self.pan_start
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - round(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - round(delta.y()))
            self.pan_start = event.position()
        elif self.drag == "paint":
            self.points.append(
                (max(0, min(point.x(), self.bounds.width())), max(0, min(point.y(), self.bounds.height())))
            )
        elif isinstance(self.drag, tuple):
            _, index, pos = self.drag
            self.marks[index].setPos(pos + point - self.start)
        elif self.drag == "move":
            self.crop = self.start_crop.translated(point - self.start)
            if self.ratio is None or self.crop_fixed_size:
                self.crop.moveTopLeft(QPointF(round(self.crop.left()), round(self.crop.top())))
            self._clamp_crop()
            self.cropChanged.emit(self.crop)
        elif isinstance(self.drag, int):
            self._resize_crop(point, self.drag)
            self.cropChanged.emit(self.crop)
        self.viewport().update()

    def _resize_crop(self, point, handle):
        r = self.start_crop
        x = max(0, min(point.x(), self.bounds.width()))
        y = max(0, min(point.y(), self.bounds.height()))
        left = x if handle in (0, 6, 7) else r.left()
        right = x if handle in (2, 3, 4) else r.right()
        top = y if handle in (0, 1, 2) else r.top()
        bottom = y if handle in (4, 5, 6) else r.bottom()
        width, height = max(1, right - left), max(1, bottom - top)
        if self.ratio:
            if handle in (1, 5):
                width = height * self.ratio
                left = r.center().x() - width / 2
            else:
                height = width / self.ratio
                if handle in (3, 7):
                    top = r.center().y() - height / 2
                elif handle in (0, 2):
                    top = r.bottom() - height
            factor = min(1, self.bounds.width() / width, self.bounds.height() / height)
            width, height = width * factor, height * factor
        else:
            left, top, width, height = round(left), round(top), round(width), round(height)
        self.crop = QRectF(left, top, width, height)
        self._clamp_crop()

    def mouseReleaseEvent(self, event):
        if self.drag == "paint":
            self.stroke_timer.stop()
            points = self.points
            self.points = []
            self.strokeFinished.emit(points)
        elif isinstance(self.drag, tuple):
            _, index, _ = self.drag
            pos = self.marks[index].pos()
            self.markMoved.emit(index, pos.x(), pos.y())
        self.drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor if self.tool == "hand" else Qt.CursorShape.CrossCursor)
        self.viewport().update()

    def mouseDoubleClickEvent(self, event):
        if self.tool in ("crop", "id"):
            self.cropApplied.emit()

    def leaveEvent(self, event):
        self.cursor_position = None
        self.viewport().update()
        super().leaveEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self.space = True
        elif event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return) and self.tool in ("crop", "id"):
            self.cropApplied.emit()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self.space = False
        super().keyReleaseEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and event.mimeData().urls()[0].isLocalFile():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            self.fileDropped.emit(event.mimeData().urls()[0].toLocalFile())
            event.acceptProposedAction()
