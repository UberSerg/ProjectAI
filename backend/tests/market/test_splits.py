"""MOEX SPLIT ingest: parse, persist, idempotency, PIT known_at, raw candles, DQ."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.infrastructure.market.models import (
    Candle,
    CorporateAction,
    DataQualityIssue,
    Instrument,
    InstrumentSource,
)
from app.infrastructure.market.moex_iss import parse_moex_splits
from app.infrastructure.market.raw_store import RawStore
from app.modules.market.application.corporate_actions import (
    SplitIngestionService,
    resolve_moex_secid,
    upsert_split_event,
)
from app.modules.market.application.data_quality import (
    DataQualityContext,
    annotate_jumps_explained_by_splits,
    run_data_quality_checks,
    split_explains_jump,
)
from app.modules.market.application.split_events import (
    EVENT_TYPE_REVERSE_SPLIT,
    EVENT_TYPE_SPLIT,
    SplitEventDraft,
    SplitParseResult,
    classify_split_factor,
    split_adjustment_factor,
)

PLZL_PAYLOAD = {
    "splits": {
        "columns": ["tradedate", "secid", "before", "after"],
        "data": [
            ["2025-03-27", "PLZL", 1, 10],
            ["2025-03-27", "FIXPLZL", 1, 10],
        ],
    }
}

ACCEPTANCE_SPLITS_PAYLOAD = {
    "splits": {
        "columns": ["tradedate", "secid", "before", "after"],
        "data": [
            ["2025-03-27", "PLZL", 1, 10],
            ["2024-02-21", "TRNFP", 1, 100],
            ["2024-04-08", "GMKN", 1, 100],
            ["2026-04-17", "T", 1, 10],
            ["2024-07-15", "VTBR", 5000, 1],
            ["2020-01-01", "NOOP", 1, 1],
        ],
    }
}

MALFORMED_PAYLOAD = {
    "splits": {
        "columns": ["tradedate", "secid", "before", "after"],
        "data": [
            ["2025-03-27", "PLZL", 1, 10],
            ["2025-03-27", "BAD0", 0, 10],
            ["2025-03-27", "BADNEG", 1, -2],
            ["not-a-date", "BADDATE", 1, 2],
            ["2025-03-27", "", 1, 2],
            ["2025-03-27", "NOAFTER", 1, None],
        ],
    }
}


class _FakeSplitFeed:
    def __init__(self, parsed: SplitParseResult) -> None:
        self.parsed = parsed

    def fetch_stock_splits(self) -> tuple[SplitParseResult, tuple[bytes, ...]]:
        return self.parsed, (b'{"splits":{"columns":[],"data":[]}}',)


def _split_draft(secid: str = "H1SPLIT") -> SplitEventDraft:
    return SplitEventDraft(
        secid=secid,
        effective_date=date(2025, 3, 27),
        split_before=Decimal("1"),
        split_after=Decimal("10"),
        adjustment_factor=Decimal("10"),
        event_type=EVENT_TYPE_SPLIT,
        known_at=None,
        raw={"tradedate": "2025-03-27", "secid": secid, "before": "1", "after": "10"},
    )


def _reverse_draft(secid: str = "H1REV") -> SplitEventDraft:
    return SplitEventDraft(
        secid=secid,
        effective_date=date(2024, 7, 15),
        split_before=Decimal("5000"),
        split_after=Decimal("1"),
        adjustment_factor=Decimal("0.0002"),
        event_type=EVENT_TYPE_REVERSE_SPLIT,
        known_at=None,
        raw={"tradedate": "2024-07-15", "secid": secid, "before": "5000", "after": "1"},
    )


def _instrument(session: Session, symbol: str, *, mapping: bool = True) -> Instrument:
    """Isolated test instrument. Do not reuse live universe tickers (PLZL already exists)."""
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
    if mapping:
        session.add(
            InstrumentSource(
                instrument_id=inst.id,
                source="MOEX",
                external_id=symbol,
                board="TQBR",
                source_metadata={},
            )
        )
        session.flush()
    return inst


def _candle(session: Session, instrument_id: int, day: date, close: Decimal) -> Candle:
    row = Candle(
        instrument_id=instrument_id,
        timeframe="1d",
        timestamp=datetime(day.year, day.month, day.day, tzinfo=UTC),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=Decimal("1000"),
        source="MOEX",
    )
    session.add(row)
    session.flush()
    return row


def test_parse_moex_splits_plzl_factor() -> None:
    parsed = parse_moex_splits(PLZL_PAYLOAD)
    assert parsed.received == 2
    assert parsed.rejected == 0
    by_secid = {item.secid: item for item in parsed.accepted}
    plzl = by_secid["PLZL"]
    assert plzl.event_type == EVENT_TYPE_SPLIT
    assert plzl.effective_date == date(2025, 3, 27)
    assert plzl.split_before == Decimal("1")
    assert plzl.split_after == Decimal("10")
    assert plzl.adjustment_factor == Decimal("10")
    assert plzl.known_at is None


def test_malformed_before_after_rejected() -> None:
    parsed = parse_moex_splits(MALFORMED_PAYLOAD)
    assert parsed.received == 6
    assert parsed.rejected == 5
    assert len(parsed.accepted) == 1
    assert parsed.accepted[0].secid == "PLZL"


def test_factor_validation_rejects_non_positive() -> None:
    with pytest.raises(ValueError, match="must be > 0"):
        split_adjustment_factor(Decimal("0"), Decimal("10"))
    with pytest.raises(ValueError, match="must be > 0"):
        split_adjustment_factor(Decimal("1"), Decimal("-1"))


def test_classify_factor_split_and_reverse() -> None:
    assert classify_split_factor(Decimal("10")) == EVENT_TYPE_SPLIT
    assert classify_split_factor(Decimal("100")) == EVENT_TYPE_SPLIT
    assert classify_split_factor(Decimal("0.0002")) == EVENT_TYPE_REVERSE_SPLIT
    assert classify_split_factor(Decimal("1")) is None


def test_parse_acceptance_classifications_and_raw_provenance() -> None:
    parsed = parse_moex_splits(ACCEPTANCE_SPLITS_PAYLOAD)
    assert parsed.received == 6
    assert parsed.rejected == 1
    by_secid = {item.secid: item for item in parsed.accepted}
    assert set(by_secid) == {"PLZL", "TRNFP", "GMKN", "T", "VTBR"}
    assert by_secid["PLZL"].event_type == EVENT_TYPE_SPLIT
    assert by_secid["PLZL"].adjustment_factor == Decimal("10")
    assert by_secid["TRNFP"].event_type == EVENT_TYPE_SPLIT
    assert by_secid["GMKN"].event_type == EVENT_TYPE_SPLIT
    assert by_secid["T"].event_type == EVENT_TYPE_SPLIT
    vtbr = by_secid["VTBR"]
    assert vtbr.event_type == EVENT_TYPE_REVERSE_SPLIT
    assert vtbr.split_before == Decimal("5000")
    assert vtbr.split_after == Decimal("1")
    assert vtbr.adjustment_factor == Decimal("1") / Decimal("5000")
    assert vtbr.raw == {"tradedate": "2024-07-15", "secid": "VTBR", "before": "5000", "after": "1"}
    assert "event_type" not in vtbr.raw
    assert by_secid["PLZL"].raw == {
        "tradedate": "2025-03-27",
        "secid": "PLZL",
        "before": "1",
        "after": "10",
    }


def test_unknown_instrument_not_auto_created(core_db: Session, tmp_path: Path) -> None:
    known = _instrument(core_db, "H1SPLIT")
    before = core_db.scalar(select(func.count()).select_from(Instrument)) or 0
    parsed = SplitParseResult(
        (_split_draft("H1SPLIT"), _split_draft("H1UNKNOWN")),
        rejected=0,
        received=2,
    )
    service = SplitIngestionService(
        core_db,
        provider=_FakeSplitFeed(parsed),
        raw_store=RawStore(root=str(tmp_path)),
    )
    summary = service.run()
    assert summary["resolved"] == 1
    assert summary["unresolved"] == 1
    assert "H1UNKNOWN" in summary["unresolved_secids"]
    assert resolve_moex_secid(core_db, "H1UNKNOWN") is None
    after = core_db.scalar(select(func.count()).select_from(Instrument)) or 0
    assert after == before
    assert core_db.scalar(select(Instrument).where(Instrument.symbol == "H1UNKNOWN")) is None
    rows = list(core_db.scalars(select(CorporateAction).where(CorporateAction.instrument_id == known.id)))
    assert len(rows) == 1


def test_idempotent_repeat_and_known_at_stays_null(core_db: Session, tmp_path: Path) -> None:
    _instrument(core_db, "H1SPLIT")
    parsed = SplitParseResult((_split_draft(),), rejected=0, received=1)
    service = SplitIngestionService(
        core_db,
        provider=_FakeSplitFeed(parsed),
        raw_store=RawStore(root=str(tmp_path)),
    )
    first = service.run()
    created_at = core_db.scalar(
        select(CorporateAction.created_at).where(CorporateAction.external_id == "H1SPLIT")
    )
    second = service.run()
    assert first["inserted"] == 1
    assert first["updated"] == 0
    assert first["unchanged"] == 0
    assert second["inserted"] == 0
    assert second["updated"] == 0
    assert second["unchanged"] == 1
    rows = list(
        core_db.scalars(select(CorporateAction).where(CorporateAction.external_id == "H1SPLIT"))
    )
    assert len(rows) == 1
    assert rows[0].known_at is None
    assert rows[0].event_type == EVENT_TYPE_SPLIT
    assert rows[0].payload["adjustment_factor"] == "10"
    assert rows[0].payload["known_at_semantics"] == "absent_from_source"
    assert rows[0].payload["raw"] == {
        "tradedate": "2025-03-27",
        "secid": "H1SPLIT",
        "before": "1",
        "after": "10",
    }
    assert rows[0].created_at == created_at
    assert rows[0].known_at is None


def test_repository_uniqueness(core_db: Session) -> None:
    inst = _instrument(core_db, "H1SPLIT")
    draft = _split_draft()
    assert upsert_split_event(core_db, inst.id, draft) == "inserted"
    core_db.flush()
    assert upsert_split_event(core_db, inst.id, draft) == "unchanged"
    core_db.flush()
    owned = core_db.scalar(
        select(func.count()).select_from(CorporateAction).where(CorporateAction.instrument_id == inst.id)
    )
    assert owned == 1
    core_db.add(
        CorporateAction(
            instrument_id=inst.id,
            event_date=date(2025, 3, 27),
            event_type=EVENT_TYPE_SPLIT,
            payload={},
            source="MOEX",
            external_id="H1SPLIT",
            known_at=None,
        )
    )
    with pytest.raises(IntegrityError):
        core_db.flush()


def test_raw_candles_unchanged(core_db: Session, tmp_path: Path) -> None:
    inst = _instrument(core_db, "H1SPLIT")
    before_close = Decimal("19011.5")
    after_close = Decimal("1890")
    _candle(core_db, inst.id, date(2025, 3, 26), before_close)
    _candle(core_db, inst.id, date(2025, 3, 27), after_close)
    service = SplitIngestionService(
        core_db,
        provider=_FakeSplitFeed(SplitParseResult((_split_draft(),), 0, 1)),
        raw_store=RawStore(root=str(tmp_path)),
    )
    service.run()
    closes = [
        row.close
        for row in core_db.scalars(
            select(Candle).where(Candle.instrument_id == inst.id).order_by(Candle.timestamp)
        )
    ]
    assert closes == [before_close, after_close]


def test_dq_jump_matches_split_effective_date(core_db: Session, tmp_path: Path) -> None:
    inst = _instrument(core_db, "H1SPLIT")
    _candle(core_db, inst.id, date(2025, 3, 26), Decimal("19011.5"))
    _candle(core_db, inst.id, date(2025, 3, 27), Decimal("1890"))
    service = SplitIngestionService(
        core_db,
        provider=_FakeSplitFeed(SplitParseResult((_split_draft(),), 0, 1)),
        raw_store=RawStore(root=str(tmp_path)),
    )
    service.run()
    assert split_explains_jump(core_db, inst.id, date(2025, 3, 27)) is True
    result = run_data_quality_checks(
        core_db,
        DataQualityContext(mode="historical", date_from=date(2025, 3, 26), date_to=date(2025, 3, 27)),
    )
    assert result["by_type"].get("abnormal_price_jump", 0) >= 1
    jump = core_db.scalar(
        select(DataQualityIssue).where(
            DataQualityIssue.issue_type == "abnormal_price_jump",
            DataQualityIssue.instrument_id == inst.id,
        )
    )
    assert jump is not None
    assert jump.details.get("explained_by_corporate_action") == EVENT_TYPE_SPLIT
    assert jump.timestamp is not None
    assert jump.timestamp.date() == date(2025, 3, 27)


def test_annotate_existing_jump_without_deleting(core_db: Session) -> None:
    inst = _instrument(core_db, "H1SPLIT")
    jump = DataQualityIssue(
        instrument_id=inst.id,
        issue_type="abnormal_price_jump",
        severity="warning",
        timestamp=datetime(2025, 3, 27, tzinfo=UTC),
        message="Close changed by 90.1% vs previous bar",
        details={"from": "19011.5", "to": "1890"},
    )
    core_db.add(jump)
    core_db.flush()
    upsert_split_event(core_db, inst.id, _split_draft())
    core_db.flush()
    assert annotate_jumps_explained_by_splits(core_db) == 1
    core_db.refresh(jump)
    assert jump.details["explained_by_corporate_action"] == EVENT_TYPE_SPLIT
    assert jump.resolved_at is None


def test_vtbr_reverse_split_persisted_and_annotates_dq(core_db: Session, tmp_path: Path) -> None:
    inst = _instrument(core_db, "H1REV")
    before_close = Decimal("0.02")
    after_close = Decimal("100")
    _candle(core_db, inst.id, date(2024, 7, 12), before_close)
    _candle(core_db, inst.id, date(2024, 7, 15), after_close)
    jump = DataQualityIssue(
        instrument_id=inst.id,
        issue_type="abnormal_price_jump",
        severity="warning",
        timestamp=datetime(2024, 7, 15, tzinfo=UTC),
        message="Close changed",
        details={"from": "0.02", "to": "100"},
    )
    core_db.add(jump)
    core_db.flush()
    service = SplitIngestionService(
        core_db,
        provider=_FakeSplitFeed(SplitParseResult((_reverse_draft(),), 0, 1)),
        raw_store=RawStore(root=str(tmp_path)),
    )
    summary = service.run()
    assert summary["inserted"] == 1
    event = core_db.scalar(select(CorporateAction).where(CorporateAction.instrument_id == inst.id))
    assert event is not None
    assert event.event_type == EVENT_TYPE_REVERSE_SPLIT
    assert event.payload["raw"] == {
        "tradedate": "2024-07-15",
        "secid": "H1REV",
        "before": "5000",
        "after": "1",
    }
    assert event.payload["adjustment_factor"] == "0.0002"
    core_db.refresh(jump)
    assert jump.details.get("explained_by_corporate_action") == EVENT_TYPE_REVERSE_SPLIT
    closes = [
        candle.close
        for candle in core_db.scalars(
            select(Candle).where(Candle.instrument_id == inst.id).order_by(Candle.timestamp)
        )
    ]
    assert closes == [before_close, after_close]


def test_reclassify_legacy_split_row_to_reverse_without_duplicate(core_db: Session) -> None:
    inst = _instrument(core_db, "H1REV")
    core_db.add(
        CorporateAction(
            instrument_id=inst.id,
            event_date=date(2024, 7, 15),
            event_type=EVENT_TYPE_SPLIT,
            payload={"split_before": "5000", "split_after": "1", "adjustment_factor": "0.0002"},
            source="MOEX",
            external_id="H1REV",
            known_at=None,
        )
    )
    core_db.flush()
    assert upsert_split_event(core_db, inst.id, _reverse_draft()) == "updated"
    core_db.flush()
    rows = list(core_db.scalars(select(CorporateAction).where(CorporateAction.instrument_id == inst.id)))
    assert len(rows) == 1
    assert rows[0].event_type == EVENT_TYPE_REVERSE_SPLIT
