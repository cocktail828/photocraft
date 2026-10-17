"""Verify a running container's real HTTP preview/apply/download workflow."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def check(base):
    def request(path, data=None):
        payload = None if data is None else json.dumps(data).encode()
        with urlopen(
            Request(base + path, data=payload, headers={"Content-Type": "application/json"}), timeout=30
        ) as response:
            raw = response.read()
            return json.loads(raw) if "application/json" in response.headers.get("Content-Type", "") else raw

    for attempt in range(60):
        try:
            health = request("/api/health")
            break
        except (HTTPError, URLError, OSError):
            time.sleep(0.5)
    else:
        raise RuntimeError("服务未在 30 秒内就绪。")
    assert health["status"] == "ok"
    assert b"PhotoCraft" in request("/")
    session = request("/api/demo", {})
    route = "/api/sessions/" + session["id"]
    try:
        original = request(route + "/download")
        entry = request(
            route + "/preview",
            {
                "revision": 0,
                "tool": "crop",
                "params": {
                    "box": [100, 100, 395, 513],
                    "size": [295, 413],
                },
            },
        )
        assert request(route + "/download") == original
        current = request(route + "/apply", {"revision": 0, "preview_id": entry["preview_id"]})
        assert current["current"]["width"] == 295 and current["current"]["height"] == 413
        downloaded = request(route + "/download")
        assert len(downloaded) == entry["info"]["bytes"] and downloaded.startswith(b"\xff\xd8")
        draft = request(
            route + "/preview",
            {"revision": current["revision"], "tool": "compress", "params": {"format": "PNG"}},
        )
        assert request(route + "/download") == downloaded
        current = request(
            route + "/apply", {"revision": current["revision"], "preview_id": draft["preview_id"]}
        )
        assert request(route + "/download").startswith(b"\x89PNG")
        request(route + "/undo", {"revision": current["revision"]})
        assert request(route + "/download") == downloaded
        print("PHOTOCRAFT_WEB_SMOKE_OK", health["version"])
    finally:
        request(route + "/close", {})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--spawn", action="store_true")
    args = parser.parse_args()
    if not args.spawn:
        check(args.url.rstrip("/"))
        return
    with tempfile.TemporaryDirectory() as folder:
        env = dict(os.environ, PHOTOCRAFT_CONFIG_DIR=folder)
        # Allocate a free local port instead of assuming a development port is unused.
        import socket

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        process = subprocess.Popen(
            [sys.executable, "-m", "photocraft", "--port", str(port)],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
        )
        try:
            check(f"http://127.0.0.1:{port}")
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
