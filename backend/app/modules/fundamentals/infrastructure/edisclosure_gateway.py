"""Typed adapter for the Interfax e-disclosure Data Gateway (gateway.e-disclosure.ru).

Never logs or prints password or token values. HTML scraping of e-disclosure.ru is out of
scope — this client talks only to the documented OpenAPI surface.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import httpx

from app.core.config import Settings, get_settings
from app.infrastructure.market.http_client import MarketHttpClient
from app.modules.fundamentals.domain.types import (
    SOURCE_EDISCLOSURE_GATEWAY,
    DisclosureEntityType,
    FileEventType,
    MessageEventType,
)

_REDACT_PATTERNS = (
    (re.compile(r'("password"\s*:\s*")[^"]*(")', re.I), r"\1[REDACTED]\2"),
    (re.compile(r'("token"\s*:\s*")[^"]*(")', re.I), r"\1[REDACTED]\2"),
    (re.compile(r"(password=)[^&\s]+", re.I), r"\1[REDACTED]"),
    (re.compile(r"(Bearer\s+)[^\s]+", re.I), r"\1[REDACTED]"),
)


def redact_secrets(text: str) -> str:
    """Remove credential-like substrings from log-safe text."""
    result = text
    for pattern, repl in _REDACT_PATTERNS:
        result = pattern.sub(repl, result)
    return result


@dataclass(frozen=True, slots=True)
class AuthParams:
    login: str
    password: str

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> AuthParams:
        login = str(payload.get("login") or "").strip()
        password = str(payload.get("password") or "")
        if not login or not password:
            raise ValueError("login and password are required")
        return cls(login=login, password=password)


@dataclass(frozen=True, slots=True)
class ApiKeyToken:
    token: str
    expiration_date: datetime | None

    @classmethod
    def from_response(cls, payload: dict[str, Any]) -> ApiKeyToken:
        token = str(payload.get("token") or "").strip()
        if not token:
            raise ValueError("token missing in auth response")
        raw_exp = payload.get("expirationDate")
        expiration: datetime | None = None
        if raw_exp:
            expiration = datetime.fromisoformat(str(raw_exp).replace("Z", "+00:00"))
        return cls(token=token, expiration_date=expiration)


def humanize_auth_failure(status_code: int, body: str | dict[str, Any] | None) -> str:
    """Turn gateway auth errors into operator-facing text without leaking secrets."""
    messages: list[str] = []
    if isinstance(body, dict):
        for err in body.get("errors") or []:
            if isinstance(err, dict) and err.get("description"):
                messages.append(str(err["description"]))
    elif isinstance(body, str) and body.strip():
        messages.append(redact_secrets(body.strip()[:500]))
    detail = "; ".join(messages) if messages else f"HTTP {status_code}"
    if status_code == 400:
        return f"Неверные учётные данные шлюза: {detail}"
    if status_code == 401:
        return f"Авторизация отклонена: {detail}"
    if status_code == 403:
        return f"Доступ к шлюзу запрещён (проверьте договор): {detail}"
    if status_code == 409:
        return f"Ограничение шлюза: {detail}"
    return f"Ошибка авторизации шлюза (HTTP {status_code}): {detail}"


def parse_event_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    elif "+" not in text and text.count("-") >= 2 and "T" in text:
        # Gateway documents Moscow time without offset.
        text = f"{text}+03:00"
    return datetime.fromisoformat(text)


def known_at_from_event(event: dict[str, Any]) -> datetime | None:
    """Use eventDate as published_at / known_at — never invent a timestamp."""
    return parse_event_date(event.get("eventDate"))


def apply_disclosure_event_versioning(
    active: dict[str, dict[str, Any]],
    event: dict[str, Any],
    *,
    entity: DisclosureEntityType,
) -> dict[str, dict[str, Any]]:
    """Apply Publish / Change / Exclude / Restore / Delete semantics in-memory."""
    uid = _subject_uid(event)
    if uid is None:
        return active
    event_type = str(event.get("eventType") or "")
    key = f"{entity.value}:{uid}"

    if entity is DisclosureEntityType.MESSAGES:
        terminal = {MessageEventType.EXCLUDE.value}
        delete_like = set()
    else:
        terminal = {FileEventType.DELETE.value}
        delete_like = {FileEventType.UNKNOWN.value}

    if event_type in terminal or event_type in delete_like:
        active.pop(key, None)
        return active
    if event_type in {
        MessageEventType.PUBLISH.value,
        MessageEventType.CHANGE.value,
        MessageEventType.RESTORE.value,
        FileEventType.PUBLISH.value,
        FileEventType.CHANGE.value,
        FileEventType.RESTORE.value,
    }:
        active[key] = event
    return active


def paginate_disclosure_events(
    events: list[dict[str, Any]], *, count: int | None = None, from_event_id: str | None = None
) -> list[dict[str, Any]]:
    """Simulate gateway pagination: events after from_event_id, limited by count."""
    rows = list(events)
    if from_event_id:
        ids = [str(e.get("eventId") or "") for e in rows]
        if from_event_id in ids:
            start = ids.index(from_event_id) + 1
            rows = rows[start:]
        else:
            rows = [e for e in rows if str(e.get("eventId") or "") > from_event_id]
    if count is not None and count >= 0:
        rows = rows[:count]
    return rows


def _subject_uid(event: dict[str, Any]) -> str | None:
    subject = event.get("subject") or {}
    if isinstance(subject, dict):
        uid = subject.get("uid")
        if uid:
            return str(uid)
    file_obj = event.get("file") or {}
    if isinstance(file_obj, dict):
        uid = file_obj.get("uid")
        if uid:
            return str(uid)
    message = event.get("message") or {}
    if isinstance(message, dict):
        uid = message.get("uid")
        if uid:
            return str(uid)
    event_id = event.get("eventId")
    return str(event_id) if event_id else None


class EdisclosureGatewayClient:
    source = SOURCE_EDISCLOSURE_GATEWAY

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: MarketHttpClient | httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self.base_url = self._settings.edisclosure_gateway_base_url.rstrip("/")
        if isinstance(client, MarketHttpClient):
            self._http = client
            self._owns_client = False
        elif client is not None:
            self._http = client
            self._owns_client = False
        else:
            self._http = httpx.Client(
                timeout=self._settings.http_timeout_seconds,
                follow_redirects=True,
                transport=transport,
                trust_env=False,
            )
            self._owns_client = True
        self._token: str | None = None

    def close(self) -> None:
        if self._owns_client and isinstance(self._http, httpx.Client):
            self._http.close()

    def _request(
        self,
        method: Literal["GET", "POST"],
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        auth: bool = False,
    ) -> httpx.Response:
        headers: dict[str, str] = {}
        if auth:
            if not self._token:
                raise RuntimeError("authenticate() required before authorized request")
            headers["Authorization"] = f"Bearer {self._token}"
        url = f"{self.base_url}{path}"
        if isinstance(self._http, MarketHttpClient):
            if method == "GET":
                return self._http.get(url, params=params, headers=headers)
            return self._http.post(url, json=json_body, headers=headers)
        if method == "GET":
            response = self._http.get(url, params=params, headers=headers)
        else:
            response = self._http.post(url, json=json_body, headers=headers)
        response.raise_for_status()
        return response

    def authenticate(self, params: AuthParams | None = None) -> ApiKeyToken:
        login = (params.login if params else self._settings.edisclosure_gateway_username).strip()
        password = params.password if params else self._settings.edisclosure_gateway_secret
        if not login or not password:
            raise ValueError("EDISCLOSURE_GATEWAY_USERNAME and EDISCLOSURE_GATEWAY_SECRET required")
        try:
            response = self._request(
                "POST",
                "/api/v1/auth",
                json_body={"login": login, "password": password},
            )
        except httpx.HTTPStatusError as exc:
            body: str | dict[str, Any] | None
            try:
                body = exc.response.json()
            except Exception:
                body = exc.response.text
            raise RuntimeError(humanize_auth_failure(exc.response.status_code, body)) from exc
        token = ApiKeyToken.from_response(response.json())
        self._token = token.token
        return token

    def fetch_message_types(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/api/v1/dictionaries/message-types", auth=True)
        payload = response.json()
        return list(payload) if isinstance(payload, list) else []

    def fetch_file_types(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/api/v1/dictionaries/file-types", auth=True)
        payload = response.json()
        return list(payload) if isinstance(payload, list) else []

    def fetch_disclosure_events(
        self,
        *,
        entity: DisclosureEntityType,
        count: int | None = None,
        from_event_id: str | None = None,
        from_event_date: datetime | None = None,
        to_event_date: datetime | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"entity": entity.value}
        if count is not None:
            params["count"] = count
        if from_event_id:
            params["fromEventId"] = from_event_id
        if from_event_date is not None:
            params["fromEventDate"] = from_event_date.isoformat()
        if to_event_date is not None:
            params["toEventDate"] = to_event_date.isoformat()
        response = self._request("GET", "/api/v1/disclosure/events", params=params, auth=True)
        payload = response.json()
        return list(payload) if isinstance(payload, list) else []

    def download_file(self, uid: str) -> bytes:
        response = self._request("GET", f"/api/v1/disclosure/download/files/{uid}", auth=True)
        return response.content

    def __repr__(self) -> str:
        return redact_secrets(
            f"EdisclosureGatewayClient(base_url={self.base_url!r}, token={'set' if self._token else 'unset'})"
        )
