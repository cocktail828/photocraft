import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter


def full_frame_stroke(image, points, mode, size, color, opacity, block=12):
    mask = Image.new("L", image.size)
    draw = ImageDraw.Draw(mask)
    xy = [(round(x), round(y)) for x, y in points]
    draw.line(xy, fill=round(opacity * 255), width=size, joint="curve")
    for x, y in xy:
        r = size / 2
        draw.ellipse((x - r, y - r, x + r, y + r), fill=round(opacity * 255))
    if mode == "blur":
        effect = image.filter(ImageFilter.GaussianBlur(max(1, block / 2)))
    elif mode == "mosaic":
        effect = image.reduce(block)
        effect = effect.resize((effect.width * block, effect.height * block), Image.Resampling.NEAREST).crop(
            (0, 0, *image.size)
        )
    else:
        effect = Image.new("RGBA", image.size, None if mode == "erase" else color)
    return Image.composite(effect, image, mask)


@pytest.mark.parametrize("mode", ["brush", "erase", "blur", "mosaic"])
@pytest.mark.parametrize(
    "points", [[(100, 90), (140, 110)], [(0, 0), (30, 20)], [(316, 210)], [(200.2, 50.8)]]
)
@pytest.mark.parametrize("size", [1, 11, 30])
@pytest.mark.parametrize("block", [2, 12, 100])
def test_local_stroke_matches_full_frame(mode, points, size, block):
    from photocraft.core import paint_stroke

    image = Image.fromarray(np.random.default_rng(1).integers(0, 256, (211, 317, 4), dtype=np.uint8))
    original = image.tobytes()
    args = (image, points, mode, size, "#ff0000", 0.4, block)
    assert paint_stroke(*args).tobytes() == full_frame_stroke(*args).tobytes()
    assert image.tobytes() == original
