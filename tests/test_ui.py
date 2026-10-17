import time
from io import BytesIO

import pytest
from PIL import Image
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QColorDialog, QFontComboBox, QLabel, QPushButton, QSlider

from photocraft.window import MainWindow


def wait_for(app, predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(10)
    assert predicate(), "后台任务未在预期时间内完成"


def window(app):
    result = MainWindow()
    result.crop_ratio.setCurrentIndex(result.crop_ratio.findData("free"))
    result.show()
    app.processEvents()
    return result


def test_full_id_workflow_and_stale_export_invalidated(app):
    editor = window(app)
    errors = []
    editor.error = errors.append
    editor.load_demo()
    editor.crop_ratio.setCurrentIndex(editor.crop_ratio.findData(0))
    editor.apply_preset()
    before = editor.doc.base.size
    editor.apply_crop()
    assert editor.doc.base.size != before
    editor.select_tool("export")
    editor.encode_preview()
    wait_for(app, lambda: not editor.jobs)
    assert not errors
    result = editor.preview_result
    assert (result.width, result.height) == (295, 413)
    assert result.max_bytes is None and result.quality == 95
    assert editor.preview_key == editor.export_generation
    assert not editor.windowIcon().isNull()
    editor.out_quality.setValue(85)
    assert editor.preview_result is None
    editor.encode_preview()
    # Changing a parameter while the worker is running must invalidate its result.
    editor.out_quality.setValue(90)
    wait_for(app, lambda: not editor.jobs)
    assert editor.preview_result is None
    editor.doc.revision = 0
    editor.close()


def test_crop_drag_is_source_pixel_based_at_any_zoom(app):
    editor = window(app)
    editor.load_demo()
    editor.select_tool("crop")
    editor.crop_ratio.setCurrentIndex(editor.crop_ratio.findData("custom"))
    editor.ratio_w.setValue(3)
    editor.ratio_h.setValue(4)
    editor.canvas.set_zoom(0.5)
    editor.canvas.set_crop_pixels(300, 400)
    assert editor.canvas.crop.width() == 300
    assert editor.canvas.crop.height() == 400
    editor.apply_crop()
    assert editor.doc.base.size == (300, 400)
    editor.undo()
    assert editor.doc.base.size == (720, 1008)
    editor.redo()
    assert editor.doc.base.size == (300, 400)
    editor.doc.revision = 0
    editor.close()


@pytest.mark.parametrize("zoom", [0.5, 1.5])
def test_dragging_crop_updates_pixel_fields_and_exports_same_size(app, zoom):
    editor = window(app)
    editor.load_demo()
    editor.select_tool("crop")
    editor.canvas.set_crop_pixels(300, 200)
    editor.canvas.set_zoom(zoom)
    viewport = editor.canvas.viewport()
    start = editor.canvas.mapFromScene(editor.canvas.crop.bottomRight())
    finish = start - QPoint(23, 17)
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(viewport, finish)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=finish)
    crop = editor.canvas.crop
    expected = (round(crop.right()) - round(crop.left()), round(crop.bottom()) - round(crop.top()))
    assert expected[0] < 300 and expected[1] < 200
    assert (editor.crop_w.value(), editor.crop_h.value()) == expected
    start = editor.canvas.mapFromScene(crop.center())
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(viewport, start + QPoint(15, 12))
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=start + QPoint(15, 12))
    assert editor.canvas.crop.topLeft() != crop.topLeft()
    assert (editor.crop_w.value(), editor.crop_h.value()) == expected
    editor.apply_crop()
    assert editor.doc.base.size == expected
    assert (editor.crop_w.maximum(), editor.crop_h.maximum()) == expected
    editor.doc.revision = 0
    editor.close()


def test_typing_crop_pixels_updates_frame_without_confirmation_and_keeps_bounds(app):
    editor = window(app)
    editor.load_demo()
    editor.select_tool("crop")
    for control, value in ((editor.crop_w, "311"), (editor.crop_h, "413")):
        control.setFocus()
        control.lineEdit().selectAll()
        QTest.keyClicks(control.lineEdit(), value)
    crop = editor.canvas.crop
    assert (crop.width(), crop.height()) == (311, 413)
    assert (editor.crop_w.value(), editor.crop_h.value()) == (311, 413)
    assert crop.left() == round(crop.left()) and crop.top() == round(crop.top())
    assert editor.canvas.ratio is None
    editor.apply_crop()
    assert editor.doc.base.size == (311, 413)
    editor.crop_w.setValue(100)
    editor.crop_h.setValue(100)
    editor.transform(90)
    assert (editor.crop_w.maximum(), editor.crop_h.maximum()) == (413, 311)
    editor.crop_w.setValue(10000)
    editor.crop_h.setValue(10000)
    assert (editor.crop_w.value(), editor.crop_h.value()) == (413, 311)
    assert (editor.canvas.crop.width(), editor.canvas.crop.height()) == (413, 311)
    assert editor.canvas.bounds.contains(editor.canvas.crop)
    editor.doc.revision = 0
    editor.close()


def test_enhancement_applies_immediately_and_preserves_values_through_export_undo_redo(app):
    editor = window(app)
    editor.load_demo()
    editor.select_tool("enhance")
    original = editor.doc.base.tobytes()
    editor.enhance_sliders["brightness"].setValue(130)
    assert editor.doc.enhancement.brightness == 1.3
    adjusted = editor.doc.render().tobytes()
    assert adjusted != original
    wait_for(app, lambda: editor.enhancement_image is not None and not editor.jobs)
    assert editor.enhancement_image.tobytes() != original
    assert editor.doc.base.tobytes() == original
    editor.select_tool("export")
    editor.encode_preview()
    wait_for(app, lambda: editor.preview_result is not None and not editor.jobs)
    assert editor.doc.enhancement.brightness == 1.3
    assert editor.enhance_sliders["brightness"].value() == 130
    assert editor.doc.render().tobytes() == adjusted
    editor.undo()
    assert editor.doc.render().tobytes() == original
    assert editor.enhance_sliders["brightness"].value() == 100
    editor.redo()
    assert editor.doc.render().tobytes() == adjusted
    assert editor.enhance_sliders["brightness"].value() == 130
    editor.doc.revision = 0
    editor.close()


def test_enhancement_drag_is_one_undo_and_survives_crop_paint_and_reset(app):
    from photocraft.core import Enhancement, enhance

    editor = window(app)
    editor.load_demo()
    editor.select_tool("enhance")
    slider = editor.enhance_sliders["brightness"]
    slider.sliderPressed.emit()
    for value in (110, 120, 130, 140):
        slider.setValue(value)
    slider.sliderReleased.emit()
    assert len(editor.doc.history) == 1
    assert editor.doc.enhancement.brightness == 1.4
    editor.undo()
    assert slider.value() == 100 and editor.doc.enhancement == Enhancement()
    editor.redo()
    assert slider.value() == 140
    editor.select_tool("crop")
    editor.crop_w.setValue(300)
    editor.crop_h.setValue(400)
    editor.apply_crop()
    assert slider.value() == 140 and editor.doc.enhancement.brightness == 1.4
    editor.select_tool("brush")
    editor.paint([(20, 20), (50, 30)])
    assert editor.doc.render().tobytes() == enhance(editor.doc.base, Enhancement(brightness=1.4)).tobytes()
    editor.reset_enhancement()
    assert slider.value() == 100 and editor.doc.render().tobytes() == editor.doc.base.tobytes()
    editor.undo()
    assert slider.value() == 140 and editor.doc.enhancement.brightness == 1.4
    editor.doc.revision = 0
    editor.close()


def test_file_info_separates_preview_from_applied_edits(app):
    from photocraft.compression import ExportOptions, compress
    from photocraft.core import compose, enhance
    from photocraft.window import size_text

    editor = window(app)
    editor.load_demo()
    wait_for(app, lambda: editor.live_size_result is not None and not editor.jobs)
    metadata = editor.doc.metadata
    original_size = metadata["size"]
    assert editor.live_size_result == (original_size, 720, 1008, "JPEG")
    original_tooltip = editor.filename.toolTip()
    assert size_text(original_size) in editor.modified_info.text()
    assert "720 × 1008 px" in editor.modified_info.text()
    editor.select_tool("enhance")
    editor.enhance_sliders["brightness"].setValue(145)
    assert editor.live_size_result is None
    wait_for(app, lambda: editor.live_size_result is not None and not editor.jobs)

    def reference_options(width, height):
        return ExportOptions(
            format="JPEG",
            width=width,
            height=height,
            dpi=300,
            quality=95,
            min_quality=95,
            max_bytes=None,
            allow_quality=False,
            keep_exif=True,
            keep_icc=True,
        )

    expected = compress(editor.doc.render(), reference_options(720, 1008), metadata)
    assert editor.live_size_result[0] == len(expected.data) != original_size
    assert f"{len(expected.data):,} 字节" in editor.modified_info.text()
    assert editor.filename.toolTip() == original_tooltip
    editor.undo()
    wait_for(app, lambda: editor.live_size_result is not None and not editor.jobs)
    assert editor.live_size_result == (original_size, 720, 1008, "JPEG")
    editor.redo()
    wait_for(app, lambda: editor.live_size_result is not None and not editor.jobs)
    assert editor.live_size_result[0] == len(expected.data)
    generation, info = editor.live_size_generation, editor.modified_info.text()
    editor.out_format.setCurrentText("PNG")
    editor.out_quality.setValue(10)
    editor.keep_alpha.setChecked(False)
    editor.keep_exif.setChecked(True)
    editor.keep_icc.setChecked(False)
    editor.export_background = "#ff0000"
    editor.invalidate_export()
    assert editor.live_size_generation == generation and editor.modified_info.text() == info
    editor.select_tool("crop")
    editor.crop_ratio.setCurrentIndex(editor.crop_ratio.findData("free"))
    editor.crop_w.setValue(300)
    editor.crop_h.setValue(400)
    editor.apply_button.click()
    wait_for(app, lambda: editor.live_size_result is not None and not editor.jobs)
    expected = compress(editor.doc.render(), reference_options(300, 400), metadata)
    assert editor.live_size_result == (len(expected.data), 300, 400, "JPEG")
    assert editor.filename.toolTip() == original_tooltip
    applied_info = editor.modified_info.text()
    editor.select_tool("watermark")
    editor.mark_text.setText("体积测试")
    editor.mark_opacity.setValue(90)
    wait_for(app, lambda: editor.preview_info_controller.result is not None and not editor.jobs)
    assert "水印预览" in editor.preview_info.text() and not editor.doc.watermarks
    draft = compose(enhance(editor.doc.base, editor.doc.enhancement), [editor.mark_from_controls()])
    expected = compress(draft, reference_options(300, 400), metadata)
    assert editor.preview_info_controller.result.data == expected.data
    assert editor.modified_info.text() == applied_info
    editor.apply_button.click()
    wait_for(app, lambda: editor.live_size_result is not None and not editor.jobs)
    assert editor.live_size_result[0] == len(expected.data)
    assert "与当前一致" in editor.preview_info.text()
    editor.doc.revision = 0
    editor.close()


@pytest.mark.parametrize("original_format", ["PNG", "WEBP", "BMP", "TIFF"])
def test_file_info_reencodes_in_original_type_with_actual_edit_dimensions(
    app, tmp_path, noise, original_format
):
    from photocraft.compression import ExportOptions, compress
    from photocraft.core import Document

    source = tmp_path / ("source." + original_format.lower())
    noise.save(source, format=original_format)
    editor = window(app)
    editor.set_document(Document.open(source))
    wait_for(app, lambda: editor.live_size_result is not None and not editor.jobs)
    assert editor.live_size_result == (source.stat().st_size, noise.width, noise.height, original_format)
    original_line = editor.filename.toolTip()
    editor.out_format.setCurrentText("JPEG")
    editor.enhance_sliders["brightness"].setValue(125)
    wait_for(app, lambda: editor.live_size_result is not None and not editor.jobs)
    reference = ExportOptions(
        format=original_format,
        width=noise.width,
        height=noise.height,
        dpi=editor.output_dpi(),
        quality=95,
        min_quality=95,
        max_bytes=None,
        allow_quality=False,
        keep_exif=True,
        keep_icc=True,
    )
    expected = compress(editor.doc.render(), reference, editor.doc.metadata)
    assert editor.live_size_result == (len(expected.data), noise.width, noise.height, original_format)
    assert editor.filename.toolTip() == original_line
    assert editor.modified_info.text().splitlines()[0].endswith(original_format)
    editor.doc.revision = 0
    editor.close()


def test_size_measurement_rejects_stale_results_and_coalesces_pending_changes(app, monkeypatch):
    import threading

    import photocraft.window as module

    editor = window(app)
    editor.load_demo()
    started, release = threading.Event(), threading.Event()
    real_compress, calls = module.compress, []
    editor.enhance_sliders["brightness"].setValue(110)

    def slow(image, options, metadata=None, progress=None):
        calls.append(options.quality)
        if len(calls) == 1:
            started.set()
            assert release.wait(5)
        return real_compress(image, options, metadata, progress)

    monkeypatch.setattr(module, "compress", slow)
    wait_for(app, started.is_set)
    for brightness in range(120, 141):
        editor.enhance_sliders["brightness"].setValue(brightness)
    release.set()
    wait_for(app, lambda: editor.live_size_result is not None and not editor.jobs)
    expected = real_compress(editor.doc.render(), editor.file_info_options(), editor.doc.metadata)
    assert editor.live_size_result[0] == len(expected.data)
    assert calls == [95, 95]
    editor.doc.revision = 0
    editor.close()


def test_compression_preview_never_replaces_file_information_until_apply(app):
    editor = window(app)
    editor.load_demo()
    errors = []
    editor.error = errors.append
    wait_for(app, lambda: editor.live_size_result is not None and not editor.jobs)
    info, measured, generation = (
        editor.modified_info.text(),
        editor.live_size_result,
        editor.live_size_generation,
    )
    assert editor.modified_info.text() == info and not editor.live_size_error
    assert editor.live_size_generation == generation
    editor.select_tool("export")
    editor.out_format.setCurrentText("PNG")
    editor.encode_preview()
    wait_for(app, lambda: editor.preview_result is not None and not editor.jobs)
    assert editor.preview_result.format == "PNG" and "压缩预览" in editor.preview_info.text()
    assert editor.live_size_result == measured and editor.modified_info.text() == info
    assert not errors
    editor.close()


def test_file_menu_shortcuts_save_fresh_edits_without_leaving_current_tool(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    from photocraft.compression import compress

    editor = window(app)
    actions = editor.menuBar().actions()[0].menu().actions()
    titles = [a.text() for a in actions if not a.isSeparator()]
    assert titles == ["打开图片…", "保存图片…", "退出"]
    assert editor.tool_buttons["export"].text() == "图像压缩"
    assert not editor.menu_actions["save_image"].isEnabled()
    assert editor.menu_actions["open"].shortcut().toString() == "Ctrl+O"
    assert editor.menu_actions["save_image"].shortcut().toString() == "Ctrl+S"
    assert "export_image" not in editor.menu_actions
    opened = []
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (opened.append(True) or "", ""))
    editor.activateWindow()
    editor.setFocus()
    app.processEvents()
    QTest.keyClick(editor, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier)
    assert opened == [True]
    editor.load_demo()
    editor.select_tool("enhance")
    assert not any(b.text() == "应用增强" for b in editor.findChildren(QPushButton))
    paths = [tmp_path / "export.jpg", tmp_path / "save.jpg"]
    destinations = iter(paths)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(next(destinations)), ""))
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Ok)
    for key, brightness, path in zip((Qt.Key.Key_S, Qt.Key.Key_S), (130, 150), paths, strict=True):
        editor.enhance_sliders["brightness"].setValue(brightness)
        editor.setFocus()
        QTest.keyClick(editor, key, Qt.KeyboardModifier.ControlModifier)
        wait_for(app, lambda: path.exists() and not editor.jobs)
        expected = compress(editor.doc.render(), editor.export_options(), editor.doc.metadata)
        assert path.read_bytes() == expected.data
        assert editor.current_tool == "enhance"
        assert editor.enhance_sliders["brightness"].value() == brightness
    assert paths[0].read_bytes() != paths[1].read_bytes()
    editor.doc.revision = 0
    editor.close()


def test_saving_reuses_applied_operations_and_valid_encoded_preview(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    from photocraft import rendering
    from photocraft import window as module
    from photocraft.core import compose, enhance

    calls = {"enhance": 0, "compose": 0, "encode": 0}
    original_compress = module.compress

    def enhancement(*args):
        calls["enhance"] += 1
        return enhance(*args)

    def composition(*args):
        calls["compose"] += 1
        return compose(*args)

    def encoding(*args, **kwargs):
        calls["encode"] += 1
        return original_compress(*args, **kwargs)

    monkeypatch.setattr(rendering, "enhance", enhancement)
    monkeypatch.setattr(rendering, "compose", composition)
    monkeypatch.setattr(module, "compress", encoding)
    editor = window(app)
    errors = []
    editor.error = errors.append
    editor.load_demo()
    editor.select_tool("enhance")
    editor.enhance_sliders["brightness"].setValue(130)
    wait_for(
        app,
        lambda: (
            editor.live_size_result is not None and editor.enhancement_image is not None and not editor.jobs
        ),
    )
    editor.add_text_mark()
    wait_for(
        app,
        lambda: (
            editor.live_size_result is not None and editor.enhancement_image is not None and not editor.jobs
        ),
    )
    assert calls["enhance"] == 1 and calls["compose"] == 1
    applied_counts = dict(calls)
    paths = [
        tmp_path / "first.jpg",
        tmp_path / "again.jpg",
        tmp_path / "new-format.png",
        tmp_path / "edited.png",
    ]
    destinations = iter(paths)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(next(destinations)), ""))
    editor.menu_actions["save_image"].trigger()
    wait_for(app, lambda: paths[0].exists() and not editor.jobs)
    assert not errors
    assert calls["enhance"] == applied_counts["enhance"] and calls["compose"] == applied_counts["compose"]
    assert calls["encode"] == applied_counts["encode"]  # Footer encoding is already a valid save result.
    encoded = editor.save_result
    assert editor.encoded_preview_image is None  # Saving does not build an unused screen thumbnail.
    editor.select_tool("crop")
    editor.canvas.fit()
    editor.toggle_theme()
    assert editor.save_result is encoded
    before = dict(calls)
    editor.menu_actions["save_image"].trigger()
    wait_for(app, lambda: paths[1].exists() and not editor.jobs)
    assert calls == before and paths[0].read_bytes() == paths[1].read_bytes() == encoded.data
    editor.select_tool("export")
    editor.encode_preview()
    wait_for(app, lambda: editor.encoded_preview_image is not None and not editor.jobs)
    assert calls["enhance"] == before["enhance"] and calls["compose"] == before["compose"]
    editor.out_format.setCurrentText("PNG")
    editor.apply_compression()
    wait_for(
        app,
        lambda: (
            editor.applied_compression is not None
            and editor.applied_compression.format == "PNG"
            and not editor.jobs
        ),
    )
    before = dict(calls)
    editor.request_save()
    wait_for(app, lambda: paths[2].exists() and not editor.jobs)
    assert calls["enhance"] == before["enhance"] and calls["compose"] == before["compose"]
    assert calls["encode"] == before["encode"]
    with Image.open(paths[2]) as saved:
        assert saved.convert("RGBA").tobytes() == editor.doc.render().tobytes()
    editor.enhance_sliders["brightness"].setValue(150)
    wait_for(
        app,
        lambda: (
            editor.live_size_result is not None and editor.enhancement_image is not None and not editor.jobs
        ),
    )
    assert calls["enhance"] == before["enhance"] + 1 and calls["compose"] == before["compose"] + 1
    before = dict(calls)
    editor.request_save()
    wait_for(app, lambda: paths[3].exists() and not editor.jobs)
    assert calls["enhance"] == before["enhance"] and calls["compose"] == before["compose"]
    assert not errors and paths[2].read_bytes() != paths[3].read_bytes()
    editor.doc.revision = 0
    editor.close()


def test_cached_save_does_not_wait_behind_background_preview_workers(app, tmp_path, monkeypatch):
    from threading import Event

    from PySide6.QtWidgets import QFileDialog

    editor = window(app)
    editor.load_demo()
    editor.encode_preview()
    wait_for(app, lambda: editor.preview_result is not None and not editor.jobs)
    editor.apply_compression()
    payload = editor.preview_result.data
    started, release = Event(), Event()
    errors = []
    editor.pool.setMaxThreadCount(1)

    def block(progress):
        started.set()
        assert release.wait(20)

    editor.start_job(block, lambda _: None, error=errors.append, background=True)
    wait_for(app, started.is_set)
    path = tmp_path / "cached.jpg"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), ""))
    try:
        editor.request_save()
        wait_for(app, lambda: path.exists() and not editor.saving, timeout=5)
        assert not errors and path.read_bytes() == payload
    finally:
        release.set()
    wait_for(app, lambda: not editor.jobs)
    editor.close()


def test_adding_template_in_dialog_and_export_dpi_do_not_change_pixel_dimensions(app):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from photocraft.template_dialog import TemplateDialog

    editor = window(app)
    editor.load_demo()
    dimensions = editor.doc.base.size
    editor.crop_ratio.setCurrentIndex(editor.crop_ratio.findData(0))
    assert (editor.id_w.value(), editor.id_h.value()) == (295, 413)

    def fill_template():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, TemplateDialog)
        dialog.name.setText("测试报名模板")
        dialog.width_px.setValue(480)
        dialog.height_px.setValue(640)
        dialog.save_button.click()

    QTimer.singleShot(0, fill_template)
    editor.add_template_button.click()
    assert editor.presets[-1]["name"] == "测试报名模板"
    assert editor.crop_output_size == (480, 640)
    editor.doc.metadata["dpi"] = (600, 600)
    editor.invalidate_export()
    assert editor.doc.base.size == dimensions
    editor.toggle_theme()
    assert "#141b29" in editor.styleSheet()
    editor.doc.revision = 0
    editor.close()


def test_template_dimensions_are_visible_but_locked_and_crop_has_no_export_controls(app):
    editor = window(app)
    editor.crop_ratio.setCurrentIndex(editor.crop_ratio.findData(0))
    app.processEvents()
    for control in (editor.id_w, editor.id_h):
        assert control.lineEdit().width() > 35
        assert control.lineEdit().isVisible()
        assert control.isReadOnly()
        original = control.value()
        control.setFocus()
        control.lineEdit().selectAll()
        QTest.keyClicks(control.lineEdit(), "999")
        QTest.keyClick(control, Qt.Key.Key_Up)
        assert control.value() == original
    panel = editor.crop_spec_fields.parentWidget()
    texts = [w.text() for kind in (QLabel, QPushButton) for w in panel.findChildren(kind)]
    for removed in ("输出格式", "大小上限", "打印设置", "下一步：压缩导出"):
        assert not any(removed in text for text in texts)
    editor.close()


def test_switching_templates_locks_output_pixels_without_overriding_export_preferences(app):
    editor = window(app)
    editor.load_demo()
    editor.out_format.setCurrentText("PNG")
    editor.out_quality.setValue(73)
    editor.doc.metadata["dpi"] = (144, 144)
    editor.crop_ratio.setCurrentIndex(editor.crop_ratio.findData(1))
    assert (editor.id_w.value(), editor.id_h.value()) == (413, 579)
    assert editor.output_dimensions() == (720, 1008)
    assert editor.canvas.ratio == pytest.approx(413 / 579)
    editor.canvas.set_crop_pixels(206, 289)
    assert (editor.id_w.value(), editor.id_h.value()) == (413, 579)
    assert editor.output_dimensions() == (720, 1008)
    editor.crop_allow_resize.setChecked(True)
    editor.canvas.set_crop_pixels(206, 289)
    editor.apply_crop()
    assert editor.output_dimensions() == editor.doc.base.size == (413, 579)
    assert editor.out_format.currentText() == "PNG"
    assert editor.out_quality.value() == 73 and editor.export_options().dpi == 144
    assert editor.export_options().max_bytes is None
    editor.crop_ratio.setCurrentIndex(editor.crop_ratio.findData("free"))
    assert editor.crop_pixel_fields.isVisible() and not editor.crop_spec_fields.isVisible()
    assert not editor.crop_w.isReadOnly() and not editor.crop_h.isReadOnly()
    editor.doc.revision = 0
    editor.close()


def test_watermark_text_label_and_input_share_one_row(app):
    editor = window(app)
    editor.select_tool("watermark")
    app.processEvents()
    panel = editor.mark_text.parentWidget()
    caption = next(w for w in panel.findChildren(QLabel) if w.text() == "水印文字")
    assert caption.geometry().right() < editor.mark_text.geometry().left()
    assert (
        editor.mark_text.geometry().top()
        <= caption.geometry().center().y()
        <= editor.mark_text.geometry().bottom()
    )
    editor.close()


def test_color_dialog_seeds_and_persists_custom_palette_without_restoring_deleted_templates(app, monkeypatch):
    from photocraft.config import DEFAULT_CUSTOM_COLORS, Config, read_toml, write_toml

    editor = window(app)
    # Simulate an external deletion made after this window opened.
    data = read_toml(editor.config.path)
    data["crop"]["templates"] = data["crop"]["templates"][:1]
    write_toml(editor.config.path, data)

    def choose(initial, parent, title, *, options):
        assert options == QColorDialog.ColorDialogOption.DontUseNativeDialog
        assert [QColorDialog.customColor(i).name() for i in range(16)] == list(DEFAULT_CUSTOM_COLORS)
        QColorDialog.setCustomColor(7, QColor("#123456"))
        return QColor("#abcdef")

    monkeypatch.setattr(QColorDialog, "getColor", choose)
    editor.choose_mark_color()
    config = Config(editor.config.directory)
    assert len(config.templates) == 1
    assert config.watermark_color == editor.mark_color == "#abcdef"
    assert config.custom_colors[7] == "#123456"
    editor.close()
    other = MainWindow(config=config)
    assert other.mark_color == "#abcdef"

    def cancel(*args, **kwargs):
        assert QColorDialog.customColor(7).name() == "#123456"
        QColorDialog.setCustomColor(0, QColor("#987654"))
        return QColor()

    monkeypatch.setattr(QColorDialog, "getColor", cancel)
    other.choose_mark_color()
    restored = Config(config.directory)
    assert restored.custom_colors[0] == "#987654"
    assert restored.watermark_color == other.mark_color == "#abcdef"
    other.close()


def test_mouse_drag_crop_handles(app):
    editor = window(app)
    editor.load_demo()
    editor.select_tool("crop")
    editor.canvas.reset_crop(3 / 4)
    editor.canvas.set_zoom(0.5)
    original = editor.canvas.crop
    viewport = editor.canvas.viewport()
    start = editor.canvas.mapFromScene(original.bottomRight())
    finish = start - QPoint(30, 40)
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(viewport, finish)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=finish)
    assert editor.canvas.crop.width() < original.width()
    assert editor.canvas.crop.width() / editor.canvas.crop.height() == pytest.approx(3 / 4)
    editor.doc.revision = 0
    editor.close()


def test_system_font_tiled_text_watermark_edit_undo_and_export(app):
    editor = window(app)
    editor.load_demo()
    editor.select_tool("watermark")
    assert isinstance(editor.mark_font, QFontComboBox)
    assert not hasattr(editor, "mark_tile")
    assert not hasattr(editor, "mark_list")
    assert editor.mark_angle.value() == 30
    assert not hasattr(editor, "add_picture_mark")
    editor.mark_font.setCurrentIndex(min(1, editor.mark_font.count() - 1))
    family = editor.mark_font.currentFont().family()
    assert family in QFontDatabase.families()
    editor.mark_text.setText("PhotoCraft 水印")
    original = editor.doc.base.tobytes()
    editor.add_text_mark()
    mark = editor.doc.watermarks[0]
    assert mark.font == family
    assert mark.text_bitmap is not None and mark.text_bitmap.getchannel("A").getbbox() is not None
    first = editor.doc.render().tobytes()
    assert first != original
    editor.mark_row_spacing.setValue(140)
    editor.add_text_mark()
    rows_changed = editor.doc.render().tobytes()
    assert rows_changed != first
    editor.mark_column_spacing.setValue(190)
    editor.add_text_mark()
    assert editor.doc.render().tobytes() != rows_changed
    editor.undo()
    assert editor.doc.render().tobytes() == rows_changed
    editor.undo()
    assert editor.doc.render().tobytes() == first
    editor.select_tool("export")
    editor.out_format.setCurrentText("PNG")
    editor.encode_preview()
    wait_for(app, lambda: not editor.jobs)
    with Image.open(BytesIO(editor.preview_result.data)) as exported:
        assert exported.convert("RGBA").tobytes() == first
    assert editor.doc.base.tobytes() == original
    editor.doc.revision = 0
    editor.close()


def test_brush_and_mosaic_sliders_adjust_active_brush(app):
    editor = window(app)
    for tool in ("brush", "mosaic"):
        editor.select_tool(tool)
        size, opacity, block = editor.brush_controls[tool]
        assert isinstance(size, QSlider) and isinstance(opacity, QSlider)
        assert size.maximum() == 100
        size.setValue(1000)
        assert size.value() == 100
        size.setValue(30)
        if tool == "mosaic":
            assert isinstance(block, QSlider)
        size.setFocus()
        before = size.value()
        QTest.keyClick(size, Qt.Key.Key_Right)
        assert size.value() == before + 1
        assert editor.canvas.brush_size == before + 1
        opacity.setValue(45)
        assert editor.canvas.brush_opacity == 0.45
    editor.close()


def test_live_mosaic_preview_commits_same_pixels_and_can_undo(app):
    editor = window(app)
    editor.load_demo()
    editor.select_tool("mosaic")
    editor.brush_controls["mosaic"][0].setValue(80)
    editor.brush_controls["mosaic"][2].setValue(30)
    editor.canvas.set_zoom(0.5)
    start = editor.canvas.mapFromScene(QPointF(250, 450))
    finish = editor.canvas.mapFromScene(QPointF(430, 450))
    original = editor.doc.base.tobytes()
    viewport = editor.canvas.viewport()
    previews = QSignalSpy(editor.canvas.strokePreview)
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(viewport, finish)
    wait_for(app, lambda: previews.count() >= 2 and len(previews.at(previews.count() - 1)[0]) >= 2)
    preview = editor.canvas.photo.pixmap().toImage()
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=finish)
    assert editor.doc.base.tobytes() != original
    assert editor.canvas.photo.pixmap().toImage() == preview
    editor.undo()
    assert editor.doc.base.tobytes() == original
    editor.doc.revision = 0
    editor.close()


def test_compare_preserves_exact_crop_and_tool(app):
    editor = window(app)
    editor.load_demo()
    editor.select_tool("crop")
    editor.canvas.set_crop_pixels(100, 120)
    crop = editor.canvas.crop
    editor.begin_compare()
    assert editor.canvas.tool == "hand"
    editor.end_compare()
    assert editor.canvas.crop == crop
    assert editor.canvas.tool == "crop"
    editor.close()


def test_explicit_output_dimensions_survive_source_crop_and_rotation(app):
    editor = window(app)
    editor.load_demo()
    editor.crop_ratio.setCurrentIndex(editor.crop_ratio.findData(0))
    editor.crop_allow_resize.setChecked(True)
    editor.canvas.reset_crop(295 / 413)
    editor.apply_crop()
    assert editor.output_dimensions() == (295, 413)
    editor.transform(180)
    assert editor.output_dimensions() == (295, 413)
    editor.select_tool("export")
    editor.encode_preview()
    wait_for(app, lambda: not editor.jobs)
    assert (editor.preview_result.width, editor.preview_result.height) == (295, 413)
    editor.doc.revision = 0
    editor.close()


def wait_for_marks(app, editor):
    wait_for(app, lambda: not editor.mark_preview_timer.isActive() and editor.mark_preview_worker is None)


def test_watermark_preview_is_temporary_and_tracks_controls(app):
    from photocraft.canvas import pixmap
    from photocraft.core import compose

    editor = window(app)
    editor.load_demo()
    editor.select_tool("watermark")
    errors = []
    editor.error = errors.append
    assert "50" in editor.mark_text.toolTip()
    assert not hasattr(editor, "mark_count")
    editor.mark_text.setText("TEST")
    for control in (
        editor.mark_opacity,
        editor.mark_angle,
        editor.mark_row_spacing,
        editor.mark_column_spacing,
    ):
        assert isinstance(control, QSlider)
    before, revision, history = editor.doc.base.tobytes(), editor.doc.revision, len(editor.doc.history)
    wait_for_marks(app, editor)
    first = editor.canvas.marks[0].pixmap().toImage()
    editor.mark_angle.setValue(-45)
    editor.mark_opacity.setValue(60)
    editor.mark_row_spacing.setValue(110)
    wait_for_marks(app, editor)
    latest = editor.canvas.marks[0].pixmap().toImage()
    assert latest != first
    mark = editor.mark_from_controls()
    expected = compose(Image.new("RGBA", editor.doc.base.size), [mark])
    assert latest == pixmap(expected).toImage()
    assert editor.doc.base.tobytes() == before
    assert editor.doc.revision == revision and len(editor.doc.history) == history
    assert not editor.doc.watermarks
    editor.mark_live_preview.setChecked(False)
    wait_for_marks(app, editor)
    assert not editor.canvas.marks
    editor.mark_live_preview.setChecked(True)
    wait_for_marks(app, editor)
    assert editor.canvas.marks[0].pixmap().toImage() == latest
    editor.add_text_mark()
    assert len(editor.doc.watermarks) == 1 and editor.doc.watermarks[0].tile
    assert editor.doc.render().tobytes() != before
    editor.undo()
    wait_for_marks(app, editor)
    assert not editor.doc.watermarks and not editor.canvas.marks
    assert not errors
    editor.doc.revision = 0
    editor.close()


def test_watermarks_replace_or_stack_and_clear_with_undo(app):
    editor = window(app)
    editor.load_demo()
    editor.select_tool("watermark")
    editor.mark_text.setText("FIRST")
    editor.add_text_mark()
    editor.mark_text.setText("SECOND")
    editor.add_text_mark()
    assert [mark.text for mark in editor.doc.watermarks] == ["SECOND"]
    editor.mark_multiple.setChecked(True)
    editor.mark_text.setText("THIRD")
    editor.add_text_mark()
    assert [mark.text for mark in editor.doc.watermarks] == ["SECOND", "THIRD"]
    editor.undo()
    assert [mark.text for mark in editor.doc.watermarks] == ["SECOND"]
    editor.redo()
    assert [mark.text for mark in editor.doc.watermarks] == ["SECOND", "THIRD"]
    editor.mark_multiple.setChecked(False)
    editor.mark_text.setText("FINAL")
    editor.add_text_mark()
    assert [mark.text for mark in editor.doc.watermarks] == ["FINAL"]
    editor.delete_mark()
    assert not editor.doc.watermarks
    editor.undo()
    assert [mark.text for mark in editor.doc.watermarks] == ["FINAL"]
    wait_for_marks(app, editor)
    editor.doc.revision = 0
    editor.close()


def test_preview_coalesces_changes_and_rejects_stale_worker_result(app, monkeypatch):
    from threading import Event

    import photocraft.window as module

    entered, release = Event(), Event()
    calls = []
    real_preview = module.watermark_preview

    def delayed(size, marks):
        calls.append(marks[-1].angle)
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        return real_preview(size, marks)

    monkeypatch.setattr(module, "watermark_preview", delayed)
    editor = window(app)
    editor.load_demo()
    editor.select_tool("watermark")
    editor.mark_text.setText("TEST")
    wait_for(app, entered.is_set)
    for value in range(10, 30):
        editor.mark_angle.setValue(value)
    QTest.qWait(180)
    app.processEvents()
    assert len(calls) == 1
    release.set()
    wait_for_marks(app, editor)
    assert calls == [30, 29]
    assert editor.canvas.marks and not editor.doc.watermarks
    editor.select_tool("export")
    wait_for_marks(app, editor)
    assert not editor.canvas.marks
    editor.close()


def test_compression_layout_has_only_compression_controls_and_preserves_crop_size(app):
    editor = window(app)
    editor.load_demo()
    editor.select_tool("export")
    assert not editor.export_advanced_toggle.isChecked()
    assert editor.quality_fields.isVisible()
    assert editor.output_dimensions() == editor.doc.base.size
    for removed in (
        "out_w",
        "out_h",
        "lock_ratio",
        "percent",
        "allow_resize",
        "out_algorithm",
        "out_dpi",
        "export_source",
        "limit_size",
        "out_kb",
        "allow_quality",
        "out_min_quality",
        "minimum_fields",
    ):
        assert not hasattr(editor, removed)
    panel = editor.panels.currentWidget().widget()
    texts = [w.text() for kind in (QLabel, QPushButton) for w in panel.findChildren(kind)]
    for removed in (
        "输出尺寸",
        "锁定宽高比",
        "恢复当前尺寸",
        "按当前图片缩放",
        "打印 DPI",
        "缩放算法",
        "当前图片",
        "原文件",
        "压缩到指定文件大小",
        "不超过",
        "自动降低质量",
        "最低保真度",
    ):
        assert not any(removed in text for text in texts)
    assert not editor.export_options().allow_resize
    assert editor.show_encoded_preview.parentWidget() is panel
    assert editor.show_encoded_preview.isVisible()
    assert (
        editor.show_encoded_preview.mapTo(editor, QPoint()).y()
        < editor.out_quality.mapTo(editor, QPoint()).y()
    )
    editor.out_format.setCurrentText("PNG")
    assert not editor.quality_fields.isVisible()
    editor.export_advanced_toggle.click()
    assert editor.keep_alpha.isVisible()
    editor.out_format.setCurrentText("WEBP")
    editor.out_quality.setValue(20)
    assert editor.export_options().quality == editor.export_options().min_quality == 20
    assert not editor.export_options().allow_quality
    editor.out_format.setCurrentText("PNG")
    editor.export_options().validate()
    assert editor.export_options().quality == editor.export_options().min_quality == 100
    editor.out_format.setCurrentText("JPEG")
    assert not editor.keep_alpha.isEnabled()
    assert editor.export_background_button.isVisible()
    editor.close()


def test_template_reload_and_deletion_only_change_the_next_crop(app):
    editor = window(app)
    editor.load_demo()
    editor.crop_ratio.setCurrentIndex(editor.crop_ratio.findData(0))
    editor.apply_crop()
    editor.select_tool("export")
    assert editor.output_dimensions() == (295, 413)
    name = editor.presets[0]["name"]
    editor.config.save_text(f'[[crop.templates]]\nname="{name}"\nwidth_px=320\nheight_px=480\n')
    editor.apply_configuration()
    assert editor.crop_output_size == (320, 480)
    assert editor.output_dimensions() == editor.doc.base.size == (295, 413)
    editor.crop_allow_resize.setChecked(True)
    editor.select_tool("crop")
    editor.apply_crop()
    assert editor.output_dimensions() == editor.doc.base.size == (320, 480)
    editor.select_tool("export")
    editor.config.save_text("[crop]\ntemplates=[]\n")
    editor.apply_configuration()
    assert editor.crop_output_size is None
    assert editor.output_dimensions() == editor.doc.base.size
    assert editor.current_tool == "export"
    editor.doc.revision = 0
    editor.close()


def test_export_canvas_displays_real_encoded_image_and_restores_source(app):
    from photocraft.canvas import pixmap

    editor = window(app)
    editor.load_demo()
    editor.config.save_template({**editor.presets[0], "name": "预览测试规格", "width": 360, "height": 504})
    editor.apply_configuration()
    editor.crop_ratio.setCurrentIndex(editor.crop_ratio.findData(len(editor.presets) - 1))
    editor.apply_crop()
    editor.select_tool("export")
    editor.out_quality.setValue(60)
    editor.encode_preview()
    wait_for(app, lambda: editor.preview_result is not None and not editor.jobs)
    with Image.open(BytesIO(editor.preview_result.data)) as decoded:
        assert editor.canvas.photo.pixmap().toImage() == pixmap(decoded.convert("RGBA")).toImage()
    assert editor.canvas.bounds.width() == 360
    assert editor.canvas.bounds.height() == 504
    editor.show_encoded_preview.setChecked(False)
    assert editor.canvas.photo.pixmap().toImage() == pixmap(editor.doc.base).toImage()
    assert editor.canvas.bounds.width() == 360
    assert editor.canvas.bounds.height() == 504
    editor.show_encoded_preview.setChecked(True)
    assert editor.canvas.bounds.width() == 360
    editor.out_quality.setValue(61)
    assert editor.preview_result is None
    assert editor.canvas.bounds.width() == 360
    editor.select_tool("crop")
    assert editor.crop_w.maximum() == 360 and editor.crop_h.maximum() == 504
    editor.doc.revision = 0
    editor.close()


def test_watermark_empty_text_and_stack_limit_preserve_history(app):
    from copy import copy

    editor = window(app)
    editor.load_demo()
    editor.select_tool("watermark")
    errors = []
    editor.error = errors.append
    editor.mark_text.clear()
    editor.add_text_mark()
    assert errors and not editor.doc.history and not editor.doc.watermarks
    editor.mark_text.setText("TEST")
    editor.add_text_mark()
    editor.doc.watermarks = [copy(editor.doc.watermarks[0]) for _ in range(10)]
    editor.mark_multiple.setChecked(True)
    history = len(editor.doc.history)
    editor.add_text_mark()
    assert len(editor.doc.watermarks) == 10 and len(editor.doc.history) == history
    assert "10" in errors[-1]
    editor.mark_multiple.setChecked(False)
    editor.add_text_mark()
    assert len(editor.doc.watermarks) == 1
    wait_for_marks(app, editor)
    editor.doc.revision = 0
    editor.close()


def test_switching_to_encoded_view_rejects_inflight_watermark_overlay(app, monkeypatch):
    from threading import Event

    import photocraft.window as module

    editor = window(app)
    editor.load_demo()
    editor.select_tool("watermark")
    editor.add_text_mark()
    editor.select_tool("export")
    editor.encode_preview()
    wait_for(app, lambda: editor.preview_result is not None)
    wait_for_marks(app, editor)
    encoded_pixels = editor.canvas.photo.pixmap().toImage()
    entered, release = Event(), Event()
    original = module.watermark_preview

    def delayed(size, marks):
        entered.set()
        assert release.wait(5)
        return original(size, marks)

    monkeypatch.setattr(module, "watermark_preview", delayed)
    editor.show_encoded_preview.setChecked(False)
    wait_for(app, entered.is_set)
    editor.show_encoded_preview.setChecked(True)
    release.set()
    wait_for_marks(app, editor)
    assert not editor.canvas.marks
    assert editor.canvas.photo.pixmap().toImage() == encoded_pixels
    editor.doc.revision = 0
    editor.close()


def test_combined_crop_templates_free_and_custom_ratio_workflow(app):
    editor = MainWindow()
    editor.show()
    editor.load_demo()
    assert "id" not in editor.tool_buttons and "id" not in editor.panel_indexes
    assert editor.current_tool == "crop"
    assert editor.preset_combo.count() == len(editor.presets) + 2
    assert all(isinstance(editor.preset_combo.itemData(i), int) for i in range(len(editor.presets)))
    assert editor.crop_output_size == (295, 413)
    assert editor.output_dimensions() == (720, 1008)
    editor.preset_combo.setCurrentIndex(editor.preset_combo.findData(1))
    assert editor.crop_output_size == (413, 579)
    assert editor.output_dimensions() == (720, 1008)
    assert editor.canvas.ratio == pytest.approx(413 / 579)
    editor.apply_crop()
    size, history = editor.doc.base.size, len(editor.doc.history)
    assert size == (413, 579)
    editor.apply_crop()
    assert editor.doc.base.size == size and len(editor.doc.history) == history
    assert not editor.apply_button.isEnabled()
    editor.preset_combo.setCurrentIndex(editor.preset_combo.findData("free"))
    assert editor.canvas.ratio is None
    assert editor.output_dimensions() == size
    assert editor.crop_pixel_fields.isVisible() and not editor.crop_spec_fields.isVisible()
    editor.preset_combo.setCurrentIndex(editor.preset_combo.findData("custom"))
    editor.ratio_w.setValue(3)
    editor.ratio_h.setValue(2)
    assert editor.canvas.ratio == 1.5
    for tool in editor.tool_buttons:
        editor.select_tool(tool)
        assert editor.offline_badge.isVisible()
        assert editor.offline_badge.mapTo(editor, QPoint(0, 0)).y() < 78
    wait_for_marks(app, editor)
    editor.doc.revision = 0
    editor.close()


def test_watermark_rejects_long_typing_and_paste_without_truncation(app):
    editor = window(app)
    editor.load_demo()
    editor.select_tool("watermark")
    assert not editor.mark_length_error.isVisible()
    editor.mark_text.setText("A" * 50)
    editor.mark_text.setFocus()
    editor.mark_text.setCursorPosition(50)
    QTest.keyClicks(editor.mark_text, "X")
    assert editor.mark_text.text() == "A" * 50
    assert editor.mark_length_error.isVisible()
    editor.mark_text.selectAll()
    app.clipboard().setText("B" * 51)
    editor.mark_text.paste()
    assert editor.mark_text.text() == "A" * 50
    QTest.keyClick(editor.mark_text, Qt.Key.Key_Backspace)
    assert not editor.mark_length_error.isVisible()
    editor.mark_text.setText("C" * 51)  # Programmatic writes also cannot reach export.
    errors = []
    editor.error = errors.append
    editor.add_text_mark()
    assert errors and "超长" in errors[-1] and not editor.doc.watermarks
    assert not editor.apply_button.isEnabled()
    editor.mark_text.setText("VALID")
    assert not editor.mark_length_error.isVisible()
    wait_for_marks(app, editor)
    editor.close()


def test_automatic_enhancement_replaces_manual_values_and_restores_them(app):
    editor = window(app)
    editor.load_demo()
    editor.select_tool("enhance")
    editor.enhance_sliders["contrast"].setValue(145)
    editor.enhance_sliders["temperature"].setValue(40)
    editor.enhance_checks["autocontrast"].setChecked(True)
    editor.enhance_checks["white_balance"].setChecked(True)
    assert not editor.enhance_sliders["contrast"].isEnabled()
    assert not editor.enhance_sliders["temperature"].isEnabled()
    settings = editor.doc.enhancement
    assert settings.autocontrast and settings.contrast == 1.45
    assert settings.white_balance and settings.temperature == 0.4
    editor.enhance_checks["autocontrast"].setChecked(False)
    editor.enhance_checks["white_balance"].setChecked(False)
    assert editor.doc.enhancement.contrast == 1.45
    assert editor.doc.enhancement.temperature == 0.4
    editor.enhance_sliders["denoise"].setValue(35)
    editor.enhance_sliders["equalize"].setValue(55)
    settings = editor.doc.enhancement
    assert settings.denoise == 0.35 and settings.equalize == 0.55
    wait_for(app, lambda: editor.enhancement_image is not None and not editor.jobs)
    editor.reset_enhancement()
    assert editor.doc.enhancement.denoise == editor.doc.enhancement.equalize == 0
    assert editor.enhance_sliders["contrast"].isEnabled()
    editor.doc.revision = 0
    editor.close()


def test_editing_toml_controls_crop_dropdown_and_empty_templates_remain_empty(app, tmp_path):
    from photocraft.config import Config

    path = tmp_path / "PhotoCraft.conf"
    path.write_text(
        """[crop]
[[crop.templates]]
name = "我编辑的规格"
width_px = 320
height_px = 480
max_kb = 150
""",
        encoding="utf-8",
    )
    editor = MainWindow(config=Config(tmp_path))
    editor.show()
    editor.load_demo()
    assert editor.preset_combo.count() == 3
    assert editor.preset_combo.itemText(0) == "我编辑的规格"
    assert editor.crop_output_size == (320, 480)
    assert editor.output_dimensions() == (720, 1008)
    editor.apply_crop()
    assert editor.output_dimensions() == (320, 480)
    assert editor.out_quality.value() == 95 and editor.export_options().max_bytes is None
    editor.doc.revision = 0
    editor.close()
    path.write_text("[crop]\ntemplates = []\n", encoding="utf-8")
    editor = MainWindow(config=Config(tmp_path))
    editor.show()
    assert editor.preset_combo.count() == 2
    assert editor.preset_combo.currentData() == "free"
    assert editor.crop_pixel_fields.isVisible()
    editor.close()
    assert path.read_text(encoding="utf-8") == "[crop]\ntemplates = []\n"


def test_window_state_is_separate_from_editable_configuration(app, tmp_path):
    from photocraft.config import Config

    config = Config(tmp_path)
    editor = MainWindow(config=config)
    editor.show()
    editor.resize(1200, 800)
    editor.move(20, 30)
    app.processEvents()
    body = config.path.read_bytes()
    state = editor.window_state()
    editor.close()
    restarted = Config(tmp_path)
    assert restarted.window == state
    assert restarted.path.read_bytes() == body


def test_config_menu_import_export_reset_apply_without_changing_photo(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    from photocraft.presets import PRESETS

    editor = window(app)
    editor.load_demo()
    errors = []
    editor.error = errors.append
    assert editor.menuBar().isVisible()
    assert [a.text() for a in editor.menuBar().actions()] == ["文件", "编辑", "视图", "配置", "帮助"]
    original = editor.doc.base.tobytes()
    source = tmp_path / "user.conf"
    source.write_text(
        '[appearance]\ntheme="dark"\n[[crop.templates]]\nname="菜单导入的模板"\nwidth_px=640\nheight_px=480\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(source), ""))
    editor.menu_actions["config_import"].trigger()
    assert not errors and editor.dark and editor.dark_action.isChecked()
    assert editor.preset_combo.count() == 3
    assert editor.preset_combo.itemText(0) == "菜单导入的模板"
    editor.crop_ratio.setCurrentIndex(editor.crop_ratio.findData(0))
    assert editor.crop_output_size == (640, 480)
    assert editor.output_dimensions() == editor.doc.base.size
    exported = tmp_path / "exported.conf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(exported), ""))
    editor.menu_actions["config_export"].trigger()
    assert exported.read_bytes() == source.read_bytes()
    source.write_text("[General]\ndark=true\n", encoding="utf-8")
    editor.menu_actions["config_import"].trigger()
    assert len(errors) == 1 and editor.dark and editor.preset_combo.count() == 3
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    editor.menu_actions["config_reset"].trigger()
    assert editor.dark and editor.preset_combo.count() == 3
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    editor.menu_actions["config_reset"].trigger()
    assert not editor.dark and editor.preset_combo.count() == len(PRESETS) + 2
    assert editor.doc.base.tobytes() == original and not editor.doc.history
    wait_for_marks(app, editor)
    editor.close()


def test_config_editor_menu_saves_valid_text_and_preserves_crop(app):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from photocraft.config_dialog import ConfigEditor

    editor = window(app)
    editor.load_demo()
    editor.canvas.set_crop_pixels(311, 413)
    crop = editor.canvas.crop
    original = editor.config.path.read_bytes()
    body = '# 编辑器备注\n[appearance]\ntheme="dark"\n[crop]\ntemplates=[]\n'
    observed = []

    def edit_dialog():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, ConfigEditor)
        dialog.editor.setPlainText("invalid = [")
        dialog.save_button.click()
        observed.append(dialog.message.isVisible())
        assert editor.config.path.read_bytes() == original
        dialog.editor.setPlainText(body)
        assert dialog.validate_text()
        dialog.save_button.click()

    QTimer.singleShot(0, edit_dialog)
    editor.menu_actions["config_edit"].trigger()
    assert observed == [True] and editor.config.path.read_text(encoding="utf-8") == body
    assert editor.dark and editor.preset_combo.count() == 2
    assert editor.canvas.crop == crop and editor.canvas.tool == "crop"
    assert not editor.doc.history
    editor.close()


def test_reload_menu_reorders_templates_and_invalid_text_keeps_active_configuration(app):
    editor = window(app)
    editor.load_demo()
    editor.crop_ratio.setCurrentIndex(editor.crop_ratio.findData(0))
    editor.canvas.set_crop_pixels(200, 280)
    crop = editor.canvas.crop
    from photocraft.config import read_toml, write_toml

    data = read_toml(editor.config.path)
    selected_name = editor.preset_combo.currentText()
    data["crop"]["templates"].reverse()
    write_toml(editor.config.path, data)
    editor.menu_actions["config_reload"].trigger()
    assert editor.preset_combo.currentText() == selected_name
    assert editor.canvas.crop == crop
    errors = []
    editor.error = errors.append
    editor.config.path.write_text("bad = [", encoding="utf-8")
    editor.menu_actions["config_reload"].trigger()
    assert errors and editor.preset_combo.currentText() == selected_name
    editor.config.reset()
    editor.close()
