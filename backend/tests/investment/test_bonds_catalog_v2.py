"""Bonds Catalog V2 — pagination + master-only detail."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.modules.investment.application.bonds_catalog import (
    bonds_catalog_v2,
    get_bond_detail_v2,
)
from app.modules.investment.domain.credit_intelligence import CreditAvailabilityStatus


def _instr(iid: int, symbol: str, *, subtype: str = "corporate_bond", active: bool = True):
    return SimpleNamespace(
        id=iid,
        symbol=symbol,
        name=f"Bond {symbol}",
        asset_class="bond",
        currency="RUB",
        is_active=active,
        support_level="FULL",
        instrument_subtype=subtype,
        primary_board="TQCB",
    )


def test_bonds_catalog_pagination_and_master_only(monkeypatch) -> None:
    i1 = _instr(1, "AAA1")
    i2 = _instr(2, "SU26238", subtype="ofz_gov")
    term_gov = SimpleNamespace(
        instrument_id=2,
        bond_type="Government",
        currency="RUB",
        nominal=1000,
        lot_size=1,
        maturity_date=date(2030, 1, 1),
        support_status="SUPPORTED",
        raw_fields={},
    )

    session = MagicMock()

    # count + page rows + summary scalars + per-row credit/cashflow
    call = {"n": 0}

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

        def first(self):
            return self._rows[0] if self._rows else None

    def _execute(stmt):
        call["n"] += 1
        text = str(stmt)
        if "count" in text.lower() and call["n"] <= 2:
            return _Result([])
        # page query returns master-only + government with term
        return _Result([(i1, None), (i2, term_gov)])

    session.execute.side_effect = _execute
    session.scalar.side_effect = lambda *a, **k: 0

    monkeypatch.setattr(
        "app.modules.investment.application.bonds_catalog._catalog_summary",
        lambda _s: {
            "active": 2,
            "valuation_ready": 1,
            "cashflow_ready": 0,
            "credit_ready": 0,
            "ofz": 1,
            "corporate": 1,
            "government_debt": 1,
            "source_not_ready": 1,
        },
    )

    def _credit(_session, *, instrument_id, symbol, bond_type, subtype=None):
        if bond_type == "Government" or (subtype or "").startswith("ofz"):
            return {
                "credit_available": False,
                "is_government_debt": True,
                "availability_status": CreditAvailabilityStatus.GOVERNMENT_RUSSIAN_FEDERAL.value,
                "credit_status": CreditAvailabilityStatus.GOVERNMENT_RUSSIAN_FEDERAL.value,
                "risk_flags": ["GOVERNMENT_DEBT"],
            }
        return {
            "credit_available": False,
            "is_government_debt": False,
            "availability_status": CreditAvailabilityStatus.SOURCE_NOT_READY.value,
            "credit_status": CreditAvailabilityStatus.SOURCE_NOT_READY.value,
            "risk_flags": ["SOURCE_NOT_READY"],
        }

    monkeypatch.setattr(
        "app.modules.investment.application.bonds_catalog.resolve_instrument_credit",
        _credit,
    )

    # Force total via scalar override for count subquery
    session.scalar = MagicMock(side_effect=[2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])

    result = bonds_catalog_v2(session, page=1, page_size=10)
    assert result["catalog_version"] == "bonds_v2"
    assert result["page"] == 1
    assert result["page_size"] == 10
    assert len(result["items"]) == 2
    master = next(i for i in result["items"] if i["symbol"] == "AAA1")
    assert master["master_only"] is True
    assert master["valuation_available"] is False
    gov = next(i for i in result["items"] if i["symbol"] == "SU26238")
    assert gov["is_government_debt"] is True
    assert any(b["label"] == "Государственный долг" for b in gov["badges"])


def test_master_only_detail_returns_payload(monkeypatch) -> None:
    instrument = _instr(5, "MASTER1")
    session = MagicMock()
    session.scalar.side_effect = [instrument, None, 0, None]

    monkeypatch.setattr(
        "app.modules.investment.application.bonds_catalog.resolve_instrument_credit",
        lambda *_a, **_k: {
            "credit_available": False,
            "is_government_debt": False,
            "availability_status": CreditAvailabilityStatus.SOURCE_NOT_READY.value,
            "credit_status": CreditAvailabilityStatus.SOURCE_NOT_READY.value,
            "risk_flags": ["SOURCE_NOT_READY"],
        },
    )

    detail = get_bond_detail_v2(session, "MASTER1")
    assert detail is not None
    assert detail["symbol"] == "MASTER1"
    assert detail["master_only"] is True
    assert detail["cashflows"] == []
    assert "SOURCE_NOT_READY" in detail["why_kraken_ru"] or "master" in detail["why_kraken_ru"].lower()
