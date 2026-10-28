"""Regression: /market/data-quality must honour instrument_id filter."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.v1 import market as market_api
from app.infrastructure.market.models import DataQualityIssue, Instrument


def _seed_instruments(session: Session) -> tuple[Instrument, Instrument]:
    a = Instrument(
        symbol="AAA",
        name="Alpha",
        asset_class="equity",
        exchange="MOEX",
        currency="RUB",
        is_active=True,
    )
    b = Instrument(
        symbol="BBB",
        name="Beta",
        asset_class="equity",
        exchange="MOEX",
        currency="RUB",
        is_active=True,
    )
    session.add_all([a, b])
    session.flush()
    session.add_all(
        [
            DataQualityIssue(
                instrument_id=a.id,
                issue_type="gap",
                severity="warning",
                message="gap on AAA",
                details={},
                created_at=datetime.now(UTC),
            ),
            DataQualityIssue(
                instrument_id=b.id,
                issue_type="jump",
                severity="error",
                message="jump on BBB",
                details={},
                created_at=datetime.now(UTC),
            ),
            DataQualityIssue(
                instrument_id=a.id,
                issue_type="resolved_gap",
                severity="warning",
                message="resolved AAA",
                details={},
                created_at=datetime.now(UTC),
                resolved_at=datetime.now(UTC),
            ),
        ]
    )
    session.flush()
    return a, b


@pytest.fixture
def _patch_session(core_db: Session, monkeypatch: pytest.MonkeyPatch):
    @contextmanager
    def _fake_core_session():
        yield core_db

    monkeypatch.setattr(market_api, "core_session", _fake_core_session)


def test_data_quality_filters_by_instrument_id(core_db: Session, _patch_session) -> None:
    a, b = _seed_instruments(core_db)

    body = market_api.list_data_quality(instrument_id=a.id, page_size=50)
    assert body["instrument_id"] == a.id
    assert body["total"] >= 1
    assert all(item["instrument_id"] == str(a.id) for item in body["items"])
    assert any("AAA" in item["message"] for item in body["items"])
    assert all(item["instrument_id"] != str(b.id) for item in body["items"])

    other = market_api.list_data_quality(instrument_id=b.id, page_size=50)
    assert other["total"] >= 1
    assert all(item["instrument_id"] == str(b.id) for item in other["items"])
    assert any("BBB" in item["message"] for item in other["items"])


def test_data_quality_include_resolved(core_db: Session, _patch_session) -> None:
    a, _b = _seed_instruments(core_db)
    open_only = market_api.list_data_quality(instrument_id=a.id, include_resolved=False, page_size=50)
    with_resolved = market_api.list_data_quality(
        instrument_id=a.id, include_resolved=True, page_size=50
    )
    assert with_resolved["total"] >= open_only["total"] + 1
    assert any(item.get("resolved_at") for item in with_resolved["items"])


def test_data_quality_rejects_bad_pagination(_patch_session) -> None:
    with pytest.raises(HTTPException) as page_err:
        market_api.list_data_quality(page=0)
    assert page_err.value.status_code == 422
    with pytest.raises(HTTPException) as size_err:
        market_api.list_data_quality(page_size=500)
    assert size_err.value.status_code == 422
    with pytest.raises(HTTPException) as iid_err:
        market_api.list_data_quality(instrument_id=0)
    assert iid_err.value.status_code == 422
