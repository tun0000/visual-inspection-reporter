"""重試判斷與限速器基本行為（不測真實等待，避免測試變慢）。"""

from inspector.retry import RateLimiter, _retry_after_seconds, is_retryable


class FakeResponse:
    def __init__(self, headers):
        self.headers = headers


class FakeHTTPError(Exception):
    def __init__(self, code=None, response=None):
        super().__init__("boom")
        if code is not None:
            self.code = code
        if response is not None:
            self.response = response


def test_is_retryable_on_status_codes():
    assert is_retryable(FakeHTTPError(code=429))
    assert is_retryable(FakeHTTPError(code=503))
    assert not is_retryable(FakeHTTPError(code=400))
    assert not is_retryable(ValueError("schema error"))  # 解析錯誤不重試
    assert is_retryable(TimeoutError())


def test_retry_after_header_parsing():
    exc = FakeHTTPError(code=429, response=FakeResponse({"Retry-After": "7"}))
    assert _retry_after_seconds(exc) == 7.0
    assert _retry_after_seconds(FakeHTTPError(code=429)) == 0.0
    exc_bad = FakeHTTPError(code=429, response=FakeResponse({"Retry-After": "garbage"}))
    assert _retry_after_seconds(exc_bad) == 0.0


def test_rate_limiter_disabled_and_under_limit():
    RateLimiter(0).acquire()  # 停用：立即返回
    limiter = RateLimiter(10)
    for _ in range(5):  # 低於上限：不阻塞
        limiter.acquire()
    assert len(limiter._calls) == 5
