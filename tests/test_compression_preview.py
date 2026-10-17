from io import BytesIO
from threading import Event

import pytest
from PIL import Image
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog
from test_ui import wait_for, window

from photocraft import window as module
from photocraft.core import Document


@pytest.fixture
def editor(app):
    result = window(app)
    result.load_demo()
    wait_for(app, lambda: result.live_size_result is not None and not result.jobs)
    yield result
    result.doc.revision = 0
    result.close()
    wait_for(app, lambda: not result.jobs)


def ready(editor):
    return editor.preview_result is not None and not editor.jobs and not editor.compression_timer.isActive()


@pytest.mark.parametrize(
    "fmt,extension",
    [
        ("JPEG", "jpg"),
        ("PNG", "png"),
        ("WEBP", "webp"),
        ("BMP", "bmp"),
        ("TIFF", "tiff"),
    ],
)
def test_automatic_preview_apply_and_save_use_the_same_real_bytes(
    app,
    editor,
    tmp_path,
    monkeypatch,
    fmt,
    extension,
):
    original_info = editor.modified_info.text()
    original_pixels = editor.doc.base.tobytes()
    editor.out_format.setCurrentText(fmt)
    editor.select_tool("export")
    wait_for(app, lambda: ready(editor))
    result = editor.preview_result
    text = editor.preview_info.text()
    assert fmt in text and f"{len(result.data):,} 字节" in text
    assert ("有损" if fmt in ("JPEG", "WEBP") else "无损") in text
    assert editor.modified_info.text() == original_info  # Adjustments are only previews.
    assert max(editor.encoded_preview_image.size) <= 1600

    def no_encoding(*args, **kwargs):
        pytest.fail("应用或保存有效预览不应再次编码")

    monkeypatch.setattr(module, "compress", no_encoding)
    editor.apply_button.click()
    assert editor.applied_compression is result
    assert editor.live_size_result == (len(result.data), result.width, result.height, fmt)
    assert fmt in editor.modified_info.text().splitlines()[0]
    assert f"{len(result.data):,} 字节" in editor.modified_info.text().splitlines()[0]
    assert editor.doc.base.tobytes() == original_pixels  # Keep full-quality editing pixels.
    path = tmp_path / f"applied.{extension}"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), ""))
    editor.request_save()
    wait_for(app, lambda: path.exists() and not editor.jobs)
    assert path.read_bytes() == result.data
    with Image.open(path) as saved:
        assert saved.format == fmt and saved.size == editor.doc.base.size


def test_next_preview_preserves_last_applied_footer_until_apply(app, editor):
    editor.select_tool("export")
    wait_for(app, lambda: ready(editor))
    editor.apply_compression()
    before = editor.modified_info.text()
    editor.out_format.setCurrentText("PNG")
    wait_for(app, lambda: ready(editor))
    assert editor.modified_info.text() == before
    editor.apply_compression()
    assert editor.modified_info.text() != before
    assert editor.modified_info.text().splitlines()[0].endswith("PNG")
    editor.select_tool("enhance")
    editor.enhance_sliders["brightness"].setValue(125)
    wait_for(app, lambda: editor.live_size_result is not None and not editor.jobs)
    assert editor.applied_compression is None
    assert editor.modified_info.text().splitlines()[0].endswith("PNG")


def test_preview_encoding_failure_is_inline_and_preserves_applied_footer(app, editor, monkeypatch):
    errors = []
    editor.error = errors.append
    editor.select_tool("export")
    wait_for(app, lambda: ready(editor))
    editor.apply_compression()
    before = editor.modified_info.text()
    real_compress = module.compress

    def failed(*args, **kwargs):
        raise OSError("编码器失败")

    monkeypatch.setattr(module, "compress", failed)
    editor.out_format.setCurrentText("PNG")
    wait_for(app, lambda: "预览失败" in editor.preview_info.text() and not editor.jobs)
    assert not errors and editor.modified_info.text() == before
    assert editor.preview_result is None and not editor.export_options().allow_resize
    monkeypatch.setattr(module, "compress", real_compress)
    editor.invalidate_export()
    wait_for(app, lambda: ready(editor))
    assert editor.preview_result.format == "PNG" and editor.modified_info.text() == before


def test_continuous_changes_coalesce_and_cancel_stale_encoding(app, editor, monkeypatch):
    entered, release = Event(), Event()
    real_compress = module.compress
    calls, active = [], []

    def slow(image, options, metadata=None, progress=None):
        calls.append(options.quality)
        active.append(True)
        assert len(active) == 1
        try:
            if len(calls) == 1:
                entered.set()
                assert release.wait(5)
            return real_compress(image, options, metadata, progress)
        finally:
            active.pop()

    monkeypatch.setattr(module, "compress", slow)
    errors = []
    editor.error = errors.append
    editor.select_tool("export")
    editor.canvas.set_zoom(0.6)
    wait_for(app, entered.is_set)
    try:
        for value in range(40, 81):
            editor.out_quality.setValue(value)
        QTest.qWait(400)
        app.processEvents()
        assert len(calls) == 1 and editor.preview_result is None
    finally:
        release.set()
    wait_for(app, lambda: ready(editor))
    assert calls == [95, 80] and not errors
    assert editor.preview_result.quality == 80
    assert editor.canvas.transform().m11() == pytest.approx(0.6)


def test_apply_during_running_preview_commits_latest_settings(app, editor, monkeypatch):
    entered, release = Event(), Event()
    real_compress = module.compress

    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return real_compress(*args, **kwargs)

    monkeypatch.setattr(module, "compress", slow)
    editor.select_tool("export")
    wait_for(app, entered.is_set)
    try:
        editor.apply_compression()
        editor.out_quality.setValue(55)
    finally:
        release.set()
    wait_for(app, lambda: ready(editor) and editor.applied_compression is not None)
    assert editor.applied_compression is editor.preview_result
    assert editor.applied_compression.quality == 55
    assert editor.live_size_result[0] == len(editor.preview_result.data)


def test_preview_thumbnail_never_becomes_the_saved_resolution(app, editor):
    source = Image.new("RGBA", (2000, 1700), (80, 120, 160, 100))
    editor.set_document(
        Document(
            source,
            {
                "name": "large.png",
                "format": "PNG",
                "dimensions": source.size,
                "size": 9000,
            },
        )
    )
    editor.out_format.setCurrentText("PNG")
    editor.select_tool("export")
    wait_for(app, lambda: ready(editor))
    assert max(editor.encoded_preview_image.size) == 1600
    with Image.open(BytesIO(editor.preview_result.data)) as decoded:
        assert decoded.size == source.size
        assert decoded.convert("RGBA").tobytes() == source.tobytes()


@pytest.mark.parametrize("fmt", ["JPEG", "WEBP", "PNG"])
def test_large_output_is_not_limited_or_automatically_reduced(app, editor, fmt):
    source = Image.effect_noise((700, 700), 100).convert("RGBA")
    editor.set_document(
        Document(
            source,
            {
                "name": "noise.png",
                "format": "PNG",
                "dimensions": source.size,
                "size": 9000,
            },
        )
    )
    editor.out_format.setCurrentText(fmt)
    editor.out_quality.setValue(100)
    editor.select_tool("export")
    wait_for(app, lambda: ready(editor))
    options, result = editor.export_options(), editor.preview_result
    assert options.max_bytes is None and not options.allow_quality and not options.allow_resize
    assert len(result.data) > 100 * 1024
    assert result.quality == (100 if fmt != "PNG" else None)
    assert (result.width, result.height) == source.size
    if fmt == "PNG":
        assert not result.lossy
        with Image.open(BytesIO(result.data)) as decoded:
            assert decoded.convert("RGBA").tobytes() == source.tobytes()
