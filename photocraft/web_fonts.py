"""Discover and render service-side fonts using Pillow, without requiring a specific family."""

import hashlib
import os
import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def system_font_dirs():
    """Search system and user font locations across supported operating systems."""
    home = Path.home()
    return (
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
        Path(os.environ.get("LOCALAPPDATA", str(home / "AppData/Local"))) / "Microsoft/Windows/Fonts",
        Path("/System/Library/Fonts"),
        Path("/Library/Fonts"),
        home / "Library/Fonts",
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        home / ".fonts",
        Path(os.environ.get("XDG_DATA_HOME", str(home / ".local/share"))) / "fonts",
    )


@lru_cache(maxsize=1)
def fonts():
    records = {}
    try:
        output = subprocess.run(
            ["fc-list", "--format", "%{family[0]}\t%{file}\t%{index}\n"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
            check=True,
        ).stdout
        for line in output.splitlines():
            family, filename, index = line.rsplit("\t", 2)
            index = int(index or 0)
            if not Path(filename).is_file() or index > 100:
                continue
            key = hashlib.sha256(f"{filename}:{index}".encode()).hexdigest()[:16]
            records[key] = dict(id=key, name=family, path=filename, index=index)
    except (OSError, ValueError, subprocess.SubprocessError):
        for root in system_font_dirs():
            if root.is_dir():
                for file in sorted(root.rglob("*")):
                    if file.suffix.lower() not in (".ttf", ".ttc", ".otf"):
                        continue
                    try:
                        family = ImageFont.truetype(str(file), 12).getname()[0]
                    except OSError:
                        continue
                    key = hashlib.sha256(str(file).encode()).hexdigest()[:16]
                    records[key] = dict(id=key, name=family, path=str(file), index=0)
    return sorted(records.values(), key=lambda f: (f["name"].casefold(), f["path"], f["index"]))


def text_bitmap(text, font_id, size, color):
    records = fonts()
    record = next((f for f in records if f["id"] == font_id), None) if font_id else next(iter(records), None)
    if font_id and record is None:
        raise ValueError("所选字体不可用，请重新选择服务端字体。")
    font = (
        ImageFont.truetype(record["path"], size, index=record["index"])
        if record
        else ImageFont.load_default(size=size)
    )
    left, top, right, bottom = font.getbbox(text)
    width, height = max(1, right - left + 8), max(1, bottom - top + 8)
    if width * height > 8_000_000:
        raise ValueError("水印尺寸过大，请减小字号。")
    bitmap = Image.new("RGBA", (width, height))
    ImageDraw.Draw(bitmap).text((4 - left, 4 - top), text, font=font, fill=color)
    return bitmap
