"""共用 fixtures：合成影像與偵測結果，全程零網路、零權重。"""

from __future__ import annotations

import pytest
from PIL import Image

from inspector.detector import Detection
from inspector.findings import build_findings


@pytest.fixture
def board_image() -> Image.Image:
    return Image.new("RGB", (400, 300), (20, 90, 30))


@pytest.fixture
def detections() -> list[Detection]:
    # 刻意亂序：build_findings 應依信心降冪編號
    return [
        Detection(0, "missing_hole", (10.0, 10.0, 20.0, 22.0), 0.5),
        Detection(3, "short", (100.0, 80.0, 140.0, 100.0), 0.9),
        Detection(5, "spurious_copper", (200.0, 150.0, 260.0, 190.0), 0.7),
    ]


@pytest.fixture
def image_findings(tmp_path, board_image, detections):
    image_path = tmp_path / "board.jpg"
    board_image.save(image_path, quality=90)
    return build_findings(image_path, board_image.size, detections)
