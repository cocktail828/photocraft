"""Git identity for the UI and generated, format-compatible package versions."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

TAG_PATTERN = re.compile(r"v?(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)\.(\d+))?")


@dataclass(frozen=True)
class BuildInfo:
    commit: str = ""
    tag: str = ""
    count: int = 0
    dirty: bool = False

    @property
    def display(self):
        if not self.commit:
            return "未标记源码"
        return self.tag or (self.commit[:12] + ("-dirty" if self.dirty else ""))

    @property
    def package_version(self):
        if self.tag:
            match = TAG_PATTERN.fullmatch(self.tag)
            major, minor, patch, kind, number = match.groups()
            suffix = {"alpha": "a", "beta": "b", "rc": "rc"}.get(kind, "")
            return f"{major}.{minor}.{patch}" + (f"{suffix}{number}" if kind else "")
        if not self.commit:
            return "0+unknown"  # PEP 440 placeholder, never an application release identity.
        return f"0.dev{self.count}+g{self.commit[:12]}" + (".dirty" if self.dirty else "")

    @property
    def deb_version(self):
        if self.tag:
            return self.tag.removeprefix("v").replace("-", "~")
        return f"0~git{self.count}.{self.commit[:12]}" + (".dirty" if self.dirty else "")

    @property
    def numeric_version(self):
        if self.tag:
            fields = TAG_PATTERN.fullmatch(self.tag).groups()[:3]
            return ".".join(fields) + ".0"
        return f"0.0.0.{self.count % 65536}"

    def write(self, path):
        path.write_text(json.dumps(asdict(self), ensure_ascii=False) + "\n", encoding="utf-8")


def _git(root, *args):
    try:
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=3)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def git_build_info(root):
    top = _git(root, "rev-parse", "--show-toplevel")
    if not top or Path(top).resolve() != Path(root).resolve():
        return None
    commit = _git(root, "rev-parse", "--verify", "HEAD")
    if not commit or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
        return None
    status = _git(root, "status", "--porcelain", "--untracked-files=normal")
    if status is None:
        return None
    dirty = bool(status)
    count = int(_git(root, "rev-list", "--count", "HEAD") or "0")
    tags = (_git(root, "tag", "--points-at", "HEAD", "--sort=-version:refname") or "").splitlines()
    tag = next((tag for tag in tags if TAG_PATTERN.fullmatch(tag)), "") if not dirty else ""
    return BuildInfo(commit, tag, count, dirty)


def build_info(root=None, *, require_identity=False):
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    info = None if getattr(sys, "frozen", False) else git_build_info(root)
    if info is None:
        try:
            record = json.loads((root / "photocraft/assets/build-info.json").read_text(encoding="utf-8"))
            info = BuildInfo(**record)
            if (
                not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", info.commit)
                or (info.tag and (not TAG_PATTERN.fullmatch(info.tag) or info.dirty))
                or type(info.count) is not int
                or info.count < 0
                or type(info.dirty) is not bool
            ):
                info = None
        except (OSError, TypeError, ValueError):
            info = None
    if info is None:
        if require_identity:
            raise ValueError("没有可用的 Git commit/tag 或构建记录；请在真实 Git 仓库中构建。")
        info = BuildInfo()
    return info


__package_version__ = build_info().package_version
