"""Deterministic committee combination: signals + knowledge + risk → decision."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date

from app.modules.intelligence.committee import policy_v1 as P
from app.modules.intelligence.contracts.committee import (
    AdvisoryState,
    CommitteeDecisionV1,
    ModelVote,
)
from app.modules.intelligence.contracts.knowledge import KnowledgeRuleEvaluation
from app.modules.intelligence.contracts.provenance import EvidenceRef
from app.modules.intelligence.contracts.risk import RiskAssessmentV1
from app.modules.intelligence.contracts.signal import SignalOutputV1


def _norm_token(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _semantic_weight(semantic: str) -> float:
    key = semantic.strip().upper()
    return float(P.SEMANTIC_WEIGHTS.get(key, P.DEFAULT_WEIGHT))


def _signed_score(signal: SignalOutputV1) -> float:
    if signal.score is not None:
        return max(-1.0, min(1.0, float(signal.score)))
    return float(P.STATE_SCORE.get(signal.state, 0.0))


def _vote_weight(signal: SignalOutputV1) -> float:
    """Weight = semantic weight × confidence (missing confidence → 1.0, not zero)."""
    base = _semantic_weight(signal.semantic)
    conf = 1.0 if signal.confidence is None else float(signal.confidence)
    return base * max(0.0, min(1.0, conf))


def _is_valid(signal: SignalOutputV1) -> bool:
    return signal.state in P.VALID_SIGNAL_STATES


def _is_severe_stale_label(value: str | None) -> bool:
    if not value:
        return False
    n = _norm_token(value)
    if n in P.SEVERE_STALE_TOKENS:
        return True
    return "stale" in n and ("severe" in n or "critical" in n)


def _is_soft_stale_label(value: str | None) -> bool:
    if not value:
        return False
    n = _norm_token(value)
    if _is_severe_stale_label(value):
        return False
    if n in P.SOFT_STALE_TOKENS:
        return True
    return "stale" in n


def _pairwise_disagreement(scores: Sequence[float]) -> float:
    """Mean pairwise |a-b| / 2 → [0, 1] for scores in [-1, 1]."""
    n = len(scores)
    if n < 2:
        return 0.0
    total = 0.0
    count = 0
    for i in range(n):
        for j in range(i + 1, n):
            total += abs(scores[i] - scores[j])
            count += 1
    return max(0.0, min(1.0, (total / count) / 2.0))


def _weighted_mean(pairs: Sequence[tuple[float, float]]) -> float | None:
    usable = [(w, v) for w, v in pairs if w > 0]
    if not usable:
        return None
    w_sum = sum(w for w, _ in usable)
    if w_sum <= 0:
        return None
    return sum(w * v for w, v in usable) / w_sum


def _collect_evidence(
    signals: Sequence[SignalOutputV1], risk: RiskAssessmentV1 | None
) -> tuple[EvidenceRef, ...]:
    refs: list[EvidenceRef] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()
    streams: list[Sequence[EvidenceRef]] = [s.evidence_refs for s in signals]
    if risk is not None:
        streams.append(risk.evidence_refs)
    for stream in streams:
        for ref in stream:
            key = (ref.source_type, ref.provider, ref.content_hash)
            if key in seen:
                continue
            seen.add(key)
            refs.append(ref)
    return tuple(refs)


def _triggered_rules(evals: Sequence[KnowledgeRuleEvaluation]) -> tuple[str, ...]:
    return tuple(e.rule_id for e in evals if e.state in {"TRIGGERED", "VIOLATED"})


def _severe_stale(
    signals: Sequence[SignalOutputV1],
    risk: RiskAssessmentV1 | None,
    knowledge: Sequence[KnowledgeRuleEvaluation],
) -> tuple[bool, list[str]]:
    reasons: list[str] = []

    for sig in signals:
        if _is_severe_stale_label(sig.data_freshness):
            reasons.append(f"severe_stale_signal:{sig.model_id}")

    if risk is not None:
        if _is_severe_stale_label(risk.data_risk):
            reasons.append("severe_stale_risk_data_risk")
        for flag in risk.risk_flags:
            if _is_severe_stale_label(flag):
                reasons.append(f"severe_stale_risk_flag:{flag}")
        # HIGH/CRITICAL data_risk combined with any soft stale marker.
        if risk.data_risk and _norm_token(risk.data_risk) in {"high", "critical"}:
            soft_present = any(_is_soft_stale_label(s.data_freshness) for s in signals)
            soft_present = soft_present or any(_is_soft_stale_label(f) for f in risk.risk_flags)
            if soft_present or _is_soft_stale_label(risk.data_risk):
                reasons.append("severe_stale_data")

    for ev in knowledge:
        if ev.rule_id != P.STALE_DATA_RULE_ID:
            continue
        if ev.state == "VIOLATED":
            reasons.append("stale_data_rule_violated")
        elif ev.state == "TRIGGERED":
            meta = ev.metadata or {}
            why_n = _norm_token(ev.why)
            if (
                meta.get("force_abstain")
                or meta.get("severity") == "HIGH"
                or ("severe" in why_n)
                or ("critical" in why_n)
            ):
                reasons.append("stale_data_rule_triggered_abstain")

    # stable unique
    return bool(reasons), list(dict.fromkeys(reasons))


def _soft_stale(
    signals: Sequence[SignalOutputV1],
    risk: RiskAssessmentV1 | None,
    knowledge: Sequence[KnowledgeRuleEvaluation],
) -> bool:
    if any(_is_soft_stale_label(s.data_freshness) for s in signals):
        return True
    if risk is not None:
        if _is_soft_stale_label(risk.data_risk):
            return True
        if any(_is_soft_stale_label(f) for f in risk.risk_flags):
            return True
    return any(
        e.rule_id == P.STALE_DATA_RULE_ID and e.state == "TRIGGERED" for e in knowledge
    )


def _material_adverse(
    signals: Sequence[SignalOutputV1],
    risk: RiskAssessmentV1 | None,
    knowledge: Sequence[KnowledgeRuleEvaluation],
) -> tuple[bool, list[str]]:
    notes: list[str] = []
    for ev in knowledge:
        if ev.rule_id == P.MATERIAL_EVENT_RULE_ID and ev.state in {"TRIGGERED", "VIOLATED"}:
            notes.append(f"knowledge:{ev.rule_id}")
    if risk is not None:
        if risk.event_risk and _norm_token(risk.event_risk) in {
            "high",
            "elevated",
            "material",
        }:
            notes.append(f"risk_event:{risk.event_risk}")
        for flag in risk.risk_flags:
            n = _norm_token(flag)
            if n in {"material_adverse_event", "adverse_event"} or (
                "material" in n and ("adverse" in n or "event" in n)
            ):
                notes.append(f"risk_flag:{flag}")
    for sig in signals:
        if sig.semantic.upper() != "EVENT":
            continue
        if sig.state != "NEGATIVE":
            continue
        score = _signed_score(sig)
        conf = 1.0 if sig.confidence is None else float(sig.confidence)
        if score <= -0.25 and conf >= 0.40:
            notes.append(f"event_model:{sig.model_id}")
    return bool(notes), list(dict.fromkeys(notes))


def _map_advisory(mean_score: float, disagreement: float) -> AdvisoryState:
    if mean_score >= P.CONSIDER_INCREASE_MIN:
        state: AdvisoryState = "CONSIDER_INCREASE"
    elif mean_score <= P.CONSIDER_REDUCE_MAX:
        state = "CONSIDER_REDUCE"
    else:
        state = "HOLD"
    if disagreement >= P.HIGH_DISAGREEMENT and state in {
        "CONSIDER_INCREASE",
        "CONSIDER_REDUCE",
    }:
        return "HOLD"
    return state


def _drivers_and_counters(
    valid: Sequence[SignalOutputV1],
    mean_score: float,
) -> tuple[list[str], list[str]]:
    drivers: list[str] = []
    counters: list[str] = []
    for sig in valid:
        signed = _signed_score(sig)
        label = f"{sig.model_id}:{sig.state}"
        if mean_score >= 0 and signed > 0:
            drivers.append(label)
        elif mean_score >= 0 and signed < 0:
            counters.append(label)
        elif mean_score < 0 and signed < 0:
            drivers.append(label)
        elif mean_score < 0 and signed > 0:
            counters.append(label)
        elif signed == 0:
            counters.append(f"{label}:neutral")
    return drivers, counters


def decide(
    *,
    as_of: date,
    instrument_id: int,
    signals: Sequence[SignalOutputV1],
    knowledge_evals: Sequence[KnowledgeRuleEvaluation] = (),
    risk: RiskAssessmentV1 | None = None,
) -> CommitteeDecisionV1:
    """Combine independent signals + knowledge + risk into CommitteeDecisionV1.

    Pure / deterministic. Never emits broker orders or execution intents.
    """
    signals = tuple(signals)
    knowledge_evals = tuple(knowledge_evals)

    limitations: list[str] = [
        P.LIMITATION_ADVISORY_ONLY,
        P.LIMITATION_PREDECLARED,
        P.LIMITATION_DISAGREEMENT_PRESERVED,
    ]
    blockers: list[str] = []
    data_gaps: list[str] = []
    risk_overrides: list[str] = []
    what_would_change: list[str] = []

    for sig in signals:
        if sig.instrument_id != instrument_id:
            blockers.append(f"instrument_mismatch:{sig.model_id}")
        if sig.as_of != as_of:
            data_gaps.append(f"as_of_mismatch:{sig.model_id}")

    votes: list[ModelVote] = []
    valid: list[SignalOutputV1] = []
    for sig in signals:
        weight = _vote_weight(sig) if _is_valid(sig) else None
        note = None
        if sig.state in P.NON_VOTING_STATES:
            note = sig.abstain_reason or sig.state.lower()
            data_gaps.append(f"{sig.model_id}:{sig.state}:{note}")
        score_for_vote = sig.score
        if score_for_vote is None and _is_valid(sig):
            score_for_vote = _signed_score(sig)
        votes.append(
            ModelVote(
                model_id=sig.model_id,
                state=sig.state,
                score=score_for_vote,
                confidence=sig.confidence,
                weight_applied=weight,
                note=note,
            )
        )
        if _is_valid(sig):
            valid.append(sig)

    triggered = _triggered_rules(knowledge_evals)
    evidence = _collect_evidence(signals, risk)

    severe, severe_reasons = _severe_stale(signals, risk, knowledge_evals)
    if severe:
        blockers.extend(severe_reasons)
        what_would_change.append("fresh_core_evidence")
        return CommitteeDecisionV1(
            as_of=as_of,
            instrument_id=instrument_id,
            advisory_state="ABSTAIN",
            confidence=None,
            consensus_strength=None,
            disagreement_score=None,
            independent_model_votes=tuple(votes),
            primary_drivers=(),
            counterarguments=(),
            blockers=tuple(dict.fromkeys(blockers)),
            data_gaps=tuple(dict.fromkeys(data_gaps)),
            triggered_knowledge_rules=triggered,
            risk_overrides=(),
            what_would_change_decision=tuple(dict.fromkeys(what_would_change)),
            evidence_refs=evidence,
            committee_policy_version=P.POLICY_VERSION,
            limitations=tuple(limitations),
            metadata={
                "policy": P.POLICY_VERSION,
                "valid_model_count": len(valid),
                "abstain_reason": "severe_stale_data",
                "issues_trades": False,
            },
        )

    if len(valid) < P.MIN_VALID_MODELS:
        blockers.append("insufficient_valid_models")
        what_would_change.append(f"at_least_{P.MIN_VALID_MODELS}_valid_independent_models")
        disagreement = (
            _pairwise_disagreement([_signed_score(s) for s in valid])
            if len(valid) >= 2
            else None
        )
        return CommitteeDecisionV1(
            as_of=as_of,
            instrument_id=instrument_id,
            advisory_state="ABSTAIN",
            confidence=None,
            consensus_strength=None,
            disagreement_score=disagreement,
            independent_model_votes=tuple(votes),
            primary_drivers=(),
            counterarguments=(),
            blockers=tuple(dict.fromkeys(blockers)),
            data_gaps=tuple(dict.fromkeys(data_gaps)),
            triggered_knowledge_rules=triggered,
            risk_overrides=(),
            what_would_change_decision=tuple(dict.fromkeys(what_would_change)),
            evidence_refs=evidence,
            committee_policy_version=P.POLICY_VERSION,
            limitations=tuple(limitations),
            metadata={
                "policy": P.POLICY_VERSION,
                "valid_model_count": len(valid),
                "min_valid_models": P.MIN_VALID_MODELS,
                "abstain_reason": "insufficient_valid_models",
                "issues_trades": False,
            },
        )

    signed_scores = [_signed_score(s) for s in valid]
    weight_pairs = [(_vote_weight(s), _signed_score(s)) for s in valid]
    mean_score = _weighted_mean(weight_pairs)
    assert mean_score is not None
    disagreement = _pairwise_disagreement(signed_scores)
    pos_w = sum(w for w, v in weight_pairs if v > 0)
    neg_w = sum(w for w, v in weight_pairs if v < 0)
    neu_w = sum(w for w, v in weight_pairs if v == 0)
    total_w = pos_w + neg_w + neu_w
    majority_w = max(pos_w, neg_w, neu_w)
    consensus_strength = (majority_w / total_w) if total_w > 0 else 0.0

    advisory = _map_advisory(mean_score, disagreement)
    primary_drivers, counterarguments = _drivers_and_counters(valid, mean_score)

    material, material_notes = _material_adverse(signals, risk, knowledge_evals)
    # Override uses non-event directional mean when available so a severe event
    # vote cannot "hide" the weak-positive setup it is supposed to block.
    non_event = [s for s in valid if s.semantic.upper() != "EVENT"]
    override_mean = mean_score
    override_advisory = advisory
    if len(non_event) >= P.MIN_VALID_MODELS:
        ne_pairs = [(_vote_weight(s), _signed_score(s)) for s in non_event]
        ne_mean = _weighted_mean(ne_pairs)
        if ne_mean is not None:
            override_mean = ne_mean
            override_advisory = _map_advisory(
                ne_mean, _pairwise_disagreement([_signed_score(s) for s in non_event])
            )
    if (
        material
        and override_advisory == "CONSIDER_INCREASE"
        and override_mean <= P.WEAK_POSITIVE_MEAN_MAX
    ):
        risk_overrides.extend(material_notes)
        risk_overrides.append("material_adverse_overrides_weak_positive")
        counterarguments.extend(material_notes)
        advisory = "HOLD"
        what_would_change.append("adverse_event_cleared_or_stronger_non_event_support")

    conf_parts = [float(s.confidence) for s in valid if s.confidence is not None]
    base_conf = sum(conf_parts) / len(conf_parts) if conf_parts else consensus_strength
    confidence = base_conf * (1.0 - P.DISAGREEMENT_CONFIDENCE_SLOPE * disagreement)
    if _soft_stale(signals, risk, knowledge_evals):
        confidence *= P.STALE_SOFT_CONFIDENCE_FACTOR
        limitations.append("soft_stale_confidence_haircut")
        data_gaps.append("soft_stale_data")
    if risk is not None:
        if risk.risk_state == "HIGH":
            confidence *= P.RISK_HIGH_CONFIDENCE_FACTOR
            if advisory == "CONSIDER_INCREASE":
                risk_overrides.append("risk_state_HIGH_blocks_increase")
                advisory = "HOLD"
                what_would_change.append("risk_state_below_HIGH")
        elif risk.risk_state == "ELEVATED":
            confidence *= P.RISK_ELEVATED_CONFIDENCE_FACTOR
        limitations.extend(risk.limitations)

    confidence = max(0.0, min(1.0, float(confidence)))

    if disagreement >= P.HIGH_DISAGREEMENT:
        what_would_change.append("model_agreement_improvement")
        counterarguments.append(f"high_disagreement:{disagreement:.2f}")

    metadata = {
        "policy": P.POLICY_VERSION,
        "valid_model_count": len(valid),
        "weighted_mean_score": round(mean_score, 6),
        "semantic_weights": dict(P.SEMANTIC_WEIGHTS),
        "min_valid_models": P.MIN_VALID_MODELS,
        "thresholds": {
            "consider_increase_min": P.CONSIDER_INCREASE_MIN,
            "consider_reduce_max": P.CONSIDER_REDUCE_MAX,
            "high_disagreement": P.HIGH_DISAGREEMENT,
        },
        "issues_trades": False,
    }

    return CommitteeDecisionV1(
        as_of=as_of,
        instrument_id=instrument_id,
        advisory_state=advisory,
        confidence=confidence,
        consensus_strength=max(0.0, min(1.0, consensus_strength)),
        disagreement_score=disagreement,
        independent_model_votes=tuple(votes),
        primary_drivers=tuple(dict.fromkeys(primary_drivers)),
        counterarguments=tuple(dict.fromkeys(counterarguments)),
        blockers=tuple(dict.fromkeys(blockers)),
        data_gaps=tuple(dict.fromkeys(data_gaps)),
        triggered_knowledge_rules=triggered,
        risk_overrides=tuple(dict.fromkeys(risk_overrides)),
        what_would_change_decision=tuple(dict.fromkeys(what_would_change)),
        evidence_refs=evidence,
        committee_policy_version=P.POLICY_VERSION,
        limitations=tuple(dict.fromkeys(limitations)),
        metadata=metadata,
    )


def decide_many(
    *,
    as_of: date,
    items: Iterable[tuple[int, Sequence[SignalOutputV1]]],
    knowledge_by_instrument: dict[int, Sequence[KnowledgeRuleEvaluation]] | None = None,
    risk_by_instrument: dict[int, RiskAssessmentV1] | None = None,
) -> list[CommitteeDecisionV1]:
    """Batch helper — one decision per instrument."""
    knowledge_by_instrument = knowledge_by_instrument or {}
    risk_by_instrument = risk_by_instrument or {}
    out: list[CommitteeDecisionV1] = []
    for instrument_id, sigs in items:
        out.append(
            decide(
                as_of=as_of,
                instrument_id=instrument_id,
                signals=sigs,
                knowledge_evals=knowledge_by_instrument.get(instrument_id, ()),
                risk=risk_by_instrument.get(instrument_id),
            )
        )
    return out
