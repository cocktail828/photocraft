"""Exact, cancellable measurements of the active preview, separate from saved edits."""

from collections.abc import Callable
from dataclasses import dataclass, replace

from PySide6.QtCore import QObject, QTimer, Signal

from .compression import EncodedImage, compress
from .core import crop_pixels, paint_stroke
from .rendering import RenderCache
from .widgets import Worker


@dataclass
class Plan:
    key: tuple
    note: str
    compute: Callable | None = None
    result: EncodedImage | None = None
    same: bool = False
    error: str = ""
    original: bool = False


class PreviewInfo(QObject):
    changed = Signal()

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.plan = Plan((), "", same=True)
        self.result = None
        self.error = ""
        self.generation = 0
        self.worker = None
        self.worker_key = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self.measure)

    def capture(self):
        w = self.window
        if w.doc is None:
            return Plan((), "请先打开图片", same=True)
        options = w.save_options()
        common = (w.edit_generation, options)
        if w.compare_state is not None:
            return Plan((*common, "original"), "原图对比", original=True)
        base, marks, settings = w.doc.snapshot(copy_base=False)
        metadata = dict(w.doc.metadata)

        def encode(image, check):
            check()
            return compress(image, replace(options, width=image.width, height=image.height), metadata, check)

        if w.current_tool == "export" and w.show_encoded_preview.isChecked():
            return Plan(
                (*common, "compression", w.export_generation),
                "压缩预览 · 未应用"
                if w.preview_result is None or w.preview_result is not w.applied_compression
                else "压缩已应用",
                result=w.preview_result,
                error=w.compression_error,
            )
        if w.current_tool == "watermark" and w.mark_draft_active and w.mark_live_preview.isChecked():
            try:
                marks = w.proposed_marks(w.mark_from_controls())
            except ValueError as error:
                return Plan((*common, "watermark-error", str(error)), "水印预览未生效", error=str(error))
            signature = tuple(
                tuple(id(v) if k == "text_bitmap" else v for k, v in vars(m).items()) for m in marks
            )

            def watermark(check):
                return encode(
                    w.render_cache.render(base, marks, settings, draft=True, check_current=check), check
                )

            return Plan((*common, "watermark", signature), "水印预览 · 未应用", compute=watermark)
        if w.current_tool == "background" and w.background_draft_active:
            ready = w.background_preview is not None and w.background_preview[0] == (
                w.edit_generation,
                w.background_color,
            )
            key = (*common, "background", w.background_color)
            if not ready:
                return Plan(key, "正在生成背景色预览…", error=w.background_error)
            if not w.background_preview[4]:
                return Plan(key, "图片不含透明区域，填充不会改变画面。请先用橡皮擦擦除原背景。", same=True)
            _, filled, _, cache, _ = w.background_preview

            def background(check):
                return encode(cache.render(filled, marks, settings, check_current=check), check)

            return Plan(key, "背景色预览 · 未应用", compute=background)
        if w.current_tool == "rotate" and w.angle.value() != 0:
            key = (*common, "rotate", w.angle.value(), w.expand.isChecked())
            cached = w.rotation_preview_cache
            if cached is None or cached[0] != (w.edit_generation, w.angle.value(), w.expand.isChecked()):
                return Plan(key, "正在生成旋转预览…")
            image = cached[1]
            return Plan(key, "旋转预览 · 未应用", compute=lambda check: encode(image, check))
        if w.current_tool == "crop" and w.canvas.tool == "crop" and not w.canvas.crop.isEmpty():
            rect = w.canvas.crop
            box = tuple(round(n) for n in (rect.left(), rect.top(), rect.right(), rect.bottom()))
            target = w.crop_output_size if isinstance(w.crop_ratio.currentData(), int) else None
            allow_resize = w.crop_allow_resize.isChecked()

            def crop(check):
                check()
                cropped, cropped_marks = crop_pixels(
                    base, marks, box, output_size=target, allow_resize=allow_resize
                )
                image = RenderCache().render(cropped, cropped_marks, settings, check_current=check)
                return encode(image, check)

            return Plan((*common, "crop", box, target, allow_resize), "裁剪预览 · 未应用", compute=crop)
        if w.current_tool in w.brush_controls and w.canvas.drag == "paint" and w.stroke_info is not None:
            generation, points, mode, size, color, opacity, block = w.stroke_info
            if generation == w.edit_generation:

                def stroke(check):
                    check()
                    painted = paint_stroke(base, points, mode, size, color, opacity, block)
                    image = RenderCache().render(painted, marks, settings, check_current=check)
                    return encode(image, check)

                return Plan(
                    (*common, "stroke", points, mode, size, color, opacity, block),
                    "笔触预览 · 松开鼠标后应用",
                    compute=stroke,
                )
        return Plan((*common, "applied"), "与当前一致", same=True)

    def refresh(self):
        plan = self.capture()
        if plan.key != self.plan.key:
            self.generation += 1
            self.result = None
            self.error = ""
            self.timer.stop()
        self.plan = plan
        if (
            plan.compute is not None
            and self.result is None
            and not self.error
            and self.worker is None
            and not self.timer.isActive()
            and not self.window.closing
        ):
            self.timer.start()

    def measure(self):
        plan = self.plan
        if self.worker is not None or plan.compute is None or self.window.closing:
            return
        generation = self.generation

        def current(message=""):
            if self.window.closing or generation != self.generation:
                raise InterruptedError("预览实测已取消")

        worker = Worker(lambda progress: plan.compute(current))
        self.worker, self.worker_key = worker, plan.key
        self.window.jobs.add(worker)
        self.window.preview_jobs.add(worker)

        def done(result):
            if not self.window.closing and generation == self.generation:
                self.result = result
                self.changed.emit()

        def failed(message):
            if not self.window.closing and generation == self.generation:
                self.error = message
                self.changed.emit()

        def finished():
            self.window.finish_job(worker)
            self.worker = None
            self.worker_key = None
            if (
                not self.window.closing
                and self.plan.compute is not None
                and self.result is None
                and not self.error
            ):
                self.timer.start()

        worker.signals.done.connect(done)
        worker.signals.error.connect(failed)
        worker.signals.finished.connect(finished)
        self.window.pool.start(worker, 0)

    def close(self):
        self.timer.stop()
        self.generation += 1
