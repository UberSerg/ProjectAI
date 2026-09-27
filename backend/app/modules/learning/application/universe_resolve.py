"""Resolve dataset build universe from DatasetSpec.universe_policy.

V1/V2: current_active_instruments (unchanged survivorship-biased cohort).
V3: historical_equity_universe_v2 with date-dependent eligibility.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Instrument
from app.modules.learning.dataset_config import (
    UNIVERSE_POLICY_CURRENT_ACTIVE,
    UNIVERSE_POLICY_HISTORICAL_V2,
)
from app.modules.market.application.historical_universe import (
    HISTORICAL_EQUITY_UNIVERSE_V2,
    QUALITY_FIRST_CANDLE,
    QUALITY_INSTRUMENT_ACTIVE_TO,
    QUALITY_LAST_CANDLE,
    QUALITY_MOEX_HISTORY_FROM,
    QUALITY_MOEX_LISTED_FROM,
    QUALITY_MOEX_LISTED_TILL,
    QUALITY_UNKNOWN,
    HistoricalEligibility,
    build_historical_equity_universe,
)

_AUTHORITATIVE_FROM = frozenset({QUALITY_MOEX_LISTED_FROM, QUALITY_MOEX_HISTORY_FROM})
_AUTHORITATIVE_TO = frozenset({QUALITY_MOEX_LISTED_TILL, QUALITY_INSTRUMENT_ACTIVE_TO})
_PROXY_BOUNDARIES = frozenset({QUALITY_FIRST_CANDLE, QUALITY_LAST_CANDLE, QUALITY_UNKNOWN})


class HistoricalUniverseResolutionError(RuntimeError):
    """Historical universe failed; Dataset V3 must not fall back to current-active."""


@dataclass(slots=True)
class ResolvedDatasetUniverse:
    policy: str
    instruments: list[Instrument]
    eligibility_by_id: dict[int, HistoricalEligibility] = field(default_factory=dict)
    resolved_universe: dict[str, Any] = field(default_factory=dict)
    apply_date_eligibility: bool = False


def _count_qualities(rows: list[HistoricalEligibility]) -> tuple[dict[str, int], dict[str, int]]:
    from_q: Counter[str] = Counter()
    to_q: Counter[str] = Counter()
    for row in rows:
        from_q[row.eligible_from_quality] += 1
        to_q[row.eligible_to_quality] += 1
    return dict(from_q), dict(to_q)


def _manifest_historical(
    *,
    policy: str,
    version: str,
    rows: list[HistoricalEligibility],
    instruments: list[Instrument],
) -> dict[str, Any]:
    by_id = {i.id: i for i in instruments}
    active_now = sum(1 for i in instruments if i.is_active)
    inactive_now = len(instruments) - active_now
    closed = sum(1 for r in rows if r.eligible_to is not None)
    open_windows = len(rows) - closed
    froms = [r.eligible_from for r in rows]
    from_q, to_q = _count_qualities(rows)
    authoritative = sum(from_q.get(q, 0) for q in _AUTHORITATIVE_FROM) + sum(
        to_q.get(q, 0) for q in _AUTHORITATIVE_TO
    )
    proxy = sum(from_q.get(q, 0) + to_q.get(q, 0) for q in _PROXY_BOUNDARIES)
    # V2 HU completeness is still PARTIAL (delisted market coverage incomplete).
    universe_quality = "PARTIAL"
    return {
        "policy": policy,
        "version": version,
        "candidate_instruments_total": len(rows),
        "historically_eligible_instruments": len(rows),
        "instruments_loaded": len(instruments),
        "instrument_ids": [i.id for i in instruments],
        "symbols": [i.symbol for i in instruments],
        "active_now": active_now,
        "inactive_now": inactive_now,
        "closed_windows": closed,
        "open_windows": open_windows,
        "earliest_eligible_from": min(froms).isoformat() if froms else None,
        "latest_eligible_from": max(froms).isoformat() if froms else None,
        "eligible_from_quality_counts": from_q,
        "eligible_to_quality_counts": to_q,
        "authoritative_boundaries": authoritative,
        "proxy_boundaries": proxy,
        "universe_quality": universe_quality,
        "survivorship_status": (
            "survivorship bias reduced where historical eligibility evidence exists"
        ),
        "members": [
            {
                "instrument_id": r.instrument_id,
                "symbol": None if by_id.get(r.instrument_id) is None else by_id[r.instrument_id].symbol,
                "is_active": None
                if by_id.get(r.instrument_id) is None
                else bool(by_id[r.instrument_id].is_active),
                "eligible_from": r.eligible_from.isoformat(),
                "eligible_to": None if r.eligible_to is None else r.eligible_to.isoformat(),
                "eligible_from_quality": r.eligible_from_quality,
                "eligible_to_quality": r.eligible_to_quality,
            }
            for r in rows
        ],
        "notes": [
            "Eligibility is listing/tradability evidence, not feature-row availability.",
            "instrument_ids filter candidates but do not bypass date eligibility.",
            "No silent fallback to current_active_instruments.",
        ],
        "fundamentals_in_features": False,
        "dividend_adjusted": False,
        "total_return": False,
    }


def resolve_dataset_universe(
    session: Session,
    *,
    universe_policy: str,
    instrument_ids: list[int] | None = None,
    parameters: dict[str, Any] | None = None,
) -> ResolvedDatasetUniverse:
    """Resolve instruments + optional HistoricalEligibility index for a DatasetSpec."""
    params = parameters or {}
    policy = (universe_policy or UNIVERSE_POLICY_CURRENT_ACTIVE).strip()

    if policy == UNIVERSE_POLICY_CURRENT_ACTIVE:
        q = select(Instrument).where(Instrument.is_active.is_(True)).order_by(Instrument.id)
        if instrument_ids:
            q = q.where(Instrument.id.in_(instrument_ids))
        instruments = list(session.scalars(q))
        return ResolvedDatasetUniverse(
            policy=policy,
            instruments=instruments,
            eligibility_by_id={},
            apply_date_eligibility=False,
            resolved_universe={
                "policy": policy,
                "instrument_ids": [i.id for i in instruments],
                "symbols": [i.symbol for i in instruments],
                "candidate_instruments_total": len(instruments),
                "active_now": len(instruments),
                "inactive_now": 0,
                "note": (
                    "current_active_instruments may contain survivorship bias; "
                    "use pit_daily_core v3 / historical_equity_universe_v2 for "
                    "survivorship-aware builds"
                ),
            },
        )

    if policy in {UNIVERSE_POLICY_HISTORICAL_V2, HISTORICAL_EQUITY_UNIVERSE_V2}:
        version = str(params.get("historical_universe_version") or HISTORICAL_EQUITY_UNIVERSE_V2)
        use_research_cohort = bool(params.get("use_research_cohort", False))
        try:
            rows = build_historical_equity_universe(
                session,
                version=version,
                instrument_ids=instrument_ids,
                use_research_cohort=use_research_cohort,
            )
        except Exception as exc:  # noqa: BLE001
            raise HistoricalUniverseResolutionError(
                f"Failed to build {version}: {exc}"
            ) from exc

        if not rows:
            raise HistoricalUniverseResolutionError(
                f"{version} produced zero eligible instruments "
                "(no silent fallback to current_active_instruments)"
            )

        eligibility_by_id = {r.instrument_id: r for r in rows}
        ids = sorted(eligibility_by_id)
        instruments = list(
            session.scalars(select(Instrument).where(Instrument.id.in_(ids)).order_by(Instrument.id))
        )
        if not instruments:
            raise HistoricalUniverseResolutionError(
                f"{version} returned eligibility rows but no Instrument ORM rows loaded"
            )

        return ResolvedDatasetUniverse(
            policy=policy,
            instruments=instruments,
            eligibility_by_id=eligibility_by_id,
            apply_date_eligibility=True,
            resolved_universe=_manifest_historical(
                policy=policy,
                version=version,
                rows=rows,
                instruments=instruments,
            ),
        )

    raise ValueError(f"Unsupported universe_policy: {policy}")


def eligibility_audit(
    eligibility: HistoricalEligibility | None,
    *,
    as_of: date,
    policy: str,
    version: str,
) -> dict[str, Any]:
    """Audit metadata for sample lineage (not model features)."""
    if eligibility is None:
        return {
            "universe_policy": policy,
            "universe_version": version,
        }
    return {
        "universe_policy": policy,
        "universe_version": version,
        "eligible_from": eligibility.eligible_from.isoformat(),
        "eligible_to": None if eligibility.eligible_to is None else eligibility.eligible_to.isoformat(),
        "eligible_from_quality": eligibility.eligible_from_quality,
        "eligible_to_quality": eligibility.eligible_to_quality,
        "historically_eligible_on_as_of": eligibility.includes(as_of),
    }
