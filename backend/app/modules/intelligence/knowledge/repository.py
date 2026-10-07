"""Versioned KnowledgeRule persistence with dedup + provenance."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.intelligence.contracts.knowledge import KnowledgeRule, KnowledgeRuleEvaluation
from app.modules.intelligence.knowledge.hashutil import content_hash
from app.modules.intelligence.knowledge.models import KnowledgeRuleEvaluationRow, KnowledgeRuleRow


class PersistOutcome(str, Enum):
    INSERTED = "INSERTED"
    UNCHANGED = "UNCHANGED"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True, slots=True)
class PersistResult:
    outcome: PersistOutcome
    rule_id: str
    version: str
    content_hash: str
    detail: str = ""


@dataclass
class StoredRule:
    rule: KnowledgeRule
    body: dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""


class KnowledgeRuleStore(Protocol):
    def persist_rule(
        self,
        rule: KnowledgeRule,
        *,
        body: dict[str, Any] | None = None,
    ) -> PersistResult: ...

    def get_rule(self, rule_id: str, version: str) -> StoredRule | None: ...

    def list_active(self) -> list[StoredRule]: ...

    def persist_evaluation(self, evaluation: KnowledgeRuleEvaluation) -> None: ...


def _row_to_rule(row: KnowledgeRuleRow) -> KnowledgeRule:
    return KnowledgeRule(
        rule_id=row.rule_id,
        version=row.version,
        domain=row.domain,
        title=row.title,
        principle=row.principle,
        applicability=tuple(row.applicability or ()),
        required_evidence=tuple(row.required_evidence or ()),
        contraindications=tuple(row.contraindications or ()),
        severity=row.severity,
        source_reference=row.source_reference,
        source_location=row.source_location,
        created_from=row.created_from,
        status=row.status,
    )


class InMemoryKnowledgeRuleStore:
    """Test / offline store — same dedup semantics as SQL repository."""

    def __init__(self) -> None:
        self._rules: dict[tuple[str, str], StoredRule] = {}
        self.evaluations: list[KnowledgeRuleEvaluation] = []

    def persist_rule(
        self,
        rule: KnowledgeRule,
        *,
        body: dict[str, Any] | None = None,
    ) -> PersistResult:
        extra = dict(body or {})
        digest = content_hash(rule, extra_body=extra)
        key = (rule.rule_id, rule.version)
        existing = self._rules.get(key)
        if existing is None:
            self._rules[key] = StoredRule(rule=rule, body=extra, content_hash=digest)
            return PersistResult(
                outcome=PersistOutcome.INSERTED,
                rule_id=rule.rule_id,
                version=rule.version,
                content_hash=digest,
            )
        if existing.content_hash == digest:
            return PersistResult(
                outcome=PersistOutcome.UNCHANGED,
                rule_id=rule.rule_id,
                version=rule.version,
                content_hash=digest,
                detail="identical content_hash",
            )
        return PersistResult(
            outcome=PersistOutcome.CONFLICT,
            rule_id=rule.rule_id,
            version=rule.version,
            content_hash=digest,
            detail=(
                f"immutable version conflict: existing={existing.content_hash[:12]} "
                f"incoming={digest[:12]}"
            ),
        )

    def get_rule(self, rule_id: str, version: str) -> StoredRule | None:
        return self._rules.get((rule_id, version))

    def list_active(self) -> list[StoredRule]:
        return [s for s in self._rules.values() if s.rule.status == "ACTIVE"]

    def persist_evaluation(self, evaluation: KnowledgeRuleEvaluation) -> None:
        self.evaluations.append(evaluation)


class SqlKnowledgeRuleStore:
    """Persist into intelligence.knowledge_rules / knowledge_rule_evaluations."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def persist_rule(
        self,
        rule: KnowledgeRule,
        *,
        body: dict[str, Any] | None = None,
    ) -> PersistResult:
        extra = dict(body or {})
        digest = content_hash(rule, extra_body=extra)
        extra_with_hash = {**extra, "content_hash": digest}
        existing = self._session.scalar(
            select(KnowledgeRuleRow).where(
                KnowledgeRuleRow.rule_id == rule.rule_id,
                KnowledgeRuleRow.version == rule.version,
            )
        )
        if existing is None:
            self._session.add(
                KnowledgeRuleRow(
                    rule_id=rule.rule_id,
                    version=rule.version,
                    domain=rule.domain,
                    title=rule.title,
                    principle=rule.principle,
                    applicability=list(rule.applicability),
                    required_evidence=list(rule.required_evidence),
                    contraindications=list(rule.contraindications),
                    severity=rule.severity,
                    source_reference=rule.source_reference,
                    source_location=rule.source_location,
                    created_from=rule.created_from,
                    status=rule.status,
                    body=extra_with_hash,
                )
            )
            return PersistResult(
                outcome=PersistOutcome.INSERTED,
                rule_id=rule.rule_id,
                version=rule.version,
                content_hash=digest,
            )

        existing_hash = str((existing.body or {}).get("content_hash") or "")
        if existing_hash == digest:
            return PersistResult(
                outcome=PersistOutcome.UNCHANGED,
                rule_id=rule.rule_id,
                version=rule.version,
                content_hash=digest,
                detail="identical content_hash",
            )
        return PersistResult(
            outcome=PersistOutcome.CONFLICT,
            rule_id=rule.rule_id,
            version=rule.version,
            content_hash=digest,
            detail=(
                f"immutable version conflict: existing={existing_hash[:12]} "
                f"incoming={digest[:12]}"
            ),
        )

    def get_rule(self, rule_id: str, version: str) -> StoredRule | None:
        row = self._session.scalar(
            select(KnowledgeRuleRow).where(
                KnowledgeRuleRow.rule_id == rule_id,
                KnowledgeRuleRow.version == version,
            )
        )
        if row is None:
            return None
        body = dict(row.body or {})
        digest = str(body.get("content_hash") or content_hash(_row_to_rule(row), extra_body=body))
        return StoredRule(rule=_row_to_rule(row), body=body, content_hash=digest)

    def list_active(self) -> list[StoredRule]:
        rows = self._session.scalars(
            select(KnowledgeRuleRow).where(KnowledgeRuleRow.status == "ACTIVE")
        ).all()
        out: list[StoredRule] = []
        for row in rows:
            body = dict(row.body or {})
            digest = str(body.get("content_hash") or "")
            out.append(StoredRule(rule=_row_to_rule(row), body=body, content_hash=digest))
        return out

    def persist_evaluation(self, evaluation: KnowledgeRuleEvaluation) -> None:
        as_of = evaluation.as_of
        if as_of is None:
            raise ValueError("evaluation.as_of is required for SQL persistence")
        as_of_date = date.fromisoformat(as_of) if isinstance(as_of, str) else as_of
        self._session.add(
            KnowledgeRuleEvaluationRow(
                rule_id=evaluation.rule_id,
                rule_version=evaluation.rule_version,
                instrument_id=evaluation.instrument_id,
                as_of=as_of_date,
                state=evaluation.state,
                why=evaluation.why,
                evidence_refs=list(evaluation.evidence_refs),
                metadata_=dict(evaluation.metadata),
            )
        )
