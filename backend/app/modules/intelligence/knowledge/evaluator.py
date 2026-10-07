"""Deterministic KnowledgeRule evaluator — advisory states only, never trades."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.modules.intelligence.contracts.knowledge import (
    RULE_EVAL_STATES,
    KnowledgeRule,
    KnowledgeRuleEvaluation,
    RuleEvalState,
)

# observation keys used by starter-pack handlers
OBS_PRICE_MOVE_DIRECTIONAL = "price_move_directional"
OBS_VOLUME_CONFIRMS = "volume_confirms"
OBS_UNKNOWN_COERCED_TO_NEUTRAL = "unknown_coerced_to_neutral"
OBS_MISSING_EVIDENCE_PRESENT = "missing_evidence_present"
OBS_ISSUER_KIND = "issuer_kind"
OBS_USED_INDUSTRIAL_RATIOS = "used_industrial_ratios"
OBS_USED_BANK_METRICS_OR_ABSTAIN = "used_bank_metrics_or_abstain"
OBS_DATA_STALE = "data_stale"
OBS_CONFIDENCE_DESPITE_STALE = "confidence_despite_stale"
OBS_MATERIAL_ADVERSE_EVENT = "material_adverse_event"
OBS_WEAK_TECHNICAL_POSITIVE = "weak_technical_positive"
OBS_EVENT_OVERRIDDEN_BY_WEAK_TREND = "event_overridden_by_weak_trend"


@dataclass(frozen=True, slots=True)
class RuleEvaluationContext:
    """Point-in-time facts available to the rule engine (no look-ahead)."""

    active_applicability: frozenset[str] = frozenset()
    available_evidence: frozenset[str] = frozenset()
    active_contraindications: frozenset[str] = frozenset()
    observations: dict[str, Any] = field(default_factory=dict)
    instrument_id: int | None = None
    as_of: str | None = None
    evidence_refs: tuple[dict[str, Any], ...] = ()

    def obs(self, key: str, default: Any = None) -> Any:
        return self.observations.get(key, default)


Handler = Callable[[KnowledgeRule, RuleEvaluationContext, dict[str, Any]], KnowledgeRuleEvaluation]


def _base_eval(
    rule: KnowledgeRule,
    ctx: RuleEvaluationContext,
    state: RuleEvalState,
    why: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> KnowledgeRuleEvaluation:
    if state not in RULE_EVAL_STATES:
        raise ValueError(f"invalid state {state!r}")
    meta = {"advisory_only": True, "issues_trades": False, **(metadata or {})}
    return KnowledgeRuleEvaluation(
        rule_id=rule.rule_id,
        rule_version=rule.version,
        state=state,
        why=why,
        evidence_refs=ctx.evidence_refs,
        instrument_id=ctx.instrument_id,
        as_of=ctx.as_of,
        metadata=meta,
    )


def _applicability_gate(
    rule: KnowledgeRule, ctx: RuleEvaluationContext
) -> KnowledgeRuleEvaluation | None:
    if not rule.applicability:
        return None
    if not any(tag in ctx.active_applicability for tag in rule.applicability):
        return _base_eval(
            rule,
            ctx,
            "NOT_APPLICABLE",
            f"applicability not met: need any of {list(rule.applicability)}",
        )
    return None


def _contraindication_gate(
    rule: KnowledgeRule, ctx: RuleEvaluationContext
) -> KnowledgeRuleEvaluation | None:
    hit = [c for c in rule.contraindications if c in ctx.active_contraindications]
    if hit:
        return _base_eval(
            rule,
            ctx,
            "UNKNOWN",
            f"contraindications active: {hit}",
            metadata={"contraindications": hit},
        )
    return None


def _evidence_gate(
    rule: KnowledgeRule, ctx: RuleEvaluationContext
) -> KnowledgeRuleEvaluation | None:
    missing = [e for e in rule.required_evidence if e not in ctx.available_evidence]
    if missing:
        return _base_eval(
            rule,
            ctx,
            "UNKNOWN",
            f"required evidence missing: {missing}",
            metadata={"missing_evidence": missing},
        )
    return None


def _eval_momentum_volume(
    rule: KnowledgeRule, ctx: RuleEvaluationContext, _body: dict[str, Any]
) -> KnowledgeRuleEvaluation:
    directional = bool(ctx.obs(OBS_PRICE_MOVE_DIRECTIONAL, False))
    volume_ok = bool(ctx.obs(OBS_VOLUME_CONFIRMS, False))
    if not directional:
        return _base_eval(
            rule,
            ctx,
            "NOT_APPLICABLE",
            "no directional price move to confirm",
        )
    if volume_ok:
        return _base_eval(
            rule,
            ctx,
            "TRIGGERED",
            "directional move has supporting volume evidence",
        )
    return _base_eval(
        rule,
        ctx,
        "VIOLATED",
        "directional price move lacks supporting volume evidence",
    )


def _eval_unknown_not_neutral(
    rule: KnowledgeRule, ctx: RuleEvaluationContext, _body: dict[str, Any]
) -> KnowledgeRuleEvaluation:
    coerced = bool(ctx.obs(OBS_UNKNOWN_COERCED_TO_NEUTRAL, False))
    missing = bool(ctx.obs(OBS_MISSING_EVIDENCE_PRESENT, False))
    if coerced:
        return _base_eval(
            rule,
            ctx,
            "VIOLATED",
            "missing/unsupported evidence was coerced to NEUTRAL or zero",
        )
    if missing:
        return _base_eval(
            rule,
            ctx,
            "TRIGGERED",
            "missing evidence correctly left as UNKNOWN/ABSTAIN",
        )
    return _base_eval(
        rule,
        ctx,
        "NOT_APPLICABLE",
        "no missing-evidence situation in context",
    )


def _eval_bank_ratios(
    rule: KnowledgeRule, ctx: RuleEvaluationContext, _body: dict[str, Any]
) -> KnowledgeRuleEvaluation:
    kind = str(ctx.obs(OBS_ISSUER_KIND, "") or "").lower()
    if kind not in {"bank", "bank_fi", "fi", "financial"}:
        return _base_eval(rule, ctx, "NOT_APPLICABLE", f"issuer_kind={kind!r} is not bank/FI")
    if bool(ctx.obs(OBS_USED_INDUSTRIAL_RATIOS, False)):
        return _base_eval(
            rule,
            ctx,
            "VIOLATED",
            "bank/FI issuer evaluated with industrial RAS ratios",
        )
    if bool(ctx.obs(OBS_USED_BANK_METRICS_OR_ABSTAIN, False)):
        return _base_eval(
            rule,
            ctx,
            "TRIGGERED",
            "bank/FI path uses bank metrics or ABSTAIN",
        )
    return _base_eval(
        rule,
        ctx,
        "UNKNOWN",
        "bank/FI issuer but metric path not declared",
    )


def _eval_stale_data(
    rule: KnowledgeRule, ctx: RuleEvaluationContext, _body: dict[str, Any]
) -> KnowledgeRuleEvaluation:
    stale = ctx.obs(OBS_DATA_STALE, None)
    if stale is None:
        return _base_eval(rule, ctx, "UNKNOWN", "data freshness not observable")
    if not stale:
        return _base_eval(rule, ctx, "NOT_APPLICABLE", "data not marked stale")
    if bool(ctx.obs(OBS_CONFIDENCE_DESPITE_STALE, False)):
        return _base_eval(
            rule,
            ctx,
            "VIOLATED",
            "stale/incomplete data did not reduce confidence",
        )
    return _base_eval(
        rule,
        ctx,
        "TRIGGERED",
        "stale/incomplete data reduces confidence or forces ABSTAIN",
    )


def _eval_material_event(
    rule: KnowledgeRule, ctx: RuleEvaluationContext, _body: dict[str, Any]
) -> KnowledgeRuleEvaluation:
    adverse = bool(ctx.obs(OBS_MATERIAL_ADVERSE_EVENT, False))
    if not adverse:
        return _base_eval(rule, ctx, "NOT_APPLICABLE", "no material adverse event in context")
    if bool(ctx.obs(OBS_EVENT_OVERRIDDEN_BY_WEAK_TREND, False)):
        return _base_eval(
            rule,
            ctx,
            "VIOLATED",
            "weak technical positive overrode material adverse event",
        )
    if bool(ctx.obs(OBS_WEAK_TECHNICAL_POSITIVE, False)):
        return _base_eval(
            rule,
            ctx,
            "TRIGGERED",
            "material adverse event surfaces as counterargument to weak technical positive",
        )
    return _base_eval(
        rule,
        ctx,
        "TRIGGERED",
        "material adverse event present with trustworthy known_at",
    )


_HANDLERS: dict[str, Handler] = {
    "momentum_needs_volume_confirmation": _eval_momentum_volume,
    "unknown_not_neutral": _eval_unknown_not_neutral,
    "bank_industrial_ratios_forbidden": _eval_bank_ratios,
    "stale_data_blocks_confidence": _eval_stale_data,
    "material_event_overrides_weak_trend": _eval_material_event,
}


def _generic_handler(
    rule: KnowledgeRule, ctx: RuleEvaluationContext, body: dict[str, Any]
) -> KnowledgeRuleEvaluation:
    """Fallback: explicit observation overrides, else UNKNOWN when applicable."""
    forced = ctx.obs(f"rule:{rule.rule_id}:state")
    if forced in RULE_EVAL_STATES:
        return _base_eval(
            rule,
            ctx,
            forced,  # type: ignore[arg-type]
            str(ctx.obs(f"rule:{rule.rule_id}:why") or "explicit observation override"),
            metadata={"handler": "generic_override"},
        )
    violations = set(ctx.obs("violated_rule_ids") or ())
    triggers = set(ctx.obs("triggered_rule_ids") or ())
    if rule.rule_id in violations:
        return _base_eval(rule, ctx, "VIOLATED", "listed in violated_rule_ids")
    if rule.rule_id in triggers:
        return _base_eval(rule, ctx, "TRIGGERED", "listed in triggered_rule_ids")
    claim = body.get("claim_key")
    if claim:
        return _base_eval(
            rule,
            ctx,
            "UNKNOWN",
            f"no dedicated handler; claim_key={claim!r} lacks evaluation evidence",
            metadata={"handler": "generic", "claim_key": claim},
        )
    return _base_eval(
        rule,
        ctx,
        "UNKNOWN",
        "no dedicated handler and no explicit observation",
        metadata={"handler": "generic"},
    )


def evaluate_rule(
    rule: KnowledgeRule,
    ctx: RuleEvaluationContext,
    *,
    body: dict[str, Any] | None = None,
) -> KnowledgeRuleEvaluation:
    body = body or {}
    gated = _applicability_gate(rule, ctx)
    if gated is not None:
        return gated
    gated = _contraindication_gate(rule, ctx)
    if gated is not None:
        return gated
    gated = _evidence_gate(rule, ctx)
    if gated is not None:
        return gated

    handler = _HANDLERS.get(rule.rule_id, _generic_handler)
    return handler(rule, ctx, body)


def evaluate_rules(
    rules: list[KnowledgeRule] | tuple[KnowledgeRule, ...],
    ctx: RuleEvaluationContext,
    *,
    bodies: dict[str, dict[str, Any]] | None = None,
) -> list[KnowledgeRuleEvaluation]:
    bodies = bodies or {}
    return [evaluate_rule(rule, ctx, body=bodies.get(rule.rule_id)) for rule in rules]
