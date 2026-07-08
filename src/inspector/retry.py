"""VLM 呼叫的韌性層：指數退避重試 + 跨執行緒 RPM 限速。

重試only限暫時性錯誤（429/5xx/連線逾時）；等待時間取「供應商建議的重試秒數」
（HTTP Retry-After 標頭，或 google-genai 429 特有、放在 JSON body 裡的
google.rpc.RetryInfo）與「指數退避+jitter」的較大值，最多 5 次。
"""

from __future__ import annotations

import threading
import time
from collections import deque
from email.utils import parsedate_to_datetime

from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _status_of(exc: BaseException) -> int | None:
    """從各家 SDK 例外撈 HTTP 狀態碼（google-genai 用 .code，openai 用 .status_code）。"""
    for attr in ("code", "status_code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    return _status_of(exc) in RETRYABLE_STATUS


def _retry_after_from_header(exc: BaseException) -> float:
    """HTTP Retry-After 標頭（openai/requests 這類走標準 HTTP 標頭的 SDK）。"""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return 0.0
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if not raw:
        return 0.0
    try:
        return float(raw)
    except ValueError:
        try:
            return max(0.0, (parsedate_to_datetime(raw).timestamp()) - time.time())
        except (TypeError, ValueError):
            return 0.0


def _retry_after_from_google_details(exc: BaseException) -> float:
    """google-genai 的 429 把建議等待秒數放在 JSON body 的
    google.rpc.RetryInfo（exc.details['details']），不是 HTTP 標頭——
    實測若不解析這裡，重試會在配額真正重置前就打完 5 次全部落空。
    """
    details = getattr(exc, "details", None)
    if not isinstance(details, dict):
        return 0.0
    error = details.get("error", details)
    for item in error.get("details", []) or []:
        if not isinstance(item, dict) or "RetryInfo" not in str(item.get("@type", "")):
            continue
        raw = str(item.get("retryDelay", "")).rstrip("s")
        try:
            return float(raw)
        except ValueError:
            return 0.0
    return 0.0


def _retry_after_seconds(exc: BaseException | None) -> float:
    """盡力解析各家 SDK 建議的重試等待秒數；解析不到回 0。"""
    if exc is None:
        return 0.0
    return max(_retry_after_from_header(exc), _retry_after_from_google_details(exc))


_exponential = wait_random_exponential(multiplier=1, max=32)


def _wait(retry_state) -> float:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    return max(_retry_after_seconds(exc), _exponential(retry_state))


vlm_retry = retry(
    retry=retry_if_exception(is_retryable),
    wait=_wait,
    stop=stop_after_attempt(5),
    reraise=True,
)


class RateLimiter:
    """滑動窗 RPM 限速（thread-safe）。免費層 flash-lite 約 10 RPM，預設 8 留餘裕。

    max_rpm <= 0 代表停用（付費層可用 --max-rpm 0 關掉）。
    """

    def __init__(self, max_rpm: int):
        self.max_rpm = max_rpm
        self._lock = threading.Lock()
        self._calls: deque[float] = deque()

    def acquire(self) -> None:
        if self.max_rpm <= 0:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= 60:
                    self._calls.popleft()
                if len(self._calls) < self.max_rpm:
                    self._calls.append(now)
                    return
                sleep_for = 60 - (now - self._calls[0]) + 0.05
            time.sleep(sleep_for)
