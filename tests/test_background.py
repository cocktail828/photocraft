from threading import Event

from PIL import Image
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QFileDialog, QPushButton
from test_ui import wait_for, window

from photocraft import rendering
from photocraft.canvas import pixmap
from photocraft.core import Document, Watermark, enhance


def ready(editor):
    return (
        editor.background_preview is not None
        and editor.background_preview[0] == (editor.edit_generation, editor.background_color)
        and not editor.background_busy
        and not editor.background_timer.isActive()
        and editor.live_size_result is not None
        and not editor.enhance_timer.isActive()
        and not editor.jobs
    )


def test_background_is_a_sidebar_tool_and_is_removed_from_crop(app):
    editor = window(app)
    assert editor.tool_buttons["background"].text() == "背景色"
    assert not editor.tool_buttons["background"].icon().isNull()
    crop = editor.panels.widget(editor.panel_indexes["crop"]).widget()
    assert all("背景色" not in item.text() for item in crop.findChildren(QPushButton))
    editor.select_tool("background")
    assert editor.background_color_button.isVisible() and editor.offline_badge.isVisible()
    panel = editor.panels.widget(editor.panel_indexes["background"]).widget()
    assert not {"白", "蓝", "红", "灰", "黑"}.intersection(
        item.text() for item in panel.findChildren(QPushButton)
    )
    assert editor.tool_buttons["background"].iconSize() == editor.tool_buttons["crop"].iconSize()
    assert editor.offline_badge.mapTo(editor, QPoint()).y() < 78
    editor.close()


def test_background_preview_apply_undo_redo_and_saved_pixels_agree(app, tmp_path, monkeypatch):
    editor = window(app)
    source = Image.new("RGBA", (150, 200), (10, 20, 30, 0))
    source.putpixel((20, 20), (200, 100, 50, 128))
    source.putpixel((30, 30), (80, 90, 100, 255))
    editor.set_document(
        Document(
            source,
            {
                "name": "source.png",
                "format": "PNG",
                "dimensions": source.size,
                "size": 9000,
            },
        )
    )
    editor.select_tool("background")
    editor.set_background_color("#438edb")
    wait_for(app, lambda: ready(editor))
    expected = Image.new("RGBA", source.size, "#438edb")
    expected.alpha_composite(source)
    assert editor.canvas.photo.pixmap().toImage() == pixmap(expected).toImage()
    assert editor.doc.base.tobytes() == source.tobytes() and not editor.doc.history
    preview_base = editor.background_preview[1]
    editor.apply_background()
    wait_for(app, lambda: ready(editor))
    assert editor.doc.base is preview_base
    assert editor.doc.base.tobytes() == expected.tobytes()
    assert editor.doc.base.getpixel((30, 30)) == (80, 90, 100, 255)
    assert editor.doc.base.getchannel("A").getextrema() == (255, 255)
    assert editor.live_size_result[1:3] == source.size
    assert len(editor.doc.history) == 1 and editor.doc.original.tobytes() == source.tobytes()
    editor.undo()
    wait_for(app, lambda: not editor.jobs)
    assert editor.doc.base.tobytes() == source.tobytes()
    assert editor.canvas.photo.pixmap().toImage() == pixmap(source).toImage()
    editor.redo()
    wait_for(app, lambda: not editor.jobs)
    assert editor.doc.base.tobytes() == expected.tobytes()
    editor.select_tool("export")
    editor.out_format.setCurrentText("PNG")
    path = tmp_path / "background.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), ""))
    editor.request_save()
    wait_for(app, lambda: path.exists() and not editor.jobs)
    with Image.open(path) as saved:
        assert saved.convert("RGBA").tobytes() == expected.tobytes()
    editor.doc.revision = 0
    editor.close()


def test_background_apply_reuses_rendered_effects_when_saving(app, tmp_path, monkeypatch):
    editor = window(app)
    source = Image.new("RGBA", (150, 200), (80, 90, 100, 100))
    editor.set_document(
        Document(
            source,
            {
                "name": "source.png",
                "format": "PNG",
                "dimensions": source.size,
                "size": 9000,
            },
        )
    )
    editor.enhance_sliders["brightness"].setValue(125)
    editor.doc.watermarks = [Watermark(text="TEST", size=10)]
    editor.changed()
    wait_for(app, lambda: not editor.jobs and not editor.enhance_timer.isActive())
    calls = []

    def measured(*args):
        calls.append(True)
        return enhance(*args)

    monkeypatch.setattr(rendering, "enhance", measured)
    editor.select_tool("background")
    editor.set_background_color("#e64340")
    wait_for(app, lambda: ready(editor))
    assert len(calls) == 1
    editor.apply_background()
    wait_for(app, lambda: ready(editor))
    expected = editor.doc.render().tobytes()
    editor.out_format.setCurrentText("PNG")
    path = tmp_path / "enhanced.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), ""))
    editor.request_save()
    wait_for(app, lambda: path.exists() and not editor.jobs)
    assert len(calls) == 1
    with Image.open(path) as saved:
        assert saved.convert("RGBA").tobytes() == expected
    editor.doc.revision = 0
    editor.close()


def test_background_stale_work_cannot_override_a_new_color_or_another_tool(app, monkeypatch):
    entered, release = Event(), Event()
    editor = window(app)
    source = Image.new("RGBA", (150, 200), (80, 90, 100, 100))
    editor.set_document(
        Document(
            source, {"name": "transparent.png", "format": "PNG", "dimensions": source.size, "size": 9000}
        )
    )
    editor.select_tool("enhance")
    editor.enhance_sliders["brightness"].setValue(125)
    wait_for(app, lambda: not editor.jobs and not editor.enhance_timer.isActive())
    calls = []

    def slow(*args):
        calls.append(True)
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        return enhance(*args)

    monkeypatch.setattr(rendering, "enhance", slow)
    editor.select_tool("background")
    wait_for(app, entered.is_set)
    try:
        for color in ("#ff0000", "#00ff00", "#0000ff"):
            editor.set_background_color(color)
    finally:
        release.set()
    wait_for(app, lambda: ready(editor))
    assert len(calls) == 2 and editor.background_preview[0][1] == "#0000ff"
    editor.set_background_color("#ffffff")
    editor.select_tool("crop")
    wait_for(app, lambda: not editor.jobs)
    assert editor.current_tool == "crop"
    assert editor.canvas.photo.pixmap().toImage() == pixmap(editor.enhancement_image).toImage()
    editor.doc.revision = 0
    editor.close()


def test_applying_before_preview_finishes_keeps_full_image_resolution(app):
    editor = window(app)
    source = Image.new("RGBA", (1800, 1601), (10, 20, 30, 0))
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
    editor.select_tool("background")
    editor.set_background_color("#ff0000")
    editor.set_background_color("#438edb")
    editor.apply_background()
    assert not editor.doc.history
    wait_for(app, lambda: ready(editor) and bool(editor.doc.history))
    assert editor.doc.base.size == source.size
    assert max(editor.background_preview[2].size) == 1600
    assert editor.doc.base.getpixel((100, 100)) == (67, 142, 219, 255)
    assert len(editor.doc.history) == 1
    editor.doc.revision = 0
    editor.close()
