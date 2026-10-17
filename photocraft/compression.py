"""Measured encoding, explicit constraints and verified atomic export."""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image

from .core import RESAMPLING, SUPPORTED


@dataclass(frozen=True)
class ExportOptions:
    format: str = "JPEG"
    width: int = 295
    height: int = 413
    dpi: int = 300
    max_bytes: int | None = 100 * 1024
    quality: int = 95
    min_quality: int = 40
    allow_quality: bool = True
    allow_resize: bool = False
    resampling: str = "Lanczos"
    background: str = "#ffffff"
    keep_alpha: bool = True
    keep_exif: bool = False
    keep_icc: bool = True

    def validate(self):
        if self.format not in SUPPORTED:
            raise ValueError("不支持的输出格式。")
        if not (1 <= self.width <= 30000 and 1 <= self.height <= 30000):
            raise ValueError("宽高必须在 1–30000 px 范围内。")
        if self.width * self.height > 100_000_000:
            raise ValueError("输出像素总数不能超过一亿。")
        if not (1 <= self.min_quality <= self.quality <= 100):
            raise ValueError("质量须满足 1 ≤ 最低质量 ≤ 起始质量 ≤ 100。")
        if self.max_bytes is not None and self.max_bytes < 1:
            raise ValueError("文件大小上限必须大于零。")
        if not 1 <= self.dpi <= 9600:
            raise ValueError("DPI 必须在 1–9600 范围内。")
        if self.resampling not in RESAMPLING:
            raise ValueError("未知缩放算法。")


@dataclass(frozen=True)
class EncodedImage:
    data: bytes
    format: str
    width: int
    height: int
    quality: int | None
    compliant: bool
    resized: bool
    strategy: str
    max_bytes: int | None
    loss_reasons: tuple[str, ...] = ()

    @property
    def lossy(self):
        return bool(self.loss_reasons)


class ConstraintError(ValueError):
    def __init__(self, message: str, smallest: int | None = None):
        super().__init__(message)
        self.smallest = smallest


def _encode(image, options, quality, metadata, colors=None):
    image = image.copy()
    fmt = options.format
    if (fmt in ("JPEG", "BMP") or not options.keep_alpha) and image.mode != "RGB":
        flattened = Image.new("RGBA", image.size, options.background)
        flattened.alpha_composite(image.convert("RGBA"))
        image = flattened.convert("RGB")
    kwargs = {}
    if fmt in ("JPEG", "PNG", "TIFF", "BMP"):
        kwargs["dpi"] = (options.dpi, options.dpi)
    if options.keep_icc and metadata.get("icc_profile") and fmt != "BMP":
        kwargs["icc_profile"] = metadata["icc_profile"]
    if options.keep_exif and metadata.get("exif") and fmt in ("JPEG", "PNG", "WEBP", "TIFF"):
        exif = Image.Exif()
        exif.load(metadata["exif"])
        for tag in (274, 256, 257, 40962, 40963):
            if tag in exif:
                del exif[tag]
        # Preserve camera/date/GPS data when explicitly requested, updating the ExifIFD dimensions.
        if 34665 in exif:
            details = exif.get_ifd(34665)
            details[40962], details[40963] = image.size
        kwargs["exif"] = exif.tobytes()
    if fmt == "JPEG":
        kwargs.update(quality=quality, optimize=True, subsampling=0 if quality >= 90 else 2)
    elif fmt == "WEBP":
        kwargs.update(quality=quality, method=6)
    elif fmt == "PNG":
        kwargs.update(optimize=True, compress_level=9)
        if colors:
            image = image.quantize(colors=colors, method=Image.Quantize.FASTOCTREE)
    elif fmt == "TIFF":
        kwargs["compression"] = "tiff_deflate"
    output = BytesIO()
    image.save(output, format=fmt, **kwargs)
    return output.getvalue()


def compress(
    image: Image.Image,
    options: ExportOptions,
    metadata: dict | None = None,
    progress: Callable[[str], None] | None = None,
) -> EncodedImage:
    options.validate()
    metadata = metadata or {}
    width, height = options.width, options.height
    smallest = None
    loses_alpha = (options.format in ("JPEG", "BMP") or not options.keep_alpha) and (
        "A" in image.getbands() and image.getchannel("A").getextrema()[0] < 255
    )
    while True:
        # Reuse immutable rendered pixels when compression does not resize them.
        resized_image = (
            image
            if image.size == (width, height)
            else image.resize((width, height), RESAMPLING[options.resampling])
        )
        # Flatten once per resolution, rather than once for every quality candidate.
        if options.format in ("JPEG", "BMP") or not options.keep_alpha:
            flattened = Image.new("RGBA", resized_image.size, options.background)
            flattened.alpha_composite(resized_image.convert("RGBA"))
            resized_image = flattened.convert("RGB")
        if options.format in ("JPEG", "WEBP"):
            # Descending exhaustive search finds the highest feasible quality even when
            # actual encoder sizes are non-monotonic. At most 100 attempts per size.
            qualities = (
                range(options.quality, options.min_quality - 1, -1)
                if options.allow_quality
                else [options.quality]
            )
            candidates = [(quality, None, f"质量 {quality}") for quality in qualities]
        elif options.format == "PNG":
            candidates = [(None, None, "PNG 无损优化")]
            if options.allow_quality:
                # Explicit palette reduction; never present PNG compression as JPEG quality.
                floor = max(2, round(256 * options.min_quality / 100))
                palette = sorted({256, 192, 128, 96, 64, 32, 16, floor}, reverse=True)
                candidates += [(None, n, f"PNG 调色板 {n} 色（有损）") for n in palette if n >= floor]
        else:
            candidates = [(None, None, "无损编码")]
        for quality, colors, strategy in candidates:
            if progress:
                progress(f"编码 {width} × {height} · {strategy}")
            data = _encode(resized_image, options, quality, metadata, colors)
            smallest = len(data) if smallest is None else min(smallest, len(data))
            if options.max_bytes is None or len(data) <= options.max_bytes:
                losses = []
                if options.format in ("JPEG", "WEBP"):
                    losses.append("有损编码")
                if colors:
                    losses.append("调色板减色")
                if loses_alpha:
                    losses.append("透明背景已填充")
                if image.size != (width, height):
                    losses.append("像素缩放")
                result = EncodedImage(
                    data,
                    options.format,
                    width,
                    height,
                    quality,
                    True,
                    (width, height) != (options.width, options.height),
                    strategy,
                    options.max_bytes,
                    tuple(losses),
                )
                verify_bytes(result)
                return result
        if not options.allow_resize or (width, height) == (1, 1):
            break
        width, height = max(1, int(width * 0.85)), max(1, int(height * 0.85))
    suffix = "已禁止降低分辨率。" if not options.allow_resize else "即使继续缩小也无法满足。"
    raise ConstraintError(
        f"无法满足大小限制。最小实测 {smallest / 1024:.2f} KB；{suffix}"
        "请放宽大小限制、降低最低质量或调整格式。",
        smallest,
    )


def verify_bytes(result: EncodedImage):
    if result.max_bytes is not None and len(result.data) > result.max_bytes:
        raise ValueError("编码结果超过大小上限。")
    with Image.open(BytesIO(result.data)) as image:
        if image.format != result.format or image.size != (result.width, result.height):
            raise ValueError("导出格式或尺寸校验失败。")
        image.verify()
    with Image.open(BytesIO(result.data)) as image:
        image.load()


def save_verified(result: EncodedImage, path: str | Path, *, overwrite=False):
    """Validate bytes and on-disk decode before publishing; preserve existing file on failure."""
    path = Path(path)
    extensions = {
        "JPEG": {".jpg", ".jpeg"},
        "PNG": {".png"},
        "WEBP": {".webp"},
        "BMP": {".bmp"},
        "TIFF": {".tif", ".tiff"},
    }
    if path.suffix.lower() not in extensions[result.format]:
        raise ValueError("文件扩展名与真实编码格式不匹配。")
    if path.exists() and not overwrite:
        raise FileExistsError(f"文件已存在：{path.name}")
    verify_bytes(result)
    fd, temp_name = tempfile.mkstemp(prefix=".photocraft-", suffix=path.suffix, dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(result.data)
            stream.flush()
            os.fsync(stream.fileno())
        if Path(temp_name).stat().st_size != len(result.data):
            raise OSError("写入大小与编码结果不一致。")
        with Image.open(temp_name) as check:
            check.load()
            if check.format != result.format or check.size != (result.width, result.height):
                raise OSError("磁盘文件校验失败。")
        if overwrite:
            os.replace(temp_name, path)
        elif sys.platform == "win32":
            # Windows rename refuses existing destinations and also works without hard links.
            os.rename(temp_name, path)
        else:
            # Exclusive creation via link avoids a check/replace race overwriting a new file.
            os.link(temp_name, path)
            os.unlink(temp_name)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
