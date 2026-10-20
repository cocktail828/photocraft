"""Build the web image with the source tree's actual Git identity."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from photocraft.version import build_info  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="photocraft:local")
    parser.add_argument("--base-image", help="Override the Docker base image for local builds")
    parser.add_argument("--pip-index-url", help="Override the Python package index for local builds")
    args = parser.parse_args()
    info = build_info(ROOT)
    command = ["docker"]
    if os.environ.get("DOCKER_CONFIG"):
        command += ["--config", os.environ["DOCKER_CONFIG"]]
    command += ["build", "--tag", args.tag]
    for key, value in (("BASE_IMAGE", args.base_image), ("PIP_INDEX_URL", args.pip_index_url)):
        if value:
            command += ["--build-arg", f"{key}={value}"]
    for key, value in dict(
        VCS_REF=info.commit, VERSION_TAG=info.tag, VCS_COUNT=info.count, VCS_DIRTY=int(info.dirty)
    ).items():
        command += ["--build-arg", f"{key}={value}"]
    subprocess.run([*command, str(ROOT)], check=True)


if __name__ == "__main__":
    main()
