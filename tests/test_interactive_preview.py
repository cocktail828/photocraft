from threading import Event

from PIL import Image
from test_ui import wait_for, window

from photocraft import window as module
from photocraft.canvas import pixmap
from photocraft.core import Document


def test_rotation_preview_tracks_latest_angle_and_includes_watermarks_once(app):
    editor = window(app)
    editor.load_demo()
    editor.add_text_mark()
    editor.select_tool("rotate")
    for angle in (10, 15, -20, 28):
        editor.angle.setValue(angle)
    wait_for(app, lambda: not editor.rotation_timer.isActive() and not editor.jobs)
    expected = editor.doc.render().rotate(28, expand=True, resample=Image.Resampling.BICUBIC)
    assert editor.canvas.photo.pixmap().toImage() == pixmap(expected).toImage()
    assert not editor.canvas.marks
    assert editor.doc.base.size == (720, 1008)  # Preview does not commit a rotation.
    editor.select_tool("crop")
    wait_for(app, lambda: not editor.jobs)
    assert editor.canvas.photo.pixmap().toImage() == pixmap(editor.doc.base).toImage()
    editor.select_tool("rotate")
    editor.angle.setValue(28)
    editor.apply_rotation()
    wait_for(app, lambda: not editor.rotation_timer.isActive() and not editor.jobs)
    assert editor.angle.value() == 0
    assert editor.canvas.photo.pixmap().toImage() == pixmap(editor.doc.render()).toImage()
    editor.doc.revision = 0
    editor.close()


def test_leaving_rotate_discards_its_running_preview(app, monkeypatch):
    entered, release = Event(), Event()
    editor = window(app)
    editor.load_demo()
    wait_for(app, lambda: not editor.jobs)
    real_rotate = Image.Image.rotate

    def slow_rotate(image, angle, *args, **kwargs):
        entered.set()
        assert release.wait(5)
        return real_rotate(image, angle, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "rotate", slow_rotate)
    editor.select_tool("rotate")
    editor.angle.setValue(30)
    wait_for(app, entered.is_set)
    try:
        editor.select_tool("crop")
    finally:
        release.set()
    wait_for(app, lambda: not editor.jobs)
    assert editor.canvas.photo.pixmap().toImage() == pixmap(editor.doc.base).toImage()
    editor.close()


def test_large_stroke_preview_is_bounded_and_commits_at_source_resolution(app, monkeypatch):
    editor = window(app)
    image = Image.new("RGBA", (2400, 1800), "white")
    editor.set_document(
        Document(
            image,
            {
                "name": "large.png",
                "format": "PNG",
                "dimensions": image.size,
                "size": 9000,
            },
        )
    )
    editor.select_tool("brush")
    editor.brush_color = "#ff0000"
    editor.brush_settings()
    points = [(1200, 900), (1300, 900)]
    original_stroke = module.paint_stroke
    sizes = []

    def measured(image, *args):
        sizes.append(image.size)
        return original_stroke(image, *args)

    monkeypatch.setattr(module, "paint_stroke", measured)
    editor.preview_paint(points)
    thumbnail = editor.stroke_preview_base[1]
    editor.preview_paint(points)
    assert editor.stroke_preview_base[1] is thumbnail
    assert sizes == [(1600, 1200), (1600, 1200)]
    assert editor.canvas.bounds.width() == 2400
    editor.paint(points)
    assert sizes[-1] == (2400, 1800) and editor.doc.base.size == image.size
    assert editor.doc.base.getpixel((1250, 900)) != (255, 255, 255, 255)
    assert editor.stroke_preview_base is None
    editor.doc.revision = 0
    wait_for(app, lambda: not editor.jobs)
    editor.close()
