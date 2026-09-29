"""Manual portfolio position valuation (equity LAST/EOD, bond dirty/NKD)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.ports.intraday_market import IntradayMarketPort
from app.infrastructure.market.models import Candle, Instrument
from app.modules.investment.domain.fixed_income import calculate_bond_purchase
from app.modules.investment.infrastructure.models import BondMarketSnapshot, BondTerm
from app.modules.market.application.instrument_capabilities import resolve_instrument_capabilities
from app.modules.market.application.intraday_cache import IntradayQuoteCache
from app.modules.market.application.operational_quote import (
    ensure_operational_quote,
    mark_from_intraday_quote,
    price_unavailable_detail,
    resolve_board_secid,
)

Quality = Literal["LIVE", "PARTIAL", "STALE", "UNSUPPORTED"]


@dataclass(slots=True)
class PositionValuation:
    instrument_id: int
    symbol: str
    asset_class: str
    units: Decimal
    market_value: Decimal | None
    unit_price: Decimal | None
    currency: str
    quality: Quality
    price_source: str | None
    detail: dict[str, Any]
    supported: bool


def _d(value: object) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def latest_eod_close(session: Session, instrument_id: int) -> tuple[Decimal | None, str | None]:
    row = session.execute(
        select(Candle.close, Candle.timestamp)
        .where(Candle.instrument_id == instrument_id, Candle.timeframe == "1d")
        .order_by(Candle.timestamp.desc())
        .limit(1)
    ).first()
    if row is None or row[0] is None:
        return None, None
    return _d(row[0]), row[1].isoformat() if row[1] else None


def equity_mark(
    session: Session,
    instrument: Instrument,
    *,
    cache: IntradayQuoteCache | None = None,
    allow_fetch: bool = True,
    provider: IntradayMarketPort | None = None,
) -> tuple[Decimal | None, str, Quality]:
    """Operational mark: cache LAST → PREVPRICE → optional MOEX cold-start → EOD.

    Never writes candles. Missing price returns NONE (not zero).
    """
    board, secid = resolve_board_secid(session, instrument)
    quote_cache = cache or IntradayQuoteCache()
    quote = quote_cache.get(board, secid)
    price, source, quality = mark_from_intraday_quote(quote)
    if price is not None:
        return price, source, quality

    if allow_fetch:
        fetched = ensure_operational_quote(
            session, instrument, cache=quote_cache, provider=provider
        )
        price, source, quality = mark_from_intraday_quote(fetched)
        if price is not None:
            return price, source, quality

    close, _ts = latest_eod_close(session, int(instrument.id))
    if close is not None:
        return close, "EOD_CLOSE", "STALE"
    return None, "NONE", "UNSUPPORTED"


def bond_dirty_value(
    session: Session,
    instrument: Instrument,
    units: Decimal,
) -> PositionValuation:
    term = session.scalar(select(BondTerm).where(BondTerm.instrument_id == instrument.id))
    snap = session.scalar(
        select(BondMarketSnapshot)
        .where(BondMarketSnapshot.instrument_id == instrument.id)
        .order_by(BondMarketSnapshot.as_of.desc())
        .limit(1)
    )
    detail: dict[str, Any] = {}
    if term is None or term.nominal is None:
        return PositionValuation(
            instrument_id=int(instrument.id),
            symbol=instrument.symbol,
            asset_class="bond",
            units=units,
            market_value=None,
            unit_price=None,
            currency=instrument.currency or "RUB",
            quality="UNSUPPORTED",
            price_source=None,
            detail={"reason": "missing_bond_terms"},
            supported=False,
        )
    if snap is None or snap.clean_price_percent is None:
        return PositionValuation(
            instrument_id=int(instrument.id),
            symbol=instrument.symbol,
            asset_class="bond",
            units=units,
            market_value=None,
            unit_price=None,
            currency=term.currency or instrument.currency or "RUB",
            quality="UNSUPPORTED",
            price_source=None,
            detail={"reason": "missing_bond_snapshot"},
            supported=False,
        )

    lot_size = int(term.lot_size or 1)
    # NEVER treat clean % (e.g. 95.5) as RUB price.
    clean_pct = _d(snap.clean_price_percent)
    nkd = _d(snap.accrued_interest or 0)
    units_int = int(units)
    if Decimal(units_int) != units or lot_size <= 0 or units_int % lot_size != 0:
        # Still value by bonds count = units (each bond).
        quantity = units_int if Decimal(units_int) == units else None
        if quantity is None:
            return PositionValuation(
                instrument_id=int(instrument.id),
                symbol=instrument.symbol,
                asset_class="bond",
                units=units,
                market_value=None,
                unit_price=None,
                currency=term.currency or "RUB",
                quality="UNSUPPORTED",
                price_source="BOND_SNAPSHOT",
                detail={"reason": "non_integer_bond_units"},
                supported=False,
            )
        lots = quantity  # treat each unit as one bond when lot unknown mismatch
        lot_size = 1
    else:
        lots = units_int // lot_size

    purchase = calculate_bond_purchase(
        nominal=_d(term.nominal),
        clean_price_percent=clean_pct,
        accrued_interest_per_bond=nkd,
        lots=lots,
        lot_size=lot_size,
    )
    dirty_per = (
        purchase.dirty_total / Decimal(purchase.quantity)
        if purchase.quantity
        else None
    )
    detail = {
        "clean_price_percent": float(clean_pct),
        "accrued_interest_per_bond": float(nkd),
        "nominal": float(term.nominal),
        "dirty_total": float(purchase.dirty_total),
        "as_of": snap.as_of.isoformat() if snap.as_of else None,
        "note": "clean_percent_times_nominal_plus_nkd",
    }
    return PositionValuation(
        instrument_id=int(instrument.id),
        symbol=instrument.symbol,
        asset_class="bond",
        units=units,
        market_value=purchase.dirty_total,
        unit_price=dirty_per,
        currency=term.currency or instrument.currency or "RUB",
        quality="PARTIAL",
        price_source="BOND_DIRTY_NKD",
        detail=detail,
        supported=True,
    )


def value_position(
    session: Session,
    instrument: Instrument,
    units: Decimal,
    *,
    cache: IntradayQuoteCache | None = None,
    allow_fetch: bool = True,
    provider: IntradayMarketPort | None = None,
) -> PositionValuation:
    asset = (instrument.asset_class or "").lower()
    if asset == "bond":
        return bond_dirty_value(session, instrument, units)

    caps = resolve_instrument_capabilities(session, instrument)
    if not caps.can_portfolio_value and asset not in {"equity", "fund"}:
        return PositionValuation(
            instrument_id=int(instrument.id),
            symbol=instrument.symbol,
            asset_class=asset,
            units=units,
            market_value=None,
            unit_price=None,
            currency=instrument.currency or "RUB",
            quality="UNSUPPORTED",
            price_source=None,
            detail={"reason": "unsupported_asset"},
            supported=False,
        )

    price, source, quality = equity_mark(
        session, instrument, cache=cache, allow_fetch=allow_fetch, provider=provider
    )
    if price is None:
        moex_missing = caps.reasons.get("can_live_quote") == "inactive_or_no_moex_or_catalog_only"
        detail = price_unavailable_detail(
            has_moex_source=not moex_missing,
            tried_fetch=allow_fetch,
        )
        return PositionValuation(
            instrument_id=int(instrument.id),
            symbol=instrument.symbol,
            asset_class=asset or "equity",
            units=units,
            market_value=None,
            unit_price=None,
            currency=instrument.currency or "RUB",
            quality="UNSUPPORTED",
            price_source=None,
            detail=detail,
            supported=False,
        )
    return PositionValuation(
        instrument_id=int(instrument.id),
        symbol=instrument.symbol,
        asset_class=asset or "equity",
        units=units,
        market_value=price * units,
        unit_price=price,
        currency=instrument.currency or "RUB",
        quality=quality,
        price_source=source,
        detail={},
        supported=True,
    )
