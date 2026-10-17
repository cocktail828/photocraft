"""Editable TOML in PhotoCraft.conf, shared by the service and optional desktop UI."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import sys
import tempfile
import tomllib
from copy import deepcopy
from datetime import date, datetime, time
from pathlib import Path

from .presets import PRESETS

CONFIG_FILENAME = "PhotoCraft.conf"
DEFAULT_WATERMARK_COLOR = "#64748b"
# Qt exposes 16 custom slots. Seed them explicitly on both native platforms.
DEFAULT_CUSTOM_COLORS = (
    "#000000",
    "#ffffff",
    "#64748b",
    "#ef4444",
    "#f97316",
    "#f59e0b",
    "#eab308",
    "#84cc16",
    "#22c55e",
    "#14b8a6",
    "#06b6d4",
    "#3b82f6",
    "#6366f1",
    "#8b5cf6",
    "#d946ef",
    "#ec4899",
)

TEMPLATE_KEYS = {
    "name": "name",
    "width": "width_px",
    "height": "height_px",
    "mm_w": "width_mm",
    "mm_h": "height_mm",
    "dpi": "dpi",
    "format": "format",
    "background": "background",
}


class ConfigError(ValueError):
    pass


def config_directory():
    override = os.environ.get("PHOTOCRAFT_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "PhotoCraft"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/PhotoCraft"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "PhotoCraft"


def template_record(preset):
    return {external: preset[internal] for internal, external in TEMPLATE_KEYS.items()}


def default_preferences():
    return {
        "appearance": {"theme": "light"},
        "watermark": {"color": DEFAULT_WATERMARK_COLOR},
        "colors": {"custom": list(DEFAULT_CUSTOM_COLORS)},
        "crop": {"templates": [template_record(p) for p in PRESETS]},
    }


def preference_colors(data):
    watermark, colors = data.get("watermark", {}), data.get("colors", {})
    if not isinstance(watermark, dict) or not isinstance(colors, dict):
        raise ConfigError("watermark 和 colors 必须是 TOML 配置节。")
    selected = watermark.get("color", DEFAULT_WATERMARK_COLOR)
    custom = colors.get("custom", list(DEFAULT_CUSTOM_COLORS))
    if not isinstance(custom, list) or len(custom) > len(DEFAULT_CUSTOM_COLORS):
        raise ConfigError("colors.custom 必须是最多 16 项的颜色列表。")
    for field, color in [("watermark.color", selected), *(("colors.custom", c) for c in custom)]:
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ConfigError(f"{field} 请使用 #RRGGBB 颜色。")
    palette = list(DEFAULT_CUSTOM_COLORS)
    palette[: len(custom)] = [color.lower() for color in custom]
    return selected.lower(), palette


def read_toml(path):
    try:
        return tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise ConfigError(f"配置读取失败：{path}\n{error}") from error


def _value(value):
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value).lower()
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{_key(k)} = {_value(v)}" for k, v in value.items()) + " }"
    raise ConfigError(f"不支持的配置值：{type(value).__name__}")


def _key(key):
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else _value(key)


def toml_text(data, *, state=False):
    lines = (
        ["# PhotoCraft 窗口状态；个人偏好与裁剪模板请编辑 PhotoCraft.conf。"]
        if state
        else [
            "# PhotoCraft 配置（UTF-8 TOML）。由部署管理员编辑，修改后重启服务生效。",
            "# 每个 [[crop.templates]] 块对应一个下拉模板，可直接修改或删除。",
            "# 仅保留自由裁剪与按比例裁剪：将 [crop] 下的 templates 设为 []。",
            "# 模板锁定输出像素 width_px / height_px；图像压缩仅设置格式、画质与编码选项。",
            "# watermark.color：默认水印颜色；colors.custom：16 个预定义颜色（#RRGGBB）。",
        ]
    )

    def tables(table, path=()):
        nested = []
        for key, value in table.items():
            array = isinstance(value, list) and bool(value) and all(isinstance(v, dict) for v in value)
            if isinstance(value, dict) or array:
                nested.append((key, value, array))
            else:
                lines.append(f"{_key(key)} = {_value(value)}")
        for key, value, array in nested:
            child_path = (*path, key)
            title = ".".join(_key(part) for part in child_path)
            for entry in value if array else [value]:
                lines.extend(["", f"[[{title}]]" if array else f"[{title}]"])
                tables(entry, child_path)

    tables(data)
    return "\n".join(lines) + "\n"


def write_toml(path, data, *, state=False):
    write_text(path, toml_text(data, state=state))


def write_text(path, text):
    path = Path(path)
    tomllib.loads(text)  # Validate before touching the existing file.
    temp_name = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix="." + path.name + "-", dir=path.parent)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except OSError as error:
        raise ConfigError(f"无法保存配置：{path}\n{error}") from error
    finally:
        if temp_name is not None:
            Path(temp_name).unlink(missing_ok=True)


def validate_preferences(data):
    preference_colors(data)

    def invalid(message):
        raise ConfigError(message)

    appearance, crop = data.get("appearance", {}), data.get("crop", {})
    if not isinstance(appearance, dict) or not isinstance(crop, dict):
        invalid("appearance 和 crop 必须是 TOML 配置节。")
    theme = appearance.get("theme", "light")
    if theme not in ("light", "dark"):
        invalid('appearance.theme 只支持 "light" 或 "dark"。')
    records = crop.get("templates", []) if "crop" in data else default_preferences()["crop"]["templates"]
    if not isinstance(records, list):
        invalid("crop.templates 必须是模板列表，使用 [[crop.templates]]。")
    templates, names = [], set()
    for index, record in enumerate(records, 1):
        prefix = f"第 {index} 个裁剪模板"
        if not isinstance(record, dict):
            invalid(prefix + "必须是 TOML 配置块。")
        name = record.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            invalid(prefix + "的 name 需为 1–100 字的非空名称。")
        name = name.strip()
        if name in names:
            invalid(f"模板名称重复：{name}")
        names.add(name)

        def integer(key, default, minimum, maximum):
            value = record.get(key, default)
            if type(value) is not int or not minimum <= value <= maximum:
                invalid(f"{prefix}（{name}）的 {key} 需为 {minimum}–{maximum} 的整数。")
            return value

        width, height = integer("width_px", None, 1, 30000), integer("height_px", None, 1, 30000)
        if width * height > 100_000_000:
            invalid(prefix + "的总像素不能超过一亿。")
        dpi = integer("dpi", 300, 1, 9600)
        fmt, background = record.get("format", "JPEG"), record.get("background", "#ffffff")
        if fmt not in ("JPEG", "PNG", "WEBP", "BMP", "TIFF"):
            invalid(f"{prefix}（{name}）的 format 不支持：{fmt}")
        if not isinstance(background, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", background):
            invalid(f"{prefix}（{name}）的 background 请使用 #RRGGBB。")
        millimeters = []
        for key, pixels in (("width_mm", width), ("height_mm", height)):
            value = record.get(key, min(1000, max(0.1, round(pixels * 25.4 / dpi, 2))))
            if type(value) not in (int, float) or not math.isfinite(value) or not 0.1 <= value <= 1000:
                invalid(f"{prefix}（{name}）的 {key} 需为 0.1–1000 的数字。")
            millimeters.append(value)
        templates.append(
            dict(
                name=name,
                width=width,
                height=height,
                dpi=dpi,
                format=fmt,
                background=background,
                mm_w=millimeters[0],
                mm_h=millimeters[1],
            )
        )
    return theme, templates


def is_obsolete_qsettings(text):
    return (
        text.lstrip("\ufeff \t\r\n").startswith("[General]")
        and re.search(r"(?m)^(?:dark|geometry|presets)\s*=", text) is not None
        and re.search(r"""(?m)^\s*\[\[?\s*(?:appearance|crop|["'](?:appearance|crop)["'])\s*[.\]]""", text)
        is None
    )


def parse_preferences(text, path):
    try:
        if is_obsolete_qsettings(text):
            raise ConfigError("不支持旧版 QSettings 配置；请使用 TOML 配置。")
        data = tomllib.loads(text.lstrip("\ufeff"))
        validate_preferences(data)
        return data
    except (ValueError, TypeError) as error:
        raise ConfigError(f"配置无效：{path}\n{error}") from error


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8-sig")
    except (OSError, ValueError) as error:
        raise ConfigError(f"无法读取配置：{path}\n{error}") from error


class Config:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else config_directory()
        self.path = self.directory / CONFIG_FILENAME
        self.state_path = self.directory / "state.toml"
        self.errors = []
        self.retired_directory = None
        self.data = default_preferences()
        reset_state = False
        try:
            if self.path.exists():
                text = read_text(self.path)
                if is_obsolete_qsettings(text):
                    self._preserve_obsolete([self.path, self.directory / "config.toml", self.state_path])
                    write_toml(self.path, self.data)
                    reset_state = True
                else:
                    self.data = parse_preferences(text, self.path)
                    self._preserve_obsolete([self.directory / "config.toml"])
            else:
                reset_state = (self.directory / "config.toml").exists()
                self._preserve_obsolete(
                    [self.directory / "config.toml", self.state_path] if reset_state else []
                )
                write_toml(self.path, self.data)
        except ConfigError as error:
            self.errors.append(str(error))
            self.data = default_preferences()
        else:
            try:
                (self.directory / "config.toml").unlink(missing_ok=True)
                if reset_state:
                    self.state_path.unlink(missing_ok=True)
            except OSError as error:
                self.errors.append(f"无法清理已停用的旧配置：{error}")
        self.theme, self.templates = validate_preferences(self.data)
        self.window = {}
        if self.state_path.exists() and not reset_state:
            try:
                self.window = self._window(read_toml(self.state_path))
            except ConfigError as error:
                self.errors.append(str(error))

    def _preferences(self):
        return parse_preferences(read_text(self.path), self.path)

    def _preserve_obsolete(self, paths):
        files = [path for path in paths if path.is_file()]
        if not files:
            return
        try:
            folder = Path(
                tempfile.mkdtemp(
                    prefix="retired-" + datetime.now().strftime("%Y%m%d-%H%M%S-"), dir=self.directory
                )
            )
            for path in files:
                shutil.copy2(path, folder / path.name)
            self.retired_directory = folder
        except OSError as error:
            raise ConfigError(f"旧配置备份失败，未覆盖旧文件：{error}") from error

    def _apply_data(self, data):
        theme, templates = validate_preferences(data)
        self.data, self.theme, self.templates = data, theme, templates
        self.errors.clear()

    def reload(self):
        self._apply_data(self._preferences())

    def save_text(self, text):
        data = parse_preferences(text, self.path)
        write_text(self.path, text.lstrip("\ufeff"))
        self._apply_data(data)

    def import_file(self, source):
        source = Path(source)
        text = read_text(source)
        data = parse_preferences(text, source)
        write_text(self.path, text.lstrip("\ufeff"))
        self._apply_data(data)

    def export_file(self, destination):
        text = read_text(self.path)
        parse_preferences(text, self.path)
        write_text(Path(destination), text)

    def reset(self):
        data = default_preferences()
        write_toml(self.path, data)
        self._apply_data(data)

    def set_theme(self, dark):
        data = self._preferences()
        data.setdefault("appearance", {})["theme"] = "dark" if dark else "light"
        write_toml(self.path, data)
        self.data, self.theme = data, data["appearance"]["theme"]

    @property
    def watermark_color(self):
        return preference_colors(self.data)[0]

    @property
    def custom_colors(self):
        return preference_colors(self.data)[1]

    def save_colors(self, custom, *, watermark_color=None):
        # Read again so choosing a color never restores manually deleted templates.
        data = self._preferences()
        data.setdefault("colors", {})["custom"] = list(custom)
        if watermark_color is not None:
            data.setdefault("watermark", {})["color"] = watermark_color
        validate_preferences(data)
        write_toml(self.path, data)
        self._apply_data(data)

    def save_template(self, preset, *, overwrite=True):
        data = self._preferences()
        _, templates = validate_preferences(data)
        records = data.setdefault("crop", {}).setdefault("templates", [template_record(p) for p in templates])
        found = next(
            (i for i, item in enumerate(records) if item["name"].strip() == preset["name"].strip()),
            len(records),
        )
        if found < len(records) and not overwrite:
            raise ConfigError("已有同名模板，请使用其他名称。")
        record = template_record(preset)
        if found == len(records):
            records.append(record)
        else:
            records[found] = {**records[found], **record}
        theme, templates = validate_preferences(data)
        write_toml(self.path, data)
        self.data, self.theme, self.templates = data, theme, templates
        return deepcopy(templates)

    @staticmethod
    def _window(data):
        window = data.get("window", {})
        if not isinstance(window, dict):
            raise ConfigError("state.toml 的 window 必须是配置节。")
        for key in ("width", "height", "x", "y"):
            if key in window and type(window[key]) is not int:
                raise ConfigError(f"state.toml 的 window.{key} 必须为整数。")
        if "maximized" in window and type(window["maximized"]) is not bool:
            raise ConfigError("state.toml 的 window.maximized 必须为 true 或 false。")
        return window

    def save_window(self, window):
        data = read_toml(self.state_path) if self.state_path.exists() else {}
        self._window(data)
        data["window"] = dict(window)
        write_toml(self.state_path, data, state=True)
        self.window = dict(window)
