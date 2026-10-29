"""Portfolio Hub batch valuations: Missing ≠ Zero; full NAV only when complete."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.modules.portfolio.application.hub_valuation import build_hub_valuations


def _book(pid: int, cash: str, *, name: str = "P") -> SimpleNamespace:
    return SimpleNamespace(
        id=pid,
        name=name,
        cash_rub=Decimal(cash),
        is_test=False,
        updated_at=None,
    )


def _pos(pid: int, iid: int, units: str = "10") -> SimpleNamespace:
    return SimpleNamespace(id=iid * 10, portfolio_id=pid, instrument_id=iid, units=Decimal(units))


def _inst(iid: int) -> SimpleNamespace:
    return SimpleNamespace(id=iid, symbol=f"T{iid}", name=f"T{iid}", asset_class="equity")


def test_cash_only_total_equals_cash() -> None:
    session = MagicMock()
    book = _book(1, "3.340000")
    session.scalars.side_effect = [
        MagicMock(all=lambda: [book]),
        MagicMock(all=lambda: []),
    ]
    out = build_hub_valuations(session, portfolio_ids=[1])
    assert len(out) == 1
    row = out[0]
    assert row["valuation_complete"] is True
    assert Decimal(row["total_nav_rub"]) == Decimal("3.34")
    assert Decimal(row["cash_rub"]) == Decimal("3.34")
    assert Decimal(row["securities_value_rub"]) == Decimal("0")
    assert row["positions_count"] == 0


def test_full_marks_sum_cash_and_securities() -> None:
    session = MagicMock()
    book = _book(2, "100000")
    positions = [_pos(2, 10), _pos(2, 11)]
    session.scalars.side_effect = [
        MagicMock(all=lambda: [book]),
        MagicMock(all=lambda: positions),
        MagicMock(__iter__=lambda self: iter([_inst(10), _inst(11)])),
    ]

    def mark(_session, instrument, units, **_kwargs):  # noqa: ANN001
        if int(instrument.id) == 10:
            return Decimal("25000"), Decimal("250000"), "2026-10-28", "equity", "EOD", None
        return Decimal("0"), Decimal("0"), "2026-10-28", "equity", "EOD", None

    with (
        patch(
            "app.modules.portfolio.application.hub_valuation.ensure_operational_quotes"
        ),
        patch(
            "app.modules.portfolio.application.hub_valuation._personal_mark",
            side_effect=mark,
        ),
    ):
        # Simplify: one equity 250k MV
        session.scalars.side_effect = [
            MagicMock(all=lambda: [book]),
            MagicMock(all=lambda: [_pos(2, 10)]),
            MagicMock(__iter__=lambda self: iter([_inst(10)])),
        ]
        out = build_hub_valuations(session, portfolio_ids=[2])
    row = out[0]
    assert row["valuation_complete"] is True
    assert Decimal(row["total_nav_rub"]) == Decimal("350000")
    assert Decimal(row["cash_rub"]) == Decimal("100000")
    assert Decimal(row["securities_value_rub"]) == Decimal("250000")


def test_partial_does_not_expose_total_nav() -> None:
    session = MagicMock()
    book = _book(3, "100000")
    session.scalars.side_effect = [
        MagicMock(all=lambda: [book]),
        MagicMock(all=lambda: [_pos(3, 1), _pos(3, 2)]),
        MagicMock(__iter__=lambda self: iter([_inst(1), _inst(2)])),
    ]

    def mark(_session, instrument, units, **_kwargs):  # noqa: ANN001
        if int(instrument.id) == 1:
            return Decimal("10"), Decimal("100"), "2026-10-28", "equity", "LAST", None
        return None, None, None, "equity", None, "NO_QUOTE"

    with (
        patch(
            "app.modules.portfolio.application.hub_valuation.ensure_operational_quotes"
        ),
        patch(
            "app.modules.portfolio.application.hub_valuation._personal_mark",
            side_effect=mark,
        ),
    ):
        out = build_hub_valuations(session, portfolio_ids=[3])
    row = out[0]
    assert row["valuation_complete"] is False
    assert row["valuation_partial"] is True
    assert row["total_nav_rub"] is None
    assert Decimal(row["known_nav_rub"]) == Decimal("100100")
    assert row["missing_price_count"] == 1


def test_explicit_ids_exclude_test_portfolios_by_default() -> None:
    session = MagicMock()
    real = _book(10, "100")
    captured: dict[str, object] = {}

    def scalars(stmt):  # noqa: ANN001
        if "stmt" not in captured:
            captured["stmt"] = stmt
            return MagicMock(all=lambda: [real])
        return MagicMock(all=lambda: [])

    session.scalars.side_effect = scalars
    out = build_hub_valuations(session, portfolio_ids=[10, 11], include_test=False)
    assert [row["portfolio_id"] for row in out] == [10]
    compiled = str(captured["stmt"].compile(compile_kwargs={"literal_binds": True}))
    assert "is_test" in compiled.lower() or "false" in compiled.lower()


def test_all_quotes_missing_unavailable() -> None:
    session = MagicMock()
    book = _book(4, "50000")
    session.scalars.side_effect = [
        MagicMock(all=lambda: [book]),
        MagicMock(all=lambda: [_pos(4, 7)]),
        MagicMock(__iter__=lambda self: iter([_inst(7)])),
    ]

    with (
        patch(
            "app.modules.portfolio.application.hub_valuation.ensure_operational_quotes"
        ),
        patch(
            "app.modules.portfolio.application.hub_valuation._personal_mark",
            return_value=(None, None, None, "equity", None, "NO_QUOTE"),
        ),
    ):
        out = build_hub_valuations(session, portfolio_ids=[4])
    row = out[0]
    assert row["valuation_unavailable"] is True
    assert row["total_nav_rub"] is None
    assert Decimal(row["known_nav_rub"]) == Decimal("50000")
