"""Contradiction detection between knowledge rules / evaluations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.modules.intelligence.contracts.knowledge import KnowledgeRule, KnowledgeRuleEvaluation
from app.modules.intelligence.knowledge.repository import StoredRule

_OPPOSING_POLARITY = {
    ("requires", "waives"),
    ("waives", "requires"),
    ("supports", "rejects"),
    ("rejects", "supports"),
    ("affirm", "deny"),
    ("deny", "affirm"),
}


@dataclass(frozen=True, slots=True)
class ContradictionReport:
    left_rule_id: str
    left_version: str
    right_rule_id: str
    right_version: str
    kind: str
    detail: str
    claim_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _body_of(stored: StoredRule | KnowledgeRule, bodies: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if isinstance(stored, StoredRule):
        return dict(stored.body or {})
    return dict(bodies.get(stored.rule_id, {}))


def _rule_of(stored: StoredRule | KnowledgeRule) -> KnowledgeRule:
    return stored.rule if isinstance(stored, StoredRule) else stored


def detect_pack_contradictions(
    rules: list[StoredRule] | list[KnowledgeRule] | tuple[KnowledgeRule, ...],
    *,
    bodies: dict[str, dict[str, Any]] | None = None,
) -> list[ContradictionReport]:
    """Static contradictions from claim_key/polarity or explicit contradicts lists."""
    bodies = bodies or {}
    items: list[tuple[KnowledgeRule, dict[str, Any]]] = []
    for item in rules:
        rule = _rule_of(item)  # type: ignore[arg-type]
        body = _body_of(item, bodies)  # type: ignore[arg-type]
        items.append((rule, body))

    reports: list[ContradictionReport] = []
    by_id = {r.rule_id: (r, b) for r, b in items}

    # Explicit contradicts edges
    for rule, body in items:
        for other_id in body.get("contradicts") or ():
            other = by_id.get(str(other_id))
            if other is None:
                reports.append(
                    ContradictionReport(
                        left_rule_id=rule.rule_id,
                        left_version=rule.version,
                        right_rule_id=str(other_id),
                        right_version="?",
                        kind="MISSING_TARGET",
                        detail=f"{rule.rule_id} contradicts unknown rule {other_id}",
                    )
                )
                continue
            other_rule, _ = other
            reports.append(
                ContradictionReport(
                    left_rule_id=rule.rule_id,
                    left_version=rule.version,
                    right_rule_id=other_rule.rule_id,
                    right_version=other_rule.version,
                    kind="EXPLICIT",
                    detail=f"{rule.rule_id} explicitly contradicts {other_rule.rule_id}",
                )
            )

    # Claim polarity clashes
    by_claim: dict[str, list[tuple[KnowledgeRule, str]]] = {}
    for rule, body in items:
        claim = body.get("claim_key")
        polarity = body.get("polarity")
        if claim and polarity:
            by_claim.setdefault(str(claim), []).append((rule, str(polarity).lower()))

    for claim, entries in by_claim.items():
        for i, (left, left_pol) in enumerate(entries):
            for right, right_pol in entries[i + 1 :]:
                if (left_pol, right_pol) in _OPPOSING_POLARITY:
                    reports.append(
                        ContradictionReport(
                            left_rule_id=left.rule_id,
                            left_version=left.version,
                            right_rule_id=right.rule_id,
                            right_version=right.version,
                            kind="POLARITY",
                            detail=(
                                f"opposing polarity on claim_key={claim!r}: "
                                f"{left.rule_id}={left_pol} vs {right.rule_id}={right_pol}"
                            ),
                            claim_key=claim,
                        )
                    )
    return reports


def detect_evaluation_contradictions(
    evaluations: list[KnowledgeRuleEvaluation] | tuple[KnowledgeRuleEvaluation, ...],
    *,
    rules: list[StoredRule] | list[KnowledgeRule] | None = None,
    bodies: dict[str, dict[str, Any]] | None = None,
) -> list[ContradictionReport]:
    """Runtime contradictions: opposing states on same claim, or TRIGGERED vs VIOLATED pairs."""
    bodies = bodies or {}
    rule_bodies: dict[str, dict[str, Any]] = dict(bodies)
    if rules:
        for item in rules:
            rule = _rule_of(item)  # type: ignore[arg-type]
            rule_bodies.setdefault(rule.rule_id, _body_of(item, bodies))  # type: ignore[arg-type]

    by_id = {e.rule_id: e for e in evaluations}
    reports: list[ContradictionReport] = []

    # Pairwise: same claim_key with TRIGGERED + VIOLATED
    claim_groups: dict[str, list[KnowledgeRuleEvaluation]] = {}
    for ev in evaluations:
        claim = (rule_bodies.get(ev.rule_id) or {}).get("claim_key")
        if claim:
            claim_groups.setdefault(str(claim), []).append(ev)

    for claim, group in claim_groups.items():
        triggered = [e for e in group if e.state == "TRIGGERED"]
        violated = [e for e in group if e.state == "VIOLATED"]
        for t in triggered:
            for v in violated:
                reports.append(
                    ContradictionReport(
                        left_rule_id=t.rule_id,
                        left_version=t.rule_version,
                        right_rule_id=v.rule_id,
                        right_version=v.rule_version,
                        kind="EVAL_STATE",
                        detail=(
                            f"TRIGGERED vs VIOLATED on claim_key={claim!r} "
                            f"({t.rule_id} vs {v.rule_id})"
                        ),
                        claim_key=claim,
                    )
                )

    # Explicit contradicts where both are TRIGGERED
    for rule_id, body in rule_bodies.items():
        left = by_id.get(rule_id)
        if left is None or left.state != "TRIGGERED":
            continue
        for other_id in body.get("contradicts") or ():
            right = by_id.get(str(other_id))
            if right is not None and right.state == "TRIGGERED":
                reports.append(
                    ContradictionReport(
                        left_rule_id=left.rule_id,
                        left_version=left.rule_version,
                        right_rule_id=right.rule_id,
                        right_version=right.rule_version,
                        kind="EVAL_EXPLICIT",
                        detail="both sides of explicit contradiction are TRIGGERED",
                    )
                )
    return reports


def detect_contradictions(
    *,
    rules: list[StoredRule] | list[KnowledgeRule] | None = None,
    evaluations: list[KnowledgeRuleEvaluation] | None = None,
    bodies: dict[str, dict[str, Any]] | None = None,
) -> list[ContradictionReport]:
    out: list[ContradictionReport] = []
    if rules:
        out.extend(detect_pack_contradictions(rules, bodies=bodies))
    if evaluations:
        out.extend(
            detect_evaluation_contradictions(evaluations, rules=rules, bodies=bodies)
        )
    return out
