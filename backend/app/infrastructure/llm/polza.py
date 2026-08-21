"""Polza API adapter boundary — no live calls in foundation stage."""

from __future__ import annotations

from app.core.config import get_settings
from app.domain.ports.llm import LLMMessage, LLMProvider, LLMResponse


class PolzaProvider(LLMProvider):
    """Adapter placeholder. Real HTTP integration comes later."""

    def __init__(self) -> None:
        self._settings = get_settings()

    def complete(self, messages: list[LLMMessage], *, model: str | None = None) -> LLMResponse:
        raise NotImplementedError(
            "PolzaProvider is configured but live LLM calls are disabled in foundation stage. "
            f"base_url={self._settings.polza_base_url!r} "
            f"model={(model or self._settings.polza_default_model)!r}"
        )
