"""Launch the frozen GUI and exercise a full encode/save/decode round trip."""

import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

root = Path(__file__).resolve().parents[1]
exe = root / "dist/PhotoCraft" / ("PhotoCraft.exe" if sys.platform == "win32" else "PhotoCraft")
with tempfile.TemporaryDirectory() as directory:
    report = Path(directory) / "result.txt"
    config_dir = Path(directory) / "config"
    config_dir.mkdir()
    (config_dir / "PhotoCraft.conf").write_text("[General]\ndark=true\npresets=[]\n", encoding="utf-8")
    (config_dir / "config.toml").write_text(
        '[appearance]\ntheme="dark"\n[crop]\ntemplates=[]\n', encoding="utf-8"
    )
    env = dict(
        os.environ,
        QT_QPA_PLATFORM="offscreen",
        PHOTOCRAFT_SMOKE_REPORT=str(report),
        PHOTOCRAFT_CONFIG_DIR=str(config_dir),
    )
    result = subprocess.run([str(exe), "--smoke-test"], env=env, capture_output=True, text=True, timeout=90)
    print(result.stdout)
    print(result.stderr)
    if result.returncode != 0 or not report.exists() or report.read_text() != "PHOTOCRAFT_SMOKE_OK":
        raise SystemExit("Frozen GUI smoke test failed")
    config = tomllib.loads((config_dir / "PhotoCraft.conf").read_text(encoding="utf-8"))
    if config.get("appearance", {}).get("theme") != "light" or not config.get("crop", {}).get("templates"):
        raise SystemExit("Frozen application did not reset obsolete configuration")
    if len(config["crop"]["templates"]) != 3:
        raise SystemExit("Frozen application restored removed crop templates")
    if len(config.get("colors", {}).get("custom", [])) != 16:
        raise SystemExit("Frozen application is missing the default custom color palette")
    if (config_dir / "config.toml").exists():
        raise SystemExit("Frozen application still uses the obsolete configuration filename")
    preserved = list(config_dir.glob("retired-*/PhotoCraft.conf"))
    if not preserved or "[General]" not in preserved[0].read_text(encoding="utf-8"):
        raise SystemExit("Frozen application did not preserve the obsolete configuration before replacing it")
    print("Frozen configuration filename and obsolete-data reset verified")
    print("Frozen GUI smoke test passed")
