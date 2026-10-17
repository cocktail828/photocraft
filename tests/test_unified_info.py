from threading import Event

import pytest
from PIL import Image
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QPushButton, QToolButton
from test_ui import wait_for, window

from photocraft import __version__
from photocraft import preview_info as measurements
from photocraft.compression import compress
from photocraft.core import Document, compose, enhance


@pytest.fixture
def editor(app, tmp_path):
    path = tmp_path / "transparent.png"
    source = Image.effect_noise((180, 240), 80).convert("RGBA")
    source.putalpha(120)
    source.save(path)
    result = window(app)
    result.select_tool("enhance")
    result.set_document(Document.open(path))
    wait_for(app, lambda: result.live_size_result is not None and not result.jobs)
    yield result
    result.doc.revision = 0
    result.close()
    wait_for(app, lambda: not result.jobs)


def preview_ready(editor, kind):
    controller = editor.preview_info_controller
    return (
        controller.plan.key[2] == kind
        and controller.result is not None
        and controller.worker is None
        and not controller.timer.isActive()
        and not editor.jobs
    )


def test_two_columns_single_top_apply_and_plain_version_replace_sidebar_about(app, editor):
    assert editor.info.layout().count() == 2
    assert editor.preview_info.mapTo(editor, QPoint()).x() < editor.modified_info.mapTo(editor, QPoint()).x()
    assert editor.apply_button.parentWidget().objectName() == "workspaceBar"
    assert editor.apply_button.mapTo(editor, QPoint()).y() < editor.canvas.mapTo(editor, QPoint()).y()
    assert [item for item in editor.findChildren(QPushButton) if item.text() == "应用"] == [
        editor.apply_button
    ]
    for name, index in editor.panel_indexes.items():
        panel = editor.panels.widget(index).widget()
        assert not any(item.text().startswith("应用") for item in panel.findChildren(QPushButton)), name
    for removed in (
        "compression_result",
        "background_status",
        "mark_status",
        "crop_info",
        "encode_button",
        "apply_crop_button",
        "mark_apply_button",
    ):
        assert not hasattr(editor, removed)
    assert not any(item.text() == "关于" for item in editor.findChildren(QToolButton))
    assert editor.version_label.text() == editor.version_label.toolTip() == __version__
    assert "原文件" in editor.filename.toolTip()
    assert not editor.apply_button.isEnabled()  # Enhancement is already applied automatically.


def test_crop_preview_and_applied_pixels_have_separate_exact_measurements(app, editor):
    before = editor.modified_info.text()
    editor.select_tool("crop")
    editor.crop_ratio.setCurrentIndex(editor.crop_ratio.findData(0))
    editor.crop_allow_resize.setChecked(True)
    wait_for(app, lambda: preview_ready(editor, "crop"))
    preview = editor.preview_info_controller.result
    assert (preview.width, preview.height) == (295, 413)
    assert "295 × 413 px" in editor.preview_info.text() and "未应用" in editor.preview_info.text()
    assert f"{len(preview.data):,} 字节" in editor.preview_info.text()
    assert editor.modified_info.text() == before and editor.doc.base.size == (180, 240)
    editor.apply_button.click()
    wait_for(app, lambda: editor.live_size_result is not None and not editor.jobs)
    assert editor.live_size_result == (len(preview.data), 295, 413, "PNG")
    assert editor.modified_info.text().splitlines()[0] == editor.preview_info.text().splitlines()[0]
    assert not editor.apply_button.isEnabled()


def test_watermark_background_and_compression_report_only_in_common_preview(app, editor):
    before = editor.modified_info.text()
    editor.select_tool("watermark")
    editor.mark_text.setText("DRAFT")
    editor.mark_opacity.setValue(80)
    wait_for(app, lambda: preview_ready(editor, "watermark"))
    draft = compose(enhance(editor.doc.base, editor.doc.enhancement), [editor.mark_from_controls()])
    expected = compress(draft, editor.save_options(), editor.doc.metadata)
    assert editor.preview_info_controller.result.data == expected.data
    assert "水印预览" in editor.preview_info.text() and editor.modified_info.text() == before
    editor.apply_button.click()
    wait_for(app, lambda: editor.live_size_result is not None and not editor.jobs)
    assert editor.live_size_result[0] == len(expected.data)
    before = editor.modified_info.text()

    editor.select_tool("background")
    editor.set_background_color("#ff0000")
    wait_for(app, lambda: preview_ready(editor, "background"))
    background = editor.preview_info_controller.result
    assert "背景色预览" in editor.preview_info.text()
    assert editor.modified_info.text() == before and editor.doc.base.getpixel((0, 0))[3] == 120
    editor.apply_button.click()
    wait_for(app, lambda: editor.live_size_result is not None and not editor.jobs)
    assert editor.live_size_result[0] == len(background.data)
    assert editor.doc.base.getpixel((0, 0))[3] == 255
    before = editor.modified_info.text()

    editor.select_tool("export")
    editor.out_format.setCurrentText("JPEG")
    editor.out_quality.setValue(65)
    wait_for(app, lambda: editor.preview_result is not None and not editor.jobs)
    assert "JPEG" in editor.preview_info.text() and "质量 65" in editor.preview_info.text()
    assert "未应用" in editor.preview_info.text() and editor.modified_info.text() == before
    editor.apply_button.click()
    assert "JPEG" in editor.modified_info.text() and "质量 65" in editor.modified_info.text()
    assert not editor.apply_button.isEnabled()


@pytest.mark.parametrize("fmt", ["JPEG", "PNG"])
def test_opaque_photos_explain_why_background_has_no_effect_and_do_not_create_history(app, tmp_path, fmt):
    path = tmp_path / ("opaque.jpg" if fmt == "JPEG" else "opaque.png")
    Image.new("RGB", (160, 200), "#cccccc").save(path)
    tool = window(app)
    tool.set_document(Document.open(path))
    pixels = tool.doc.base.tobytes()
    tool.select_tool("background")
    tool.set_background_color("#ff0000")
    tool.apply_background()  # Even an early click while alpha detection is pending must be harmless.
    wait_for(
        app,
        lambda: tool.background_preview is not None and tool.live_size_result is not None and not tool.jobs,
    )
    assert "不含透明区域" in tool.preview_info.text()
    assert "不会改变画面" in tool.preview_info.text()
    assert not tool.apply_button.isEnabled()
    assert tool.doc.base.tobytes() == pixels and not tool.doc.history and tool.doc.revision == 0
    assert tool.preview_info.text().splitlines()[0] == tool.modified_info.text().splitlines()[0]
    tool.close()


def test_rotation_and_disabled_compression_preview_show_the_actual_visible_state(app, editor):
    before = editor.modified_info.text()
    editor.select_tool("rotate")
    editor.angle.setValue(30)
    wait_for(app, lambda: preview_ready(editor, "rotate"))
    assert editor.preview_info_controller.result.width > editor.doc.base.width
    assert "旋转预览" in editor.preview_info.text() and editor.modified_info.text() == before
    editor.select_tool("export")
    editor.out_format.setCurrentText("JPEG")
    wait_for(app, lambda: editor.preview_result is not None and not editor.jobs)
    editor.show_encoded_preview.setChecked(False)
    assert editor.preview_info.text().splitlines()[0] == editor.modified_info.text().splitlines()[0]
    editor.show_encoded_preview.setChecked(True)
    assert "JPEG" in editor.preview_info.text() and editor.modified_info.text() == before


def test_preview_measurement_coalesces_changes_and_discards_stale_results(app, editor, monkeypatch):
    entered, release = Event(), Event()
    real_compress, calls = measurements.compress, []

    def slow(image, options, metadata, progress):
        calls.append(True)
        if len(calls) == 1:
            entered.set()
            assert release.wait(10)
        return real_compress(image, options, metadata, progress)

    monkeypatch.setattr(measurements, "compress", slow)
    before = editor.modified_info.text()
    editor.select_tool("watermark")
    wait_for(app, entered.is_set)
    try:
        for angle in range(-45, 46, 5):
            editor.mark_angle.setValue(angle)
        assert editor.preview_info_controller.result is None
    finally:
        release.set()
    wait_for(app, lambda: preview_ready(editor, "watermark"))
    expected_image = compose(editor.doc.base, [editor.mark_from_controls()])
    expected = real_compress(expected_image, editor.save_options(), editor.doc.metadata, None)
    assert calls == [True, True]
    assert editor.preview_info_controller.result.data == expected.data
    assert editor.modified_info.text() == before and not editor.doc.watermarks
