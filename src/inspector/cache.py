"""VLM 回應的內容雜湊快取：同圖、同偵測結果、同 prompt/schema/模型 → 不重打 API。

鍵 = sha256(原圖 bytes + 偵測 JSON + model_id + PROMPT_VERSION + SCHEMA_VERSION)。
值以 JSON 檔存於 .cache/vlm/，含評估結果與當時的 token 用量。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from inspector.config import CACHE_DIR, PROMPT_VERSION, SCHEMA_VERSION
from inspector.providers.base import Usage
from inspector.schema import ImageAssessment


def cache_key(image_bytes: bytes, findings_json: list[dict], model_id: str) -> str:
    h = hashlib.sha256()
    h.update(image_bytes)
    h.update(json.dumps(findings_json, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    h.update(f"|{model_id}|{PROMPT_VERSION}|{SCHEMA_VERSION}".encode("utf-8"))
    return h.hexdigest()


class VLMCache:
    def __init__(self, cache_dir: Path = CACHE_DIR, enabled: bool = True):
        self.cache_dir = cache_dir
        self.enabled = enabled

    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def get(self, key: str) -> tuple[ImageAssessment, Usage] | None:
        if not self.enabled:
            return None
        path = self._path(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            assessment = ImageAssessment.model_validate(payload["assessment"])
            usage = Usage(**payload["usage"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            path.unlink(missing_ok=True)  # 壞掉的快取直接作廢重打
            return None
        return assessment, usage

    def put(self, key: str, assessment: ImageAssessment, usage: Usage) -> None:
        if not self.enabled:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "assessment": assessment.model_dump(mode="json"),
            "usage": usage.__dict__,
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self._path(key).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
