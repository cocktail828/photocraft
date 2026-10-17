from threading import Event

import pytest
from PIL import Image, ImageOps
from PySide6.QtWidgets import QFileDialog
from test_ui import wait_for, window

from photocraft import window as module
from photocraft.core import Document


def save_to(app, editor, monkeypatch, path):
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), ""))
    editor.request_save()
    wait_for(app, lambda: path.exists() and not editor.saving)


@pytest.fixture
def editor(app, tmp_path):
    source = Image.new("RGBA", (150, 200), (100, 120, 140, 80))
    path = tmp_path / "original.png"
    source.save(path, dpi=(72, 72))
    result = window(app)
    result.set_document(Document.open(path))
    wait_for(app, lambda: result.live_size_result is not None and not result.jobs)
    yield result, path
    result.doc.revision = 0
    result.close()
    wait_for(app, lambda: not result.jobs)


def test_unapplied_compression_can_preview_but_save_keeps_opened_bytes(app, editor, tmp_path, monkeypatch):
    tool, source = editor
    original = source.read_bytes()
    tool.select_tool("export")
    tool.out_format.setCurrentText("JPEG")
    tool.out_quality.setValue(10)
    tool.keep_alpha.setChecked(False)
    tool.keep_exif.setChecked(False)
    wait_for(app, lambda: tool.preview_result is not None and not tool.jobs)
    assert tool.preview_result.format == "JPEG" and tool.preview_result.quality == 10
    assert tool.applied_export_options is None
    # Saving the opened document must not reread a file changed by another program.
    source.write_bytes(b"changed outside the editor")
    target = tmp_path / "unchanged.png"
    save_to(app, tool, monkeypatch, target)
    assert target.read_bytes() == original
    with Image.open(target) as saved:
        assert saved.format == "PNG" and saved.getpixel((0, 0))[3] == 80


def test_save_uses_last_applied_compression_until_a_new_preview_is_applied(
    app, editor, tmp_path, monkeypatch
):
    tool, _ = editor
    tool.select_tool("export")
    tool.out_format.setCurrentText("PNG")
    tool.apply_compression()
    wait_for(app, lambda: tool.applied_compression is not None and not tool.jobs)
    applied = tool.applied_compression
    tool.out_format.setCurrentText("JPEG")
    tool.out_quality.setValue(5)
    tool.keep_alpha.setChecked(False)
    wait_for(app, lambda: tool.preview_result is not None and not tool.jobs)
    preview = tool.preview_result
    assert preview.format == "JPEG" and preview.data != applied.data

    def no_encoding(*args, **kwargs):
        pytest.fail("保存和应用已有结果不应重新编码")

    monkeypatch.setattr(module, "compress", no_encoding)
    first = tmp_path / "last-applied.png"
    save_to(app, tool, monkeypatch, first)
    assert first.read_bytes() == applied.data
    assert tool.preview_result is preview
    tool.apply_compression()
    second = tmp_path / "newly-applied.jpg"
    save_to(app, tool, monkeypatch, second)
    assert second.read_bytes() == preview.data


def test_save_does_not_wait_for_or_commit_a_running_compression_draft(app, editor, tmp_path, monkeypatch):
    tool, _ = editor
    tool.select_tool("export")
    tool.out_quality.setValue(90)
    tool.apply_compression()
    wait_for(app, lambda: tool.applied_compression is not None and not tool.jobs)
    applied = tool.applied_compression
    entered, release = Event(), Event()
    real_compress = module.compress

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return real_compress(*args, **kwargs)

    monkeypatch.setattr(module, "compress", blocked)
    tool.out_quality.setValue(10)
    wait_for(app, entered.is_set)
    try:
        path = tmp_path / "applied.jpg"
        save_to(app, tool, monkeypatch, path)
        assert path.read_bytes() == applied.data
        assert tool.encoding and tool.applied_compression is applied
    finally:
        release.set()
    wait_for(app, lambda: tool.preview_result is not None and not tool.jobs)
    assert tool.preview_result.quality == 10 and tool.applied_compression is applied


@pytest.mark.parametrize("mode", ["crop", "rotate", "watermark", "background"])
def test_other_unapplied_previews_never_enter_saved_pixels(app, editor, tmp_path, monkeypatch, mode):
    tool, source = editor
    original = source.read_bytes()
    tool.select_tool(mode)
    if mode == "crop":
        tool.crop_ratio.setCurrentIndex(tool.crop_ratio.findData(0))
    elif mode == "rotate":
        tool.angle.setValue(30)
        wait_for(app, lambda: not tool.rotation_busy and not tool.rotation_timer.isActive() and not tool.jobs)
        assert tool.canvas.bounds.width() != tool.doc.base.width
    elif mode == "watermark":
        tool.mark_text.setText("DRAFT")
        wait_for(app, lambda: bool(tool.canvas.marks) and not tool.jobs)
        assert not tool.doc.watermarks
    else:
        tool.set_background_color("#ff0000")
        wait_for(app, lambda: tool.background_preview is not None and not tool.jobs)
        assert tool.background_preview[1].tobytes() != tool.doc.base.tobytes()
    path = tmp_path / f"without-{mode}-draft.png"
    save_to(app, tool, monkeypatch, path)
    assert path.read_bytes() == original and not tool.doc.history


def test_applied_output_settings_survive_edits_without_including_new_draft_parameters(
    app, editor, tmp_path, monkeypatch
):
    tool, _ = editor
    tool.select_tool("export")
    tool.out_format.setCurrentText("PNG")
    tool.apply_compression()
    wait_for(app, lambda: tool.applied_compression is not None and not tool.jobs)
    tool.out_format.setCurrentText("JPEG")
    tool.out_quality.setValue(10)
    tool.keep_alpha.setChecked(False)
    tool.select_tool("crop")
    tool.crop_ratio.setCurrentIndex(tool.crop_ratio.findData(0))
    tool.crop_allow_resize.setChecked(True)
    tool.apply_crop()
    wait_for(app, lambda: tool.live_size_result is not None and not tool.jobs)
    assert tool.save_options().format == "PNG" and tool.save_options().keep_alpha
    assert tool.live_size_result[1:] == (295, 413, "PNG")
    target = tmp_path / "applied-crop.png"
    save_to(app, tool, monkeypatch, target)
    with Image.open(target) as saved:
        assert saved.size == (295, 413) and saved.convert("RGBA").tobytes() == tool.doc.render().tobytes()


def test_untouched_exif_oriented_photo_is_saved_without_reencoding(app, tmp_path, monkeypatch):
    source = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (80, 40), "red").save(source, quality=37, exif=exif)
    original = source.read_bytes()
    tool = window(app)
    tool.set_document(Document.open(source))
    assert tool.doc.base.size == (40, 80)
    tool.out_format.setCurrentText("PNG")
    target = tmp_path / "copy.jpg"
    save_to(app, tool, monkeypatch, target)
    assert target.read_bytes() == original
    with Image.open(target) as saved:
        assert ImageOps.exif_transpose(saved).size == tool.doc.base.size
    wait_for(app, lambda: not tool.jobs)
    tool.close()
