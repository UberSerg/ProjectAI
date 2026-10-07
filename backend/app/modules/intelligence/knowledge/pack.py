"""Knowledge pack containers (YAML / Markdown ingested rules)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.modules.intelligence.contracts.knowledge import KnowledgeRule


@dataclass(frozen=True, slots=True)
class KnowledgePack:
    pack_id: str
    version: str
    created_from: str
    rules: tuple[KnowledgeRule, ...]
    source_path: str | None = None
    rule_bodies: dict[str, dict[str, Any]] = field(default_factory=dict)

    def body_for(self, rule_id: str) -> dict[str, Any]:
        return dict(self.rule_bodies.get(rule_id, {}))
