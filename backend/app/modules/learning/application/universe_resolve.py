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
    HISTORICAL_EQUITY_UNIVERSE_V1,
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
_PROXY_FROM = frozenset({QUALITY_FIRST_CANDLE})
_PROXY_TO = frozenset({QUALITY_LAST_CANDLE})
_PROXY_BOUNDARIES = frozenset({QUALITY_FIRST_CANDLE, QUALITY_LAST_CANDLE, QUALITY_UNKNOWN})

_INACTIVE_EXAMPLES_LIMIT = 15


class HistoricalUniverseResolutionError(RuntimeError):
    """Historical universe failed; Dataset V3 must not fall back to current-active."""


@dataclass(slots=True)
class ResolvedDatasetUniverse:
    policy: str
    instruments: list[Instrument]
    eligibility_by_id: dict[int, HistoricalEligibility] = field(default_factory=dict)
    resolved_universe: dict[str, Any] = field(default_factory=dict)
    apply_date_eligibility: bool = False


def _pct(numerator: int, denominator: int) -> float | None:
    """Percentage or None when denominator is unknown/empty (never zero-fill as 0.0/100.0)."""
    if denominator <= 0:
        return None
    return round(100.0 * numerator / denominator, 2)


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
    tos = [r.eligible_to for r in rows if r.eligible_to is not None]
    from_q, to_q = _count_qualities(rows)

    authoritative_from = sum(from_q.get(q, 0) for q in _AUTHORITATIVE_FROM)
    authoritative_to = sum(to_q.get(q, 0) for q in _AUTHORITATIVE_TO)
    proxy_from = sum(from_q.get(q, 0) for q in _PROXY_FROM)
    proxy_to = sum(to_q.get(q, 0) for q in _PROXY_TO)
    unknown_to = int(to_q.get(QUALITY_UNKNOWN, 0))
    authoritative = authoritative_from + authoritative_to
    proxy = sum(from_q.get(q, 0) + to_q.get(q, 0) for q in _PROXY_BOUNDARIES)
    n_members = len(rows)
    n_from = n_members
    n_to = n_members

    inactive_examples: list[dict[str, Any]] = []
    for r in rows:
        inst = by_id.get(r.instrument_id)
        if inst is None or inst.is_active:
            continue
        inactive_examples.append(
            {
                "instrument_id": r.instrument_id,
                "symbol": inst.symbol,
                "eligible_from": r.eligible_from.isoformat(),
                "eligible_to": None if r.eligible_to is None else r.eligible_to.isoformat(),
                "eligible_from_quality": r.eligible_from_quality,
                "eligible_to_quality": r.eligible_to_quality,
            }
        )
        if len(inactive_examples) >= _INACTIVE_EXAMPLES_LIMIT:
            break

    # V2 HU completeness is still PARTIAL (delisted market coverage incomplete).
    universe_quality = "PARTIAL"
    return {
        "policy": policy,
        "version": version,
        "members": n_members,
        "candidate_instruments_total": n_members,
        "historically_eligible_instruments": n_members,
        "instruments_loaded": len(instruments),
        "instrument_ids": [i.id for i in instruments],
        "symbols": [i.symbol for i in instruments],
        "active_now": active_now,
        "inactive_now": inactive_now,
        "active_now_pct": _pct(active_now, len(instruments)),
        "inactive_now_pct": _pct(inactive_now, len(instruments)),
        "closed_windows": closed,
        "open_windows": open_windows,
        "earliest_eligible_from": min(froms).isoformat() if froms else None,
        "latest_eligible_from": max(froms).isoformat() if froms else None,
        "earliest_eligible_to": min(tos).isoformat() if tos else None,
        "latest_eligible_to": max(tos).isoformat() if tos else None,
        "eligible_from_quality_counts": from_q,
        "eligible_to_quality_counts": to_q,
        "authoritative_from": authoritative_from,
        "authoritative_to": authoritative_to,
        "proxy_from": proxy_from,
        "proxy_to": proxy_to,
        "unknown_to": unknown_to,
        "authoritative_boundaries": authoritative,
        "proxy_boundaries": proxy,
        "authoritative_from_pct": _pct(authoritative_from, n_from),
        "authoritative_to_pct": _pct(authoritative_to, n_to),
        "proxy_from_pct": _pct(proxy_from, n_from),
        "proxy_to_pct": _pct(proxy_to, n_to),
        "unknown_to_pct": _pct(unknown_to, n_to),
        "inactive_examples": inactive_examples,
        "universe_quality": universe_quality,
        "survivorship_status": (
            "survivorship bias reduced where historical eligibility evidence exists"
        ),
        # Full member rows (audit); `members` above is the count.
        "member_rows": [
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
    raw_policy = (universe_policy or "").strip()
    # Explicit historical version in parameters must not silently become current-active
    # when the policy string is blank/missing.
    if not raw_policy and params.get("historical_universe_version"):
        policy = UNIVERSE_POLICY_HISTORICAL_V2
    elif not raw_policy:
        policy = UNIVERSE_POLICY_CURRENT_ACTIVE
    else:
        policy = raw_policy

    if policy == UNIVERSE_POLICY_CURRENT_ACTIVE:
        # Guard: V3 parameters must never resolve via current-active.
        if params.get("historical_universe_version") or params.get("require_historical_universe"):
            raise HistoricalUniverseResolutionError(
                "historical universe requested via parameters but universe_policy is "
                f"{UNIVERSE_POLICY_CURRENT_ACTIVE}; refusing silent V3→current_active fallback"
            )
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
                "members": len(instruments),
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
        if version not in {HISTORICAL_EQUITY_UNIVERSE_V1, HISTORICAL_EQUITY_UNIVERSE_V2}:
            raise HistoricalUniverseResolutionError(
                f"Unsupported historical_universe_version for V3-style policy: {version!r} "
                "(no silent fallback to current_active_instruments)"
            )
        use_research_cohort = bool(params.get("use_research_cohort", False))
        try:
            rows = build_historical_equity_universe(
                session,
                version=version,
                instrument_ids=instrument_ids,
                use_research_cohort=use_research_cohort,
            )
        except HistoricalUniverseResolutionError:
            raise
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

    raise HistoricalUniverseResolutionError(
        f"Unsupported universe_policy: {policy!r} "
        "(no silent fallback to current_active_instruments)"
    )


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
