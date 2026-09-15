"""Historical equity universe contracts V1 (candle) + V2 (MOEX board evidence).

V1: eligible_from/to from first/last daily candles (proxy).
V2: prefer MOEX board ``listed_from`` / ``history_from`` stored in
``InstrumentSource.source_metadata``, then candle fallback.

Eligibility (listing/tradability evidence) is distinct from feature-data
availability (whether candles/features exist for as_of).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Candle, Instrument, InstrumentSource, UniverseMembership
from app.modules.market.application.research_universe import RESEARCH_EQUITY_V1

HISTORICAL_EQUITY_UNIVERSE_V1 = "historical_equity_universe_v1"
HISTORICAL_EQUITY_UNIVERSE_V2 = "historical_equity_universe_v2"

QUALITY_FIRST_CANDLE = "DERIVED_FROM_FIRST_CANDLE"
QUALITY_LAST_CANDLE = "DERIVED_FROM_LAST_CANDLE"
QUALITY_MOEX_LISTED_FROM = "MOEX_BOARD_LISTED_FROM"
QUALITY_MOEX_HISTORY_FROM = "MOEX_BOARD_HISTORY_FROM"
QUALITY_MOEX_LISTED_TILL = "MOEX_BOARD_LISTED_TILL"
QUALITY_INSTRUMENT_ACTIVE_TO = "INSTRUMENT_ACTIVE_TO"
QUALITY_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class HistoricalEligibility:
    instrument_id: int
    eligible_from: date
    eligible_to: date | None
    eligible_from_quality: str
    eligible_to_quality: str
    provenance: dict[str, Any] = field(default_factory=dict)

    def includes(self, as_of: date) -> bool:
        if as_of < self.eligible_from:
            return False
        if self.eligible_to is not None and as_of > self.eligible_to:
            return False
        return True


def _as_date(value: date | datetime | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value


def _parse_meta_date(raw: Any) -> date | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _cohort_instrument_ids(
    session: Session,
    *,
    instrument_ids: Iterable[int] | None,
    use_research_cohort: bool,
) -> list[int]:
    if instrument_ids is not None:
        return sorted({int(i) for i in instrument_ids})

    if use_research_cohort:
        research_ids = list(
            session.scalars(
                select(UniverseMembership.instrument_id).where(
                    UniverseMembership.universe_code == RESEARCH_EQUITY_V1
                )
            )
        )
        if research_ids:
            return sorted({int(i) for i in research_ids})

    rows = session.execute(
        select(Instrument.id)
        .join(Candle, Candle.instrument_id == Instrument.id)
        .where(Instrument.asset_class == "equity", Candle.timeframe == "1d")
        .distinct()
    ).scalars()
    return sorted({int(i) for i in rows})


def _board_evidence(session: Session, instrument_ids: Sequence[int]) -> dict[int, dict[str, Any]]:
    """Collect earliest listed_from / history_from and latest listed_till from sources."""
    out: dict[int, dict[str, Any]] = {}
    if not instrument_ids:
        return out
    sources = session.scalars(
        select(InstrumentSource).where(InstrumentSource.instrument_id.in_(list(instrument_ids)))
    )
    for src in sources:
        meta = dict(src.source_metadata or {})
        listed_from = _parse_meta_date(meta.get("listed_from"))
        history_from = _parse_meta_date(meta.get("history_from"))
        listed_till = _parse_meta_date(meta.get("listed_till"))
        bucket = out.setdefault(
            int(src.instrument_id),
            {
                "listed_from": None,
                "history_from": None,
                "listed_till": None,
                "boards": [],
            },
        )
        if listed_from is not None and (
            bucket["listed_from"] is None or listed_from < bucket["listed_from"]
        ):
            bucket["listed_from"] = listed_from
        if history_from is not None and (
            bucket["history_from"] is None or history_from < bucket["history_from"]
        ):
            bucket["history_from"] = history_from
        if listed_till is not None and (
            bucket["listed_till"] is None or listed_till > bucket["listed_till"]
        ):
            bucket["listed_till"] = listed_till
        bucket["boards"].append(
            {
                "source": src.source,
                "board": src.board,
                "external_id": src.external_id,
                "listed_from": None if listed_from is None else listed_from.isoformat(),
                "history_from": None if history_from is None else history_from.isoformat(),
                "listed_till": None if listed_till is None else listed_till.isoformat(),
            }
        )
    return out


def build_historical_equity_universe(
    session: Session,
    *,
    version: str = HISTORICAL_EQUITY_UNIVERSE_V1,
    instrument_ids: Sequence[int] | None = None,
    use_research_cohort: bool = True,
) -> list[HistoricalEligibility]:
    """Build eligibility windows for the research equity cohort (or all candle equities)."""
    if version not in {HISTORICAL_EQUITY_UNIVERSE_V1, HISTORICAL_EQUITY_UNIVERSE_V2}:
        raise ValueError(f"Unsupported historical universe version: {version}")

    ids = _cohort_instrument_ids(
        session,
        instrument_ids=instrument_ids,
        use_research_cohort=use_research_cohort,
    )
    if not ids:
        return []

    instruments = {
        int(row.id): row
        for row in session.scalars(select(Instrument).where(Instrument.id.in_(ids)))
    }
    candle_bounds = {
        int(instrument_id): (_as_date(first), _as_date(last))
        for instrument_id, first, last in session.execute(
            select(
                Candle.instrument_id,
                func.min(Candle.timestamp),
                func.max(Candle.timestamp),
            )
            .where(Candle.instrument_id.in_(ids), Candle.timeframe == "1d")
            .group_by(Candle.instrument_id)
        )
    }
    board = _board_evidence(session, ids) if version == HISTORICAL_EQUITY_UNIVERSE_V2 else {}

    out: list[HistoricalEligibility] = []
    for iid in ids:
        bounds = candle_bounds.get(iid)
        first_candle = None if bounds is None else bounds[0]
        last_candle = None if bounds is None else bounds[1]
        instrument = instruments.get(iid)
        inactive = False
        if instrument is not None:
            inactive = (not bool(instrument.is_active)) or (instrument.active_to is not None)

        evidence = board.get(iid) or {}
        listed_from = evidence.get("listed_from")
        history_from = evidence.get("history_from")
        listed_till = evidence.get("listed_till")

        if version == HISTORICAL_EQUITY_UNIVERSE_V2 and listed_from is not None:
            eligible_from = listed_from
            from_quality = QUALITY_MOEX_LISTED_FROM
            from_basis = "min(InstrumentSource.source_metadata.listed_from)"
        elif version == HISTORICAL_EQUITY_UNIVERSE_V2 and history_from is not None:
            eligible_from = history_from
            from_quality = QUALITY_MOEX_HISTORY_FROM
            from_basis = "min(InstrumentSource.source_metadata.history_from)"
        elif first_candle is not None:
            eligible_from = first_candle
            from_quality = QUALITY_FIRST_CANDLE
            from_basis = "min(market.candles.timestamp) where timeframe=1d"
        else:
            continue

        if version == HISTORICAL_EQUITY_UNIVERSE_V2 and inactive and listed_till is not None:
            eligible_to = listed_till
            to_quality = QUALITY_MOEX_LISTED_TILL
            to_basis = "max(InstrumentSource.source_metadata.listed_till)"
        elif (
            version == HISTORICAL_EQUITY_UNIVERSE_V2
            and inactive
            and instrument is not None
            and instrument.active_to is not None
        ):
            eligible_to = instrument.active_to
            to_quality = QUALITY_INSTRUMENT_ACTIVE_TO
            to_basis = "market.instruments.active_to"
        elif inactive and last_candle is not None:
            eligible_to = last_candle
            to_quality = QUALITY_LAST_CANDLE
            to_basis = "max(market.candles.timestamp) where timeframe=1d"
        else:
            eligible_to = None
            to_quality = QUALITY_UNKNOWN
            to_basis = "open_ended_while_active"

        provenance = {
            "version": version,
            "eligible_from_basis": from_basis,
            "eligible_to_basis": to_basis,
            "instrument_is_active": None if instrument is None else bool(instrument.is_active),
            "instrument_active_to": (
                None
                if instrument is None or instrument.active_to is None
                else instrument.active_to.isoformat()
            ),
            "first_candle": None if first_candle is None else first_candle.isoformat(),
            "last_candle": None if last_candle is None else last_candle.isoformat(),
            "moex_listed_from": None if listed_from is None else listed_from.isoformat(),
            "moex_history_from": None if history_from is None else history_from.isoformat(),
            "moex_listed_till": None if listed_till is None else listed_till.isoformat(),
            "note": (
                "Eligibility ≠ feature data availability; candle bounds remain for coverage checks."
                if version == HISTORICAL_EQUITY_UNIVERSE_V2
                else "Candle-derived proxy only."
            ),
        }
        out.append(
            HistoricalEligibility(
                instrument_id=iid,
                eligible_from=eligible_from,
                eligible_to=eligible_to,
                eligible_from_quality=from_quality,
                eligible_to_quality=to_quality,
                provenance=provenance,
            )
        )
    return out


def universe_as_of(
    session: Session,
    as_of: date,
    *,
    version: str = HISTORICAL_EQUITY_UNIVERSE_V1,
    instrument_ids: Sequence[int] | None = None,
    use_research_cohort: bool = True,
) -> list[int]:
    """Instrument ids eligible on ``as_of`` under the historical universe contract."""
    rows = build_historical_equity_universe(
        session,
        version=version,
        instrument_ids=instrument_ids,
        use_research_cohort=use_research_cohort,
    )
    return [row.instrument_id for row in rows if row.includes(as_of)]


def summarize_historical_universe(
    session: Session,
    *,
    version: str = HISTORICAL_EQUITY_UNIVERSE_V1,
) -> dict[str, Any]:
    """Compact evidence blob for Data Readiness."""
    rows = build_historical_equity_universe(session, version=version)
    if not rows:
        return {"version": version, "members": 0, "instrument_count": 0}
    froms = [r.eligible_from for r in rows]
    tos = [r.eligible_to for r in rows if r.eligible_to is not None]
    from_qualities: dict[str, int] = {}
    to_qualities: dict[str, int] = {}
    for r in rows:
        from_qualities[r.eligible_from_quality] = from_qualities.get(r.eligible_from_quality, 0) + 1
        to_qualities[r.eligible_to_quality] = to_qualities.get(r.eligible_to_quality, 0) + 1
    authoritative_from = sum(
        from_qualities.get(q, 0)
        for q in (QUALITY_MOEX_LISTED_FROM, QUALITY_MOEX_HISTORY_FROM)
    )
    proxy_from = from_qualities.get(QUALITY_FIRST_CANDLE, 0)
    return {
        "version": version,
        "members": len(rows),
        "instrument_count": len(rows),
        "earliest_eligible_from": min(froms).isoformat(),
        "latest_eligible_from": max(froms).isoformat(),
        "closed_windows": len(tos),
        "open_ended": sum(1 for r in rows if r.eligible_to is None),
        "eligible_from_quality_counts": from_qualities,
        "eligible_to_quality_counts": to_qualities,
        "authoritative_from_boundaries": authoritative_from,
        "proxy_from_boundaries": proxy_from,
        "quality_from": (
            QUALITY_MOEX_LISTED_FROM
            if version == HISTORICAL_EQUITY_UNIVERSE_V2
            else QUALITY_FIRST_CANDLE
        ),
        "quality_to_when_inactive": (
            QUALITY_MOEX_LISTED_TILL
            if version == HISTORICAL_EQUITY_UNIVERSE_V2
            else QUALITY_LAST_CANDLE
        ),
        "readiness": (
            "PARTIAL"
            if version == HISTORICAL_EQUITY_UNIVERSE_V2 and authoritative_from > 0
            else "PARTIAL"
        ),
    }
