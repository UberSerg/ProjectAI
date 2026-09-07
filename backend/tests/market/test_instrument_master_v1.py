"""MOEX Instrument Master V1 unit/DB tests."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.infrastructure.market.models import (
    Candle,
    Instrument,
    InstrumentSource,
    UniverseMembership,
)
from app.modules.market.application.instrument_capabilities import resolve_instrument_capabilities
from app.modules.market.application.instrument_classification import (
    CATALOG_ONLY,
    EQUITY_COMMON,
    EQUITY_PREFERRED,
    FULL,
    FUND,
    OFZ_GOV,
    PARTIAL,
    classify_moex_row,
)
from app.modules.market.application.instrument_master_sync import MoexInstrumentMasterSync
from app.modules.market.application.instrument_search import search_instruments
from app.modules.market.application.moex_board_securities import MoexSecurityRow
from app.modules.market.application.research_universe import (
    RESEARCH_EQUITY_V1,
    seed_research_equity_membership,
)
from app.modules.market.application.seed import seed_market_universe
from app.modules.market.universe import INSTRUMENTS


class FakeBoardClient:
    def __init__(self, boards: dict[tuple[str, str], list[MoexSecurityRow] | Exception]) -> None:
        self.boards = boards
        self.calls: list[tuple[str, str]] = []

    def fetch_board_securities(self, market: str, board: str) -> list[MoexSecurityRow]:
        self.calls.append((market, board))
        value = self.boards.get((market, board), [])
        if isinstance(value, Exception):
            raise value
        return list(value)


def _row(
    secid: str,
    board: str,
    *,
    market: str = "shares",
    name: str | None = None,
    lotsize: int | None = 10,
    sec_type: str | None = None,
    is_traded: bool | None = True,
) -> MoexSecurityRow:
    return MoexSecurityRow(
        secid=secid,
        board=board,
        market=market,
        name=name or secid,
        isin=None,
        lotsize=lotsize,
        sec_type=sec_type,
        is_traded=is_traded,
        currency="RUB",
        raw={},
    )


def _master_schema_ready(session: Session) -> bool:
    try:
        session.execute(text("SELECT support_level FROM market.instruments LIMIT 0"))
        session.execute(text("SELECT 1 FROM market.universe_memberships LIMIT 0"))
        session.execute(text("SELECT 1 FROM market.instrument_master_sync_runs LIMIT 0"))
        return True
    except Exception:
        session.rollback()
        return False


@pytest.fixture
def master_db() -> Generator[Session, None, None]:
    """Transactional session; skip when postgres-core / migration unavailable."""
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
        if not _master_schema_ready(session):
            pytest.skip("alembic 20260908_0021 not applied")
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_classify_equity_common_preferred_fund_ofz() -> None:
    assert classify_moex_row(secid="SBER", board="TQBR").instrument_subtype == EQUITY_COMMON
    assert classify_moex_row(secid="SBER", board="TQBR").support_level == FULL
    assert classify_moex_row(secid="SBERP", board="TQBR").instrument_subtype == EQUITY_PREFERRED
    assert classify_moex_row(secid="FXGD", board="TQTF").instrument_subtype == FUND
    assert classify_moex_row(secid="FXGD", board="TQTF").support_level == PARTIAL
    ofz = classify_moex_row(secid="SU26238RMFS0", board="TQOB", market="bonds")
    assert ofz.instrument_subtype == OFZ_GOV
    assert ofz.support_level == PARTIAL
    smal = classify_moex_row(secid="TINY", board="SMAL")
    assert smal.support_level == CATALOG_ONLY


def test_sync_creates_and_updates(master_db) -> None:
    client = FakeBoardClient(
        {("shares", "TQBR"): [_row("ZZZZ", "TQBR", name="Zed One", lotsize=1)]}
    )
    sync = MoexInstrumentMasterSync(
        master_db,
        client=client,
        boards=(("shares", "TQBR"),),
        deactivate_missing=False,
    )
    report = sync.run()
    assert report["status"] in {"SUCCESS", "SUCCESS_WITH_ERRORS"}
    assert report["created"] >= 1
    inst = master_db.scalar(
        select(Instrument).where(Instrument.symbol == "ZZZZ", Instrument.exchange == "MOEX")
    )
    assert inst is not None
    assert inst.name == "Zed One"
    assert inst.support_level == FULL

    client2 = FakeBoardClient(
        {("shares", "TQBR"): [_row("ZZZZ", "TQBR", name="Zed Two", lotsize=10)]}
    )
    report2 = MoexInstrumentMasterSync(
        master_db, client=client2, boards=(("shares", "TQBR"),), deactivate_missing=False
    ).run()
    assert report2["updated"] >= 1
    master_db.refresh(inst)
    assert inst.name == "Zed Two"
    src = master_db.scalar(
        select(InstrumentSource).where(
            InstrumentSource.external_id == "ZZZZ",
            InstrumentSource.board == "TQBR",
        )
    )
    assert src is not None
    assert src.source_metadata.get("LOTSIZE") == 10


def test_sync_no_mass_deactivate_on_empty_failure(master_db) -> None:
    inst = Instrument(
        symbol="KEEP1",
        name="Keep",
        asset_class="equity",
        exchange="MOEX",
        currency="RUB",
        is_active=True,
        support_level=FULL,
        primary_board="TQBR",
    )
    master_db.add(inst)
    master_db.flush()
    master_db.add(
        InstrumentSource(
            instrument_id=inst.id,
            source="MOEX",
            external_id="KEEP1",
            board="TQBR",
            source_metadata={},
        )
    )
    master_db.flush()

    client = FakeBoardClient(
        {
            ("shares", "TQBR"): [],
            ("shares", "TQTF"): RuntimeError("network"),
        }
    )
    report = MoexInstrumentMasterSync(
        master_db,
        client=client,
        boards=(("shares", "TQBR"), ("shares", "TQTF")),
        deactivate_missing=True,
    ).run()
    assert report["status"] == "FAILED_EMPTY"
    assert report["mass_deactivate_blocked"] is True
    assert report["deactivated"] == 0
    master_db.refresh(inst)
    assert inst.is_active is True


def test_sync_does_not_auto_add_research_membership(master_db) -> None:
    client = FakeBoardClient(
        {("shares", "TQBR"): [_row("NEWEQ", "TQBR", name="New Equity", lotsize=1)]}
    )
    MoexInstrumentMasterSync(
        master_db, client=client, boards=(("shares", "TQBR"),), deactivate_missing=False
    ).run()
    inst = master_db.scalar(select(Instrument).where(Instrument.symbol == "NEWEQ"))
    assert inst is not None
    member = master_db.get(UniverseMembership, (RESEARCH_EQUITY_V1, int(inst.id)))
    assert member is None


def test_search_ranking_exact_prefix_contains(master_db) -> None:
    for symbol, name in (
        ("ZRANK", "Exact rank"),
        ("ZRANKP", "Prefix rank"),
        ("XZRANK", "Contains rank"),
    ):
        master_db.add(
            Instrument(
                symbol=symbol,
                name=name,
                asset_class="equity",
                exchange="MOEX",
                currency="RUB",
                is_active=True,
            )
        )
    master_db.flush()
    result = search_instruments(master_db, q="ZRANK", page=1, page_size=10)
    symbols = [i["symbol"] for i in result["items"]]
    assert symbols[0] == "ZRANK"
    assert "ZRANKP" in symbols
    assert symbols.index("ZRANK") < symbols.index("ZRANKP")


def test_capabilities_predict_only_research_member(master_db) -> None:
    seed_market_universe(master_db)
    seed_research_equity_membership(master_db)
    sber = master_db.scalar(select(Instrument).where(Instrument.symbol == "SBER"))
    outsider = Instrument(
        symbol="OUTX",
        name="Outside",
        asset_class="equity",
        exchange="MOEX",
        currency="RUB",
        is_active=True,
        support_level=FULL,
        primary_board="TQBR",
    )
    master_db.add(outsider)
    master_db.flush()
    master_db.add(
        InstrumentSource(
            instrument_id=outsider.id,
            source="MOEX",
            external_id="OUTX",
            board="TQBR",
            source_metadata={"LOTSIZE": 1},
        )
    )
    for iid in (sber.id, outsider.id):
        master_db.add(
            Candle(
                instrument_id=iid,
                timeframe="1d",
                timestamp=datetime(2026, 1, 2, tzinfo=UTC),
                open=Decimal("10"),
                high=Decimal("10"),
                low=Decimal("10"),
                close=Decimal("10"),
                volume=Decimal("1"),
                source="MOEX",
            )
        )
    master_db.flush()

    caps_sber = resolve_instrument_capabilities(master_db, sber)
    caps_out = resolve_instrument_capabilities(master_db, outsider)
    assert caps_sber.can_predict is True
    assert caps_out.can_predict is False
    assert caps_out.can_portfolio_value is True


def test_research_seed_from_universe_symbols(master_db) -> None:
    seed_market_universe(master_db)
    result = seed_research_equity_membership(master_db)
    equity_count = sum(1 for i in INSTRUMENTS if i.asset_class == "equity")
    assert result["seeded"] == equity_count
    result2 = seed_research_equity_membership(master_db)
    assert result2["seeded"] == equity_count
