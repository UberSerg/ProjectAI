"""Collect independent SignalOutputV1 adapters for one instrument.

Does not combine models. Missing session → None (builder emits UNKNOWN stubs).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.intelligence.contracts.provenance import EvidenceRef
from app.modules.intelligence.contracts.signal import SignalOutputV1, unknown_signal
from app.modules.intelligence.signals.base import optional_float
from app.modules.intelligence.signals.event import EventModelV1
from app.modules.intelligence.signals.fundamental import FundamentalModelV1
from app.modules.intelligence.signals.intraday import IntradayStructureModelV1
from app.modules.intelligence.signals.macro import MacroModelV1
from app.modules.intelligence.signals.technical import TechnicalModelV1


def _f(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:
        return None
    return out


def _load_technical_features(session: Session, instrument_id: int, as_of: date) -> dict[str, Any] | None:
    from app.infrastructure.analytics.models import InstrumentFeatureDaily
    from app.infrastructure.technical.models import InstrumentTechnicalFeatureDaily

    basic = session.scalar(
        select(InstrumentFeatureDaily)
        .where(
            InstrumentFeatureDaily.instrument_id == instrument_id,
            InstrumentFeatureDaily.date <= as_of,
            InstrumentFeatureDaily.timeframe == "1d",
        )
        .order_by(InstrumentFeatureDaily.date.desc(), InstrumentFeatureDaily.id.desc())
        .limit(1)
    )
    tech = session.scalar(
        select(InstrumentTechnicalFeatureDaily)
        .where(
            InstrumentTechnicalFeatureDaily.instrument_id == instrument_id,
            InstrumentTechnicalFeatureDaily.date <= as_of,
            InstrumentTechnicalFeatureDaily.timeframe == "1d",
        )
        .order_by(
            InstrumentTechnicalFeatureDaily.date.desc(),
            InstrumentTechnicalFeatureDaily.id.desc(),
        )
        .limit(1)
    )
    if basic is None and tech is None:
        return None
    features: dict[str, Any] = {}
    quality: dict[str, Any] = {}
    is_valid = True
    if basic is not None:
        features.update(
            {
                "return_5d": _f(basic.return_5d),
                "return_20d": _f(basic.return_20d),
                "volatility_20d": _f(basic.volatility_20d),
                "drawdown_20d": _f(basic.drawdown_20d),
                "volume_zscore_20d": _f(basic.volume_zscore_20d),
            }
        )
        quality.update(dict(basic.quality_flags or {}))
        is_valid = is_valid and bool(basic.is_valid)
    if tech is not None:
        features.update(
            {
                "sma20_distance": _f(tech.sma20_distance),
                "ema20_distance": _f(tech.ema20_distance),
                "atr14_pct": _f(tech.atr14_pct),
                "rsi14": _f(tech.rsi14),
            }
        )
        quality.update(dict(tech.quality_flags or {}))
        is_valid = is_valid and bool(tech.is_valid)
    features["_quality_flags"] = quality
    features["_is_valid"] = is_valid
    return features


def _fundamental_payload(session: Session, instrument_id: int, as_of: date) -> dict[str, Any] | None:
    try:
        from app.modules.intelligence.fundamentals import build_fundamental_snapshot
    except ImportError:
        return None
    try:
        snap = build_fundamental_snapshot(session, instrument_id, as_of)
    except TypeError:
        return None
    if snap is None:
        return None
    return snap.to_dict() if hasattr(snap, "to_dict") else dict(snap)


def _intraday_payload(session: Session, instrument_id: int, as_of: date) -> dict[str, Any] | None:
    try:
        from app.modules.intelligence.intraday import build_intraday_snapshot
    except ImportError:
        return None
    from datetime import timedelta

    # Prefer completed READY session on/before as_of (today may be incomplete PARTIAL).
    partial: dict[str, Any] | None = None
    for delta in range(0, 8):
        day = as_of - timedelta(days=delta)
        if day.weekday() >= 5:
            continue
        snap = build_intraday_snapshot(instrument_id=instrument_id, as_of=day, session=session)
        if snap is None:
            continue
        payload = snap.to_dict() if hasattr(snap, "to_dict") else dict(snap)
        coverage = str(payload.get("coverage_status") or "").upper()
        if coverage == "READY":
            return payload
        if partial is None and coverage == "PARTIAL" and int(payload.get("bars_used") or 0) >= 9:
            partial = payload
    return partial


def _macro_payload(session: Session, as_of: date) -> dict[str, Any] | None:
    try:
        from app.modules.intelligence.macro import build_macro_snapshot
    except ImportError:
        return None
    snap = build_macro_snapshot(session, as_of)
    if snap is None:
        return None
    return snap.to_dict() if hasattr(snap, "to_dict") else dict(snap)


def _bank_signal(
    instrument_id: int,
    as_of: date,
    fund: dict[str, Any] | None,
) -> SignalOutputV1:
    """PARTIAL CBR evidence abstains. Silence stays the no-data unknown signal."""
    payload = fund or {}
    kind = str(payload.get("issuer_kind") or "").upper()
    status = str(payload.get("status") or "").upper()
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    if kind == "BANK_FI" and status == "PARTIAL" and metrics:
        known_at = payload.get("known_at")
        parsed_known = None
        if isinstance(known_at, datetime):
            parsed_known = known_at
        elif isinstance(known_at, str):
            parsed_known = datetime.fromisoformat(known_at)
        return SignalOutputV1(
            model_id="BankModelV1",
            model_version="1",
            semantic="BANK_FI",
            instrument_id=instrument_id,
            as_of=as_of,
            known_at=parsed_known,
            horizon="reporting_cycle",
            state="ABSTAIN",
            score=None,
            confidence=None,
            abstain_reason="bank_partial_metrics_insufficient",
            limitations=(
                "partial_cbr_evidence_present",
                "directional_bank_score_not_supported",
            ),
            evidence_refs=(
                EvidenceRef(
                    source_type="bank_fundamental_snapshot",
                    provider=str(payload.get("provider") or "CBR_CREDITORGINFO_SOAP"),
                    known_at=parsed_known,
                    note="partial_cbr_metrics:" + ",".join(sorted(metrics)),
                ),
            ),
            model_metadata={
                "status": status,
                "metric_codes": sorted(metrics),
                "directional_score": False,
            },
        )
    return unknown_signal(
        model_id="BankModelV1",
        model_version="1",
        semantic="BANK_FI",
        instrument_id=instrument_id,
        as_of=as_of,
        reason="bank_universe_metrics_not_available",
        horizon="reporting_cycle",
    )


def collect_instrument_signals(
    *,
    instrument_id: int,
    as_of: date,
    session: Session | None = None,
) -> tuple[SignalOutputV1, ...] | None:
    """Return independent model outputs, or None when no DB session is available."""
    if session is None:
        return None

    tech_feats = _load_technical_features(session, instrument_id, as_of)
    fund = _fundamental_payload(session, instrument_id, as_of)
    intra = _intraday_payload(session, instrument_id, as_of)
    macro = _macro_payload(session, as_of)

    technical = TechnicalModelV1().evaluate(
        instrument_id=instrument_id,
        as_of=as_of,
        features=None if tech_feats is None else {k: v for k, v in tech_feats.items() if not k.startswith("_")},
        quality_flags=None if tech_feats is None else tech_feats.get("_quality_flags"),
        is_valid=None if tech_feats is None else tech_feats.get("_is_valid"),
    )
    fundamental = FundamentalModelV1().evaluate(
        instrument_id=instrument_id,
        as_of=as_of,
        snapshot=fund,
    )
    # Session exists, so the payload is a list. [] abstains with no_valid_events.
    # None is reserved for the no-session return above (events_payload_missing).
    event = EventModelV1().evaluate(
        instrument_id=instrument_id,
        as_of=as_of,
        events=_load_instrument_events(session, instrument_id, as_of),
    )
    intraday = IntradayStructureModelV1().evaluate(
        instrument_id=instrument_id,
        as_of=as_of,
        snapshot=intra,
    )
    if intraday.semantic != "INTRADAY":
        intraday = replace(intraday, semantic="INTRADAY")

    macro_sig = MacroModelV1().evaluate(
        instrument_id=instrument_id,
        as_of=as_of,
        snapshot=macro,
        sector_sensitivity_known=False,
    )
    from app.modules.intelligence.signals.cross_sectional_ml import CrossSectionalMLModelV1

    ml = CrossSectionalMLModelV1().evaluate(
        instrument_id=instrument_id,
        as_of=as_of,
        provenance=None,
    )
    bank = _bank_signal(instrument_id, as_of, fund)
    news = _news_coverage_signal(session, instrument_id, as_of)
    return (technical, fundamental, event, intraday, macro_sig, ml, bank, news)


def _known_at_cutoff(as_of: date) -> datetime:
    """Inclusive end of the UTC calendar day. Later known_at values stay unseen."""
    return datetime(as_of.year, as_of.month, as_of.day, 23, 59, 59, 999999, tzinfo=UTC)


def _load_instrument_events(
    session: Session,
    instrument_id: int,
    as_of: date,
) -> list[dict[str, Any]]:
    """PIT events for EventModel. Empty list means the query ran and found none.

    Direction is copied as stored. UNKNOWN is not rewritten to NEUTRAL.
    ``timestamp_trusted`` is true only when ``known_at`` is present.
    Claim identity is forwarded so the same article at two URLs is one vote.
    """
    from app.modules.intelligence.extraction.deterministic import MATERIALITY_WEIGHT
    from app.modules.intelligence.news.models import IntelligenceEvent

    cutoff = _known_at_cutoff(as_of)
    rows = session.scalars(
        select(IntelligenceEvent)
        .where(
            IntelligenceEvent.instrument_id == instrument_id,
            IntelligenceEvent.known_at <= cutoff,
        )
        .order_by(IntelligenceEvent.known_at.asc(), IntelligenceEvent.id.asc())
    ).all()
    return [_event_payload(row, MATERIALITY_WEIGHT) for row in rows]


def _event_payload(row: Any, materiality_weight: dict[str, float | None]) -> dict[str, Any]:
    payload = dict(row.payload or {})
    if "materiality_weight" in payload:
        materiality = optional_float(payload.get("materiality_weight"))
    else:
        materiality = materiality_weight.get(str(row.materiality or "UNKNOWN").upper())
    known_at = row.known_at
    direction = row.direction
    return {
        "event_id": row.id,
        "event_type": row.event_type,
        "direction": direction,
        "materiality": materiality,
        "known_at": known_at,
        "confidence": optional_float(payload.get("confidence")),
        "source_document_id": row.source_document_id,
        "timestamp_trusted": known_at is not None,
        "provider": "intelligence_events",
        "claim_hash": payload.get("claim_hash") or None,
        "evidence_fragment": payload.get("evidence_fragment") or None,
        "content_hash": payload.get("content_hash") or None,
    }


def _news_coverage_signal(session: Session, instrument_id: int, as_of: date) -> SignalOutputV1:
    """NEWS reports which documents are in coverage. It does not vote a direction.

    EventModel is the only directional consumer of the same extracted events.
    """
    from app.modules.intelligence.news.models import IntelligenceSourceDocument

    cutoff = _known_at_cutoff(as_of)
    documents = list(
        session.scalars(
            select(IntelligenceSourceDocument)
            .where(
                IntelligenceSourceDocument.instrument_id == instrument_id,
                IntelligenceSourceDocument.known_at <= cutoff,
            )
            .order_by(IntelligenceSourceDocument.known_at.asc(), IntelligenceSourceDocument.id.asc())
        ).all()
    )
    limitations = ["news_source_coverage_only", "news_does_not_cast_directional_vote"]
    if documents:
        limitations.append("source_documents_in_coverage")
    evidence = tuple(
        EvidenceRef(
            source_type=document.source_type or "source_document",
            provider=document.provider or "news",
            source_document_id=str(document.id),
            content_hash=document.content_hash,
            known_at=document.known_at,
            note="coverage_only",
        )
        for document in documents[:10]
    )
    return SignalOutputV1(
        model_id="NewsModelV1",
        model_version="1",
        semantic="NEWS",
        instrument_id=instrument_id,
        as_of=as_of,
        known_at=documents[-1].known_at if documents else None,
        horizon="event_window",
        state="UNKNOWN",
        score=None,
        confidence=None,
        evidence_refs=evidence,
        limitations=tuple(limitations),
        abstain_reason="news_source_coverage_only",
        model_metadata={
            "source_document_count": len(documents),
            "directional_vote": False,
        },
    )
