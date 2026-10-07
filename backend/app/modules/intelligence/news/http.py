"""Bounded HTTP client for allowlisted news sources (no arbitrary URL fetch)."""

from __future__ import annotations

import time
from urllib.parse import urlparse

import httpx

from app.modules.intelligence.news.registry import SourceDefinition, is_host_allowed

USER_AGENT = "ProjectAI-IntelligenceNews/1.0 (+research; polite; allowlisted-only)"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_SECONDS = 1.0


class NewsHttpError(RuntimeError):
    """Fetch failed after bounded retries or policy violation."""


class NewsHttpClient:
    """httpx wrapper with timeout, retries, UA, rate limit, and host allowlist."""

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._last_fetch_at: dict[str, float] = {}
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
            headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> NewsHttpClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def fetch_bytes(self, source: SourceDefinition, url: str | None = None) -> bytes:
        target = url or source.feed_url
        self._assert_url_allowed(source, target)
        self._pace(source)
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.get(target)
                if response.status_code in {429, 500, 502, 503, 504}:
                    response.raise_for_status()
                response.raise_for_status()
                self._last_fetch_at[source.source_id] = time.monotonic()
                return response.content
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                delay = self.backoff_seconds * (2**attempt)
                time.sleep(delay)
        raise NewsHttpError(f"fetch failed for {source.source_id}: {last_error}") from last_error

    def _pace(self, source: SourceDefinition) -> None:
        last = self._last_fetch_at.get(source.source_id)
        if last is None:
            return
        wait = source.rate_limit_seconds - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)

    @staticmethod
    def _assert_url_allowed(source: SourceDefinition, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise NewsHttpError(f"unsupported URL scheme for {source.source_id}: {parsed.scheme!r}")
        host = parsed.hostname or ""
        if not host or not is_host_allowed(source, host):
            raise NewsHttpError(
                f"SSRF block: host {host!r} not allowlisted for source {source.source_id}"
            )
        # Block obvious redirect-to-internal patterns in the requested URL itself.
        if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"} or host.startswith("169.254."):
            raise NewsHttpError(f"SSRF block: forbidden host {host!r}")
