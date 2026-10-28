"""Shared helpers for Investor Journey MVP reliability / DEMO bootstrap tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Candle, Instrument, InstrumentSource
from app.modules.portfolio.application.personal_portfolio_service import get_or_create_test_portfolio
from app.modules.portfolio.infrastructure.models import ManualPosition, PersonalOperation


def schema_ready(session: Session) -> bool:
    try:
        session.execute(text("SELECT 1 FROM portfolio.personal_operations LIMIT 0"))
        return True
    except Exception:
        session.rollback()
        return False


def wipe_portfolio(session: Session, name: str):
    from sqlalchemy import delete

    portfolio = get_or_create_test_portfolio(session, name=name)
    session.execute(delete(PersonalOperation).where(PersonalOperation.portfolio_id == portfolio.id))
    session.execute(delete(ManualPosition).where(ManualPosition.portfolio_id == portfolio.id))
    portfolio.cash_rub = Decimal("0")
    portfolio.total_contributed_rub = Decimal("0")
    portfolio.total_withdrawn_rub = Decimal("0")
    portfolio.realized_pnl_rub = Decimal("0")
    portfolio.status = "DRAFT"
    session.flush()
    return portfolio


def make_equity(
    session: Session,
    symbol: str,
    *,
    close: Decimal | None = Decimal("100"),
    lot_size: int | None = 1,
    as_of: date = date(2026, 9, 25),
    reuse_existing: bool = False,
) -> Instrument:
    """Create a test equity. With ``reuse_existing`` reuse master row if present.

    Prefer unique symbols in unit tests. Use ``reuse_existing=True`` only when
    asserting DEMO bootstrap against real master tickers (SBER/LKOH/MGNT).
    """
    if reuse_existing:
        existing = session.scalar(
            select(Instrument).where(
                func.upper(Instrument.symbol) == symbol.upper(),
                Instrument.exchange == "MOEX",
            )
        )
        if existing is not None:
            return existing

    inst = Instrument(
        symbol=symbol,
        name=symbol,
        asset_class="equity",
        exchange="MOEX",
        currency="RUB",
        is_active=True,
        support_level="FULL",
        primary_board="TQBR",
    )
    session.add(inst)
    session.flush()
    meta = {}
    if lot_size is not None:
        meta["LOTSIZE"] = lot_size
    session.add(
        InstrumentSource(
            instrument_id=inst.id,
            source="MOEX_ISS",
            external_id=symbol,
            board="TQBR",
            source_metadata=meta,
        )
    )
    if close is not None:
        session.add(
            Candle(
                instrument_id=inst.id,
                timeframe="1d",
                timestamp=datetime(as_of.year, as_of.month, as_of.day, tzinfo=UTC),
                open=close,
                high=close,
                low=close,
                close=close,
                volume=Decimal("1000"),
                source="TEST",
            )
        )
    session.flush()
    return inst


def make_bond(session: Session, symbol: str = "MVPBND") -> Instrument:
    from app.modules.investment.infrastructure.models import BondMarketSnapshot, BondTerm

    inst = Instrument(
        symbol=symbol,
        name=symbol,
        asset_class="bond",
        exchange="MOEX",
        currency="RUB",
        is_active=True,
        support_level="PARTIAL",
        primary_board="TQOB",
        instrument_subtype="ofz_gov",
    )
    session.add(inst)
    session.flush()
    session.add(
        BondTerm(
            instrument_id=inst.id,
            bond_type="Government",
            nominal=Decimal("1000"),
            currency="RUB",
            lot_size=1,
            support_status="SUPPORTED",
            credit_quality_status="OBSERVED",
            known_at=date(2026, 1, 1),
            source="TEST",
            raw_fields={},
        )
    )
    session.add(
        BondMarketSnapshot(
            instrument_id=inst.id,
            as_of=date(2026, 9, 20),
            clean_price_percent=Decimal("95.5"),
            accrued_interest=Decimal("12.5"),
            source="TEST",
            observed_fields={},
        )
    )
    session.flush()
    return inst


def stub_decision_deps(monkeypatch: pytest.MonkeyPatch, *, positions: list[dict] | None = None) -> None:
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.get_latest_candidate_snapshot",
        lambda session: None,
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.preview_portfolio_candidate",
        lambda session, **kwargs: {
            "candidate_id": "mvp-stub",
            "positions": positions or [],
        },
    )
    monkeypatch.setattr(
        "app.modules.investment.application.risk_opportunity_service.run_investment_decision",
        lambda session, **kwargs: {
            "decision": {
                "cash_weight": 0.2,
                "equity_weight": 0.6,
                "fixed_income_weight": 0.2,
                "status": "RESEARCH_ONLY",
                "cbr_hurdle_annual": 0.16,
            }
        },
    )
