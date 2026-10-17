import pytest
from PIL import Image
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox
from test_ui import wait_for, window

from photocraft.core import Document


@pytest.fixture
def editor(app):
    result = window(app)
    result.load_demo()
    yield result
    result.doc.revision = 0
    result.close()
    wait_for(app, lambda: not result.jobs)


@pytest.mark.parametrize("target", [(200, 280), (50, 70), (100, 141)])
def test_template_scaling_requires_explicit_permission_and_preserves_history_on_error(target):
    doc = Document(Image.effect_noise((100, 140), 70).convert("RGBA"), {})
    pixels = doc.base.tobytes()
    with pytest.raises(ValueError, match="未勾选“允许缩放”"):
        doc.crop((0, 0, 100, 140), output_size=target)
    assert doc.base.tobytes() == pixels and not doc.history and doc.revision == 0
    doc.crop((0, 0, 100, 140), output_size=target, allow_resize=True)
    assert doc.base.size == target and len(doc.history) == 1
    doc.undo()
    assert doc.base.tobytes() == pixels


def test_default_template_crop_moves_at_exact_pixel_size_without_resampling(app, editor):
    editor.crop_ratio.setCurrentIndex(editor.crop_ratio.findData(0))
    assert not editor.crop_allow_resize.isChecked() and editor.canvas.crop_fixed_size
    assert (editor.canvas.crop.width(), editor.canvas.crop.height()) == (295, 413)
    assert "放大可能模糊" in editor.crop_allow_resize.toolTip()
    start = editor.canvas.mapFromScene(editor.canvas.crop.bottomRight())
    QTest.mousePress(editor.canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    assert editor.canvas.drag == "move"  # Fixed-size templates have no resize handles.
    QTest.mouseMove(editor.canvas.viewport(), start + QPoint(-30, -20))
    QTest.mouseRelease(editor.canvas.viewport(), Qt.MouseButton.LeftButton, pos=start + QPoint(-30, -20))
    rect = editor.canvas.crop
    box = tuple(round(n) for n in (rect.left(), rect.top(), rect.right(), rect.bottom()))
    expected = editor.doc.base.crop(box)
    editor.apply_button.click()
    assert editor.doc.base.size == (295, 413)
    assert editor.doc.base.tobytes() == expected.tobytes()


def test_one_inch_to_two_inches_is_rejected_with_dialog_until_scaling_is_allowed(app, editor, monkeypatch):
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, message: messages.append(message))
    editor.crop_ratio.setCurrentIndex(editor.crop_ratio.findData(0))
    editor.apply_button.click()
    wait_for(app, lambda: editor.live_size_result is not None and not editor.jobs)
    pixels, before, history = editor.doc.base.tobytes(), editor.modified_info.text(), len(editor.doc.history)
    editor.crop_ratio.setCurrentIndex(editor.crop_ratio.findData(1))
    wait_for(app, lambda: bool(editor.preview_info_controller.error) and not editor.jobs)
    assert "未勾选“允许缩放”" in editor.preview_info.text()
    editor.apply_button.click()
    assert len(messages) == 1 and "413 × 579 px" in messages[0]
    assert editor.doc.base.tobytes() == pixels and len(editor.doc.history) == history
    assert editor.modified_info.text() == before
    editor.crop_allow_resize.setChecked(True)
    assert not editor.canvas.crop_fixed_size
    wait_for(app, lambda: editor.preview_info_controller.result is not None and not editor.jobs)
    preview = editor.preview_info_controller.result
    assert (preview.width, preview.height) == (413, 579)
    editor.apply_button.click()
    wait_for(app, lambda: editor.live_size_result is not None and not editor.jobs)
    assert editor.doc.base.size == (413, 579)
    assert editor.live_size_result[0] == len(preview.data)
    assert len(messages) == 1
    editor.undo()
    assert editor.doc.base.tobytes() == pixels


def test_undo_returns_to_original_for_larger_template_without_scaling(app, editor):
    editor.crop_ratio.setCurrentIndex(editor.crop_ratio.findData(0))
    editor.apply_button.click()
    editor.undo()
    editor.crop_ratio.setCurrentIndex(editor.crop_ratio.findData(1))
    editor.apply_button.click()
    assert editor.doc.base.size == (413, 579)
    assert not editor.crop_allow_resize.isChecked()


@pytest.mark.parametrize("mode", ["free", "custom"])
def test_free_and_ratio_crops_do_not_resize_or_expose_template_scaling(app, editor, mode):
    editor.crop_ratio.setCurrentIndex(editor.crop_ratio.findData(0))
    editor.crop_ratio.setCurrentIndex(editor.crop_ratio.findData(mode))
    assert not editor.crop_scaling_fields.isVisible() and not editor.canvas.crop_fixed_size
    editor.canvas.set_crop_pixels(300, 420)
    editor.apply_button.click()
    assert editor.doc.base.size == (300, 420)
