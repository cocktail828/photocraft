from io import BytesIO

import pytest
from PIL import Image
from PySide6.QtWidgets import QFileDialog
from test_ui import wait_for, window

from photocraft.compression import compress


@pytest.mark.parametrize("preset,size", [(0, (295, 413)), (1, (413, 579)), (2, (260, 378))])
def test_applied_template_pixels_footer_export_and_undo_agree(app, tmp_path, monkeypatch, preset, size):
    editor = window(app)
    editor.load_demo()
    wait_for(app, lambda: editor.live_size_result is not None and not editor.jobs)
    original_line = editor.filename.toolTip()
    editor.crop_ratio.setCurrentIndex(editor.crop_ratio.findData(preset))
    source_rect = editor.canvas.crop
    box = (
        round(source_rect.left()),
        round(source_rect.top()),
        round(source_rect.right()),
        round(source_rect.bottom()),
    )
    expected = editor.doc.base.crop(box).resize(size, Image.Resampling.LANCZOS)
    assert editor.doc.base.size == editor.output_dimensions() == (720, 1008)
    editor.apply_crop()
    assert editor.doc.base.size == editor.output_dimensions() == size
    assert editor.doc.base.tobytes() == expected.tobytes()
    assert len(editor.doc.history) == 1
    assert editor.canvas.bounds.width() == size[0] and editor.canvas.bounds.height() == size[1]
    wait_for(app, lambda: editor.live_size_result is not None and not editor.jobs)
    reference = compress(editor.doc.render(), editor.file_info_options(), editor.doc.metadata)
    assert editor.live_size_result == (len(reference.data), *size, "JPEG")
    assert editor.filename.toolTip() == original_line
    assert f"{size[0]} × {size[1]} px" in editor.modified_info.text().splitlines()[0]

    editor.select_tool("export")
    editor.out_format.setCurrentText("PNG")
    editor.apply_compression()
    wait_for(app, lambda: editor.applied_compression is not None and not editor.jobs)
    path = tmp_path / "cropped.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), ""))
    editor.request_save()
    wait_for(app, lambda: path.exists() and not editor.jobs)
    with Image.open(path) as saved:
        assert saved.size == size and saved.convert("RGBA").tobytes() == expected.tobytes()
    editor.undo()
    wait_for(app, lambda: editor.live_size_result is not None and not editor.jobs)
    assert editor.doc.base.size == editor.output_dimensions() == (720, 1008)
    assert editor.live_size_result[1:3] == (720, 1008)
    editor.redo()
    wait_for(
        app,
        lambda: editor.live_size_result is not None and editor.preview_result is not None and not editor.jobs,
    )
    assert editor.doc.base.size == editor.output_dimensions() == size
    with Image.open(BytesIO(editor.preview_result.data)) as preview:
        assert preview.size == size
    editor.transform(90)
    assert editor.doc.base.size == editor.output_dimensions() == (size[1], size[0])
    editor.doc.revision = 0
    wait_for(app, lambda: not editor.jobs)
    editor.close()
