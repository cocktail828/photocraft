"""Embed supplied CI/Git identity in an image without copying the .git directory."""

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from photocraft.version import TAG_PATTERN, BuildInfo  # noqa: E402


def main():
    commit = os.environ.get("VCS_REF", "")
    tag = os.environ.get("VERSION_TAG", "")
    dirty = os.environ.get("VCS_DIRTY", "0") == "1"
    if not commit:
        if tag:
            raise SystemExit("提供版本 tag 时也必须提供 VCS_REF commit。")
        return
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
        raise SystemExit("VCS_REF 必须是完整的 Git commit。")
    if tag and not TAG_PATTERN.fullmatch(tag):
        raise SystemExit("VERSION_TAG 需符合 vMAJOR.MINOR.PATCH 格式。")
    info = BuildInfo(commit, tag if not dirty else "", int(os.environ.get("VCS_COUNT", "0")), dirty)
    info.write(ROOT / "photocraft/assets/build-info.json")
    print("镜像版本：", info.display)


if __name__ == "__main__":
    main()
