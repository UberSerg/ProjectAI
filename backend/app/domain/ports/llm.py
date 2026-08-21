"""LLM provider port — Polza is one adapter, not a domain dependency."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class LLMMessage:
    role: str
    content: str


@dataclass(slots=True, frozen=True)
class LLMResponse:
    content: str
    model: str
    provider: str


class LLMProvider(ABC):
    @abstractmethod
    def complete(self, messages: list[LLMMessage], *, model: str | None = None) -> LLMResponse:
        raise NotImplementedError
