"""Build native offline bundles; run separately on Linux and Windows."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from photocraft.version import build_info  # noqa: E402


def run(args):
    subprocess.run([str(arg) for arg in args], cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-freeze", action="store_true", help="Package an existing dist/PhotoCraft")
    parser.add_argument(
        "--freeze-only", action="store_true", help="Build a local executable; Git identity is optional"
    )
    args = parser.parse_args()
    if args.freeze_only and args.skip_freeze:
        parser.error("--freeze-only 和 --skip-freeze 不能同时使用。")
    try:
        identity = build_info(ROOT, require_identity=not args.freeze_only)
    except ValueError as error:
        parser.error(str(error))
    version = identity.display
    if sys.platform not in ("linux", "win32"):
        parser.error("请在 Linux 或 Windows 本机构建。")
    os.chdir(ROOT)
    if not args.skip_freeze:
        run([sys.executable, "scripts/generate_icons.py"])
        record = ROOT / "photocraft/assets/build-info.json"
        original_record = record.read_bytes() if record.exists() else None
        if identity.commit:
            identity.write(record)
        else:
            record.unlink(missing_ok=True)
        try:
            run(
                [
                    sys.executable,
                    "-m",
                    "PyInstaller",
                    "--noconfirm",
                    "--clean",
                    "--onedir",
                    "--windowed",
                    "--name",
                    "PhotoCraft",
                    "--icon",
                    "photocraft/assets/photocraft.ico",
                    "--add-data",
                    "photocraft/assets:photocraft/assets",
                    "--exclude-module",
                    "PySide6.QtWebEngineCore",
                    "--exclude-module",
                    "PySide6.QtQml",
                    "--exclude-module",
                    "PySide6.QtQuick",
                    "run.py",
                ]
            )
        finally:
            if original_record is None:
                record.unlink(missing_ok=True)
            else:
                record.write_bytes(original_record)
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    bundle = ROOT / "dist/PhotoCraft"
    if not bundle.is_dir():
        raise SystemExit("未找到 dist/PhotoCraft，请先执行冻结构建。")
    frozen_record = bundle / "_internal/photocraft/assets/build-info.json"
    if identity.commit and (
        not frozen_record.exists() or json.loads(frozen_record.read_text()) != asdict(identity)
    ):
        raise SystemExit("冻结程序的 Git 版本与当前源码不一致，请重新构建。")
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", bundle)
    shutil.copy2(ROOT / "LICENSE", bundle)
    notices = bundle / "licenses"
    shutil.copytree(ROOT / "packaging/licenses", notices, dirs_exist_ok=True)
    for name in ("PySide6-Essentials", "shiboken6", "Pillow", "numpy", "pyinstaller"):
        distribution = importlib.metadata.distribution(name)
        destination = notices / name
        destination.mkdir(exist_ok=True)
        (destination / "METADATA.txt").write_text(distribution.read_text("METADATA") or "", encoding="utf-8")
        for file in distribution.files or []:
            if any(word in str(file).lower() for word in ("license", "copying", "notice")):
                source = Path(distribution.locate_file(file))
                if source.is_file():
                    relative = Path(*file.parts[1:]) if ".dist-info" in file.parts[0] else Path(file)
                    target = destination / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    if args.freeze_only:
        print(
            "可执行程序构建完成：", bundle / ("PhotoCraft.exe" if sys.platform == "win32" else "PhotoCraft")
        )
        print("版本：", version)
        return
    if sys.platform == "linux":
        deb_version = identity.deb_version
        stage = ROOT / "build/deb"
        if stage.exists():
            shutil.rmtree(stage)
        (stage / "opt").mkdir(parents=True)
        shutil.copytree(bundle, stage / "opt/photocraft", symlinks=True)
        for size in (16, 32, 48, 64, 128, 256, 512):
            destination = stage / f"usr/share/icons/hicolor/{size}x{size}/apps"
            destination.mkdir(parents=True)
            shutil.copy2(ROOT / f"photocraft/assets/icon-{size}.png", destination / "photocraft.png")
        scalable = stage / "usr/share/icons/hicolor/scalable/apps"
        scalable.mkdir(parents=True)
        shutil.copy2(ROOT / "photocraft/assets/logo.svg", scalable / "photocraft.svg")
        desktop = stage / "usr/share/applications"
        desktop.mkdir(parents=True)
        shutil.copy2(ROOT / "packaging/photocraft.desktop", desktop)
        binary = stage / "usr/bin"
        binary.mkdir(parents=True)
        (binary / "photocraft").symlink_to("/opt/photocraft/PhotoCraft")
        control = stage / "DEBIAN"
        control.mkdir()
        libc_version = platform.libc_ver()[1] or "2.35"
        (control / "control").write_text(
            f"Package: photocraft\nVersion: {deb_version}\nSection: graphics\nPriority: optional\n"
            "Architecture: amd64\nMaintainer: PhotoCraft contributors <photocraft@users.noreply.github.com>\n"
            f"Depends: libc6 (>= {libc_version}), libgl1, libegl1, libopengl0, libxkbcommon0, libxkbcommon-x11-0, "
            "libxcb-cursor0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-randr0, "
            "libxcb-render-util0, libxcb-shape0, libxcb-xfixes0, libxcb-xinerama0, libxcb-xkb1, "
            "libdbus-1-3, libfontconfig1, libglib2.0-0\n"
            "Description: Offline photo editing and application photo preparation\n"
            " Crop, retouch, watermark and export photos with verified byte limits.\n"
        )
        run(
            [
                "dpkg-deb",
                "--root-owner-group",
                "--build",
                stage,
                artifacts / f"PhotoCraft-{version}-linux-amd64.deb",
            ]
        )
        with tarfile.open(artifacts / f"PhotoCraft-{version}-linux-amd64.tar.gz", "w:gz") as archive:
            archive.add(bundle, arcname="PhotoCraft")
    else:
        with zipfile.ZipFile(
            artifacts / f"PhotoCraft-{version}-windows-x64-portable.zip", "w", zipfile.ZIP_DEFLATED
        ) as archive:
            for file in bundle.rglob("*"):
                if file.is_file():
                    archive.write(file, file.relative_to(bundle.parent))
        iscc = shutil.which("ISCC") or shutil.which("ISCC.exe")
        if not iscc:
            fallback = (
                Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Inno Setup 6/ISCC.exe"
            )
            iscc = str(fallback) if fallback.exists() else None
        if not iscc:
            raise SystemExit("请先安装 Inno Setup 6，或将 ISCC.exe 加入 PATH。便携 ZIP 已生成。")
        run(
            [
                iscc,
                f"/DAppVersion={version}",
                f"/DAppNumericVersion={identity.numeric_version}",
                "packaging/windows.iss",
            ]
        )
    suffix = "linux" if sys.platform == "linux" else "windows"
    files = sorted(file for file in artifacts.glob(f"PhotoCraft-{version}-{suffix}-*") if file.is_file())
    with (artifacts / f"SHA256SUMS-{suffix}.txt").open("w", newline="\n") as stream:
        for file in files:
            digest = hashlib.file_digest(file.open("rb"), "sha256").hexdigest()
            stream.write(f"{digest}  {file.name}\n")
    print("构建完成：", artifacts)


if __name__ == "__main__":
    main()
