"""Acceptance instrument resolution must use Instrument Master, not hardcoded IDs."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.modules.intelligence.application.instrument_resolve import (
    DEFAULT_ACCEPTANCE_SYMBOLS,
    resolve_acceptance_set,
    resolve_equity_by_symbol,
)


def test_default_acceptance_symbols() -> None:
    assert DEFAULT_ACCEPTANCE_SYMBOLS == ("SBER", "LKOH", "MGNT")


def test_resolve_equity_by_symbol_queries_moex_equity() -> None:
    session = MagicMock()
    instrument = SimpleNamespace(id=42, symbol="SBER")
    session.scalars.return_value.first.return_value = instrument
    assert resolve_equity_by_symbol(session, "SBER") is instrument
    assert session.scalars.called


def test_resolve_acceptance_set_skips_missing() -> None:
    session = MagicMock()
    sber = SimpleNamespace(id=1, symbol="SBER")

    def _first_side_effect():
        # each scalars().first() call
        pass

    # Return SBER then None then LKOH-like
    results = [sber, None, SimpleNamespace(id=3, symbol="MGNT")]
    session.scalars.return_value.first.side_effect = results
    found = resolve_acceptance_set(session)
    assert [x.symbol for x in found] == ["SBER", "MGNT"]
