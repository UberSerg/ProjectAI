"""Manual Portfolio V1 tests."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Candle, Instrument, InstrumentSource
from app.modules.fundamentals.infrastructure.models import Issuer, SecurityIssuerMapping
from app.modules.investment.infrastructure.models import BondMarketSnapshot, BondTerm
from app.modules.market.application.instrument_capabilities import resolve_instrument_capabilities
from app.modules.market.application.research_universe import (
    RESEARCH_EQUITY_V1,
    seed_research_equity_membership,
)
from app.modules.market.application.seed import seed_market_universe
from app.modules.portfolio.application.manual_portfolio_service import (
    LotValidationError,
    add_position,
    advisory_rebalance,
    analyze_manual_portfolio,
    compare_to_candidate,
    delete_position,
    get_or_create_primary,
    patch_position,
    update_cash,
)
from app.modules.portfolio.domain.lots import assert_lot_compatible
from app.modules.portfolio.domain.valuation import bond_dirty_value, value_position
from app.modules.portfolio.infrastructure.models import ManualPosition
from app.modules.shadow.application.intraday_universe import resolve_intraday_universe


def _schema_ready(session: Session) -> bool:
    try:
        session.execute(text("SELECT 1 FROM portfolio.manual_portfolios LIMIT 0"))
        session.execute(text("SELECT support_level FROM market.instruments LIMIT 0"))
        return True
    except Exception:
        session.rollback()
        return False


def _reset_primary_portfolio(session: Session) -> None:
    """Isolate analysis assertions from live primary holdings (txn rolls back)."""
    portfolio = get_or_create_primary(session)
    for pos in list(portfolio.positions or []):
        session.delete(pos)
    portfolio.cash_rub = Decimal("0")
    portfolio.updated_at = datetime.now(UTC)
    session.flush()
    session.expire(portfolio, ["positions"])


@pytest.fixture
def mp_db() -> Generator[Session, None, None]:
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
            pytest.skip("alembic 20260908_0021 not applied")
        _reset_primary_portfolio(session)
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _equity(session, symbol: str = "SBER", *, lot: int = 10) -> Instrument:
    inst = session.scalar(
        select(Instrument).where(Instrument.symbol == symbol, Instrument.exchange == "MOEX")
    )
    if inst is None:
        inst = Instrument(
            symbol=symbol,
            name=symbol,
            asset_class="equity",
            exchange="MOEX",
            currency="RUB",
            is_active=True,
            support_level="FULL",
            primary_board="TQBR",
            instrument_subtype="equity_common",
        )
        session.add(inst)
        session.flush()
    src = session.scalar(
        select(InstrumentSource).where(
            InstrumentSource.instrument_id == inst.id,
            InstrumentSource.board == "TQBR",
        )
    )
    if src is None:
        session.add(
            InstrumentSource(
                instrument_id=inst.id,
                source="MOEX",
                external_id=symbol,
                board="TQBR",
                source_metadata={"LOTSIZE": lot},
            )
        )
    else:
        meta = dict(src.source_metadata or {})
        meta["LOTSIZE"] = lot
        src.source_metadata = meta
    candle_ts = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    existing_candle = session.scalar(
        select(Candle).where(
            Candle.instrument_id == inst.id,
            Candle.timeframe == "1d",
            Candle.timestamp == candle_ts,
            Candle.source == "TEST_MP",
        )
    )
    if existing_candle is None:
        session.add(
            Candle(
                instrument_id=inst.id,
                timeframe="1d",
                timestamp=candle_ts,
                open=Decimal("100"),
                high=Decimal("100"),
                low=Decimal("100"),
                close=Decimal("100"),
                volume=Decimal("1"),
                source="TEST_MP",
            )
        )
    session.flush()
    return inst


def _bond(session, symbol: str = "SU26238") -> Instrument:
    inst = Instrument(
        symbol=symbol,
        name="OFZ test",
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
        InstrumentSource(
            instrument_id=inst.id,
            source="MOEX_ISS",
            external_id=symbol,
            board="TQOB",
            source_metadata={"LOTSIZE": 1},
        )
    )
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
            as_of=date(2026, 1, 5),
            clean_price_percent=Decimal("95.5"),
            accrued_interest=Decimal("10"),
            source="TEST",
            observed_fields={},
        )
    )
    session.flush()
    return inst


def test_lot_validation_unit() -> None:
    assert_lot_compatible(Decimal("20"), 10)
    with pytest.raises(LotValidationError):
        assert_lot_compatible(Decimal("15"), 10)
    assert_lot_compatible(Decimal("15"), 10, non_standard_lot=True)


def test_manual_crud_and_lot_validation(mp_db) -> None:
    inst = _equity(mp_db, "MPCRUD", lot=10)
    portfolio = get_or_create_primary(mp_db)
    assert portfolio.id > 0
    update_cash(mp_db, Decimal("50000"))
    with pytest.raises(LotValidationError):
        add_position(mp_db, instrument_id=inst.id, units=Decimal("15"))
    pos = add_position(mp_db, instrument_id=inst.id, units=Decimal("20"))
    assert float(pos.units) == 20
    patch_position(mp_db, pos.id, units=Decimal("30"))
    delete_position(mp_db, pos.id)
    assert mp_db.get(ManualPosition, pos.id) is None


def test_equity_and_bond_valuation(mp_db) -> None:
    eq = _equity(mp_db, "MPVALE", lot=1)
    val = value_position(mp_db, eq, Decimal("3"))
    assert val.supported is True
    assert val.market_value == Decimal("300")

    bond = _bond(mp_db)
    bval = bond_dirty_value(mp_db, bond, Decimal("2"))
    assert bval.supported is True
    assert bval.market_value == Decimal("1930")
    assert bval.detail["clean_price_percent"] == 95.5


def test_unsupported_not_zero(mp_db) -> None:
    inst = Instrument(
        symbol="NOSRC",
        name="No source",
        asset_class="other",
        exchange="MOEX",
        currency="RUB",
        is_active=True,
        support_level="CATALOG_ONLY",
    )
    mp_db.add(inst)
    mp_db.flush()
    add_position(
        mp_db,
        instrument_id=inst.id,
        units=Decimal("1"),
        non_standard_lot=True,
    )
    update_cash(mp_db, Decimal("1000"))
    analysis = analyze_manual_portfolio(mp_db)
    assert analysis["unsupported_count"] >= 1
    assert analysis["nav"] == 1000.0
    row = next(r for r in analysis["positions"] if r["symbol"] == "NOSRC")
    assert row["market_value"] is None
    assert row["supported"] is False


def test_concentration_by_issuer(mp_db) -> None:
    try:
        mp_db.execute(text("SELECT 1 FROM fundamentals.issuers LIMIT 0"))
    except Exception:
        mp_db.rollback()
        pytest.skip("fundamentals schema not applied")
    a = _equity(mp_db, "AAA1", lot=1)
    b = _equity(mp_db, "AAA2", lot=1)
    issuer = Issuer(title="Issuer AAA", moex_emitent_id=999001)
    mp_db.add(issuer)
    mp_db.flush()
    for inst in (a, b):
        mp_db.add(
            SecurityIssuerMapping(
                instrument_id=inst.id,
                issuer_id=issuer.id,
                source="TEST",
                mapping_status="MAPPED",
            )
        )
    update_cash(mp_db, Decimal("0"))
    add_position(mp_db, instrument_id=a.id, units=Decimal("10"))
    add_position(mp_db, instrument_id=b.id, units=Decimal("10"))
    analysis = analyze_manual_portfolio(mp_db)
    assert analysis["concentration_by_issuer"]
    top = analysis["concentration_by_issuer"][0]
    assert top["weight"] >= 0.99
    assert any(f["code"] == "ISSUER_CONCENTRATION" for f in analysis["risk_findings"])


def test_compare_and_rebalance_cash_safe(mp_db, monkeypatch) -> None:
    eq = _equity(mp_db, "MPCMP1", lot=10)
    update_cash(mp_db, Decimal("100000"))
    add_position(mp_db, instrument_id=eq.id, units=Decimal("10"))

    def fake_candidate(session, **kwargs):
        return {
            "candidate_id": "test",
            "positions": [
                {"symbol": "MPCMP1", "weight": 0.2},
                {"symbol": "MISSING", "weight": 0.8},
            ],
        }

    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.get_latest_candidate_snapshot",
        lambda session: None,
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.preview_portfolio_candidate",
        fake_candidate,
    )
    compare = compare_to_candidate(mp_db)
    by_sym = {c["symbol"]: c for c in compare["comparisons"]}
    assert by_sym["MISSING"]["status"] == "NOT_IN_MANUAL"
    assert by_sym["MISSING"]["suggested_action"] != "SELL"

    plan = advisory_rebalance(mp_db)
    assert plan["advisory"] is True
    assert plan["persisted_orders"] is False
    assert plan["cash_safe"] is True
    assert plan["projected_cash"] >= 0


def test_outside_research_can_value_not_predict(mp_db) -> None:
    seed_market_universe(mp_db)
    seed_research_equity_membership(mp_db)
    outsider = _equity(mp_db, "OUTY", lot=1)
    from app.infrastructure.market.models import UniverseMembership

    assert mp_db.get(UniverseMembership, (RESEARCH_EQUITY_V1, outsider.id)) is None
    caps = resolve_instrument_capabilities(mp_db, outsider)
    assert caps.can_predict is False
    val = value_position(mp_db, outsider, Decimal("2"))
    assert val.supported is True
    assert val.market_value == Decimal("200")


def test_intraday_universe_includes_manual_positions(mp_db) -> None:
    inst = _equity(mp_db, "MPINTR", lot=1)
    add_position(mp_db, instrument_id=inst.id, units=Decimal("1"))
    members = resolve_intraday_universe(mp_db)
    ids = {m.instrument_id for m in members}
    assert inst.id in ids
