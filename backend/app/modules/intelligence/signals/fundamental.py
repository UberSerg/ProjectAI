"""FundamentalModelV1 — industrial FundamentalSnapshotV1 → SignalOutputV1.

Banks / FI must ABSTAIN (industrial RAS ratios unsupported). Missing ≠ zero.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from app.modules.intelligence.contracts.provenance import EvidenceRef
from app.modules.intelligence.contracts.signal import SignalOutputV1, abstain_signal, unknown_signal
from app.modules.intelligence.signals.base import (
    clip,
    optional_float,
    parse_as_of,
    parse_known_at,
    pit_allows,
    score_to_state,
    weighted_mean,
)

MODEL_ID = "FundamentalModelV1"
MODEL_VERSION = "1"
SEMANTIC = "FUNDAMENTAL"
HORIZON = "reporting_cycle"

_BANK_KINDS = frozenset({"BANK_FI", "BANK", "FI"})
_READY_STATUSES = frozenset({"READY", "PARTIAL"})

# Soft thresholds for defensible industrial ratios (not valuation astrology).
_ROE_SCALE = 0.20
_ROA_SCALE = 0.10
_GROWTH_SCALE = 0.20
_DE_SCALE = 1.5  # debt_to_equity; higher → adverse
_FRESHNESS_GOOD_DAYS = 180
_FRESHNESS_STALE_DAYS = 540


def _metrics_map(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    raw = snapshot.get("metrics")
    return dict(raw) if isinstance(raw, Mapping) else {}


def _profitability(metrics: Mapping[str, Any]) -> float | None:
    roe = optional_float(metrics.get("roe") or metrics.get("ROE"))
    roa = optional_float(metrics.get("roa") or metrics.get("ROA"))
    net = optional_float(metrics.get("NET_INCOME") or metrics.get("net_income"))
    parts: list[tuple[float, float]] = []
    if roe is not None:
        parts.append((0.6, clip(roe / _ROE_SCALE)))
    if roa is not None:
        parts.append((0.4, clip(roa / _ROA_SCALE)))
    if parts:
        return weighted_mean(parts)
    if net is not None:
        # Sign-only when ratios absent — never invent magnitude from missing equity.
        if net > 0:
            return 0.25
        if net < 0:
            return -0.35
        return 0.0
    return None


def _growth(metrics: Mapping[str, Any]) -> float | None:
    for key in ("revenue_yoy", "REVENUE_YOY", "net_income_yoy", "NET_INCOME_YOY", "growth"):
        val = optional_float(metrics.get(key))
        if val is not None:
            return clip(val / _GROWTH_SCALE)
    return None


def _balance_sheet(metrics: Mapping[str, Any]) -> float | None:
    de = optional_float(metrics.get("debt_to_equity") or metrics.get("DEBT_TO_EQUITY"))
    if de is None:
        return None
    # Low leverage supportive; high leverage adverse. Missing stays None (not zero).
    return clip(1.0 - (de / _DE_SCALE))


def _cash_flow(metrics: Mapping[str, Any]) -> float | None:
    fcf = optional_float(metrics.get("fcf") or metrics.get("FCF") or metrics.get("operating_cash_flow"))
    fcf_status = metrics.get("fcf_status")
    if fcf_status in {"NOT_DERIVED", "NOT_DERIVED_AMBIGUOUS"} and fcf is None:
        return None
    if fcf is None:
        return None
    # Sign-based only without a defensible scale.
    if fcf > 0:
        return 0.3
    if fcf < 0:
        return -0.3
    return 0.0


def _valuation(metrics: Mapping[str, Any]) -> float | None:
    """Only when honest valuation inputs exist; never invent multiples."""
    pe = optional_float(metrics.get("pe") or metrics.get("PE") or metrics.get("pe_ttm"))
    if pe is None or pe <= 0:
        return None
    # Extremely high PE → mild adverse; moderate PE → near neutral. Not a fair-value claim.
    return clip(1.0 - (pe / 25.0))


def _freshness_factor(snapshot: Mapping[str, Any], as_of: date) -> float | None:
    period_end = parse_as_of(snapshot.get("period_end"))
    known_at = parse_known_at(snapshot.get("known_at"))
    anchor = period_end or (known_at.date() if isinstance(known_at, datetime) else known_at)
    if anchor is None:
        return None
    age = (as_of - anchor).days
    if age <= _FRESHNESS_GOOD_DAYS:
        return 0.4
    if age <= _FRESHNESS_STALE_DAYS:
        return 0.0
    return -0.4


def _deterioration(metrics: Mapping[str, Any]) -> float | None:
    trend = metrics.get("trend") or metrics.get("deterioration")
    if isinstance(trend, str):
        mapping = {
            "IMPROVING": 0.4,
            "STABLE": 0.0,
            "DETERIORATING": -0.5,
            "UNKNOWN": None,
        }
        return mapping.get(trend.upper())
    return optional_float(trend)


class FundamentalModelV1:
    model_id = MODEL_ID
    model_version = MODEL_VERSION
    semantic = SEMANTIC

    def evaluate(
        self,
        *,
        instrument_id: int,
        as_of: date | datetime | str,
        snapshot: Mapping[str, Any] | None,
    ) -> SignalOutputV1:
        as_of_d = parse_as_of(as_of)
        if as_of_d is None:
            return abstain_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=date.today(),
                reason="missing_as_of",
                horizon=HORIZON,
            )

        if snapshot is None:
            return unknown_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=as_of_d,
                reason="missing_fundamental_snapshot",
                horizon=HORIZON,
            )

        issuer_kind = str(snapshot.get("issuer_kind") or "UNKNOWN").upper()
        if issuer_kind in _BANK_KINDS:
            return abstain_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=as_of_d,
                reason="bank_industrial_metrics_unsupported",
                horizon=HORIZON,
                limitations=("use_bank_specific_model_or_abstain",),
            )

        status = str(snapshot.get("status") or "UNKNOWN").upper()
        if status in {"NOT_AVAILABLE", "UNKNOWN"}:
            return unknown_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=as_of_d,
                reason=f"fundamental_status_{status.lower()}",
                horizon=HORIZON,
            )

        known_at = parse_known_at(snapshot.get("known_at"))
        if known_at is not None and not pit_allows(as_of_d, known_at):
            return abstain_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=as_of_d,
                reason="fundamental_known_at_after_as_of",
                horizon=HORIZON,
            )

        if status not in _READY_STATUSES:
            return unknown_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=as_of_d,
                reason=f"fundamental_status_{status.lower()}",
                horizon=HORIZON,
            )

        metrics = _metrics_map(snapshot)
        dims: dict[str, float | None] = {
            "profitability": _profitability(metrics),
            "growth": _growth(metrics),
            "balance_sheet": _balance_sheet(metrics),
            "cash_flow": _cash_flow(metrics),
            "valuation": _valuation(metrics),
            "freshness": _freshness_factor(snapshot, as_of_d),
            "trend": _deterioration(metrics),
        }
        weights = {
            "profitability": 0.30,
            "growth": 0.20,
            "balance_sheet": 0.20,
            "cash_flow": 0.10,
            "valuation": 0.05,
            "freshness": 0.05,
            "trend": 0.10,
        }
        available = {k: v for k, v in dims.items() if v is not None}
        if "profitability" not in available and "growth" not in available and "balance_sheet" not in available:
            return unknown_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=as_of_d,
                reason="insufficient_fundamental_dimensions",
                horizon=HORIZON,
            )

        score = weighted_mean([(weights[k], available[k]) for k in available])
        assert score is not None
        score = clip(score)
        coverage = len(available) / len(weights)
        confidence = clip(coverage * (0.45 + 0.55 * abs(score)), 0.0, 1.0)

        missing = snapshot.get("missing_metrics") or ()
        limitations = list(snapshot.get("limitations") or ())
        if "valuation" not in available:
            limitations.append("valuation_inputs_absent")
        if "cash_flow" not in available:
            limitations.append("cash_flow_not_derived")
        if missing:
            limitations.append("partial_metrics")

        snap_instrument = int(snapshot.get("instrument_id") or instrument_id)
        return SignalOutputV1(
            model_id=MODEL_ID,
            model_version=MODEL_VERSION,
            semantic=SEMANTIC,
            instrument_id=snap_instrument,
            as_of=as_of_d,
            known_at=known_at,
            horizon=HORIZON,
            state=score_to_state(score),
            score=score,
            confidence=confidence,
            confidence_semantic="EVIDENCE_COMPLETENESS",
            evidence_refs=(
                EvidenceRef(
                    source_type="fundamental_snapshot",
                    provider=str(snapshot.get("provider") or "fundamentals"),
                    known_at=known_at,
                    note="FundamentalSnapshotV1",
                ),
            ),
            data_freshness=str(status),
            limitations=tuple(dict.fromkeys(limitations)),
            model_metadata={
                "dimensions": dims,
                "issuer_kind": issuer_kind,
                "status": status,
                "candidate_promotion": False,
            },
        )
