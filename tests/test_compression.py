from dataclasses import replace
from io import BytesIO

import pytest
from PIL import Image

from photocraft.compression import (
    ConstraintError,
    ExportOptions,
    _encode,
    compress,
    save_verified,
    verify_bytes,
)


@pytest.mark.parametrize(
    "fmt,extension", [("JPEG", "jpg"), ("PNG", "png"), ("WEBP", "webp"), ("BMP", "bmp"), ("TIFF", "tiff")]
)
def test_actual_format_size_pixels_and_disk_decode(noise, tmp_path, fmt, extension):
    options = ExportOptions(format=fmt, width=59, height=83, max_bytes=100_000)
    result = compress(noise, options)
    target = tmp_path / f"output.{extension}"
    save_verified(result, target)
    assert target.stat().st_size == len(result.data) <= options.max_bytes
    with Image.open(target) as image:
        image.load()
        assert image.format == fmt
        assert image.size == (59, 83)
        if fmt in ("JPEG", "PNG", "TIFF", "BMP"):
            assert image.info["dpi"][0] == pytest.approx(300, abs=1)


def test_highest_quality_matches_actual_full_search(noise):
    options = ExportOptions(width=120, height=160, max_bytes=10_000, min_quality=30)
    result = compress(noise, options)
    assert result.quality < options.quality
    assert result.quality >= options.min_quality
    for quality in range(result.quality + 1, options.quality + 1):
        assert len(_encode(noise, options, quality, {})) > options.max_bytes


def test_nonmonotonic_quality_search(monkeypatch):
    from photocraft import compression

    encoded = []

    def encode(image, options, quality, metadata, colors=None):
        encoded.append(quality)
        # Quality 93 fits while lower qualities 92..91 do not.
        return b"x" * {95: 110, 94: 105, 93: 99, 92: 120, 91: 115, 90: 80}[quality]

    monkeypatch.setattr(compression, "_encode", encode)
    monkeypatch.setattr(compression, "verify_bytes", lambda result: None)
    result = compress(
        Image.new("RGBA", (10, 10)), ExportOptions(width=10, height=10, max_bytes=100, min_quality=90)
    )
    assert result.quality == 93
    assert encoded == [95, 94, 93]


def test_unachievable_limit_never_silently_changes_resolution(noise):
    options = ExportOptions(width=120, height=160, max_bytes=1000, min_quality=80, allow_resize=False)
    with pytest.raises(ConstraintError, match="已禁止降低分辨率") as error:
        compress(noise, options)
    assert error.value.smallest > 1000


def test_resize_requires_explicit_consent(noise):
    result = compress(
        noise, ExportOptions(width=120, height=160, max_bytes=2500, min_quality=80, allow_resize=True)
    )
    assert result.resized
    assert result.width < 120 and result.height < 160
    assert len(result.data) <= 2500


def test_quality_reduction_requires_consent(noise):
    options = ExportOptions(width=120, height=160, max_bytes=10_000, allow_quality=False)
    with pytest.raises(ConstraintError):
        compress(noise, options)


def test_png_lossless_when_quality_changes_disallowed(noise):
    result = compress(
        noise, ExportOptions(format="PNG", width=120, height=160, max_bytes=None, allow_quality=False)
    )
    with Image.open(BytesIO(result.data)) as image:
        assert image.convert("RGBA").tobytes() == noise.tobytes()
    assert "无损" in result.strategy


def test_alpha_flattening_is_encoded_and_not_just_preview():
    source = Image.new("RGBA", (12, 12), (255, 0, 0, 0))
    options = ExportOptions(
        format="PNG", width=12, height=12, max_bytes=None, keep_alpha=False, background="#123456"
    )
    result = compress(source, options)
    with Image.open(BytesIO(result.data)) as image:
        assert image.convert("RGB").getpixel((0, 0)) == (18, 52, 86)


def test_corrupt_payload_never_replaces_existing_file(noise, tmp_path):
    result = compress(noise, ExportOptions(width=20, height=30))
    path = tmp_path / "original.jpg"
    path.write_bytes(b"original")
    with pytest.raises(Exception):
        save_verified(replace(result, data=b"invalid"), path, overwrite=True)
    assert path.read_bytes() == b"original"
    with pytest.raises(FileExistsError):
        save_verified(result, path)
    assert path.read_bytes() == b"original"
    save_verified(result, path, overwrite=True)
    assert path.read_bytes() == result.data
    assert not list(tmp_path.glob(".photocraft-*"))


@pytest.mark.parametrize("outcome", ["saved", "conflict", "denied"])
def test_windows_export_without_hard_links_preserves_other_files_and_cleans_up(
    noise, tmp_path, monkeypatch, outcome
):
    from photocraft import compression

    directory = tmp_path / "导出 图片"
    directory.mkdir()
    target = directory / "照片.jpg"
    result = compress(noise, ExportOptions(width=20, height=30))
    native_windows = compression.sys.platform == "win32"
    rename = compression.os.rename
    monkeypatch.setattr(compression.sys, "platform", "win32")

    def no_links(*args, **kwargs):
        raise OSError("This filesystem does not support hard links")

    def publish(source, destination):
        if outcome == "denied":
            raise PermissionError("Access denied")
        if outcome == "conflict":
            target.write_bytes(b"another application's file")
            if not native_windows:
                # Emulate Windows' exclusive rename when running this regression on POSIX.
                raise FileExistsError(destination)
        return rename(source, destination)

    monkeypatch.setattr(compression.os, "link", no_links)
    monkeypatch.setattr(compression.os, "rename", publish)
    if outcome == "saved":
        save_verified(result, target)
        assert target.read_bytes() == result.data
    elif outcome == "conflict":
        with pytest.raises(FileExistsError):
            save_verified(result, target)
        assert target.read_bytes() == b"another application's file"
    else:
        with pytest.raises(PermissionError):
            save_verified(result, target)
        assert not target.exists()
    assert not list(directory.glob(".photocraft-*"))


def test_reject_fake_extension_and_incorrect_metadata(noise, tmp_path):
    result = compress(noise, ExportOptions(width=20, height=30))
    with pytest.raises(ValueError, match="扩展名"):
        save_verified(result, tmp_path / "image.png")
    with pytest.raises(ValueError, match="格式或尺寸"):
        verify_bytes(replace(result, width=21))
    with pytest.raises(ValueError, match="上限"):
        verify_bytes(replace(result, max_bytes=1))


@pytest.mark.parametrize(
    "changes",
    [
        dict(width=0),
        dict(height=40000),
        dict(width=30000, height=30000),
        dict(min_quality=96, quality=95),
        dict(dpi=0),
        dict(format="GIF"),
        dict(max_bytes=0),
        dict(resampling="fake"),
    ],
)
def test_invalid_constraints_fail_before_encoding(changes):
    with pytest.raises(ValueError):
        replace(ExportOptions(), **changes).validate()


@pytest.mark.parametrize("fmt", ["JPEG", "WEBP"])
def test_quality_changes_real_size_without_changing_dimensions(noise, fmt):
    options = ExportOptions(format=fmt, width=noise.width, height=noise.height, max_bytes=None)
    high = compress(noise, options)
    low = compress(noise, replace(options, quality=40))
    assert len(low.data) < len(high.data)
    assert (low.width, low.height) == (high.width, high.height) == noise.size
    assert high.lossy and low.lossy
    assert compress(noise, replace(options, quality=100)).lossy


@pytest.mark.parametrize("fmt", ["PNG", "BMP", "TIFF"])
def test_lossless_formats_report_lossless_when_pixels_are_preserved(noise, fmt):
    source = noise.convert("RGB").convert("RGBA")
    result = compress(
        source,
        ExportOptions(
            format=fmt,
            width=source.width,
            height=source.height,
            max_bytes=None,
        ),
    )
    assert not result.lossy and not result.loss_reasons
    with Image.open(BytesIO(result.data)) as decoded:
        assert decoded.convert("RGBA").tobytes() == source.tobytes()


def test_png_palette_reduction_is_reported_as_lossy(noise):
    options = ExportOptions(format="PNG", width=noise.width, height=noise.height, max_bytes=None)
    full = compress(noise, options)
    reduced = _encode(noise, options, None, {}, colors=256)
    assert len(reduced) < len(full.data)
    result = compress(noise, replace(options, max_bytes=len(reduced)))
    assert result.lossy and "调色板减色" in result.loss_reasons
    assert len(result.data) <= len(reduced)


def test_lossless_codec_reports_transparency_removal_and_resizing():
    source = Image.new("RGBA", (40, 50), (100, 120, 140, 80))
    options = ExportOptions(format="PNG", width=40, height=50, max_bytes=None)
    assert not compress(source, options).lossy
    flattened = compress(source, replace(options, keep_alpha=False))
    assert flattened.lossy and "透明背景已填充" in flattened.loss_reasons
    resized = compress(source, replace(options, width=20, height=25))
    assert resized.lossy and "像素缩放" in resized.loss_reasons


def test_cancelled_search_stops_before_the_next_encoder_attempt(noise, monkeypatch):
    from photocraft import compression

    attempts = []
    real_encode = compression._encode

    def encode(*args, **kwargs):
        attempts.append(args[2])
        return real_encode(*args, **kwargs)

    def check_current(message):
        if attempts:
            raise InterruptedError("设置已改变")

    monkeypatch.setattr(compression, "_encode", encode)
    with pytest.raises(InterruptedError):
        compress(
            noise, ExportOptions(width=noise.width, height=noise.height, max_bytes=1), progress=check_current
        )
    assert attempts == [95]
