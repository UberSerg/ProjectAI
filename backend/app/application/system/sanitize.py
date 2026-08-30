"""Centralized secret sanitization for logs and diagnostics."""

from __future__ import annotations

import re
from typing import Any

_SENSITIVE_KEY = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|authorization|cookie|credential|"
    r"polza|dsn|broker|private[_-]?key|access[_-]?key)",
    re.IGNORECASE,
)
_SENSITIVE_VALUE = re.compile(
    r"(?i)(?:(?:password|passwd|secret|token|api[_-]?key|authorization|bearer|polza_api_key)"
    r"\s*[=:]\s*[^\s,;\"']+|bearer\s+[A-Za-z0-9\-._~+/]+=*|authorization\s*:\s*[^\r\n]+)"
)


def sanitize_value(value: Any, *, key: str | None = None) -> Any:
    if key and _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): sanitize_value(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, str):
        return _SENSITIVE_VALUE.sub("[REDACTED]", value)
    return value


def sanitize_text(text: str, *, max_len: int | None = None) -> str:
    cleaned = _SENSITIVE_VALUE.sub("[REDACTED]", text)
    if max_len is not None and len(cleaned) > max_len:
        return cleaned[: max_len - 3] + "..."
    return cleaned
