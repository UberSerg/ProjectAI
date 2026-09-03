"""H2 instrument/source validity windows (no live network)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import CorporateAction, Instrument, InstrumentSource
from app.infrastructure.market.raw_store import RawStore
from app.modules.market.application.corporate_actions import SplitIngestionService, resolve_moex_secid
from app.modules.market.application.identity import (
    InvalidMappingWindowError,
    MappingOverlapError,
    add_source_mapping,
    resolve_current_source,
    resolve_source_as_of,
)
from app.modules.market.application.ingest import MarketIngestionService
from app.modules.market.application.seed import seed_market_universe
from app.modules.market.application.split_events import EVENT_TYPE_SPLIT, SplitEventDraft, SplitParseResult
from app.modules.market.universe import INSTRUMENTS


class _FakeSplitFeed:
    def __init__(self, parsed: SplitParseResult) -> None:
        self.parsed = parsed

    def fetch_stock_splits(self) -> tuple[SplitParseResult, tuple[bytes, ...]]:
        return self.parsed, (b'{"splits":{"columns":[],"data":[]}}',)


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


def test_current_open_ended_resolves_today(core_db: Session) -> None:
    inst = _instrument(core_db, "H2CUR")
    add_source_mapping(
        core_db,
        instrument_id=inst.id,
        source="MOEX",
        external_id="H2CUR",
        board="TQBR",
        valid_from=None,
        valid_to=None,
    )
    current = resolve_current_source(core_db, inst.id)
    assert current is not None
    assert current.external_id == "H2CUR"
    assert current.board == "TQBR"
    assert resolve_source_as_of(core_db, inst.id, date(2026, 9, 3)) is None


def test_historical_window_and_changeover(core_db: Session) -> None:
    inst = _instrument(core_db, "H2CHG")
    add_source_mapping(
        core_db,
        instrument_id=inst.id,
        source="MOEX",
        external_id="OLDSEC",
        board="EQBR",
        valid_from=date(2013, 1, 1),
        valid_to=date(2020, 1, 1),
    )
    add_source_mapping(
        core_db,
        instrument_id=inst.id,
        source="MOEX",
        external_id="NEWSEC",
        board="TQBR",
        valid_from=date(2020, 1, 1),
        valid_to=None,
    )
    before = resolve_source_as_of(core_db, inst.id, date(2019, 12, 31))
    on_cut = resolve_source_as_of(core_db, inst.id, date(2020, 1, 1))
    after = resolve_source_as_of(core_db, inst.id, date(2021, 6, 1))
    assert before is not None and before.external_id == "OLDSEC" and before.board == "EQBR"
    assert on_cut is not None and on_cut.external_id == "NEWSEC" and on_cut.board == "TQBR"
    assert after is not None and after.external_id == "NEWSEC"
    assert resolve_source_as_of(core_db, inst.id, date(2012, 12, 31)) is None
    current = resolve_current_source(core_db, inst.id)
    assert current is not None and current.external_id == "NEWSEC"


def test_after_valid_to_does_not_resolve(core_db: Session) -> None:
    inst = _instrument(core_db, "H2END")
    add_source_mapping(
        core_db,
        instrument_id=inst.id,
        source="MOEX",
        external_id="H2END",
        board="EQBR",
        valid_from=date(2011, 11, 21),
        valid_to=date(2013, 3, 25),
    )
    assert resolve_source_as_of(core_db, inst.id, date(2013, 3, 24)) is not None
    assert resolve_source_as_of(core_db, inst.id, date(2013, 3, 25)) is None


def test_overlapping_mappings_rejected(core_db: Session) -> None:
    inst = _instrument(core_db, "H2OVL")
    add_source_mapping(
        core_db,
        instrument_id=inst.id,
        source="MOEX",
        external_id="A",
        board="EQBR",
        valid_from=date(2013, 1, 1),
        valid_to=date(2020, 1, 1),
    )
    with pytest.raises(MappingOverlapError):
        add_source_mapping(
            core_db,
            instrument_id=inst.id,
            source="MOEX",
            external_id="B",
            board="TQBR",
            valid_from=date(2019, 6, 1),
            valid_to=date(2021, 1, 1),
        )
    add_source_mapping(
        core_db,
        instrument_id=inst.id,
        source="MOEX",
        external_id="CUR",
        board="TQBR",
        valid_from=None,
        valid_to=None,
    )
    with pytest.raises(MappingOverlapError):
        add_source_mapping(
            core_db,
            instrument_id=inst.id,
            source="MOEX",
            external_id="CUR2",
            board="SNDX",
            valid_from=None,
            valid_to=None,
        )
    with pytest.raises(InvalidMappingWindowError):
        add_source_mapping(
            core_db,
            instrument_id=inst.id,
            source="MOEX",
            external_id="BAD",
            board="TQBR",
            valid_from=None,
            valid_to=date(2020, 1, 1),
        )


def test_unknown_historical_period_does_not_return_current(core_db: Session) -> None:
    inst = _instrument(core_db, "H2UNK")
    add_source_mapping(
        core_db,
        instrument_id=inst.id,
        source="MOEX",
        external_id="H2UNK",
        board="TQBR",
        valid_from=None,
        valid_to=None,
    )
    assert resolve_current_source(core_db, inst.id) is not None
    assert resolve_source_as_of(core_db, inst.id, date(2010, 1, 1)) is None
    assert resolve_source_as_of(core_db, inst.id, date(2014, 1, 1)) is None


def test_seed_and_current_ingest_resolution_unchanged(core_db: Session) -> None:
    seed_market_universe(core_db)
    sber = core_db.scalar(select(Instrument).where(Instrument.symbol == "SBER"))
    assert sber is not None
    current = resolve_current_source(core_db, sber.id)
    assert current is not None
    assert current.external_id == "SBER"
    assert (current.board or "").upper() == "TQBR"
    assert current.valid_to is None
    loaded = MarketIngestionService(core_db)._load_instruments(["SBER"])
    assert loaded and loaded[0].id == sber.id
    resolved = resolve_current_source(core_db, loaded[0].id)
    assert resolved is not None and resolved.external_id == "SBER"


def test_h1_plzl_split_still_resolves(core_db: Session, tmp_path: Path) -> None:
    seed_market_universe(core_db)
    plzl = core_db.scalar(select(Instrument).where(Instrument.symbol == "PLZL"))
    assert plzl is not None
    assert resolve_moex_secid(core_db, "PLZL") == plzl.id
    draft = SplitEventDraft(
        secid="PLZL",
        effective_date=date(2025, 3, 27),
        split_before=Decimal("1"),
        split_after=Decimal("10"),
        adjustment_factor=Decimal("10"),
        event_type=EVENT_TYPE_SPLIT,
        raw={"tradedate": "2025-03-27", "secid": "PLZL", "before": "1", "after": "10"},
    )
    summary = SplitIngestionService(
        core_db,
        provider=_FakeSplitFeed(SplitParseResult((draft,), 0, 1)),
        raw_store=RawStore(root=str(tmp_path)),
    ).run()
    assert summary["resolved"] == 1
    assert summary["inserted"] + summary.get("updated", 0) + summary.get("unchanged", 0) == 1
    row = core_db.scalar(
        select(CorporateAction).where(
            CorporateAction.instrument_id == plzl.id,
            CorporateAction.event_type == EVENT_TYPE_SPLIT,
            CorporateAction.event_date == date(2025, 3, 27),
        )
    )
    assert row is not None
    assert row.external_id == "PLZL"


def test_migration_preserves_existing_source_rows(core_db: Session) -> None:
    before = core_db.scalar(select(func.count()).select_from(InstrumentSource)) or 0
    seed_market_universe(core_db)
    after_seed = core_db.scalar(select(func.count()).select_from(InstrumentSource)) or 0
    assert after_seed >= before
    assert after_seed >= len(INSTRUMENTS)
    current = (
        core_db.scalar(
            select(func.count()).select_from(InstrumentSource).where(InstrumentSource.valid_to.is_(None))
        )
        or 0
    )
    assert current >= len(INSTRUMENTS)


def test_dataset_uses_instrument_id_not_historical_secid(core_db: Session) -> None:
    inst = _instrument(core_db, "H2DS")
    mapping = add_source_mapping(
        core_db,
        instrument_id=inst.id,
        source="MOEX",
        external_id="OTHERSEC",
        board="TQBR",
        valid_from=None,
        valid_to=None,
    )
    current = resolve_current_source(core_db, inst.id)
    assert current is not None
    assert current.instrument_id == inst.id
    assert mapping.external_id != inst.symbol
    assert resolve_source_as_of(core_db, inst.id, date(2014, 1, 1)) is None
