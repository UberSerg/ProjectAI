"""Bank refresh stores CBR evidence; reads and captures do not call the network."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Instrument
from app.modules.intelligence.banks.metrics import INDUSTRIAL_RATIO_CODES
from app.modules.intelligence.banks.providers import CbrCreditOrgRef
from app.modules.intelligence.committee.refresh import refresh_committee
from app.modules.intelligence.fundamentals.refresh import refresh_fundamentals
from app.modules.intelligence.fundamentals.service import build_fundamental_snapshot
from app.modules.intelligence.prospective.capture import read_prospective_capture
from app.modules.intelligence.signals.collect import collect_instrument_signals
from app.modules.intelligence.signals.fundamental import FundamentalModelV1
from tests.intelligence.banks.test_sber_cbr_soap import _FIXTURES


def _instrument(session: Session) -> Instrument:
    row = Instrument(
        symbol=f"BNK{uuid4().hex[:6].upper()}",
        name="Bank runtime fixture",
        asset_class="equity",
        exchange="MOEX",
        currency="RUB",
        is_active=True,
    )
    session.add(row)
    session.flush()
    return row


def _patch_bank(monkeypatch: pytest.MonkeyPatch, symbol: str, calls: list[str]) -> None:
    is_bank = lambda secid: str(secid).upper() == symbol  # noqa: E731
    monkeypatch.setattr(
        "app.modules.intelligence.banks.classification.is_bank_fi_secid",
        is_bank,
    )
    monkeypatch.setattr(
        "app.modules.intelligence.banks.snapshot.is_bank_fi_secid",
        is_bank,
    )
    monkeypatch.setattr(
        "app.modules.intelligence.banks.service.is_bank_fi_secid",
        is_bank,
    )
    monkeypatch.setattr(
        "app.modules.intelligence.fundamentals.service.BANK_FI_SECIDS",
        frozenset({symbol}),
    )
    monkeypatch.setattr(
        "app.modules.intelligence.banks.service.CBR_CREDIT_ORG_BY_SECID",
        {symbol: CbrCreditOrgRef(secid=symbol, regnum="1481", ogrn="1027700132195")},
    )

    def _fetch(*, regnum: str, timeout_s: float = 60.0) -> dict[str, str]:
        calls.append(regnum)
        return dict(_FIXTURES)

    monkeypatch.setattr(
        "app.modules.intelligence.banks.service.fetch_cbr_soap_bundle",
        _fetch,
    )


def test_force_refresh_stores_partial_cbr_and_get_does_not_fetch(
    core_db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instrument = _instrument(core_db)
    calls: list[str] = []
    _patch_bank(monkeypatch, instrument.symbol, calls)
    as_of = datetime.now(UTC).date()

    skipped = refresh_fundamentals(
        core_db,
        {"instrument_ids": [instrument.id], "as_of": as_of.isoformat(), "live_fetch": False},
    )
    assert skipped["bank_live_fetch"] is False
    assert calls == []

    live = refresh_fundamentals(
        core_db,
        {"instrument_ids": [instrument.id], "as_of": as_of.isoformat(), "live_fetch": True},
    )
    assert calls == ["1481"]
    bank = live["banks"][0]
    assert bank["issuer_kind"] == "BANK_FI"
    assert bank["status"] == "PARTIAL"
    assert bank["period_end"] == "2026-09-01"
    assert bank["known_at"] != bank["period_end"]
    assert not (set(bank["metric_codes"]) & INDUSTRIAL_RATIO_CODES)

    def _explode(**_kwargs: object) -> dict[str, str]:
        raise AssertionError("GET snapshot must not call CBR")

    monkeypatch.setattr(
        "app.modules.intelligence.banks.service.fetch_cbr_soap_bundle",
        _explode,
    )
    stored = build_fundamental_snapshot(core_db, instrument.id, as_of)
    assert stored.issuer_kind == "BANK_FI"
    assert stored.status == "PARTIAL"
    assert stored.known_at != stored.period_end
    assert "EQUITY" in stored.metrics
    assert not (set(stored.metrics) & INDUSTRIAL_RATIO_CODES)

    signals = collect_instrument_signals(
        instrument_id=instrument.id,
        as_of=as_of,
        session=core_db,
    )
    assert signals is not None
    fundamental = next(item for item in signals if item.model_id == "FundamentalModelV1")
    bank_signal = next(item for item in signals if item.model_id == "BankModelV1")
    assert fundamental.state == "ABSTAIN"
    assert fundamental.abstain_reason == "bank_industrial_metrics_unsupported"
    assert bank_signal.state == "ABSTAIN"
    assert bank_signal.semantic == "BANK_FI"
    assert bank_signal.abstain_reason == "bank_partial_metrics_insufficient"
    assert "bank_universe_metrics_not_available" not in (bank_signal.abstain_reason or "")
    direct = FundamentalModelV1().evaluate(
        instrument_id=instrument.id,
        as_of=as_of,
        snapshot=stored.to_dict(),
    )
    assert direct.state == "ABSTAIN"


def test_second_prospective_capture_does_not_rewrite_the_first(core_db: Session) -> None:
    instrument = _instrument(core_db)
    ctx = {
        "instrument_ids": [instrument.id],
        "as_of": datetime.now(UTC).date().isoformat(),
        "live_fetch": True,
    }
    first = refresh_committee(core_db, ctx)
    second = refresh_committee(core_db, ctx)
    first_id = first["captures"][0]["id"]
    second_id = second["captures"][0]["id"]
    assert first_id != second_id
    first_hash = first["captures"][0]["payload_hash"]
    read_back = read_prospective_capture(core_db, first_id)
    assert read_back is not None
    assert read_back["hash_matches"] is True
    assert read_back["payload_hash"] == first_hash
    assert read_back["payload"]["coverage_not_accuracy"] is True
    assert "win_rate" not in read_back["payload"]
    again = read_prospective_capture(core_db, first_id)
    assert again is not None
    assert again["payload_hash"] == first_hash
    assert again["payload"]["captured_at"] == read_back["payload"]["captured_at"]
