"""findings 組裝：編號、裁切邊界、標註縮圖、偵測 JSON。"""

from inspector.config import ANNOTATED_MAX_SIDE, CROP_MIN_SIDE
from inspector.domains import PCB_PROFILE
from inspector.findings import annotate, crop_finding, findings_to_json


def test_build_findings_orders_by_confidence(image_findings):
    ids = [(f.finding_id, f.detection.class_name, f.detection.conf) for f in image_findings.findings]
    assert ids == [
        (1, "short", 0.9),
        (2, "spurious_copper", 0.7),
        (3, "missing_hole", 0.5),
    ]


def test_crop_interior_finding_has_min_side_and_upscale(board_image, image_findings):
    # spurious_copper (200,150,260,190)：60x40 bbox，外擴後受 CROP_MIN_SIDE 支配，
    # 最長邊 < CROP_UPSCALE_BELOW → 放大 2 倍
    crop = crop_finding(board_image, image_findings.findings[1])
    assert crop.size == (CROP_MIN_SIDE * 2, CROP_MIN_SIDE * 2)


def test_crop_near_corner_is_clamped(board_image, image_findings):
    # missing_hole 貼近左上角：裁切不可超出影像邊界
    finding = image_findings.findings[2]
    crop = crop_finding(board_image, finding)
    assert crop.width > 0 and crop.height > 0
    # 夾邊後尺寸不超過（min_side 上限 + 邊界）再乘上放大倍數
    assert crop.width <= CROP_MIN_SIDE * 2 and crop.height <= CROP_MIN_SIDE * 2


def test_annotate_respects_max_side(board_image, image_findings):
    big = board_image.resize((2000, 1500))
    scaled = [
        f.__class__(f.finding_id, f.detection.__class__(
            f.detection.class_id, f.detection.class_name,
            tuple(v * 5 for v in f.detection.xyxy), f.detection.conf,
        ))
        for f in image_findings.findings
    ]
    out = annotate(big, scaled)
    assert max(out.size) == ANNOTATED_MAX_SIDE


def test_annotate_no_findings_is_noop_size(board_image):
    out = annotate(board_image, [])
    assert out.size == board_image.size  # 小於 max_side 不縮放


def test_findings_to_json_normalized(image_findings):
    payload = findings_to_json(image_findings, PCB_PROFILE.class_names_zh)
    assert [item["id"] for item in payload] == [1, 2, 3]
    for item in payload:
        assert set(item) == {"id", "class", "class_zh", "confidence", "bbox_norm"}
        assert all(0.0 <= v <= 1.0 for v in item["bbox_norm"])
    assert payload[0]["class_zh"] == "短路"
