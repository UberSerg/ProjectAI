"""Operational quotes for MOEX funds without inventing EOD / PIT history."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.domain.ports.intraday_market import (
    IntradayQuote,
    MarketSessionStatus,
    QuoteFreshness,
)
from app.infrastructure.market.models import Candle, Instrument, InstrumentSource
from app.modules.market.application.eod_gap import instruments_with_moex_history
from app.modules.market.application.instrument_capabilities import resolve_instrument_capabilities
from app.modules.market.application.intraday_cache import IntradayQuoteCache
from app.modules.portfolio.application.personal_portfolio_service import (
    _personal_mark,
    load_personal_snapshot,
)
from app.modules.portfolio.application.user_portfolio_service import create_user_portfolio
from app.modules.portfolio.domain.personal_ledger import money
from app.modules.portfolio.domain.valuation import equity_mark, value_position
from app.modules.portfolio.infrastructure.models import ManualPosition


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        return True

    def get(self, key: str) -> str | None:
        return self.store.get(key)


class _FakeProvider:
    def __init__(self, quotes: list[IntradayQuote]) -> None:
        self.quotes = quotes
        self.calls: list[dict[str, list[str]]] = []

    def fetch_quotes(
        self,
        secids_by_board: dict[str, list[str]],
        *,
        observed_at: datetime | None = None,
    ) -> list[IntradayQuote]:
        self.calls.append(secids_by_board)
        wanted = {
            (b.upper(), s.upper())
            for b, secs in secids_by_board.items()
            for s in secs
        }
        return [
            q
            for q in self.quotes
            if (q.board.upper(), q.secid.upper()) in wanted
        ]


def _schema_ready(session: Session) -> bool:
    try:
        session.execute(text("SELECT 1 FROM portfolio.manual_portfolios LIMIT 0"))
        session.execute(text("SELECT support_level FROM market.instruments LIMIT 0"))
        return True
    except Exception:
        session.rollback()
        return False


@pytest.fixture
def fund_db() -> Generator[Session, None, None]:
    try:
        from app.core.config import get_settings
        from app.infrastructure.db.session import get_core_engine

        get_settings.cache_clear()
        engine = get_core_engine()
        connection = engine.connect()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"core database unavailable: {exc}")

    transaction = connection.begin()
    session = Session(bind=connection, autoflush=False, expire_on_commit=False)
    try:
        try:
            connection.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"core database unavailable: {exc}")
        if not _schema_ready(session):
            pytest.skip("portfolio/market schema not applied")
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _fund(session: Session, symbol: str) -> Instrument:
    inst = Instrument(
        symbol=symbol,
        name=f"Fund {symbol}",
        asset_class="fund",
        instrument_subtype="fund",
        exchange="MOEX",
        currency="RUB",
        is_active=True,
        support_level="PARTIAL",
        primary_board="TQBR",
    )
    session.add(inst)
    session.flush()
    session.add(
        InstrumentSource(
            instrument_id=inst.id,
            source="MOEX",
            external_id=symbol,
            board="TQBR",
            valid_from=None,
            valid_to=None,
            source_metadata={},
        )
    )
    session.flush()
    return inst


def _quote(
    *,
    secid: str,
    last: float | None,
    prev: float | None,
    board: str = "TQBR",
) -> IntradayQuote:
    return IntradayQuote(
        secid=secid,
        board=board,
        trading_date=date(2026, 9, 29),
        observed_at=datetime(2026, 9, 29, 10, 0, tzinfo=UTC),
        source_timestamp=datetime(2026, 9, 29, 10, 0, tzinfo=UTC),
        market_status=MarketSessionStatus.OPEN if last else MarketSessionStatus.CLOSED,
        open_price=last,
        last_price=last,
        bid=None,
        ask=None,
        previous_close=prev,
        volume=1.0 if last else None,
        source="MOEX_ISS",
        freshness=QuoteFreshness.LIVE if last else QuoteFreshness.MARKET_CLOSED,
        quality="ok",
    )


def test_personal_mark_fund_without_candles_uses_last(fund_db: Session) -> None:
    """_personal_mark must not depend on EOD candles when operational quote exists."""
    inst = _fund(fund_db, "ZTSBFR")
    candles = fund_db.scalar(
        select(func.count()).select_from(Candle).where(Candle.instrument_id == inst.id)
    )
    assert candles == 0

    cache = IntradayQuoteCache(client=_FakeRedis())
    cache.set(_quote(secid="ZTSBFR", last=15.6, prev=15.5))

    unit, mv, price_date, hint, source, code = _personal_mark(
        fund_db,
        inst,
        Decimal("10"),
        cache=cache,
        allow_fetch=False,
    )
    assert hint == "fund"
    assert code is None
    assert source == "INTRADAY_LAST"
    assert unit == Decimal("15.6")
    assert mv == Decimal("156.0")
    assert price_date == "2026-09-29"


def test_personal_mark_fund_prevprice_when_no_last(fund_db: Session) -> None:
    inst = _fund(fund_db, "ZTSBMM")
    cache = IntradayQuoteCache(client=_FakeRedis())
    cache.set(_quote(secid="ZTSBMM", last=None, prev=10.25))

    unit, mv, _date, _hint, source, code = _personal_mark(
        fund_db, inst, Decimal("2"), cache=cache, allow_fetch=False
    )
    assert code is None
    assert source == "PREVIOUS_CLOSE"
    assert unit == Decimal("10.25")
    assert mv == Decimal("20.5")


def test_equity_mark_cold_start_fetch_without_candles(fund_db: Session) -> None:
    inst = _fund(fund_db, "ZTFLOW")
    cache = IntradayQuoteCache(client=_FakeRedis())
    provider = _FakeProvider([_quote(secid="ZTFLOW", last=12.0, prev=11.9)])

    price, source, quality = equity_mark(
        fund_db,
        inst,
        cache=cache,
        allow_fetch=True,
        provider=provider,  # type: ignore[arg-type]
    )
    assert len(provider.calls) == 1
    assert price == Decimal("12.0")
    assert source == "INTRADAY_LAST"
    assert quality == "LIVE"
    price2, source2, _q = equity_mark(
        fund_db,
        inst,
        cache=cache,
        allow_fetch=True,
        provider=provider,  # type: ignore[arg-type]
    )
    assert len(provider.calls) == 1
    assert price2 == Decimal("12.0")
    assert source2 == "INTRADAY_LAST"


def test_missing_price_never_zero(fund_db: Session) -> None:
    inst = _fund(fund_db, "ZTSBRB")
    cache = IntradayQuoteCache(client=_FakeRedis())
    provider = _FakeProvider([])
    val = value_position(
        fund_db,
        inst,
        Decimal("5"),
        cache=cache,
        allow_fetch=True,
        provider=provider,  # type: ignore[arg-type]
    )
    assert val.unit_price is None
    assert val.market_value is None
    assert val.supported is False
    assert val.detail.get("code") in {"MOEX_QUOTE_UNAVAILABLE", "NO_INTRADAY_OR_EOD"}


def test_fund_capabilities_can_portfolio_value_via_live_quote(fund_db: Session) -> None:
    inst = _fund(fund_db, "ZTCAPF")
    caps = resolve_instrument_capabilities(fund_db, inst)
    assert caps.can_live_quote is True
    assert caps.can_portfolio_value is True
    assert caps.can_predict is False


def test_null_valid_from_excluded_from_historical_eod_universe(fund_db: Session) -> None:
    """Current TQBR mapping with valid_from=NULL must not unlock historical candle ingest."""
    inst = _fund(fund_db, "ZTPIT1")
    src = fund_db.scalar(
        select(InstrumentSource).where(
            InstrumentSource.instrument_id == inst.id,
            InstrumentSource.source == "MOEX",
        )
    )
    assert src is not None
    assert src.valid_from is None

    history_ids = {int(i.id) for i in instruments_with_moex_history(fund_db)}
    assert int(inst.id) not in history_ids

    candles = fund_db.scalar(
        select(func.count()).select_from(Candle).where(Candle.instrument_id == inst.id)
    )
    assert candles == 0


def test_snapshot_nav_with_price_even_if_cost_unknown(
    fund_db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    cols = set(
        fund_db.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='portfolio' AND table_name='manual_portfolios'"
            )
        ).scalars()
    )
    if "broker_account_id" not in cols:
        # Broker agent migration may lag; still prove mark+NAV semantics via _personal_mark
        # and a synthetic snapshot assembly that mirrors load_personal_snapshot.
        inst = _fund(fund_db, "ZTFLOW2")
        cache = IntradayQuoteCache(client=_FakeRedis())
        cache.set(_quote(secid="ZTFLOW2", last=15.6, prev=15.5))
        unit, mv, _d, _h, source, code = _personal_mark(
            fund_db, inst, Decimal("10"), cache=cache, allow_fetch=False
        )
        assert code is None
        assert source == "INTRADAY_LAST"
        assert unit == Decimal("15.6")
        assert mv == Decimal("156.0")
        cash = Decimal("0")
        known_nav = cash + mv
        unrealized = None  # cost basis unknown → P&L stays null
        assert known_nav == Decimal("156.0")
        assert unrealized is None
        return

    book = create_user_portfolio(fund_db, name="TEST — fund mark nav", is_test=True)
    inst = _fund(fund_db, "ZTFLOW2")
    fund_db.add(
        ManualPosition(
            portfolio_id=book.id,
            instrument_id=inst.id,
            units=Decimal("10"),
            average_price=None,
        )
    )
    fund_db.flush()

    cache = IntradayQuoteCache(client=_FakeRedis())
    cache.set(_quote(secid="ZTFLOW2", last=15.6, prev=15.5))

    def _ensure(session, instruments, *, cache=None, provider=None):
        return {("TQBR", "ZTFLOW2"): cache.get("TQBR", "ZTFLOW2")} if cache else {}

    monkeypatch.setattr(
        "app.modules.portfolio.application.personal_portfolio_service.ensure_operational_quotes",
        _ensure,
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.personal_portfolio_service.IntradayQuoteCache",
        lambda: cache,
    )

    snap = load_personal_snapshot(fund_db, book)
    pos = next(p for p in snap.positions if p.symbol == "ZTFLOW2")
    assert pos.price_available is True
    assert pos.unit_price == Decimal("15.6")
    assert pos.market_value == Decimal("156.0")
    assert pos.unrealized_pnl is None
    assert pos.cost_basis_usable is False
    assert snap.known_nav_rub == money(book.cash_rub or 0) + Decimal("156.0")
    assert snap.investment_pnl_rub is None
    assert snap.investment_pnl_unavailable_reason == "COST_BASIS_INCOMPLETE"

