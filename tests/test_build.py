"""Exercise package identity wiring while stubbing only platform build executables."""

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from photocraft.version import build_info

PROJECT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("platform", ["linux", "win32"])
@pytest.mark.parametrize("tagged", [True, False])
def test_native_packages_embed_and_use_the_git_identity(tmp_path, monkeypatch, platform, tagged):
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md", ".gitignore"):
        shutil.copy2(PROJECT / name, tmp_path / name)
    shutil.copytree(PROJECT / "packaging", tmp_path / "packaging")
    shutil.copytree(PROJECT / "photocraft/assets", tmp_path / "photocraft/assets")
    for args in (
        ["init"],
        ["add", "."],
        ["-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "native fixture"],
    ):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)
    if tagged:
        subprocess.run(["git", "-C", str(tmp_path), "tag", "v1.2.3"], check=True)
    identity = build_info(tmp_path, require_identity=True)
    spec = importlib.util.spec_from_file_location("native_build_test", PROJECT / "scripts/build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module.sys, "argv", ["build.py"])
    monkeypatch.setattr(module.sys, "platform", platform)
    monkeypatch.setattr(module.shutil, "which", lambda name: "ISCC" if name.startswith("ISCC") else None)
    monkeypatch.chdir(tmp_path)
    invoked = []

    def run(args):
        invoked.append([str(arg) for arg in args])
        if "PyInstaller" in args:
            output = tmp_path / "dist/PhotoCraft/_internal/photocraft/assets"
            output.mkdir(parents=True)
            shutil.copy2(tmp_path / "photocraft/assets/build-info.json", output / "build-info.json")
        elif str(args[0]) == "dpkg-deb":
            Path(args[-1]).write_bytes(b"test-package")
        elif args[0] == "ISCC":
            (tmp_path / f"artifacts/PhotoCraft-{identity.display}-windows-x64-setup.exe").write_bytes(
                b"test-setup"
            )

    monkeypatch.setattr(module, "run", run)
    module.main()
    assert not (tmp_path / "photocraft/assets/build-info.json").exists()
    frozen = json.loads(
        (tmp_path / "dist/PhotoCraft/_internal/photocraft/assets/build-info.json").read_text()
    )
    assert frozen["commit"] == identity.commit and frozen["tag"] == identity.tag
    if platform == "linux":
        control = (tmp_path / "build/deb/DEBIAN/control").read_text()
        assert f"Version: {identity.deb_version}\n" in control
        assert (tmp_path / f"artifacts/PhotoCraft-{identity.display}-linux-amd64.deb").exists()
    else:
        installer = next(args for args in invoked if args[0] == "ISCC")
        assert f"/DAppVersion={identity.display}" in installer
        assert f"/DAppNumericVersion={identity.numeric_version}" in installer
    assert (tmp_path / f"artifacts/SHA256SUMS-{'linux' if platform == 'linux' else 'windows'}.txt").is_file()
