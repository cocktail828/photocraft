import subprocess

import pytest

from photocraft.version import build_info


def git(root, *args):
    result = subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def repository(tmp_path):
    git(tmp_path, "init")
    (tmp_path / "source.txt").write_text("first")
    git(tmp_path, "add", "source.txt")
    git(tmp_path, "commit", "-m", "first")
    return tmp_path


def test_commit_identity_and_format_specific_versions(repository):
    info = build_info(repository, require_identity=True)
    assert info.display == git(repository, "rev-parse", "HEAD")[:12]
    assert info.package_version == f"0.dev1+g{info.display}"
    assert info.deb_version == f"0~git1.{info.display}"
    assert info.numeric_version == "0.0.0.1"


@pytest.mark.parametrize(
    "tag,pep,deb",
    [
        ("v1.2.3", "1.2.3", "1.2.3"),
        ("v2.4.6-rc.2", "2.4.6rc2", "2.4.6~rc.2"),
        ("v2.4.6-alpha.3", "2.4.6a3", "2.4.6~alpha.3"),
        ("2.4.6-beta.1", "2.4.6b1", "2.4.6~beta.1"),
    ],
)
def test_exact_tag_identity(repository, tag, pep, deb):
    git(repository, "tag", "-a", tag, "-m", tag)
    info = build_info(repository)
    assert info.display == tag and info.package_version == pep and info.deb_version == deb
    assert info.numeric_version == tag.removeprefix("v").split("-")[0] + ".0"
    (repository / "source.txt").write_text("second")
    git(repository, "add", "source.txt")
    git(repository, "commit", "-m", "second")
    assert build_info(repository).display == git(repository, "rev-parse", "HEAD")[:12]


def test_dirty_tag_uses_commit_instead_of_claiming_release(repository):
    git(repository, "tag", "v1.2.3")
    (repository / "source.txt").write_text("changed")
    info = build_info(repository)
    assert info.display == info.commit[:12] + "-dirty" and not info.tag


def test_frozen_build_retains_verified_git_identity_without_git(repository, monkeypatch):
    import photocraft.version as module

    git(repository, "tag", "v1.2.3")
    info = build_info(repository)
    record = repository / "photocraft/assets/build-info.json"
    record.parent.mkdir(parents=True)
    info.write(record)
    monkeypatch.setattr(module.sys, "frozen", True, raising=False)
    assert build_info(repository, require_identity=True) == info


def test_source_archive_without_identity_does_not_invent_a_release(tmp_path):
    assert build_info(tmp_path).display == "未标记源码"
    with pytest.raises(ValueError, match="Git commit/tag"):
        build_info(tmp_path, require_identity=True)
    record = tmp_path / "photocraft/assets/build-info.json"
    record.parent.mkdir(parents=True)
    record.write_text('{"commit": "forged", "tag": "v1.2.3"}')
    with pytest.raises(ValueError):
        build_info(tmp_path, require_identity=True)


def test_installed_library_does_not_pick_up_an_unrelated_parent_repository(repository):
    nested = repository / "venv/lib/site-packages"
    nested.mkdir(parents=True)
    assert build_info(nested).display == "未标记源码"


def test_wheel_and_source_archive_preserve_tag_without_git(repository):
    import json
    import shutil
    import sys
    import tarfile
    import zipfile
    from pathlib import Path

    project = Path(__file__).resolve().parents[1]
    for name in ("setup.py", "pyproject.toml", ".gitignore", "README.md"):
        shutil.copy2(project / name, repository / name)
    package = repository / "photocraft"
    (package / "assets").mkdir(parents=True)
    for name in ("__init__.py", "version.py"):
        shutil.copy2(project / "photocraft" / name, package / name)
    git(repository, "add", ".")
    git(repository, "commit", "-m", "package fixture")
    git(repository, "tag", "v1.2.3")
    commit = git(repository, "rev-parse", "HEAD")
    result = subprocess.run(
        [sys.executable, "setup.py", "bdist_wheel", "sdist"],
        cwd=repository,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    wheel = next((repository / "dist").glob("*.whl"))
    installed = repository / "installed"
    with zipfile.ZipFile(wheel) as archive:
        info = json.loads(archive.read("photocraft/assets/build-info.json"))
        assert info["tag"] == "v1.2.3" and info["commit"] == commit
        archive.extractall(installed)
    with tarfile.open(next((repository / "dist").glob("*.tar.gz"))) as archive:
        member = next(
            member for member in archive.getmembers() if member.name.endswith("assets/build-info.json")
        )
        assert json.load(archive.extractfile(member)) == info
    assert build_info(installed, require_identity=True).display == "v1.2.3"
    assert not (package / "assets/build-info.json").exists()


@pytest.mark.parametrize("kind", ["editable", "wheel"])
def test_pep517_build_without_application_installed_or_source_on_import_path(repository, kind):
    import shutil
    import sys
    import zipfile
    from pathlib import Path

    import setuptools

    project = Path(__file__).resolve().parents[1]
    for name in ("setup.py", "pyproject.toml", ".gitignore", "README.md"):
        shutil.copy2(project / name, repository / name)
    package = repository / "photocraft"
    (package / "assets").mkdir(parents=True)
    for name in ("__init__.py", "version.py"):
        shutil.copy2(project / "photocraft" / name, package / name)
    git(repository, "add", ".")
    git(repository, "commit", "-m", "isolated build fixture")
    git(repository, "tag", "v1.2.3")
    output = repository / "dist"
    output.mkdir()
    # Disable site initialization so this project's editable-install .pth is never loaded.
    backend_root = str(Path(setuptools.__file__).resolve().parent.parent)
    script = (
        "import sys, importlib.util\n"
        f"sys.path.insert(0, {backend_root!r})\n"
        "assert importlib.util.find_spec('photocraft') is None\n"
        "from setuptools import build_meta\n"
        f"build_meta.get_requires_for_build_{kind}()\n"
        f"build_meta.prepare_metadata_for_build_{kind}({str(output)!r})\n"
        f"build_meta.build_{kind}({str(output)!r})\n"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", script],
        cwd=repository,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    with zipfile.ZipFile(next(output.glob("*.whl"))) as archive:
        metadata = archive.read("photocraft-1.2.3.dist-info/METADATA").decode()
        assert "Version: 1.2.3\n" in metadata
