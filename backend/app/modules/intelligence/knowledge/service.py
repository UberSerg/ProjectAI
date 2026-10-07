"""KnowledgeEngine — ingest packs, persist versioned rules, evaluate, surface contradictions."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.modules.intelligence.contracts.knowledge import KnowledgeRule, KnowledgeRuleEvaluation
from app.modules.intelligence.knowledge.contradictions import (
    ContradictionReport,
    detect_contradictions,
)
from app.modules.intelligence.knowledge.evaluator import RuleEvaluationContext, evaluate_rules
from app.modules.intelligence.knowledge.ingest import (
    KnowledgePack,
    default_knowledge_packs_dir,
    load_packs_from_dir,
)
from app.modules.intelligence.knowledge.repository import (
    InMemoryKnowledgeRuleStore,
    KnowledgeRuleStore,
    PersistOutcome,
    PersistResult,
)


@dataclass
class KnowledgeEngineReport:
    packs_loaded: list[str] = field(default_factory=list)
    rule_count: int = 0
    persist_results: list[PersistResult] = field(default_factory=list)
    inserted: int = 0
    unchanged: int = 0
    conflicts: int = 0
    contradictions: list[ContradictionReport] = field(default_factory=list)
    books_pdfs_found: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "packs_loaded": list(self.packs_loaded),
            "rule_count": self.rule_count,
            "inserted": self.inserted,
            "unchanged": self.unchanged,
            "conflicts": self.conflicts,
            "persist_results": [
                {
                    "outcome": r.outcome.value,
                    "rule_id": r.rule_id,
                    "version": r.version,
                    "content_hash": r.content_hash,
                    "detail": r.detail,
                }
                for r in self.persist_results
            ],
            "contradictions": [c.to_dict() for c in self.contradictions],
            "books_pdfs_found": list(self.books_pdfs_found),
        }


class KnowledgeEngine:
    """Advisory knowledge rules engine. Never emits trade/order intents."""

    def __init__(self, store: KnowledgeRuleStore | None = None) -> None:
        self.store: KnowledgeRuleStore = store or InMemoryKnowledgeRuleStore()
        self._pack_bodies: dict[str, dict[str, Any]] = {}
        self._packs: list[KnowledgePack] = []

    @property
    def packs(self) -> list[KnowledgePack]:
        return list(self._packs)

    def load_packs(self, directory: Path | str | None = None) -> list[KnowledgePack]:
        packs = load_packs_from_dir(directory)
        self._packs = packs
        for pack in packs:
            for rule in pack.rules:
                body = pack.body_for(rule.rule_id)
                if body:
                    self._pack_bodies[rule.rule_id] = body
        return packs

    def persist_packs(self, packs: list[KnowledgePack] | None = None) -> list[PersistResult]:
        packs = packs if packs is not None else self._packs
        results: list[PersistResult] = []
        for pack in packs:
            for rule in pack.rules:
                body = {
                    "pack_id": pack.pack_id,
                    "pack_version": pack.version,
                    **pack.body_for(rule.rule_id),
                }
                result = self.store.persist_rule(rule, body=body)
                results.append(result)
                if result.outcome is not PersistOutcome.CONFLICT:
                    self._pack_bodies[rule.rule_id] = body
        return results

    def ingest_default_packs(self) -> KnowledgeEngineReport:
        packs = self.load_packs(default_knowledge_packs_dir())
        results = self.persist_packs(packs)
        stored = self.store.list_active()
        contradictions = detect_contradictions(rules=stored, bodies=self._pack_bodies)
        report = KnowledgeEngineReport(
            packs_loaded=[p.pack_id for p in packs],
            rule_count=len(stored),
            persist_results=results,
            inserted=sum(1 for r in results if r.outcome is PersistOutcome.INSERTED),
            unchanged=sum(1 for r in results if r.outcome is PersistOutcome.UNCHANGED),
            conflicts=sum(1 for r in results if r.outcome is PersistOutcome.CONFLICT),
            contradictions=contradictions,
            books_pdfs_found=[],
        )
        return report

    def active_rules(self) -> list[KnowledgeRule]:
        return [s.rule for s in self.store.list_active()]

    def evaluate(
        self,
        ctx: RuleEvaluationContext,
        *,
        persist: bool = False,
    ) -> list[KnowledgeRuleEvaluation]:
        stored = self.store.list_active()
        rules = [s.rule for s in stored]
        bodies = {s.rule.rule_id: s.body for s in stored}
        evaluations = evaluate_rules(rules, ctx, bodies=bodies)
        if persist:
            for ev in evaluations:
                self.store.persist_evaluation(ev)
        return evaluations

    def contradictions_for(
        self, evaluations: list[KnowledgeRuleEvaluation] | None = None
    ) -> list[ContradictionReport]:
        stored = self.store.list_active()
        return detect_contradictions(
            rules=stored,
            evaluations=evaluations,
            bodies=self._pack_bodies,
        )

    def report_dict(self) -> dict[str, Any]:
        stored = self.store.list_active()
        return {
            "packs_loaded": [p.pack_id for p in self._packs],
            "rule_count": len(stored),
            "rule_ids": [s.rule.rule_id for s in stored],
            "issues_trades": False,
            "schema": "KnowledgeEngineReport",
        }
