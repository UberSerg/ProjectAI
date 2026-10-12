"""Small HTTP transport for macro source adapters.

Uses the default TLS trust store. It does not disable certificate checks
and does not attach API keys.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

USER_AGENT = "ProjectAI-historical-macro/1.0"


@dataclass(frozen=True, slots=True)
class HttpResult:
    url: str
    status: int
    body: bytes
    content_type: str | None = None


class Transport(Protocol):
    def request(
        self,
        url: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResult: ...


class UrllibTransport:
    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        self._timeout_seconds = timeout_seconds

    def request(
        self,
        url: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResult:
        header_map = {"User-Agent": USER_AGENT, "Accept": "application/json,text/json,*/*"}
        if headers:
            header_map.update(headers)
        request = urllib.request.Request(url, data=data, headers=header_map)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                return HttpResult(
                    url=response.geturl(),
                    status=response.status,
                    body=response.read(),
                    content_type=response.headers.get("Content-Type"),
                )
        except urllib.error.HTTPError as exc:
            return HttpResult(
                url=exc.geturl() or url,
                status=exc.code,
                body=exc.read(),
                content_type=exc.headers.get("Content-Type") if exc.headers else None,
            )
