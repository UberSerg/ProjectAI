"""Dividend provider port — readiness without inventing data.

MOEX ISS dividend endpoints remain REJECTED (description / candles, not dividend tables).
No accepted public provider is wired for ingest in this stage.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.fundamentals.domain.total_return import (
    DividendCashPoint,
    compute_gross_total_return,
)


@dataclass(frozen=True, slots=True)
class DividendProviderRecord:
    """Normalized dividend observation from an accepted provider (future)."""

    symbol: str
    ex_date: date
    amount_per_share: float | None
    currency: str | None = None
    known_at: date | None = None
    record_date: date | None = None
    source: str | None = None
    external_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class DividendProvider(Protocol):
    """Port for a lawful, audited dividend history source."""

    name: str

    def fetch_dividends(self, symbol: str) -> Sequence[DividendProviderRecord]:
        ...

    def readiness(self) -> dict[str, Any]:
        ...


class NotReadyDividendProvider:
    """Default provider — documents why ingest is blocked."""

    name = "NOT_READY"

    def __init__(self, *, reasons: Sequence[str] | None = None) -> None:
        self._reasons = list(
            reasons
            or (
                "moex_iss_securities_dividends_rejected",
                "moex_iss_history_dividends_rejected",
                "no_accepted_public_provider_in_env",
            )
        )

    def fetch_dividends(self, symbol: str) -> Sequence[DividendProviderRecord]:
        return ()

    def readiness(self) -> dict[str, Any]:
        return {
            "status": "NOT_READY",
            "provider": self.name,
            "accepted": False,
            "reasons": list(self._reasons),
            "notes": [
                "MOEX ISS /iss/securities/{SECID}/dividends.json returns security description, not dividends.",
                "MOEX ISS history/.../dividends returns candle history, not dividend records.",
                "Do not invent ex-dates or amounts. Dataset/features must not gain dividends.",
            ],
            "as_of": date.today().isoformat(),
        }


def get_dividend_provider() -> DividendProvider:
    """Resolve provider from env/repo. Currently always NOT_READY."""
    from app.core.config import get_settings

    settings = get_settings()
    if not settings.dividend_sync_enabled:
        return NotReadyDividendProvider(
            reasons=(
                "DIVIDEND_SYNC_ENABLED=false",
                "moex_iss_dividends_rejected",
                "no_accepted_public_provider_in_env",
            )
        )
    # Even if flag is on, no accepted implementation exists yet.
    return NotReadyDividendProvider(
        reasons=(
            "DIVIDEND_SYNC_ENABLED=true_but_no_accepted_provider_implementation",
            "moex_iss_dividends_rejected",
        )
    )


def dividend_coverage_v2(session: Session) -> dict[str, Any]:
    from app.infrastructure.market.models import Candle, Instrument
    from app.modules.fundamentals.application.total_return import build_dividend_coverage_report

    provider = get_dividend_provider()
    provider_ready = provider.readiness()
    base = build_dividend_coverage_report(session)
    payload = base.to_dict()
    payload["provider"] = provider_ready
    payload["verdict"] = "NOT_READY" if not provider_ready.get("accepted") else payload.get("quality")
    payload["ingest_enabled"] = False
    payload["dataset_mutation"] = False
    # Richer readiness fields for System Data Coverage.
    eq_with_candles = int(
        session.scalar(
            select(func.count(func.distinct(Candle.instrument_id)))
            .select_from(Candle)
            .join(Instrument, Instrument.id == Candle.instrument_id)
            .where(Instrument.asset_class == "equity", Candle.timeframe == "1d")
        )
        or 0
    )
    payload["instruments_with_price_history"] = max(
        int(payload.get("instruments_with_price_history") or 0),
        eq_with_candles,
    )
    payload["generated_at"] = datetime.now(UTC).isoformat()
    return payload


def total_return_readiness_report(session: Session) -> dict[str, Any]:
    """Richer total-return readiness for artifact + API."""
    from app.modules.fundamentals.application.total_return import build_dividend_coverage_report
    from app.modules.fundamentals.infrastructure.models import DividendEvent

    cov = build_dividend_coverage_report(session)
    provider = get_dividend_provider().readiness()
    events = int(session.scalar(select(func.count()).select_from(DividendEvent)) or 0)

    # Wire domain compute with real events when present (fixture path for tests).
    sample_tr = None
    if events > 0:
        row = session.execute(
            select(DividendEvent).where(DividendEvent.amount_per_share.is_not(None)).limit(5)
        ).scalars().all()
        points = [
            DividendCashPoint(
                ex_date=r.ex_date,
                amount_per_share=float(r.amount_per_share) if r.amount_per_share is not None else None,
                currency=r.currency,
                known_at=r.known_at if isinstance(r.known_at, date) else None,
                status=r.status,
            )
            for r in row
            if getattr(r, "ex_date", None) is not None
        ]
        if points:
            sample_tr = compute_gross_total_return(
                start_date=date(2025, 1, 1),
                end_date=date(2026, 1, 1),
                start_price=100.0,
                end_price=100.0,
                dividends=points,
            ).to_dict()

    return {
        "quality": cov.quality.value,
        "verdict": "NOT_READY" if not provider.get("accepted") and events == 0 else cov.quality.value,
        "provider": provider,
        "dividend_coverage": cov.to_dict(),
        "dividend_events_stored": events,
        "sample_total_return_with_stored_events": sample_tr,
        "compute_gross_total_return_wired": True,
        "dataset_mutation": False,
        "training": False,
        "generated_at": datetime.now(UTC).isoformat(),
        "notes": [
            "compute_gross_total_return accepts real DividendEvent rows when present.",
            "Empty store → price-only / NOT_READY coverage; no fabricated dividends.",
        ],
    }


def write_total_return_readiness_artifact(session: Session, path=None):
    import json
    from pathlib import Path

    report = total_return_readiness_report(session)
    root = Path(__file__).resolve().parents[5]
    target = path or (root / ".tmp" / "fixed-income-dividend-enrichment-v2" / "total-return-readiness.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def load_dividend_cash_points(
    session: Session,
    *,
    instrument_id: int,
    start_date: date,
    end_date: date,
) -> list[DividendCashPoint]:
    """Load real DividendEvent rows for total-return computation (empty OK)."""
    from app.modules.fundamentals.infrastructure.models import DividendEvent

    rows = session.scalars(
        select(DividendEvent).where(
            DividendEvent.instrument_id == instrument_id,
            DividendEvent.ex_date > start_date,
            DividendEvent.ex_date <= end_date,
        )
    ).all()
    return [
        DividendCashPoint(
            ex_date=r.ex_date,
            amount_per_share=float(r.amount_per_share) if r.amount_per_share is not None else None,
            currency=getattr(r, "currency", None),
            known_at=r.known_at if isinstance(getattr(r, "known_at", None), date) else None,
            status=getattr(r, "status", None),
        )
        for r in rows
        if r.ex_date is not None
    ]


def compute_instrument_gross_total_return(
    session: Session,
    *,
    instrument_id: int,
    start_date: date,
    end_date: date,
    start_price: float | None,
    end_price: float | None,
) -> dict[str, Any]:
    dividends = load_dividend_cash_points(
        session,
        instrument_id=instrument_id,
        start_date=start_date,
        end_date=end_date,
    )
    result = compute_gross_total_return(
        start_date=start_date,
        end_date=end_date,
        start_price=start_price,
        end_price=end_price,
        dividends=dividends,
    )
    payload = result.to_dict()
    payload["dividends_loaded_from_db"] = len(dividends)
    return payload
