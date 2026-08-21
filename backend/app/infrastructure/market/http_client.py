"""Small resilient HTTP client used by market providers."""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__, component="market")


class MarketHttpClient:
    def __init__(
        self,
        *,
        timeout: float | None = None,
        max_retries: int | None = None,
        backoff_seconds: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        settings = get_settings()
        self.max_retries = settings.http_max_retries if max_retries is None else max_retries
        self.backoff_seconds = (
            settings.http_retry_backoff_seconds if backoff_seconds is None else backoff_seconds
        )
        self._client = httpx.Client(
            timeout=timeout or settings.http_timeout_seconds,
            follow_redirects=True,
            transport=transport,
            headers={"User-Agent": "ProjectAI-MarketData/1.0"},
        )

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.request(method, url, **kwargs)
                if response.status_code in {429, 500, 502, 503, 504}:
                    response.raise_for_status()
                response.raise_for_status()
                return response
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                delay = self.backoff_seconds * (2**attempt)
                logger.warning(
                    "market_http_retry",
                    extra={"url": url, "attempt": attempt + 1, "delay_seconds": delay},
                )
                time.sleep(delay)
        assert last_error is not None
        raise last_error

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def close(self) -> None:
        self._client.close()
