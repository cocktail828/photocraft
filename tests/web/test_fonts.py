from types import SimpleNamespace

import pytest

from photocraft import web_fonts


@pytest.fixture(autouse=True)
def clear_font_cache():
    web_fonts.fonts.cache_clear()
    yield
    web_fonts.fonts.cache_clear()


def test_no_system_fonts_can_render(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(web_fonts.subprocess, "run", missing)
    monkeypatch.setattr(web_fonts, "system_font_dirs", lambda: ())
    assert web_fonts.fonts() == []
    bitmap = web_fonts.text_bitmap("Sample", "", 24, "#123456")
    assert bitmap.mode == "RGBA"
    assert bitmap.getchannel("A").getbbox() is not None
    with pytest.raises(ValueError, match="字体不可用"):
        web_fonts.text_bitmap("Sample", "unavailable", 24, "#123456")


def test_discovers_arbitrary_system_family(tmp_path, monkeypatch):
    file = tmp_path / "system-font.ttc"
    file.touch()
    monkeypatch.setattr(
        web_fonts.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=f"Available Family\t{file}\t1\n"),
    )
    record, = web_fonts.fonts()
    assert record["name"] == "Available Family"
    assert record["path"] == str(file)
    assert record["index"] == 1


def test_directory_fallback_uses_discovered_family(tmp_path, monkeypatch):
    file = tmp_path / "arbitrary.otf"
    file.touch()

    def missing(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(web_fonts.subprocess, "run", missing)
    monkeypatch.setattr(web_fonts, "system_font_dirs", lambda: (tmp_path,))
    monkeypatch.setattr(
        web_fonts.ImageFont, "truetype", lambda *args: SimpleNamespace(getname=lambda: ("Local Family", "Regular"))
    )
    record, = web_fonts.fonts()
    assert record["name"] == "Local Family"
