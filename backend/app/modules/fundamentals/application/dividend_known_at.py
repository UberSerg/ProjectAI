"""Dividend known_at quality breakdown + lifecycle regression helpers."""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.fundamentals.domain.types import (
    KNOWN_AT_QUALITY_APPROXIMATE_PUBLICATION_PROXY,
    KNOWN_AT_QUALITY_EXACT_PUBLICATION_TIMESTAMP,
    KNOWN_AT_QUALITY_MEETING_DATE_PROXY,
    KNOWN_AT_QUALITY_RECORD_DATE_PROXY,
    KNOWN_AT_QUALITY_SOURCE_PUBLICATION_DATE,
    KNOWN_AT_QUALITY_UNKNOWN,
    DividendEventRef,
    DividendStatus,
)


def classify_known_at_quality(metadata: dict[str, Any] | None) -> str:
    meta = dict(metadata or {})
    raw = str(meta.get("known_at_quality") or KNOWN_AT_QUALITY_UNKNOWN)
    return raw


def dividend_known_at_quality_report(session: Session) -> dict[str, Any]:
    from app.modules.fundamentals.infrastructure.models import DividendEvent, fundamentals_schema_ready

    if not fundamentals_schema_ready(session):
        return {"status": "NOT_READY", "events": 0}
    rows = list(session.scalars(select(DividendEvent)))
    counts: Counter[str] = Counter()
    by_secid: dict[str, Counter[str]] = {}
    for row in rows:
        meta = dict(getattr(row, "metadata_", None) or {})
        quality = classify_known_at_quality(meta)
        counts[quality] += 1
        secid = str(meta.get("secid") or "?")
        by_secid.setdefault(secid, Counter())[quality] += 1
    exact = counts.get(KNOWN_AT_QUALITY_EXACT_PUBLICATION_TIMESTAMP, 0)
    official_date = counts.get(KNOWN_AT_QUALITY_SOURCE_PUBLICATION_DATE, 0)
    high_quality = exact + official_date
    total = sum(counts.values())
    return {
        "status": "PARTIAL" if total else "NOT_READY",
        "events": total,
        "exact_publication_datetime": exact,
        "official_publication_date": official_date,
        "meeting_proxy": counts.get(KNOWN_AT_QUALITY_MEETING_DATE_PROXY, 0)
        + counts.get(KNOWN_AT_QUALITY_APPROXIMATE_PUBLICATION_PROXY, 0),
        "record_date_proxy": counts.get(KNOWN_AT_QUALITY_RECORD_DATE_PROXY, 0),
        "unknown": counts.get(KNOWN_AT_QUALITY_UNKNOWN, 0),
        "high_quality_share": (high_quality / total) if total else 0.0,
        "by_quality": dict(counts),
        "by_secid": {k: dict(v) for k, v in by_secid.items()},
        "notes": [
            "Exact disclosure timestamps remain unavailable from lawful free feeds "
            "(e-disclosure 403; MOEX sitenews search does not filter issuer dividends).",
            "Meeting/approval dates are proxies, not publication clocks.",
        ],
    }


def synthetic_recommendation_then_approval_revision() -> list[DividendEventRef]:
    """Regression fixture: recommendation 100 then approval 80 — distinct known_at states."""
    return [
        DividendEventRef(
            known_at=date(2024, 5, 1),
            status=DividendStatus.RECOMMENDED,
            source="TEST_LIFECYCLE",
            board_recommendation_date=date(2024, 5, 1),
            amount_per_share=100.0,
            currency="RUB",
            version=1,
            metadata={
                "known_at_quality": KNOWN_AT_QUALITY_MEETING_DATE_PROXY,
                "lifecycle": "board_recommendation",
            },
        ),
        DividendEventRef(
            known_at=date(2024, 6, 15),
            status=DividendStatus.APPROVED,
            source="TEST_LIFECYCLE",
            board_recommendation_date=date(2024, 5, 1),
            shareholder_approval_date=date(2024, 6, 15),
            record_date=date(2024, 7, 1),
            amount_per_share=80.0,
            currency="RUB",
            version=2,
            metadata={
                "known_at_quality": KNOWN_AT_QUALITY_MEETING_DATE_PROXY,
                "lifecycle": "shareholder_approval_revision",
                "supersedes_recommendation_amount": 100.0,
            },
        ),
    ]
