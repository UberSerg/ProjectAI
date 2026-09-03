"""H2.1 MOEX source-window sync (no live network)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import CorporateAction, Instrument
from app.infrastructure.market.moex_iss import parse_moex_security_boards
from app.infrastructure.market.raw_store import RawStore
from app.modules.market.application.corporate_actions import SplitIngestionService, resolve_moex_secid
from app.modules.market.application.identity import (
    add_source_mapping,
    resolve_current_source,
    resolve_source_as_of,
)
from app.modules.market.application.source_windows import (
    SourceWindowSyncService,
    normalize_source_windows,
)
from app.modules.market.application.split_events import EVENT_TYPE_SPLIT, SplitEventDraft, SplitParseResult


def _boards(secid: str, rows: list[list]) -> dict:
    return {
        "description": {"columns": ["name", "value"], "data": [["SECID", secid]]},
        "boards": {
            "columns": [
                "secid",
                "boardid",
                "market",
                "history_from",
                "history_till",
                "listed_from",
                "listed_till",
                "is_primary",
                "is_traded",
            ],
            "data": rows,
        },
    }


SBER_LIKE = _boards(
    "H21SB",
    [
        ["H21SB", "TQBR", "shares", "2013-03-25", "2026-09-02", "2013-03-25", "2026-09-03", 1, 1],
        ["H21SB", "EQBR", "shares", "2011-11-21", "2013-08-30", "2011-11-21", "2013-08-30", 0, 0],
        ["H21SB", "SMAL", "shares", "2011-11-21", "2025-07-31", "2011-11-21", "2025-08-01", 0, 0],
    ],
)

T_LIKE = _boards(
    "H21T",
    [["H21T", "TQBR", "shares", "2024-11-28", "2026-09-02", "2024-11-28", "2026-09-03", 1, 1]],
)

PLZL_LIKE = _boards(
    "H21PL",
    [["H21PL", "TQBR", "shares", "2014-06-09", "2026-09-02", "2014-06-09", "2026-09-03", 1, 1]],
)

class _FakeBoardFeed:
    def __init__(self, by_secid: dict[str, list]) -> None:
        self.by_secid = by_secid

    def fetch_security_boards(self, secid: str):
        return self.by_secid[secid], b"{}"


class _FakeSplitFeed:
    def __init__(self, parsed: SplitParseResult) -> None:
        self.parsed = parsed

    def fetch_stock_splits(self) -> tuple[SplitParseResult, tuple[bytes, ...]]:
        return self.parsed, (b"{}",)


def _instrument(session: Session, symbol: str, board: str = "TQBR") -> Instrument:
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
    add_source_mapping(
        session,
        instrument_id=inst.id,
        source="MOEX",
        external_id=symbol,
        board=board,
        valid_from=None,
        valid_to=None,
    )
    return inst


def test_parse_moex_board_windows_uses_history_fields() -> None:
    boards = parse_moex_security_boards(SBER_LIKE)
    tqbr = next(row for row in boards if row.board == "TQBR")
    eqbr = next(row for row in boards if row.board == "EQBR")
    assert tqbr.history_from == date(2013, 3, 25)
    assert tqbr.listed_from == date(2013, 3, 25)
    assert eqbr.history_from == date(2011, 11, 21)
    assert eqbr.history_till == date(2013, 8, 30)
    assert tqbr.is_primary is True


def test_overlap_normalization_clips_eqbr_to_tqbr_history_from() -> None:
    drafts, notes = normalize_source_windows(
        current_secid="H21SB",
        current_board="TQBR",
        boards=parse_moex_security_boards(SBER_LIKE),
    )
    assert notes == []
    by_board = {item.board: item for item in drafts}
    assert by_board["TQBR"].valid_from == date(2013, 3, 25)
    assert by_board["TQBR"].valid_to is None
    assert by_board["EQBR"].valid_from == date(2011, 11, 21)
    assert by_board["EQBR"].valid_to == date(2013, 3, 25)
    assert "SMAL" not in by_board


def test_later_listed_does_not_resolve_before_history_from(core_db: Session, tmp_path: Path) -> None:
    inst = _instrument(core_db, "H21T")
    SourceWindowSyncService(
        core_db,
        provider=_FakeBoardFeed({"H21T": parse_moex_security_boards(T_LIKE)}),
        raw_store=RawStore(root=str(tmp_path)),
        pause_seconds=0,
    ).run(symbols=["H21T"])
    current = resolve_current_source(core_db, inst.id)
    assert current is not None and current.valid_from == date(2024, 11, 28)
    assert resolve_source_as_of(core_db, inst.id, date(2014, 1, 1)) is None
    assert resolve_source_as_of(core_db, inst.id, date(2025, 1, 1)) is not None


def test_sber_windows_current_and_as_of(core_db: Session, tmp_path: Path) -> None:
    inst = _instrument(core_db, "H21SB")
    SourceWindowSyncService(
        core_db,
        provider=_FakeBoardFeed({"H21SB": parse_moex_security_boards(SBER_LIKE)}),
        raw_store=RawStore(root=str(tmp_path)),
        pause_seconds=0,
    ).run(symbols=["H21SB"])
    assert resolve_current_source(core_db, inst.id).board == "TQBR"
    assert resolve_source_as_of(core_db, inst.id, date(2014, 1, 1)).board == "TQBR"
    assert resolve_source_as_of(core_db, inst.id, date(2012, 6, 1)).board == "EQBR"
    assert resolve_source_as_of(core_db, inst.id, date(2010, 1, 1)) is None


def test_repeat_sync_idempotent(core_db: Session, tmp_path: Path) -> None:
    _instrument(core_db, "H21SB")
    service = SourceWindowSyncService(
        core_db,
        provider=_FakeBoardFeed({"H21SB": parse_moex_security_boards(SBER_LIKE)}),
        raw_store=RawStore(root=str(tmp_path)),
        pause_seconds=0,
    )
    first = service.run(symbols=["H21SB"])
    second = service.run(symbols=["H21SB"])
    assert first["inserted"] >= 1
    assert second["inserted"] == 0
    assert second["updated"] == 0
    assert second["unchanged"] >= 1


def test_unknown_board_not_guessed(core_db: Session, tmp_path: Path) -> None:
    inst = _instrument(core_db, "H21UNK")
    empty = parse_moex_security_boards({"boards": {"columns": ["boardid"], "data": []}})
    summary = SourceWindowSyncService(
        core_db,
        provider=_FakeBoardFeed({"H21UNK": empty}),
        raw_store=RawStore(root=str(tmp_path)),
        pause_seconds=0,
    ).run(symbols=["H21UNK"])
    assert summary["unknown"] == 1
    current = resolve_current_source(core_db, inst.id)
    assert current is not None
    assert current.valid_from is None
    assert resolve_source_as_of(core_db, inst.id, date(2014, 1, 1)) is None


def test_foreign_secid_not_merged(core_db: Session, tmp_path: Path) -> None:
    inst = _instrument(core_db, "H21T")
    mixed = _boards(
        "H21T",
        [
            ["H21T", "TQBR", "shares", "2024-11-28", "2026-09-02", "2024-11-28", "2026-09-03", 1, 1],
            ["TCSG", "TQBR", "shares", "2019-10-18", "2024-11-27", "2019-10-18", "2024-11-27", 0, 0],
        ],
    )
    summary = SourceWindowSyncService(
        core_db,
        provider=_FakeBoardFeed({"H21T": parse_moex_security_boards(mixed)}),
        raw_store=RawStore(root=str(tmp_path)),
        pause_seconds=0,
    ).run(symbols=["H21T"])
    assert summary["identity_change_candidates"]
    assert summary["identity_change_candidates"][0]["foreign_secids"] == ["TCSG"]
    assert resolve_source_as_of(core_db, inst.id, date(2020, 1, 1)) is None
    assert resolve_source_as_of(core_db, inst.id, date(2025, 1, 1)).external_id == "H21T"


def test_h1_split_still_resolves_after_windows(core_db: Session, tmp_path: Path) -> None:
    inst = _instrument(core_db, "H21PL")
    SourceWindowSyncService(
        core_db,
        provider=_FakeBoardFeed({"H21PL": parse_moex_security_boards(PLZL_LIKE)}),
        raw_store=RawStore(root=str(tmp_path)),
        pause_seconds=0,
    ).run(symbols=["H21PL"])
    assert resolve_moex_secid(core_db, "H21PL") == inst.id
    assert resolve_source_as_of(core_db, inst.id, date(2014, 1, 1)) is None
    assert resolve_source_as_of(core_db, inst.id, date(2015, 1, 1)) is not None
    draft = SplitEventDraft(
        secid="H21PL",
        effective_date=date(2025, 3, 27),
        split_before=Decimal("1"),
        split_after=Decimal("10"),
        adjustment_factor=Decimal("10"),
        event_type=EVENT_TYPE_SPLIT,
        raw={"tradedate": "2025-03-27", "secid": "H21PL", "before": "1", "after": "10"},
    )
    summary = SplitIngestionService(
        core_db,
        provider=_FakeSplitFeed(SplitParseResult((draft,), 0, 1)),
        raw_store=RawStore(root=str(tmp_path)),
    ).run()
    assert summary["resolved"] == 1
    rows = list(
        core_db.scalars(
            select(CorporateAction).where(
                CorporateAction.instrument_id == inst.id,
                CorporateAction.event_date == date(2025, 3, 27),
            )
        )
    )
    assert len(rows) == 1
