"""Compose IntelligenceSnapshotV1 from available pieces; honest UNKNOWN when unwired."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Protocol

from app.modules.intelligence.contracts.committee import (
    COMMITTEE_POLICY_VERSION,
    CommitteeDecisionV1,
    ModelVote,
)
from app.modules.intelligence.contracts.risk import RiskAssessmentV1
from app.modules.intelligence.contracts.signal import SignalOutputV1, unknown_signal
from app.modules.intelligence.contracts.snapshot import CoverageItem, IntelligenceSnapshotV1
from app.modules.intelligence.contracts.snapshots_domain import (
    FundamentalSnapshotV1,
    IntradayFeatureSnapshotV1,
    MacroSnapshotV1,
)
from app.modules.intelligence.isolation import production_isolation_report

# Independent analytical models expected by the OWNER company view.
# Until agent modules wire real collectors, each emits UNKNOWN (not NEUTRAL).
EXPECTED_MODELS: tuple[tuple[str, str, str], ...] = (
    ("TechnicalModelV1", "1", "TECHNICAL"),
    ("FundamentalModelV1", "1", "FUNDAMENTAL"),
    ("EventModelV1", "1", "EVENT"),
    ("IntradayModelV1", "1", "INTRADAY"),
    ("MacroModelV1", "1", "MACRO"),
    ("BankModelV1", "1", "BANK_FI"),
    ("NewsModelV1", "1", "NEWS"),
)

COVERAGE_DOMAINS: tuple[str, ...] = (
    "technical",
    "fundamentals",
    "events",
    "intraday",
    "macro",
    "news",
    "knowledge",
    "committee",
    "risk",
)

NOT_WIRED_REASON = "model_collector_not_integrated"
_EVENT_FETCH_LIMIT = 64
_EXTRACTED_EVENT_LIMIT = 16
_UNSCORED_NEWS_LIMIT = 8


class InstrumentIdentity(Protocol):
    id: int
    symbol: str
    name: str


@dataclass(frozen=True, slots=True)
class SnapshotBuildContext:
    instrument_id: int
    symbol: str | None
    name: str | None
    as_of: date
    generated_at: datetime
    session: Any | None = None


class IntelligenceSnapshotBuilder:
    """Composes an OWNER-facing aggregate without inventing model outputs."""

    def build(
        self,
        *,
        instrument: InstrumentIdentity | None,
        instrument_id: int,
        as_of: date | None = None,
        generated_at: datetime | None = None,
        session: Any | None = None,
        signals: tuple[SignalOutputV1, ...] | None = None,
        committee: CommitteeDecisionV1 | None = None,
        risk: RiskAssessmentV1 | None = None,
        fundamentals_summary: dict[str, Any] | None = None,
        macro_summary: dict[str, Any] | None = None,
        recent_events: tuple[dict[str, Any], ...] | None = None,
        knowledge_evaluations: tuple[dict[str, Any], ...] | None = None,
        intraday_summary: dict[str, Any] | None = None,
    ) -> IntelligenceSnapshotV1:
        as_of_date = as_of or datetime.now(UTC).date()
        generated = generated_at or datetime.now(UTC)
        symbol = instrument.symbol if instrument is not None else None
        name = instrument.name if instrument is not None else None
        iid = int(instrument.id) if instrument is not None else int(instrument_id)

        ctx = SnapshotBuildContext(
            instrument_id=iid,
            symbol=symbol,
            name=name,
            as_of=as_of_date,
            generated_at=generated,
            session=session,
        )

        resolved_signals = signals if signals is not None else self._default_signals(ctx)
        resolved_risk = risk if risk is not None else self._default_risk(ctx)
        resolved_knowledge = (
            knowledge_evaluations
            if knowledge_evaluations is not None
            else self._default_knowledge(ctx, resolved_signals)
        )
        resolved_committee = (
            committee
            if committee is not None
            else self._default_committee(ctx, resolved_signals, resolved_risk, resolved_knowledge)
        )
        resolved_fundamentals = (
            fundamentals_summary
            if fundamentals_summary is not None
            else self._default_fundamentals(ctx)
        )
        resolved_macro = macro_summary if macro_summary is not None else self._default_macro(ctx)
        resolved_events = recent_events if recent_events is not None else self._default_events(ctx)
        resolved_intraday = (
            intraday_summary if intraday_summary is not None else self._default_intraday(ctx)
        )

        coverage = self._coverage(
            signals=resolved_signals,
            committee=resolved_committee,
            risk=resolved_risk,
            fundamentals=resolved_fundamentals,
            macro=resolved_macro,
            events=resolved_events,
            knowledge=resolved_knowledge,
            intraday=resolved_intraday,
        )

        limitations = (
            "advisory_research_only",
            "committee_aborts_without_usable_votes",
            "unknown_is_not_neutral",
            "confidence_is_not_probability_of_profit",
        )

        return IntelligenceSnapshotV1(
            instrument_id=iid,
            symbol=symbol,
            name=name,
            as_of=as_of_date,
            generated_at=generated,
            freshness=(
                "PARTIAL"
                if any(s.state not in {"UNKNOWN", "ABSTAIN"} for s in resolved_signals)
                else "STALE_OR_UNWIRED"
            ),
            coverage=coverage,
            signals=resolved_signals,
            committee=resolved_committee,
            risk=resolved_risk,
            fundamentals_summary=resolved_fundamentals,
            macro_summary=resolved_macro,
            recent_events=resolved_events,
            knowledge_evaluations=resolved_knowledge,
            intraday_summary=resolved_intraday,
            limitations=limitations,
            production_isolation=production_isolation_report(),
        )

    def _default_signals(self, ctx: SnapshotBuildContext) -> tuple[SignalOutputV1, ...]:
        # Prefer live collectors when other agents land; ImportError → UNKNOWN.
        collected = self._try_collect_signals(ctx)
        if collected is not None:
            return collected
        return tuple(
            unknown_signal(
                model_id=model_id,
                model_version=version,
                semantic=semantic,
                instrument_id=ctx.instrument_id,
                as_of=ctx.as_of,
                reason=NOT_WIRED_REASON,
                horizon="unspecified",
            )
            for model_id, version, semantic in EXPECTED_MODELS
        )

    def _try_collect_signals(
        self, ctx: SnapshotBuildContext
    ) -> tuple[SignalOutputV1, ...] | None:
        try:
            from app.modules.intelligence.signals import collect_instrument_signals  # type: ignore
        except ImportError:
            return None
        result = collect_instrument_signals(
            instrument_id=ctx.instrument_id,
            as_of=ctx.as_of,
            session=ctx.session,
        )
        if not result:
            return None
        return tuple(result)

    def _default_committee(
        self,
        ctx: SnapshotBuildContext,
        signals: tuple[SignalOutputV1, ...],
        risk: RiskAssessmentV1 | None = None,
        knowledge: tuple[dict[str, Any], ...] = (),
    ) -> CommitteeDecisionV1:
        try:
            from app.modules.intelligence.committee import decide_committee  # type: ignore
            from app.modules.intelligence.contracts.knowledge import KnowledgeRuleEvaluation
        except ImportError:
            decide_committee = None
            KnowledgeRuleEvaluation = None  # type: ignore[assignment]

        evals = ()
        if KnowledgeRuleEvaluation is not None:
            parsed = []
            for item in knowledge:
                if hasattr(item, "rule_id"):
                    parsed.append(item)
                elif isinstance(item, dict) and "rule_id" in item:
                    parsed.append(
                        KnowledgeRuleEvaluation(
                            rule_id=str(item["rule_id"]),
                            rule_version=str(item.get("rule_version") or "1"),
                            state=item.get("state") or "UNKNOWN",
                            why=str(item.get("why") or ""),
                        )
                    )
            evals = tuple(parsed)

        if decide_committee is not None:
            decision = decide_committee(
                instrument_id=ctx.instrument_id,
                as_of=ctx.as_of,
                signals=list(signals),
                knowledge_evals=evals,
                risk=risk,
            )
            if decision is not None:
                return decision

        votes = tuple(
            ModelVote(
                model_id=s.model_id,
                state=s.state,
                score=s.score,
                confidence=s.confidence,
                note=s.abstain_reason,
            )
            for s in signals
        )
        unknown_ids = [s.model_id for s in signals if s.state in {"UNKNOWN", "ABSTAIN"}]
        return CommitteeDecisionV1(
            as_of=ctx.as_of,
            instrument_id=ctx.instrument_id,
            advisory_state="ABSTAIN",
            confidence=None,
            consensus_strength=None,
            disagreement_score=None,
            independent_model_votes=votes,
            primary_drivers=(),
            counterarguments=(),
            blockers=("no_integrated_independent_models",),
            data_gaps=tuple(f"signal_unavailable:{mid}" for mid in unknown_ids),
            triggered_knowledge_rules=(),
            risk_overrides=(),
            what_would_change_decision=(
                "wire_at_least_one_non_unknown_signal",
                "integrate_committee_policy_evaluator",
                "resolve_risk_assessment_from_risk_module",
                "populate_fundamentals_and_events_with_known_at",
            ),
            evidence_refs=(),
            committee_policy_version=COMMITTEE_POLICY_VERSION,
            limitations=(
                "committee_not_integrated",
                "advisory_only_no_orders",
            ),
            metadata={"composition": "honest_stub"},
        )

    def _default_risk(self, ctx: SnapshotBuildContext) -> RiskAssessmentV1:
        try:
            from app.modules.intelligence.risk import assess_instrument_risk  # type: ignore
        except ImportError:
            assess_instrument_risk = None

        if assess_instrument_risk is not None:
            assessed = assess_instrument_risk(
                instrument_id=ctx.instrument_id,
                as_of=ctx.as_of,
                session=ctx.session,
            )
            if assessed is not None:
                return assessed

        return RiskAssessmentV1(
            as_of=ctx.as_of,
            instrument_id=ctx.instrument_id,
            risk_state="UNKNOWN",
            risk_score=None,
            risk_flags=("risk_module_not_integrated",),
            data_risk="UNKNOWN",
            limitations=("risk_assessment_not_wired",),
        )

    def _default_fundamentals(self, ctx: SnapshotBuildContext) -> dict[str, Any]:
        try:
            from app.modules.intelligence.fundamentals import (  # type: ignore
                build_fundamental_snapshot,
            )
        except ImportError:
            build_fundamental_snapshot = None

        # Agent B signature requires a DB session; without it stay UNKNOWN (not fabricated).
        if build_fundamental_snapshot is not None and ctx.session is not None:
            try:
                snap = build_fundamental_snapshot(
                    ctx.session,
                    ctx.instrument_id,
                    ctx.as_of,
                )
            except TypeError:
                snap = None
            if snap is not None:
                return snap.to_dict() if hasattr(snap, "to_dict") else dict(snap)

        return FundamentalSnapshotV1(
            instrument_id=ctx.instrument_id,
            as_of=ctx.as_of,
            status="UNKNOWN",
            issuer_kind="UNKNOWN",
            limitations=(NOT_WIRED_REASON,),
        ).to_dict()

    def _default_macro(self, ctx: SnapshotBuildContext) -> dict[str, Any]:
        try:
            from app.modules.intelligence.macro import build_macro_snapshot  # type: ignore
        except ImportError:
            build_macro_snapshot = None

        if build_macro_snapshot is not None and ctx.session is not None:
            snap = build_macro_snapshot(ctx.session, ctx.as_of)
            if snap is not None:
                return snap.to_dict() if hasattr(snap, "to_dict") else dict(snap)

        return MacroSnapshotV1(
            as_of=ctx.as_of,
            status="UNKNOWN",
            limitations=(NOT_WIRED_REASON,),
        ).to_dict()

    def _default_intraday(self, ctx: SnapshotBuildContext) -> dict[str, Any]:
        try:
            from app.modules.intelligence.intraday import (  # type: ignore
                build_intraday_snapshot,
            )
        except ImportError:
            build_intraday_snapshot = None

        if build_intraday_snapshot is not None and ctx.session is not None:
            from datetime import timedelta

            partial: dict[str, Any] | None = None
            for delta in range(0, 8):
                day = ctx.as_of - timedelta(days=delta)
                if day.weekday() >= 5:
                    continue
                snap = build_intraday_snapshot(
                    instrument_id=ctx.instrument_id,
                    as_of=day,
                    session=ctx.session,
                )
                if snap is None:
                    continue
                payload = snap.to_dict() if hasattr(snap, "to_dict") else dict(snap)
                coverage = str(payload.get("coverage_status") or "").upper()
                if coverage == "READY":
                    return payload
                if (
                    partial is None
                    and coverage == "PARTIAL"
                    and int(payload.get("bars_used") or 0) >= 9
                ):
                    partial = payload
            if partial is not None:
                return partial

        return IntradayFeatureSnapshotV1(
            instrument_id=ctx.instrument_id,
            as_of=ctx.as_of,
            coverage_status="UNKNOWN",
            limitations=(NOT_WIRED_REASON,),
        ).to_dict()

    def _default_events(self, ctx: SnapshotBuildContext) -> tuple[dict[str, Any], ...]:
        """Accepted intelligence events first, then source docs with no extracted event.

        IntelligenceEvent rows are the accepted facts already projected onto the
        instrument. Direction is copied as stored: UNKNOWN and ABSTAIN stay
        distinct and are never rewritten to NEUTRAL. A source document with no
        visible extracted event is unscored news evidence, not a neutral vote.
        """
        if ctx.session is None:
            return ()
        try:
            from app.modules.intelligence.news.models import (
                IntelligenceEvent,
                IntelligenceSourceDocument,
            )
        except ImportError:
            return ()
        from sqlalchemy import select

        cutoff = _as_of_cutoff(ctx.as_of)
        event_rows = list(
            ctx.session.scalars(
                select(IntelligenceEvent)
                .where(
                    IntelligenceEvent.instrument_id == ctx.instrument_id,
                    IntelligenceEvent.known_at <= cutoff,
                )
                .order_by(IntelligenceEvent.known_at.desc(), IntelligenceEvent.id.desc())
                .limit(_EVENT_FETCH_LIMIT)
            ).all()
        )
        document_rows = list(
            ctx.session.scalars(
                select(IntelligenceSourceDocument)
                .where(
                    IntelligenceSourceDocument.instrument_id == ctx.instrument_id,
                    IntelligenceSourceDocument.known_at <= cutoff,
                )
                .order_by(
                    IntelligenceSourceDocument.known_at.desc(),
                    IntelligenceSourceDocument.id.desc(),
                )
                .limit(_EVENT_FETCH_LIMIT)
            ).all()
        )
        docs_by_id: dict[int, Any] = {}
        for row in document_rows:
            if not _visible_row(row, cutoff):
                continue
            docs_by_id[int(row.id)] = row

        visible_events = [
            row
            for row in event_rows
            if _visible_row(row, cutoff) and _same_instrument(row, ctx.instrument_id)
        ]
        visible_events.sort(key=_recency_key, reverse=True)
        visible_events = visible_events[:_EXTRACTED_EVENT_LIMIT]

        missing_doc_ids = [
            int(row.source_document_id)
            for row in visible_events
            if row.source_document_id is not None
            and int(row.source_document_id) not in docs_by_id
        ]
        if missing_doc_ids:
            extra_docs = ctx.session.scalars(
                select(IntelligenceSourceDocument).where(
                    IntelligenceSourceDocument.id.in_(missing_doc_ids),
                    IntelligenceSourceDocument.known_at <= cutoff,
                )
            ).all()
            for row in extra_docs:
                if _visible_row(row, cutoff):
                    docs_by_id[int(row.id)] = row

        used_doc_ids: set[int] = set()
        extracted: list[dict[str, Any]] = []
        for row in visible_events:
            source_id = int(row.source_document_id) if row.source_document_id is not None else None
            document = docs_by_id.get(source_id) if source_id is not None else None
            if source_id is not None:
                used_doc_ids.add(source_id)
            extracted.append(_extracted_event_payload(row, document))

        unscored_docs = [
            row
            for row in document_rows
            if _visible_row(row, cutoff)
            and _same_instrument(row, ctx.instrument_id)
            and int(row.id) not in used_doc_ids
        ]
        unscored_docs.sort(key=_recency_key, reverse=True)
        unscored = [_unscored_news_payload(row) for row in unscored_docs[:_UNSCORED_NEWS_LIMIT]]
        return tuple(extracted + unscored)

    def _default_knowledge(
        self,
        ctx: SnapshotBuildContext,
        signals: tuple[SignalOutputV1, ...],
    ) -> tuple[dict[str, Any], ...]:
        try:
            from app.modules.intelligence.knowledge.evaluator import (
                OBS_UNKNOWN_COERCED_TO_NEUTRAL,
                RuleEvaluationContext,
            )
            from app.modules.intelligence.knowledge.service import KnowledgeEngine
        except ImportError:
            return ()
        engine = KnowledgeEngine()
        try:
            engine.ingest_default_packs()
        except Exception:  # noqa: BLE001
            return ()
        by_sem = {s.semantic: s for s in signals}
        tech = by_sem.get("TECHNICAL")
        obs: dict[str, Any] = {
            OBS_UNKNOWN_COERCED_TO_NEUTRAL: False,
            "issuer_kind": "UNKNOWN",
        }
        if tech is not None:
            obs["price_move_directional"] = tech.state in {"POSITIVE", "NEGATIVE"}
            obs["volume_confirms"] = "volume_confirmation_unavailable" not in tech.limitations
            obs["weak_technical_positive"] = tech.state == "POSITIVE" and (tech.score or 0) < 0.45
        ctx_eval = RuleEvaluationContext(
            instrument_id=ctx.instrument_id,
            as_of=ctx.as_of.isoformat(),
            observations=obs,
            available_evidence=frozenset({"signals"}),
            active_applicability=frozenset({"TECHNICAL", "FUNDAMENTAL", "EVENT", "RISK", "BANK"}),
        )
        evals = engine.evaluate(ctx_eval)
        return tuple(e.to_dict() for e in evals)

    def _coverage(
        self,
        *,
        signals: tuple[SignalOutputV1, ...],
        committee: CommitteeDecisionV1,
        risk: RiskAssessmentV1,
        fundamentals: dict[str, Any],
        macro: dict[str, Any],
        events: tuple[dict[str, Any], ...],
        knowledge: tuple[dict[str, Any], ...],
        intraday: dict[str, Any],
    ) -> tuple[CoverageItem, ...]:
        by_semantic = {s.semantic: s for s in signals}

        def signal_coverage(domain: str, semantic: str) -> CoverageItem:
            sig = by_semantic.get(semantic)
            if sig is None:
                return CoverageItem(domain=domain, status="NOT_READY", detail="no_signal")
            if sig.state == "UNKNOWN":
                return CoverageItem(domain=domain, status="UNKNOWN", detail=sig.abstain_reason)
            if sig.state == "ABSTAIN":
                return CoverageItem(domain=domain, status="PARTIAL", detail=sig.abstain_reason)
            return CoverageItem(domain=domain, status="READY", detail=sig.state)

        items: list[CoverageItem] = [
            signal_coverage("technical", "TECHNICAL"),
            CoverageItem(
                domain="fundamentals",
                status=_status_from_payload(fundamentals.get("status")),
                detail=fundamentals.get("provider"),
            ),
            signal_coverage("events", "EVENT")
            if not events
            else CoverageItem(domain="events", status="PARTIAL", detail=f"events={len(events)}"),
            CoverageItem(
                domain="intraday",
                status=_status_from_payload(intraday.get("coverage_status") or intraday.get("status")),
                detail=intraday.get("interval"),
            ),
            CoverageItem(
                domain="macro",
                status=_status_from_payload(macro.get("status")),
                detail=",".join(macro.get("sources") or []) or None,
            ),
            signal_coverage("news", "NEWS"),
            CoverageItem(
                domain="knowledge",
                status="UNKNOWN" if not knowledge else "PARTIAL",
                detail=None if not knowledge else f"rules={len(knowledge)}",
            ),
            CoverageItem(
                domain="committee",
                status="PARTIAL" if committee.advisory_state != "ABSTAIN" else "UNKNOWN",
                detail=committee.advisory_state,
            ),
            CoverageItem(
                domain="risk",
                status="UNKNOWN" if risk.risk_state == "UNKNOWN" else "PARTIAL",
                detail=risk.risk_state,
            ),
        ]
        # Preserve declared domain order for UI stability.
        order = {name: idx for idx, name in enumerate(COVERAGE_DOMAINS)}
        items.sort(key=lambda c: order.get(c.domain, 99))
        return tuple(items)


def _as_of_cutoff(as_of: date) -> datetime:
    """Inclusive end of the UTC calendar day. Later known_at values stay unseen."""
    return datetime(as_of.year, as_of.month, as_of.day, 23, 59, 59, 999999, tzinfo=UTC)


def _coerce_aware(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    return None


def _iso_stamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


def _stored_direction(raw: Any) -> str | None:
    """Copy a stored direction. Missing is not NEUTRAL; UNKNOWN and ABSTAIN stay."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return text.upper()


def _row_known_at(row: Any) -> datetime | None:
    return _coerce_aware(getattr(row, "known_at", None))


def _visible_row(row: Any, cutoff: datetime) -> bool:
    known = _row_known_at(row)
    return known is not None and known <= cutoff


def _same_instrument(row: Any, instrument_id: int) -> bool:
    raw = getattr(row, "instrument_id", None)
    if raw is None:
        return False
    try:
        return int(raw) == int(instrument_id)
    except (TypeError, ValueError):
        return False


def _recency_key(row: Any) -> tuple[float, int]:
    known = _row_known_at(row)
    stamp = known.timestamp() if known is not None else float("-inf")
    try:
        ident = int(getattr(row, "id", 0) or 0)
    except (TypeError, ValueError):
        ident = 0
    return (stamp, ident)


def _extracted_event_payload(row: Any, document: Any | None) -> dict[str, Any]:
    title = getattr(row, "title", None) or (getattr(document, "title", None) if document else None)
    source_id = getattr(row, "source_document_id", None)
    return {
        "id": getattr(row, "id", None),
        "evidence_role": "extracted_event",
        "event_type": getattr(row, "event_type", None),
        "materiality": getattr(row, "materiality", None),
        "direction": _stored_direction(getattr(row, "direction", None)),
        "published_at": _iso_stamp(getattr(row, "published_at", None)),
        "known_at": _iso_stamp(getattr(row, "known_at", None)),
        "observed_at": _iso_stamp(getattr(row, "observed_at", None)),
        "provider": getattr(document, "provider", None) if document is not None else None,
        "title": title,
        "canonical_url": getattr(document, "canonical_url", None) if document is not None else None,
        "source_document_id": int(source_id) if source_id is not None else None,
        "mapping_basis": getattr(document, "mapping_basis", None) if document is not None else None,
    }


def _unscored_news_payload(row: Any) -> dict[str, Any]:
    return {
        "id": getattr(row, "id", None),
        "evidence_role": "unscored_news",
        "event_type": None,
        "materiality": None,
        "direction": None,
        "published_at": _iso_stamp(getattr(row, "published_at", None)),
        "known_at": _iso_stamp(getattr(row, "known_at", None)),
        "observed_at": _iso_stamp(getattr(row, "observed_at", None)),
        "provider": getattr(row, "provider", None),
        "title": getattr(row, "title", None),
        "canonical_url": getattr(row, "canonical_url", None),
        "source_document_id": int(row.id) if getattr(row, "id", None) is not None else None,
        "mapping_basis": getattr(row, "mapping_basis", None),
        "historical_eligible": False,
    }


def _status_from_payload(raw: Any) -> str:
    if raw is None:
        return "UNKNOWN"
    text = str(raw).upper()
    if text in {"READY", "PARTIAL", "NOT_READY", "UNKNOWN", "NOT_AVAILABLE"}:
        if text == "NOT_AVAILABLE":
            return "NOT_READY"
        return text
    return "UNKNOWN"


def build_intelligence_snapshot(
    *,
    instrument: InstrumentIdentity | None,
    instrument_id: int,
    as_of: date | None = None,
    **kwargs: Any,
) -> IntelligenceSnapshotV1:
    return IntelligenceSnapshotBuilder().build(
        instrument=instrument,
        instrument_id=instrument_id,
        as_of=as_of,
        **kwargs,
    )
