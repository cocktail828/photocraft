"""Immutable applied states and bounded, reusable full-resolution preview results."""

import hashlib
import json
import os
import secrets
import threading
import time
from collections import OrderedDict
from copy import copy
from dataclasses import dataclass, field, replace
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageDraw

from .compression import EncodedImage, ExportOptions, compress
from .core import Enhancement, Watermark, crop_pixels, load_image, paint_stroke, transform_pixels
from .rendering import RenderCache
from .web_fonts import text_bitmap
from .web_models import PARAMETERS, Operation

MAX_PIXELS = int(os.environ.get("PHOTOCRAFT_MAX_PIXELS", "24000000"))
EXTENSIONS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "BMP": "bmp", "TIFF": "tiff"}
MIMES = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "BMP": "image/bmp",
    "TIFF": "image/tiff",
}
RENDER_SLOTS = threading.BoundedSemaphore(2)


class Conflict(ValueError):
    pass


@dataclass
class State:
    base: Image.Image
    marks: list = field(default_factory=list)
    enhancement: Enhancement = field(default_factory=Enhancement)
    options: ExportOptions | None = None


@dataclass
class Entry:
    state: State
    rendered: Image.Image
    encoded: EncodedImage
    tool: str = ""
    warning: str = ""
    changed: bool = True
    thumbnail: bytes | None = None
    stroke_origin: "Entry | None" = field(default=None, repr=False)

    def info(self):
        return dict(
            bytes=len(self.encoded.data),
            width=self.rendered.width,
            height=self.rendered.height,
            format=self.encoded.format,
            quality=self.encoded.quality,
            lossy=self.encoded.lossy,
            losses=list(self.encoded.loss_reasons),
            original=self.encoded.strategy == "原文件编码",
        )

    def clipboard(self):
        # Decode the saved result at full size, including its actual compression and alpha.
        from PIL import ImageOps

        with RENDER_SLOTS, Image.open(BytesIO(self.encoded.data)) as source:
            image = ImageOps.exif_transpose(source).convert("RGBA")
            output = BytesIO()
            image.save(output, "PNG", compress_level=3)
            return output.getvalue()

    def image(self):
        if self.thumbnail is None:
            # Display the actual encoded result, never use this bounded thumbnail for downloads.
            with Image.open(BytesIO(self.encoded.data)) as source:
                from PIL import ImageOps

                image = ImageOps.exif_transpose(source).convert("RGBA")
                image.thumbnail((1600, 1600))
                output = BytesIO()
                image.save(output, "WEBP", lossless=True, method=0)
                self.thumbnail = output.getvalue()
        return self.thumbnail


class Editor:
    def __init__(self, image, metadata):
        self.id = secrets.token_urlsafe(24)
        self.original, self.metadata = image, metadata
        raw_w, raw_h = metadata.get("encoded_dimensions", image.size)
        encoded = EncodedImage(
            metadata["source_data"],
            metadata["format"],
            raw_w,
            raw_h,
            None,
            True,
            False,
            "原文件编码",
            None,
        )
        self.source = Entry(State(image), image, encoded, changed=False)
        self.current = self.source
        self.history, self.future = [], []
        self.previews = OrderedDict()
        self.revision = 0
        self.applied = (self.current, self.revision)
        self.cache = RenderCache()
        self.lock = threading.RLock()
        self.touched = time.monotonic()
        self.last_gesture = ""

    def check_revision(self, revision):
        if revision != self.revision:
            raise Conflict("图片已更新，请根据当前结果重新预览。")

    def options(self, state):
        dpi = self.metadata.get("dpi", (300, 300))
        if isinstance(dpi, (list, tuple)):
            dpi = dpi[0] if dpi else 300
        dpi = round(dpi) if isinstance(dpi, (float, int)) and 1 <= dpi <= 9600 else 300
        return replace(
            state.options
            or ExportOptions(
                format=self.metadata["format"],
                max_bytes=None,
                quality=95,
                min_quality=95,
                allow_quality=False,
                keep_exif=True,
                keep_icc=True,
            ),
            width=state.base.width,
            height=state.base.height,
            dpi=dpi,
        )

    def describe(self):
        entry = self.current
        return dict(
            id=self.id,
            revision=self.revision,
            name=self.metadata["name"],
            current=entry.info(),
            original=self.source.info(),
            image_url=f"/api/sessions/{self.id}/image?revision={self.revision}",
            original_url=f"/api/sessions/{self.id}/original",
            can_undo=bool(self.history),
            can_redo=bool(self.future),
            can_remove_marks=entry.tool in ("brush", "mosaic", "blur") and bool(self.history or entry.stroke_origin),
            dirty=entry is not self.source,
            enhancement=vars(entry.state.enhancement),
            compression=vars(self.options(entry.state)),
        )

    def preview(self, operation: Operation):
        with self.lock, RENDER_SLOTS:
            self.check_revision(operation.revision)
            params = PARAMETERS[operation.tool].model_validate(operation.params)
            key = hashlib.sha256(
                json.dumps(
                    [self.revision, operation.tool, params.model_dump()],
                    sort_keys=True,
                ).encode()
            ).hexdigest()[:32]
            if key not in self.previews:
                entry = self.propose(operation.tool, params)
                entry.image()
                self.previews[key] = entry
                while len(self.previews) > 2:
                    self.previews.popitem(last=False)
            entry = self.previews[key]
            return dict(
                preview_id=key,
                revision=self.revision,
                info=entry.info(),
                image_url=f"/api/sessions/{self.id}/previews/{key}",
                warning=entry.warning,
                can_apply=entry.changed,
            )

    def propose(self, tool, p):
        old = self.current.state
        state = State(old.base, [copy(m) for m in old.marks], copy(old.enhancement), old.options)
        if tool == "crop":
            if p.size and (min(p.size) < 1 or p.size[0] * p.size[1] > MAX_PIXELS):
                raise ValueError("模板尺寸超过服务允许的像素上限。")
            state.base, state.marks = crop_pixels(
                state.base,
                state.marks,
                p.box,
                output_size=p.size,
                allow_resize=p.allow_resize,
            )
        elif tool == "rotate":
            if p.angle == 0 and p.flip is None:
                return replace(self.current, changed=False, tool=tool)
            state.base, state.marks = transform_pixels(state.base, state.marks, p.angle, p.flip, p.expand)
        elif tool in ("brush", "mosaic", "blur"):
            state.base = paint_stroke(
                old.base,
                p.points,
                "erase" if tool == "brush" and p.erase else tool,
                p.size,
                p.color,
                p.opacity,
                p.block,
            )
        elif tool == "watermark":
            if p.multiple and len(state.marks) >= 10:
                raise ValueError("最多叠加 10 组水印，请先清除或撤销。")
            mark = Watermark(
                text=p.text,
                size=p.size,
                color=p.color,
                opacity=p.opacity,
                angle=p.angle,
                row_spacing=p.row_spacing,
                column_spacing=p.column_spacing,
                tile=True,
                text_bitmap=text_bitmap(p.text, p.font, p.size, p.color),
            )
            state.marks = [*state.marks, mark] if p.multiple else [mark]
        elif tool == "enhance":
            state.enhancement = Enhancement(**p.model_dump())
            if state.enhancement == old.enhancement:
                return replace(self.current, changed=False, tool=tool)
        elif tool == "clear_watermarks":
            if not state.marks:
                return replace(self.current, changed=False, tool=tool)
            state.marks = []
        elif tool == "compress":
            quality = p.quality if p.format in ("JPEG", "WEBP") else 100
            state.options = replace(
                self.options(state),
                **p.model_dump(exclude={"quality"}),
                quality=quality,
                min_quality=quality,
                max_bytes=None,
                allow_quality=False,
                allow_resize=False,
            )
            if state.options == old.options:
                return replace(self.current, changed=False, tool=tool)
        if state.base.width * state.base.height > MAX_PIXELS:
            raise ValueError("调整后的像素超过服务允许的上限。")
        image = self.cache.render(state.base, state.marks, state.enhancement, draft=True)
        encoded = compress(image, self.options(state), self.metadata)
        return Entry(state, image, encoded, tool=tool)

    def apply(self, data):
        with self.lock:
            self.check_revision(data.revision)
            entry = self.previews.get(data.preview_id)
            if entry is None:
                raise Conflict("预览已过期，请重新预览后应用。")
            if entry.changed:
                coalesce = entry.tool == "enhance" and data.gesture and self.last_gesture == data.gesture
                if not coalesce:
                    self.history.append(self.current)
                self.future.clear()
                if entry.tool in ("brush", "mosaic", "blur"):
                    entry.stroke_origin = self.current.stroke_origin or self.current
                self.current = entry
                self.revision += 1
                self.applied = (self.current, self.revision)
                self.last_gesture = data.gesture if entry.tool == "enhance" else ""
                self.trim_history()
            self.previews.clear()
            return self.describe()

    def trim_history(self):
        limit = int(os.environ.get("PHOTOCRAFT_HISTORY_MB", "128")) * 1024 * 1024
        while len(self.history) > 1:
            images = {}
            total = 0
            entries = [*self.history, self.current]
            if self.current.stroke_origin is not None and all(self.current.stroke_origin is not item for item in entries):
                entries.append(self.current.stroke_origin)
            for entry in entries:
                for image in (entry.state.base, entry.rendered):
                    images[id(image)] = image.width * image.height * 4
                total += len(entry.encoded.data)
            if sum(images.values()) + total <= limit and len(self.history) <= 20:
                break
            self.history.pop(0)

    def remove_strokes(self, revision, *, all_strokes=False):
        """Undo the trailing stroke group without stepping across other edits."""
        with self.lock:
            self.check_revision(revision)
            if self.current.tool not in ("brush", "mosaic", "blur"):
                return self.describe()
            if not all_strokes:
                if not self.history:
                    raise Conflict("上一笔已超出撤销记录，请长按移除当前全部笔迹。")
                return self.travel(revision)
            origin = self.current.stroke_origin
            if origin is None:
                return self.describe()
            self.future.append(self.current)
            while self.history and self.history[-1] is not origin:
                if self.history[-1].tool not in ("brush", "mosaic", "blur"):
                    break
                self.future.append(self.history.pop())
            if self.history and self.history[-1] is origin:
                self.history.pop()
            self.current = origin
            self.revision += 1
            self.applied = (self.current, self.revision)
            self.last_gesture = ""
            self.previews.clear()
            return self.describe()

    def travel(self, revision, redo=False):
        with self.lock:
            self.check_revision(revision)
            source, destination = (self.future, self.history) if redo else (self.history, self.future)
            if source:
                destination.append(self.current)
                self.current = source.pop()
                self.revision += 1
                self.applied = (self.current, self.revision)
            self.last_gesture = ""
            self.previews.clear()
            return self.describe()


class Editors:
    def __init__(self):
        self.items = {}
        self.lock = threading.RLock()
        self.limit = int(os.environ.get("PHOTOCRAFT_MAX_SESSIONS", "4"))
        self.ttl = int(os.environ.get("PHOTOCRAFT_SESSION_TTL", "3600"))

    def purge(self):
        with self.lock:
            now = time.monotonic()
            self.items = {key: item for key, item in self.items.items() if now - item.touched < self.ttl}

    def get(self, key):
        with self.lock:
            self.purge()
            editor = self.items.get(key)
            if editor is None:
                raise KeyError("编辑会话已过期，请重新打开图片。")
            editor.touched = time.monotonic()
            return editor

    def add(self, data, name):
        with self.lock, RENDER_SLOTS:
            self.purge()
            if len(self.items) >= self.limit:
                raise Conflict("当前编辑会话已满，请关闭其他照片或稍后再试。")
            with TemporaryDirectory(prefix="photocraft-") as folder:
                path = Path(folder) / "upload"
                path.write_bytes(data)
                with Image.open(path) as header:
                    if header.width * header.height > MAX_PIXELS:
                        raise ValueError("图片像素超过服务允许的上限。")
                image, metadata = load_image(path)
            metadata.update(name=name, path="")
            item = Editor(image, metadata)
            item.current.image()
            self.items[item.id] = item
            return item.describe()

    def remove(self, key):
        with self.lock:
            self.items.pop(key, None)


def demo_bytes():
    image = Image.new("RGB", (720, 900), "#dce8dc")
    draw = ImageDraw.Draw(image)
    for y in range(900):
        t = y / 900
        draw.line((0, y, 720, y), fill=(round(232 - t * 40), round(238 - t * 40), round(219 - t * 35)))
    draw.ellipse((50, 655, 670, 1250), fill="#344e62")
    draw.polygon(((290, 620), (430, 620), (470, 760), (360, 855), (250, 760)), fill="#efd1b6")
    draw.polygon(((245, 725), (360, 840), (475, 725), (510, 900), (210, 900)), fill="#faf8ee")
    draw.ellipse((175, 175, 545, 655), fill="#283338")
    draw.ellipse((190, 250, 530, 670), fill="#f1cfb0")
    draw.polygon(
        ((185, 440), (210, 250), (425, 205), (540, 365), (455, 325), (350, 330), (230, 410)), fill="#283338"
    )
    for x in (270, 420):
        draw.arc((x - 15, 425, x + 35, 455), 190, 345, fill="#51483f", width=7)
        draw.ellipse((x, 467, x + 12, 479), fill="#413b36")
    draw.line((360, 490, 352, 530, 372, 533), fill="#cd9e7e", width=5)
    draw.arc((315, 540, 405, 595), 10, 170, fill="#b87766", width=5)
    output = BytesIO()
    image.save(output, "JPEG", quality=95)
    return output.getvalue()
