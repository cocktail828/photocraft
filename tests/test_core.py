from io import BytesIO

import pytest
from PIL import Image

from photocraft.compression import ExportOptions, compress
from photocraft.core import (
    Document,
    Enhancement,
    Watermark,
    compose,
    enhance,
    load_image,
    mm_to_px,
    paint_stroke,
)


def test_exif_orientation_is_applied_once_and_stripped(tmp_path):
    source = Image.new("RGB", (80, 40), "#ff0000")
    exif = Image.Exif()
    exif[274] = 6
    path = tmp_path / "rotated.jpg"
    source.save(path, exif=exif)
    image, metadata = load_image(path)
    assert image.size == (40, 80)
    result = compress(image, ExportOptions(width=40, height=80, keep_exif=True), metadata)
    with Image.open(BytesIO(result.data)) as exported:
        assert exported.getexif().get(274) is None
        assert exported.size == (40, 80)


def test_physical_dimensions_and_dpi_do_not_resample():
    assert mm_to_px(25, 300) == 295
    assert mm_to_px(35, 300) == 413
    source = Image.new("RGBA", (100, 140), "white")
    result = compress(source, ExportOptions(width=100, height=140, dpi=600))
    assert (result.width, result.height) == (100, 140)


def test_history_tracks_pixels_and_independent_watermark_objects(noise):
    doc = Document(noise, {})
    doc.checkpoint()
    doc.watermarks.append(Watermark(text="TEST", x=15, y=20))
    pixels = doc.base.tobytes()
    doc.crop((10, 10, 90, 100))
    assert doc.base.size == (80, 90)
    assert doc.watermarks[0].x == 5
    assert doc.watermarks[0].y == 10
    assert doc.render().tobytes() != doc.base.tobytes()
    doc.undo()
    assert doc.base.tobytes() == pixels
    assert doc.watermarks[0].x == 15
    doc.redo()
    assert doc.base.size == (80, 90)
    doc.undo()
    doc.undo()
    assert not doc.watermarks
    assert doc.original.tobytes() == pixels


def test_template_crop_resamples_pixels_and_editable_marks_in_one_undo_step(noise):
    bitmap = Image.new("RGBA", (20, 10), "red")
    mark = Watermark(x=20, y=40, size=20, angle=0, row_spacing=12, column_spacing=10, text_bitmap=bitmap)
    doc = Document(noise, {})
    doc.watermarks = [mark]
    doc.enhancement = Enhancement(brightness=1.2)
    borrowed_base, borrowed_marks, _ = doc.snapshot(copy_base=False)
    expected = noise.crop((10, 20, 110, 140)).resize((50, 60), Image.Resampling.LANCZOS)
    doc.crop((10, 20, 110, 140), output_size=(50, 60), allow_resize=True)
    assert doc.base.size == (50, 60) and doc.base.tobytes() == expected.tobytes()
    assert len(doc.history) == 1 and doc.enhancement.brightness == 1.2
    scaled = doc.watermarks[0]
    assert (scaled.x, scaled.y, scaled.size) == (5, 10, 10)
    assert scaled.text_bitmap.size == (10, 5)
    assert (scaled.row_spacing, scaled.column_spacing) == (6, 5)
    assert borrowed_base.tobytes() == noise.tobytes()
    assert borrowed_marks[0].text_bitmap is bitmap and bitmap.size == (20, 10)
    doc.undo()
    assert doc.base.size == noise.size and doc.base.tobytes() == noise.tobytes()
    assert doc.watermarks[0].x == 20 and doc.watermarks[0].text_bitmap.size == (20, 10)
    assert not doc.history
    doc.redo()
    assert doc.base.tobytes() == expected.tobytes() and doc.watermarks[0].text_bitmap.size == (10, 5)


@pytest.mark.parametrize("size", [(0, 10), (10, -1), (30001, 10), (20000, 20000)])
def test_invalid_template_crop_keeps_pixels_and_history_unchanged(noise, size):
    doc = Document(noise, {})
    with pytest.raises(ValueError, match="裁剪输出尺寸"):
        doc.crop((0, 0, 100, 120), output_size=size)
    assert not doc.history and doc.revision == 0
    assert doc.base.tobytes() == noise.tobytes()


@pytest.mark.parametrize("mode", ["brush", "mosaic", "blur", "erase"])
def test_local_stroke_changes_only_selected_region(noise, mode):
    edited = paint_stroke(noise, [(20, 20), (35, 35), (50, 35)], mode, 12, "#ff0000", 1, 10)
    assert edited.getpixel((30, 30)) != noise.getpixel((30, 30))
    assert edited.getpixel((90, 90)) == noise.getpixel((90, 90))
    assert noise.getpixel((30, 30))[3] == 255
    if mode == "erase":
        assert edited.getpixel((30, 30))[3] == 0
    if mode == "mosaic":
        assert edited.getpixel((31, 30)) == edited.getpixel((32, 30))


def test_enhancement_combines_preserving_alpha_and_original(noise):
    source = noise.copy()
    source.putalpha(127)
    result = enhance(
        source,
        Enhancement(
            brightness=1.2,
            contrast=1.1,
            saturation=0.8,
            temperature=0.2,
            gamma=1.1,
            white_balance=True,
            denoise=True,
            equalize=True,
            autocontrast=True,
        ),
    )
    assert result.size == source.size
    assert result.getchannel("A").tobytes() == source.getchannel("A").tobytes()
    assert result.tobytes() != source.tobytes()
    assert source.getpixel((0, 0))[3] == 127


def test_document_render_and_history_preserve_editable_enhancement_parameters(noise):
    doc = Document(noise, {})
    original = noise.tobytes()
    doc.checkpoint()
    doc.enhancement.brightness = 1.3
    adjusted = doc.render().tobytes()
    assert adjusted != original and doc.base.tobytes() == original
    doc.checkpoint()
    doc.enhancement.contrast = 1.5
    doc.undo()
    assert doc.render().tobytes() == adjusted
    assert doc.enhancement.brightness == 1.3 and doc.enhancement.contrast == 1
    doc.redo()
    assert doc.enhancement.contrast == 1.5
    doc.undo()
    doc.undo()
    assert doc.enhancement == Enhancement() and doc.render().tobytes() == original


def test_automatic_enhancement_ignores_inactive_manual_parameters(noise):
    automatic = Enhancement(autocontrast=True, white_balance=True)
    retained = Enhancement(autocontrast=True, contrast=1.5, white_balance=True, temperature=0.4)
    assert enhance(noise, automatic).tobytes() == enhance(noise, retained).tobytes()


def test_tiled_text_watermark_spacing_opacity_and_lossless_export():
    source = Image.new("RGBA", (500, 400), "white")
    mark = Watermark(
        text="TEST",
        x=10,
        y=10,
        size=18,
        angle=0,
        opacity=0.5,
        row_spacing=20,
        column_spacing=30,
        color="#ff0000",
    )
    glyph = mark.bitmap()
    sample = next(
        (x, y) for y in range(glyph.height) for x in range(glyph.width) if glyph.getpixel((x, y))[3] > 0
    )
    x, y = 10 + sample[0], 10 + sample[1]
    step_x, step_y = glyph.width + mark.column_spacing, glyph.height + mark.row_spacing
    result = compose(source, [mark])
    assert result.getpixel((x, y)) != source.getpixel((x, y))
    assert result.getpixel((x, y)) == result.getpixel((x + step_x, y)) == result.getpixel((x, y + step_y))
    assert result.getpixel((10 + glyph.width + 15, y)) == source.getpixel((x, y))
    encoded = compress(
        result, ExportOptions(format="PNG", width=500, height=400, max_bytes=None, allow_quality=False)
    )
    with Image.open(BytesIO(encoded.data)) as exported:
        assert exported.convert("RGBA").tobytes() == result.tobytes()
    mark.column_spacing = 150
    wider_columns = compose(source, [mark])
    assert wider_columns.getpixel((x + step_x, y)) == source.getpixel((x, y))
    assert wider_columns.getpixel((x, y + step_y)) == result.getpixel((x, y))
    mark.column_spacing = 30
    mark.row_spacing = 100
    wider_rows = compose(source, [mark])
    assert wider_rows.getpixel((x, y + step_y)) == source.getpixel((x, y))
    assert wider_rows.getpixel((x + step_x, y)) == result.getpixel((x, y))


@pytest.mark.parametrize("spacing", [(0, 0), (60, 80)])
def test_crop_preserves_existing_tiled_text_pattern(spacing):
    source = Image.new("RGBA", (500, 400), "white")
    doc = Document(source, {})
    doc.watermarks.append(
        Watermark(text="TEST", x=90, y=80, row_spacing=spacing[0], column_spacing=spacing[1])
    )
    expected = doc.render().crop((43, 31, 340, 290))
    doc.crop((43, 31, 340, 290))
    assert doc.render().tobytes() == expected.tobytes()


@pytest.mark.parametrize("origin", [(0, 0), (-91, -63), (80, 95)])
@pytest.mark.parametrize("spacing", [(0, 0), (17, 23), (900, 700)])
def test_optimized_tiling_matches_individual_glyph_composition(origin, spacing):
    source = Image.new("RGBA", (310, 250), (54, 88, 110, 130))
    mark = Watermark(
        text="TEST", size=14, x=origin[0], y=origin[1], row_spacing=spacing[0], column_spacing=spacing[1]
    )
    layer = mark.bitmap()
    expected = source.copy()
    step_x, step_y = layer.width + spacing[1], layer.height + spacing[0]
    for y in range(round(mark.y) % step_y - step_y, source.height, step_y):
        for x in range(round(mark.x) % step_x - step_x, source.width, step_x):
            expected.alpha_composite(layer, (x, y))
    assert compose(source, [mark]).tobytes() == expected.tobytes()


def test_large_photo_preview_bounds_memory_and_retains_watermark_pattern():
    from photocraft.core import watermark_preview

    preview, scale = watermark_preview(
        (10000, 8000), [Watermark(text="X", size=4, row_spacing=0, column_spacing=0)]
    )
    assert preview.size == (1600, 1280) and scale == 0.16
    assert preview.getchannel("A").getbbox() is not None


@pytest.mark.parametrize("key", ["denoise", "equalize"])
def test_enhancement_strength_interpolates_without_changing_alpha(noise, key):
    original = enhance(noise, Enhancement())
    full = enhance(noise, Enhancement(**{key: 1}))
    half = enhance(noise, Enhancement(**{key: 0.5}))
    assert half.tobytes() == Image.blend(original, full, 0.5).tobytes()
    assert half.getchannel("A").tobytes() == noise.getchannel("A").tobytes()
