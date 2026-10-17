import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PIL import Image


@pytest.fixture
def noise():
    return Image.fromarray(np.random.default_rng(42).integers(0, 256, (160, 120, 3), dtype=np.uint8)).convert(
        "RGBA"
    )


@pytest.fixture(scope="session")
def app():
    from PySide6.QtWidgets import QApplication

    instance = QApplication.instance() or QApplication([])
    return instance


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOCRAFT_CONFIG_DIR", str(tmp_path / "config"))
