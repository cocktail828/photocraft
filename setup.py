"""Preserve Git identity when creating wheels or source archives without .git."""

import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist

ROOT = Path(__file__).resolve().parent
# PEP 517 executes this file without necessarily adding its directory to sys.path.
sys.path.insert(0, str(ROOT))

from photocraft.version import build_info  # noqa: E402

IDENTITY = build_info(ROOT)


def write_identity(root):
    if IDENTITY.commit:
        path = Path(root) / "photocraft/assets/build-info.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        IDENTITY.write(path)


class BuildPy(build_py):
    def run(self):
        super().run()
        write_identity(self.build_lib)


class SourceArchive(sdist):
    def make_release_tree(self, base_dir, files):
        super().make_release_tree(base_dir, files)
        write_identity(base_dir)


setup(cmdclass={"build_py": BuildPy, "sdist": SourceArchive})
