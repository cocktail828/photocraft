from copy import deepcopy

import pytest

from photocraft.config import (
    Config,
    ConfigError,
    config_directory,
    default_preferences,
    read_toml,
    write_toml,
)
from photocraft.presets import PRESETS


def test_old_formats_are_discarded_without_importing_templates(tmp_path):
    path = tmp_path / "PhotoCraft.conf"
    path.write_text("[General]\ndark=true\npresets=old-templates\ngeometry=@ByteArray(old)\n")
    obsolete = tmp_path / "config.toml"
    obsolete.write_text(
        '[appearance]\ntheme="dark"\n[[crop.templates]]\nname="旧模板"\nwidth_px=999\nheight_px=999\n',
        encoding="utf-8",
    )
    state = tmp_path / "state.toml"
    state.write_text("[window]\nwidth=2000\nheight=1200\n")
    original = {p.name: p.read_bytes() for p in (path, obsolete, state)}
    config = Config(tmp_path)
    assert not config.errors
    assert config.path == path and config.theme == "light"
    assert len(config.templates) == len(PRESETS)
    assert all(p["name"] != "旧模板" for p in config.templates)
    assert not obsolete.exists() and not state.exists()
    assert config.retired_directory is not None
    assert all((config.retired_directory / name).read_bytes() == body for name, body in original.items())
    assert "[[crop.templates]]" in path.read_text(encoding="utf-8")
    assert "@ByteArray" not in path.read_text(encoding="utf-8")
    assert Config(tmp_path).templates == config.templates
    assert len(list(tmp_path.glob("retired-*"))) == 1


def test_old_toml_filename_is_not_imported_when_main_config_is_missing(tmp_path):
    (tmp_path / "config.toml").write_text('[appearance]\ntheme="dark"\n[crop]\ntemplates=[]\n')
    config = Config(tmp_path)
    assert config.path.name == "PhotoCraft.conf" and config.theme == "light"
    assert len(config.templates) == len(PRESETS)
    assert not (tmp_path / "config.toml").exists()


def test_manual_minimal_template_empty_list_and_theme(tmp_path):
    path = tmp_path / "PhotoCraft.conf"
    path.write_text(
        """[appearance]
theme = "dark"
[[crop.templates]]
name = "自定义头像"
width_px = 300
height_px = 400
""",
        encoding="utf-8",
    )
    config = Config(tmp_path)
    assert not config.errors and config.theme == "dark"
    assert config.templates[0]["width"] == 300 and config.templates[0]["dpi"] == 300
    assert config.templates[0]["format"] == "JPEG"
    path.write_text("[crop]\ntemplates = []\n", encoding="utf-8")
    assert Config(tmp_path).templates == []


def test_new_templates_have_no_size_limit_and_old_limit_is_only_preserved_data(tmp_path):
    config = Config(tmp_path)
    assert all("max_kb" not in p for p in read_toml(config.path)["crop"]["templates"])
    config.path.write_text(
        '[[crop.templates]]\nname="旧模板"\nwidth_px=700\nheight_px=700\nmax_kb=1\n',
        encoding="utf-8",
    )
    config.reload()
    assert not config.errors and "kb" not in config.templates[0]
    config.save_template({**config.templates[0], "width": 800})
    assert read_toml(config.path)["crop"]["templates"][0]["max_kb"] == 1
    assert config.templates[0]["width"] == 800


def test_saving_template_merges_new_manual_edits_and_preserves_unknown_fields(tmp_path):
    config = Config(tmp_path)
    manual = read_toml(config.path)
    manual["extra"] = {"note": "用户备注", "enabled": True, "list": [1, "hello", False]}
    manual["crop"]["templates"][0]["note"] = "模板备注"
    manual["crop"]["templates"][1]["width_px"] = 420
    write_toml(config.path, manual)
    changed = {**PRESETS[0], "width": 300}
    templates = config.save_template(changed)
    assert len(templates) == len(PRESETS)
    assert templates[0]["width"] == 300 and templates[1]["width"] == 420
    saved = read_toml(config.path)
    assert saved["extra"] == manual["extra"]
    assert saved["crop"]["templates"][0]["note"] == "模板备注"
    config.set_theme(True)
    assert read_toml(config.path)["crop"] == saved["crop"]


@pytest.mark.parametrize(
    "body,field",
    [
        ('[crop]\ntemplates = "oops"\n', "crop.templates"),
        ('[appearance]\ntheme = "oops"\n', "appearance.theme"),
        ('[watermark]\ncolor = "red"\n', "watermark.color"),
        ('[colors]\ncustom = ["#abc"]\n', "colors.custom"),
        ('[colors]\ncustom = "#ffffff"\n', "colors.custom"),
        ("colors = []\n", "colors"),
        ("[colors]\ncustom = [" + ",".join(['"#ffffff"'] * 17) + "]\n", "colors.custom"),
        ('[[crop.templates]]\nname="X"\nwidth_px=0\nheight_px=10\n', "width_px"),
        ('[[crop.templates]]\nname="X"\nwidth_px=true\nheight_px=10\n', "width_px"),
        ('[[crop.templates]]\nname="X"\nwidth_px=10\nheight_px=10\ndpi=-1\n', "dpi"),
        ('[[crop.templates]]\nname="X"\nwidth_px=10\nheight_px=10\nwidth_mm=nan\n', "width_mm"),
        ('[[crop.templates]]\nname="X"\nwidth_px=10\nheight_px=10\nbackground="bad"\n', "background"),
    ],
)
def test_invalid_values_report_field_and_never_overwrite_file(tmp_path, body, field):
    path = tmp_path / "PhotoCraft.conf"
    path.write_text(body, encoding="utf-8")
    config = Config(tmp_path)
    assert config.errors and field in config.errors[0] and str(path) in config.errors[0]
    with pytest.raises(ConfigError):
        config.set_theme(True)
    with pytest.raises(ConfigError):
        config.save_template(PRESETS[0])
    assert path.read_text(encoding="utf-8") == body


def test_broken_toml_is_kept_and_can_be_fixed_without_reinstalling(tmp_path):
    path = tmp_path / "PhotoCraft.conf"
    body = '[appearance\ntheme = "dark"\n'
    path.write_text(body, encoding="utf-8")
    config = Config(tmp_path)
    assert config.errors and str(path) in config.errors[0]
    assert path.read_text(encoding="utf-8") == body
    path.write_text('[appearance]\ntheme = "dark"\n', encoding="utf-8")
    assert Config(tmp_path).theme == "dark"


def test_state_changes_do_not_rewrite_manual_comments_or_templates(tmp_path):
    config = Config(tmp_path)
    body = config.path.read_text(encoding="utf-8") + "\n# 我的备注，不要在退出时重写\n"
    config.path.write_text(body, encoding="utf-8")
    state = dict(width=1200, height=800, x=20, y=30, maximized=False)
    config.save_window(state)
    assert config.path.read_text(encoding="utf-8") == body
    assert read_toml(config.state_path)["window"] == state
    assert Config(tmp_path).window == state
    assert "@ByteArray" not in config.state_path.read_text(encoding="utf-8")


def test_failed_atomic_save_keeps_existing_preferences(tmp_path, monkeypatch):
    import photocraft.config as module

    config = Config(tmp_path)
    original = config.path.read_bytes()

    def fail_replace(*args):
        raise OSError("simulated write failure")

    monkeypatch.setattr(module.os, "replace", fail_replace)
    with pytest.raises(ConfigError, match="simulated"):
        config.set_theme(True)
    assert config.path.read_bytes() == original
    assert not list(tmp_path.glob(".PhotoCraft.conf-*"))


def test_duplicate_template_names_are_reported(tmp_path):
    data = default_preferences()
    data["crop"]["templates"].append(deepcopy(data["crop"]["templates"][0]))
    write_toml(tmp_path / "PhotoCraft.conf", data)
    assert "重复" in Config(tmp_path).errors[0]


def test_config_directory_matches_platform_conventions(tmp_path, monkeypatch):
    import photocraft.config as module

    monkeypatch.delenv("PHOTOCRAFT_CONFIG_DIR")
    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert config_directory() == tmp_path / "xdg/PhotoCraft"
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    assert config_directory() == tmp_path / "roaming/PhotoCraft"
    monkeypatch.setenv("PHOTOCRAFT_CONFIG_DIR", str(tmp_path / "portable"))
    assert config_directory() == tmp_path / "portable"


def test_import_export_and_reload_preserve_text_and_use_fixed_filename(tmp_path):
    config = Config(tmp_path / "app")
    source = tmp_path / "import.toml"
    body = '# 手写备注\n[appearance]\ntheme = "dark"\n[[crop.templates]]\nname = "导入模板"\nwidth_px = 360\nheight_px = 480\n'
    source.write_text(body, encoding="utf-8")
    config.import_file(source)
    assert config.path.name == "PhotoCraft.conf"
    assert config.theme == "dark" and config.templates[0]["width"] == 360
    assert config.path.read_text(encoding="utf-8") == body
    destination = tmp_path / "backup/PhotoCraft.conf"
    config.export_file(destination)
    assert destination.read_text(encoding="utf-8") == body
    config.path.write_text("[crop]\ntemplates=[]\n", encoding="utf-8")
    config.reload()
    assert config.templates == [] and config.theme == "light"


@pytest.mark.parametrize(
    "body",
    [
        '[appearance\ntheme="dark"',
        '[[crop.templates]]\nname="bad"\nwidth_px=-2\nheight_px=300\n',
        "[General]\ndark=true\n",
    ],
)
def test_invalid_import_leaves_saved_configuration_and_current_values_unchanged(tmp_path, body):
    config = Config(tmp_path / "app")
    original, templates = config.path.read_bytes(), deepcopy(config.templates)
    source = tmp_path / "invalid.conf"
    source.write_text(body, encoding="utf-8")
    with pytest.raises(ConfigError):
        config.import_file(source)
    assert config.path.read_bytes() == original
    assert config.theme == "light" and config.templates == templates


def test_invalid_reload_does_not_replace_in_memory_preferences(tmp_path):
    config = Config(tmp_path)
    templates = deepcopy(config.templates)
    config.path.write_text('[appearance]\ntheme="invalid"\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        config.reload()
    assert config.theme == "light" and config.templates == templates
    config.reset()
    assert not config.errors and read_toml(config.path) == default_preferences()


def test_reset_does_not_reset_window_state_and_export_refuses_invalid_data(tmp_path):
    config = Config(tmp_path)
    config.save_window(dict(width=1200, height=800, x=1, y=2, maximized=False))
    state = config.state_path.read_bytes()
    config.set_theme(True)
    config.path.write_text("broken = [", encoding="utf-8")
    destination = tmp_path / "export.conf"
    destination.write_text("existing export", encoding="utf-8")
    with pytest.raises(ConfigError):
        config.export_file(destination)
    assert destination.read_text(encoding="utf-8") == "existing export"
    config.reset()
    assert config.theme == "light" and config.templates == Config(tmp_path).templates
    assert config.state_path.read_bytes() == state


def test_new_toml_with_an_extra_general_section_is_not_discarded(tmp_path):
    path = tmp_path / "PhotoCraft.conf"
    body = '[General]\ndark=true\n[appearance]\ntheme="dark"\n[crop]\ntemplates=[]\n'
    path.write_text(body, encoding="utf-8")
    config = Config(tmp_path)
    assert not config.errors and config.theme == "dark" and config.templates == []
    assert path.read_text(encoding="utf-8") == body


def test_palette_roundtrip_reload_and_reset_preserve_deleted_templates(tmp_path):
    from photocraft.config import DEFAULT_CUSTOM_COLORS, DEFAULT_WATERMARK_COLOR

    path = tmp_path / "PhotoCraft.conf"
    path.write_text('[crop]\ntemplates=[]\n[extra]\nnote="保留"\n', encoding="utf-8")
    config = Config(tmp_path)
    assert config.custom_colors == list(DEFAULT_CUSTOM_COLORS)
    custom = ["#123456", "#ABCDEF"]
    config.save_colors(custom, watermark_color="#223344")
    restored = Config(tmp_path)
    assert restored.custom_colors[:2] == ["#123456", "#abcdef"]
    assert len(restored.custom_colors) == 16 and restored.watermark_color == "#223344"
    assert restored.templates == [] and read_toml(path)["extra"]["note"] == "保留"
    source = tmp_path / "palette.conf"
    source.write_text('[watermark]\ncolor="#FF0000"\n[colors]\ncustom=["#010203"]\n', encoding="utf-8")
    restored.import_file(source)
    assert restored.watermark_color == "#ff0000" and restored.custom_colors[0] == "#010203"
    restored.reset()
    assert restored.custom_colors == list(DEFAULT_CUSTOM_COLORS)
    assert restored.watermark_color == DEFAULT_WATERMARK_COLOR


def test_default_templates_include_exam_sizes():
    assert [p["name"] for p in PRESETS] == [
        "1 寸证件照 · 295 × 413 px",
        "2 寸证件照 · 413 × 579 px",
        "教师资格考试（参考）· 150 × 200 px",
        "国家公务员考试（参考）· 295 × 413 px",
    ]
    assert [(p["width"], p["height"]) for p in PRESETS[-2:]] == [(150, 200), (295, 413)]
