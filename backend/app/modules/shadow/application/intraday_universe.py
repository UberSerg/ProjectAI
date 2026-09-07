"""Resolve tickers/boards for intraday refresh from active shadow portfolios
and Manual Portfolio positions.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import InstrumentSource
from app.modules.shadow.infrastructure.models import ShadowOrder, ShadowPortfolio

PREFERRED_EQUITY_BOARDS = ("TQBR", "TQTF", "SMAL")
ACTIVE_STATUSES = (
    "INITIALIZED",
    "WAITING_FOR_NEW_MARKET",
    "WAITING_FOR_FUTURE_MARKET_OPEN",
    "DECISION_READY",
    "ACTIVE",
    "RUNNING",
)


@dataclass(slots=True, frozen=True)
class UniverseMember:
    instrument_id: int
    ticker: str
    board: str
    secid: str


def _pick_board_source(sources: list[InstrumentSource]) -> InstrumentSource | None:
    if not sources:
        return None
    by_board = {str(s.board or "").upper(): s for s in sources if s.board}
    for board in PREFERRED_EQUITY_BOARDS:
        if board in by_board:
            return by_board[board]
    # Any current MOEX mapping.
    return sources[0]


def _manual_position_ids(session: Session) -> dict[int, str]:
    """Union Manual Portfolio position instrument_ids into the intraday universe."""
    try:
        from app.modules.portfolio.infrastructure.models import ManualPortfolio, ManualPosition
    except Exception:  # noqa: BLE001 — module/table may be absent pre-migration
        return {}

    needed: dict[int, str] = {}
    try:
        portfolios = list(session.scalars(select(ManualPortfolio)))
    except Exception:  # noqa: BLE001
        return {}
    for portfolio in portfolios:
        for pos in session.scalars(
            select(ManualPosition).where(ManualPosition.portfolio_id == portfolio.id)
        ):
            if abs(float(pos.units or 0)) < 1e-12:
                continue
            needed[int(pos.instrument_id)] = ""
    return needed


def resolve_intraday_universe(session: Session) -> list[UniverseMember]:
    """Union of PENDING order tickers + open position tickers across active shadows
    + Manual Portfolio positions.
    """
    portfolios = list(
        session.scalars(
            select(ShadowPortfolio).where(ShadowPortfolio.status.in_(ACTIVE_STATUSES))
        )
    )
    needed: dict[int, str] = {}
    for portfolio in portfolios:
        for order in session.scalars(
            select(ShadowOrder).where(
                ShadowOrder.portfolio_id == portfolio.id,
                ShadowOrder.status == "PENDING",
            )
        ):
            needed[int(order.instrument_id)] = str(order.ticker)
        positions = portfolio.positions or {}
        if isinstance(positions, dict):
            for key, row in positions.items():
                if not isinstance(row, dict):
                    continue
                qty = float(row.get("quantity") or 0)
                if abs(qty) < 1e-12:
                    continue
                iid = int(row.get("instrument_id") or key)
                ticker = str(row.get("ticker") or needed.get(iid) or "")
                needed[iid] = ticker

    for iid, ticker in _manual_position_ids(session).items():
        needed.setdefault(iid, ticker)

    if not needed:
        return []

    sources = list(
        session.scalars(
            select(InstrumentSource).where(
                InstrumentSource.instrument_id.in_(list(needed.keys())),
                InstrumentSource.source.in_(("MOEX", "MOEX_ISS")),
                InstrumentSource.valid_to.is_(None),
            )
        )
    )
    by_instrument: dict[int, list[InstrumentSource]] = {}
    for src in sources:
        by_instrument.setdefault(int(src.instrument_id), []).append(src)

    members: list[UniverseMember] = []
    for instrument_id, ticker in sorted(needed.items()):
        src = _pick_board_source(by_instrument.get(instrument_id, []))
        if src is None:
            continue
        board = str(src.board or "TQBR").upper()
        secid = str(src.external_id or ticker).upper()
        members.append(
            UniverseMember(
                instrument_id=instrument_id,
                ticker=ticker or secid,
                board=board,
                secid=secid,
            )
        )
    return members


def group_secids_by_board(members: list[UniverseMember]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for m in members:
        out.setdefault(m.board, [])
        if m.secid not in out[m.board]:
            out[m.board].append(m.secid)
    return out
