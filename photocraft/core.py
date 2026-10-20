"""Image operations in source pixels; deliberately independent of Qt."""

from __future__ import annotations

import math
from copy import copy
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

RESAMPLING = {
    name.title(): getattr(Image.Resampling, name.upper())
    for name in ("nearest", "bilinear", "bicubic", "lanczos")
}
SUPPORTED = {"JPEG", "PNG", "WEBP", "BMP", "TIFF"}


def mm_to_px(mm: float, dpi: float) -> int:
    return round(mm / 25.4 * dpi)


def load_image(path: str | Path) -> tuple[Image.Image, dict]:
    source_data = Path(path).read_bytes()
    with Image.open(BytesIO(source_data)) as source:
        if source.format not in SUPPORTED:
            raise ValueError("不支持此图片格式，请使用 JPEG、PNG、WEBP、BMP 或 TIFF。")
        source.load()
        oriented = ImageOps.exif_transpose(source)
        exif = oriented.getexif()
        for key in (274, 256, 257, 40962, 40963):
            if key in exif:
                del exif[key]
        metadata = {
            "path": str(path),
            "name": Path(path).name,
            "format": source.format,
            "size": len(source_data),
            "source_data": source_data,
            "encoded_dimensions": source.size,
            "dimensions": oriented.size,
            "dpi": source.info.get("dpi"),
            "icc_profile": source.info.get("icc_profile"),
            "exif": exif.tobytes() if exif else None,
        }
        # Convert a profile-aware source to sRGB for consistent editing when possible.
        if metadata["icc_profile"]:
            try:
                import io

                from PIL import ImageCms

                srgb = ImageCms.createProfile("sRGB")
                profile_source = (
                    oriented if oriented.mode in ("RGB", "CMYK", "L", "LAB") else oriented.convert("RGB")
                )
                rgb = ImageCms.profileToProfile(
                    profile_source,
                    ImageCms.ImageCmsProfile(io.BytesIO(metadata["icc_profile"])),
                    srgb,
                    outputMode="RGB",
                )
                rgb.putalpha(oriented.convert("RGBA").getchannel("A"))
                oriented = rgb
                metadata["icc_profile"] = ImageCms.ImageCmsProfile(srgb).tobytes()
            except (OSError, ValueError, ImageCms.PyCMSError):
                # Do not attach a source CMYK/invalid profile to newly encoded RGB pixels.
                metadata["icc_profile"] = None
        return oriented.convert("RGBA"), metadata


@dataclass
class Watermark:
    text: str = "仅用于报名审核"
    x: float = 0
    y: float = 0
    size: int = 28
    color: str = "#64748b"
    opacity: float = 0.28
    angle: float = 30
    tile: bool = True
    font: str = ""
    row_spacing: int = 60
    column_spacing: int = 80
    text_bitmap: Image.Image | None = None

    def validate_bitmap_size(self, size):
        width, height = size
        theta = math.radians(self.angle)
        rotated_w = abs(width * math.cos(theta)) + abs(height * math.sin(theta))
        rotated_h = abs(width * math.sin(theta)) + abs(height * math.cos(theta))
        if rotated_w * rotated_h > 16_000_000:
            raise ValueError("水印尺寸过大，请减小字号或缩短文字。")

    def bitmap(self) -> Image.Image:
        if self.text_bitmap is not None:
            layer = self.text_bitmap.copy()
        else:
            try:
                font = (
                    ImageFont.truetype(self.font, self.size)
                    if self.font
                    else ImageFont.load_default(size=self.size)
                )
            except OSError:
                font = ImageFont.load_default(size=self.size)
            box = font.getbbox(self.text or " ")
            layer = Image.new("RGBA", (max(1, box[2] - box[0] + 8), max(1, box[3] - box[1] + 8)))
            ImageDraw.Draw(layer).text((4 - box[0], 4 - box[1]), self.text, font=font, fill=self.color)
        layer = layer.convert("RGBA")
        self.validate_bitmap_size(layer.size)
        layer.putalpha(layer.getchannel("A").point(lambda a: round(a * self.opacity)))
        return layer.rotate(self.angle, expand=True, resample=Image.Resampling.BICUBIC)


def tiled_layer(size, layer, step_x, step_y, x=0, y=0):
    """Repeat a period by doubling strips, avoiding per-glyph loops on large photos."""
    width, height = size
    period = Image.new("RGBA", (min(width, step_x), min(height, step_y)))
    start_x, start_y = round(x) % step_x - step_x, round(y) % step_y - step_y
    for cy in (start_y, start_y + step_y):
        for cx in (start_x, start_x + step_x):
            period.paste(layer, (cx, cy))
    result = Image.new("RGBA", size)
    result.paste(period, (0, 0))
    filled_w, filled_h = period.size
    while filled_w < width:
        count = min(filled_w, width - filled_w)
        result.paste(result.crop((0, 0, count, filled_h)), (filled_w, 0))
        filled_w += count
    while filled_h < height:
        count = min(filled_h, height - filled_h)
        result.paste(result.crop((0, 0, width, count)), (0, filled_h))
        filled_h += count
    return result


def watermark_preview(size, watermarks, maximum=1600):
    """Bound preview work independently of source resolution; export uses compose."""
    scale = min(1, maximum / max(size))
    preview_size = tuple(max(1, round(d * scale)) for d in size)
    result = Image.new("RGBA", preview_size)
    for mark in watermarks:
        layer = mark.bitmap()
        step_x = max(1, round((layer.width + mark.column_spacing) * scale))
        step_y = max(1, round((layer.height + mark.row_spacing) * scale))
        if scale < 1:
            layer = layer.resize(
                (
                    min(step_x, max(1, round(layer.width * scale))),
                    min(step_y, max(1, round(layer.height * scale))),
                ),
                Image.Resampling.LANCZOS,
            )
        if mark.tile:
            result.alpha_composite(
                tiled_layer(preview_size, layer, step_x, step_y, mark.x * scale, mark.y * scale)
            )
        else:
            result.alpha_composite(layer, (round(mark.x * scale), round(mark.y * scale)))
    return result, scale


def compose(base: Image.Image, watermarks: list[Watermark]) -> Image.Image:
    result = base.convert("RGBA").copy()
    for mark in watermarks:
        layer = mark.bitmap()
        if mark.tile:
            step_x = layer.width + max(0, mark.column_spacing)
            step_y = layer.height + max(0, mark.row_spacing)
            result.alpha_composite(tiled_layer(base.size, layer, step_x, step_y, mark.x, mark.y))
        else:
            result.alpha_composite(layer, (round(mark.x), round(mark.y)))
    return result


@dataclass
class Enhancement:
    brightness: float = 1
    contrast: float = 1
    saturation: float = 1
    sharpness: float = 1
    temperature: float = 0
    gamma: float = 1
    autocontrast: bool = False
    white_balance: bool = False
    denoise: float = 0
    equalize: float = 0


def enhance(image: Image.Image, settings: Enhancement) -> Image.Image:
    if settings == Enhancement():
        return image.copy()
    alpha = image.getchannel("A")
    result = image.convert("RGB")
    if settings.denoise:
        result = Image.blend(result, result.filter(ImageFilter.MedianFilter(3)), settings.denoise)
    if settings.autocontrast:
        result = ImageOps.autocontrast(result, cutoff=0.5)
    if settings.equalize:
        # Equalize luminance, retaining chroma rather than shifting skin hues per channel.
        y, cb, cr = result.convert("YCbCr").split()
        balanced = Image.merge("YCbCr", (ImageOps.equalize(y), cb, cr)).convert("RGB")
        result = Image.blend(result, balanced, settings.equalize)
    if settings.white_balance or settings.temperature or settings.gamma != 1:
        pixels = np.asarray(result, dtype=np.float32).copy()
        if settings.white_balance:
            averages = pixels.mean(axis=(0, 1))
            pixels *= averages.mean() / np.maximum(averages, 1)
        temperature = 0 if settings.white_balance else settings.temperature
        pixels[:, :, 0] *= 1 + temperature * 0.25
        pixels[:, :, 2] *= 1 - temperature * 0.25
        pixels = np.clip(pixels, 0, 255) / 255
        pixels = np.power(pixels, 1 / settings.gamma)
        result = Image.fromarray(np.uint8(np.clip(pixels * 255, 0, 255)))
    for cls, value in (
        (ImageEnhance.Brightness, settings.brightness),
        (ImageEnhance.Contrast, 1 if settings.autocontrast else settings.contrast),
        (ImageEnhance.Color, settings.saturation),
        (ImageEnhance.Sharpness, settings.sharpness),
    ):
        if value != 1:
            result = cls(result).enhance(value)
    result.putalpha(alpha)
    return result


def paint_stroke(
    image: Image.Image,
    points: list[tuple[float, float]],
    mode: str,
    size: int,
    color: str,
    opacity: float,
    block: int = 12,
) -> Image.Image:
    """Commit a source-pixel stroke; effect pixels, not the displayed mask, are exported."""
    if not points:
        return image.copy()
    # Allocate masks and run filters only near the stroke. The final image is
    # still independent of the source so history and undo retain their pixels.
    xy = [(round(x), round(y)) for x, y in points]
    radius = size / 2
    left = max(0, math.floor(min(x for x, _ in xy) - radius))
    top = max(0, math.floor(min(y for _, y in xy) - radius))
    right = min(image.width, math.ceil(max(x for x, _ in xy) + radius) + 1)
    bottom = min(image.height, math.ceil(max(y for _, y in xy) + radius) + 1)
    result = image.copy()
    if right <= left or bottom <= top or opacity == 0:
        return result
    box = (left, top, right, bottom)
    region = image.crop(box)
    mask = Image.new("L", region.size)
    draw = ImageDraw.Draw(mask)
    local = [(x - left, y - top) for x, y in xy]
    alpha = round(opacity * 255)
    draw.line(local, fill=alpha, width=size, joint="curve")
    for x, y in local:
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=alpha)
    if mode == "mosaic":
        # Align to the image origin so separate strokes share the same grid.
        x0, y0 = left // block * block, top // block * block
        x1 = min(image.width, math.ceil(right / block) * block)
        y1 = min(image.height, math.ceil(bottom / block) * block)
        tile = image.crop((x0, y0, x1, y1))
        effect = tile.reduce(block)
        effect = effect.resize((effect.width * block, effect.height * block), Image.Resampling.NEAREST)
        effect = effect.crop((left - x0, top - y0, right - x0, bottom - y0))
    elif mode == "blur":
        blur_radius = max(1, block / 2)
        # Pillow's Gaussian approximation has bounded support; this halo avoids
        # seams where the processed region meets untouched source pixels.
        halo = math.ceil(blur_radius * 4) + 2
        x0, y0 = max(0, left - halo), max(0, top - halo)
        x1, y1 = min(image.width, right + halo), min(image.height, bottom + halo)
        effect = image.crop((x0, y0, x1, y1)).filter(ImageFilter.GaussianBlur(blur_radius))
        effect = effect.crop((left - x0, top - y0, right - x0, bottom - y0))
    elif mode == "erase":
        effect = Image.new("RGBA", region.size)
    else:
        effect = Image.new("RGBA", region.size, color)
    result.paste(Image.composite(effect, region, mask), (left, top))
    return result


def crop_pixels(base, watermarks, box, *, output_size=None, allow_resize=False):
    """Shared geometry for crop previews and committed crops, without history copies."""
    left, top, right, bottom = map(round, box)
    left, top = max(0, left), max(0, top)
    right, bottom = min(base.width, right), min(base.height, bottom)
    if right <= left or bottom <= top:
        raise ValueError("裁剪区域不能为空。")
    if output_size is not None:
        width, height = output_size
        if (
            type(width) is not int
            or type(height) is not int
            or not (1 <= width <= 30000 and 1 <= height <= 30000)
            or width * height > 100_000_000
        ):
            raise ValueError("裁剪输出尺寸无效。")
        if not allow_resize and (right - left, bottom - top) != output_size:
            raise ValueError(
                f"裁剪区域为 {right - left} × {bottom - top} px，模板要求 {width} × {height} px。\n"
                "未勾选“允许缩放”，不能放大或缩小到模板尺寸。\n"
                "请选择像素足够的原图重新裁剪，或勾选“允许缩放”。放大可能模糊，缩小会丢失细节。"
            )
    cropped = base.crop((left, top, right, bottom))
    source_w, source_h = cropped.size
    if output_size is not None and cropped.size != output_size:
        cropped = cropped.resize(output_size, Image.Resampling.LANCZOS)
    scale_x, scale_y = cropped.width / source_w, cropped.height / source_h
    marks = []
    for existing in watermarks:
        mark = copy(existing)
        mark.x, mark.y = (mark.x - left) * scale_x, (mark.y - top) * scale_y
        if scale_x != 1 or scale_y != 1:
            glyph = copy(mark)
            glyph.angle, glyph.opacity = 0, 1
            bitmap = glyph.bitmap()
            bitmap_size = (max(1, round(bitmap.width * scale_x)), max(1, round(bitmap.height * scale_y)))
            mark.validate_bitmap_size(bitmap_size)
            mark.text_bitmap = bitmap.resize(
                bitmap_size,
                Image.Resampling.LANCZOS,
            )
            mark.size = max(1, round(mark.size * (scale_x + scale_y) / 2))
            mark.column_spacing = max(0, round(mark.column_spacing * scale_x))
            mark.row_spacing = max(0, round(mark.row_spacing * scale_y))
        marks.append(mark)
    return cropped, marks


@dataclass
class Document:
    original: Image.Image
    metadata: dict
    base: Image.Image = field(init=False)
    watermarks: list[Watermark] = field(default_factory=list)
    enhancement: Enhancement = field(default_factory=Enhancement)
    revision: int = 0
    history: list = field(default_factory=list)
    future: list = field(default_factory=list)

    def __post_init__(self):
        self.base = self.original.copy()

    @classmethod
    def open(cls, path):
        image, meta = load_image(path)
        return cls(image, meta)

    def snapshot(self, *, copy_base=True):
        # Render workers borrow the immutable base; checkpoints keep independent pixels.
        base = self.base.copy() if copy_base else self.base
        return base, [copy(mark) for mark in self.watermarks], copy(self.enhancement)

    def checkpoint(self):
        self.history.append(self.snapshot())
        self.future.clear()
        # Bound memory, always allowing at least one undo.
        budget = 256 * 1024 * 1024
        total = sum(image.width * image.height * 4 for image, _, _ in self.history)
        while len(self.history) > 1 and total > budget:
            image, _, _ = self.history.pop(0)
            total -= image.width * image.height * 4
        self.revision += 1

    def undo(self):
        if self.history:
            self.future.append(self.snapshot())
            self.base, self.watermarks, self.enhancement = self.history.pop()
            self.revision += 1

    def redo(self):
        if self.future:
            self.history.append(self.snapshot())
            self.base, self.watermarks, self.enhancement = self.future.pop()
            self.revision += 1

    def render(self):
        return compose(enhance(self.base, self.enhancement), self.watermarks)

    def crop(self, box, *, output_size=None, allow_resize=False):
        cropped, marks = crop_pixels(
            self.base, self.watermarks, box, output_size=output_size, allow_resize=allow_resize
        )
        self.checkpoint()
        self.base, self.watermarks = cropped, marks

    def transform(self, angle=0, flip=None, expand=True):
        base, marks = transform_pixels(self.base, self.watermarks, angle, flip, expand)
        self.checkpoint()
        self.base, self.watermarks = base, marks


def transform_pixels(base, watermarks, angle=0, flip=None, expand=True):
    """Transform immutable pixels and copied editable watermarks without history copies."""
    if angle and flip:
        base, watermarks = transform_pixels(base, watermarks, angle, None, expand)
        return transform_pixels(base, watermarks, 0, flip, expand)
    if flip == "both":
        base, watermarks = transform_pixels(base, watermarks, 0, "horizontal", expand)
        return transform_pixels(base, watermarks, 0, "vertical", expand)
    watermarks = [copy(mark) for mark in watermarks]
    old_w, old_h = base.size
    if flip:
        base = ImageOps.mirror(base) if flip == "horizontal" else ImageOps.flip(base)
    else:
        base = base.rotate(angle, expand=expand, resample=Image.Resampling.BICUBIC)
    # Keep watermark objects editable through geometry transformations.
    for mark in watermarks:
        layer = mark.bitmap()
        cx, cy = mark.x + layer.width / 2, mark.y + layer.height / 2
        if flip:
            cx, cy = (old_w - cx, cy) if flip == "horizontal" else (cx, old_h - cy)
        else:
            theta = math.radians(angle)
            dx, dy = cx - old_w / 2, cy - old_h / 2
            cx = base.width / 2 + dx * math.cos(theta) + dy * math.sin(theta)
            cy = base.height / 2 - dx * math.sin(theta) + dy * math.cos(theta)
            mark.angle += angle
        layer = mark.bitmap()
        mark.x, mark.y = cx - layer.width / 2, cy - layer.height / 2
    return base, watermarks
