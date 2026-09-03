"""H3 board-aware backfill (no live network)."""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.ports.market_data import CandleBar, ProviderFetchResult
from app.infrastructure.market.models import Candle, CorporateAction, Instrument
from app.infrastructure.market.raw_store import RawStore
from app.modules.market.application.identity import add_source_mapping
from app.modules.market.application.ingest import MarketIngestionService
from app.modules.market.application.split_events import EVENT_TYPE_SPLIT


class _FakeMoex:
    def __init__(self) -> None:
        self.calls: list[tuple[str, date, date, str]] = []

    def fetch_daily_candles(self, external_id: str, start_date: date, end_date: date, *, board: str = "TQBR"):
        self.calls.append((external_id, start_date, end_date, board))
        ts = datetime.combine(start_date, datetime.min.time(), UTC)
        return ProviderFetchResult(
            source="MOEX",
            records=(
                CandleBar(
                    timestamp=ts,
                    open=Decimal("10"),
                    high=Decimal("11"),
                    low=Decimal("9"),
                    close=Decimal("10"),
                    volume=Decimal("100"),
                ),
            ),
            raw_payloads=(b'{"history":{"data":[]}}',),
            metadata={"external_id": external_id, "board": board},
        )

    def fetch_series(self, external_id: str, start_date: date, end_date: date):
        return ProviderFetchResult(source="MOEX", records=(), raw_payloads=())


class _FakeCbr:
    def fetch_series(self, external_id: str, start_date: date, end_date: date):
        return ProviderFetchResult(source="CBR", records=(), raw_payloads=(b"<ok/>",))


def _instrument(session: Session, symbol: str) -> Instrument:
    inst = Instrument(
        symbol=symbol,
        name=symbol,
        asset_class="equity",
        exchange="MOEX",
        currency="RUB",
        is_active=True,
    )
    session.add(inst)
    session.flush()
    return inst


def _service(session: Session, moex: _FakeMoex, tmp_path: Path) -> MarketIngestionService:
    return MarketIngestionService(
        session,
        moex=moex,
        cbr=_FakeCbr(),
        raw_store=RawStore(root=str(tmp_path)),
        pause_seconds=0,
        commit_progress=False,
    )


def test_board_aware_fetch_uses_planned_board(core_db: Session, tmp_path: Path) -> None:
    inst = _instrument(core_db, "H3SB")
    add_source_mapping(
        core_db,
        instrument_id=inst.id,
        source="MOEX",
        external_id="H3SB",
        board="EQBR",
        valid_from=date(2011, 11, 21),
        valid_to=date(2013, 3, 25),
    )
    add_source_mapping(
        core_db,
        instrument_id=inst.id,
        source="MOEX",
        external_id="H3SB",
        board="TQBR",
        valid_from=date(2013, 3, 25),
        valid_to=None,
    )
    moex = _FakeMoex()
    _service(core_db, moex, tmp_path).run_backfill(
        symbols=["H3SB"],
        date_from=date(2012, 6, 1),
        date_to=date(2014, 1, 15),
    )
    assert ("H3SB", date(2012, 6, 1), date(2013, 3, 24), "EQBR") in moex.calls
    assert ("H3SB", date(2013, 3, 25), date(2014, 1, 15), "TQBR") in moex.calls
    assert all(call[3] != "TQBR" or call[1] >= date(2013, 3, 25) for call in moex.calls)
    raw_names = [path.name for path in tmp_path.rglob("*.json")]
    assert any("H3SB_EQBR_" in name for name in raw_names)
    assert any("H3SB_TQBR_" in name for name in raw_names)


def test_later_listed_is_not_fetched_before_window(core_db: Session, tmp_path: Path) -> None:
    inst = _instrument(core_db, "H3T")
    add_source_mapping(
        core_db,
        instrument_id=inst.id,
        source="MOEX",
        external_id="H3T",
        board="TQBR",
        valid_from=date(2024, 11, 28),
        valid_to=None,
    )
    moex = _FakeMoex()
    _service(core_db, moex, tmp_path).run_backfill(
        symbols=["H3T"],
        date_from=date(2014, 1, 1),
        date_to=date(2015, 12, 31),
    )
    assert moex.calls == []
    assert core_db.scalar(select(func.count()).select_from(Candle).where(Candle.instrument_id == inst.id)) == 0


def test_unknown_start_mapping_not_used_historically(core_db: Session, tmp_path: Path) -> None:
    inst = _instrument(core_db, "H3UNK")
    add_source_mapping(
        core_db,
        instrument_id=inst.id,
        source="MOEX",
        external_id="H3UNK",
        board="TQBR",
        valid_from=None,
        valid_to=None,
    )
    moex = _FakeMoex()
    _service(core_db, moex, tmp_path).run_backfill(
        symbols=["H3UNK"],
        date_from=date(2014, 1, 1),
        date_to=date(2014, 2, 1),
    )
    assert moex.calls == []


def test_repeat_backfill_is_idempotent(core_db: Session, tmp_path: Path) -> None:
    inst = _instrument(core_db, "H3ID")
    add_source_mapping(
        core_db,
        instrument_id=inst.id,
        source="MOEX",
        external_id="H3ID",
        board="TQBR",
        valid_from=date(2014, 6, 9),
        valid_to=None,
    )
    moex = _FakeMoex()
    service = _service(core_db, moex, tmp_path)
    first = service.run_backfill(symbols=["H3ID"], date_from=date(2015, 1, 1), date_to=date(2015, 1, 10))
    second = service.run_backfill(symbols=["H3ID"], date_from=date(2015, 1, 1), date_to=date(2015, 1, 10))
    assert first["stats"]["inserted"] == 1
    assert second["stats"]["inserted"] == 0
    assert second["stats"]["updated"] == 1
    assert core_db.scalar(select(func.count()).select_from(Candle).where(Candle.instrument_id == inst.id)) == 1


def test_corporate_action_survives_backfill(core_db: Session, tmp_path: Path) -> None:
    inst = _instrument(core_db, "H3PL")
    add_source_mapping(
        core_db,
        instrument_id=inst.id,
        source="MOEX",
        external_id="H3PL",
        board="TQBR",
        valid_from=date(2014, 6, 9),
        valid_to=None,
    )
    core_db.add(
        CorporateAction(
            instrument_id=inst.id,
            event_date=date(2025, 3, 27),
            event_type=EVENT_TYPE_SPLIT,
            payload={"split_before": "1", "split_after": "10"},
            source="MOEX",
            external_id="H3PL",
            known_at=None,
        )
    )
    core_db.flush()
    _service(core_db, _FakeMoex(), tmp_path).run_backfill(
        symbols=["H3PL"],
        date_from=date(2015, 1, 1),
        date_to=date(2015, 1, 10),
    )
    rows = list(
        core_db.scalars(
            select(CorporateAction).where(
                CorporateAction.instrument_id == inst.id,
                CorporateAction.event_date == date(2025, 3, 27),
            )
        )
    )
    assert len(rows) == 1
    assert rows[0].known_at is None
    assert rows[0].event_type == EVENT_TYPE_SPLIT


def test_ingest_does_not_trigger_downstream() -> None:
    from app.modules.market.application import ingest

    src = inspect.getsource(ingest)
    assert "app.modules.analytics" not in src
    assert "app.modules.technical" not in src
    assert "app.modules.relations" not in src
    assert "app.modules.learning" not in src
    assert "dataset_build" not in src
    assert "feature_backfill" not in src
