"""Lukoil IR declared-dividends single-sheet XLSX adapter."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from app.modules.fundamentals.domain.types import (
    KNOWN_AT_QUALITY_MEETING_DATE_PROXY,
    KNOWN_AT_QUALITY_RECORD_DATE_PROXY,
    SOURCE_ISSUER_IR_XLS_V1,
    DividendEventRef,
    DividendStatus,
)
from app.modules.fundamentals.infrastructure.issuer_ir_xlsx_dividend_provider import (
    LUKOIL_DECLARED_URL,
    PeriodKey,
    _clean_text,
    _sheet_rows,
    parse_russian_date,
)

_AGM_DOT_DATE_RE = re.compile(r"от\s+(?P<day>\d{2})\.(?P<month>\d{2})\.(?P<year>\d{4})")
_AMOUNT_SHARE_RE = re.compile(
    r"(?P<amount>[\d\s]+(?:[.,]\d+)?)\s*(?P<cls>ао|ап|ao|ap)?",
    re.IGNORECASE | re.UNICODE,
)


def parse_agm_dot_date(text: str) -> date | None:
    match = _AGM_DOT_DATE_RE.search(_clean_text(text))
    if match is None:
        return None
    try:
        return date(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
        )
    except ValueError:
        return None


def parse_lukoil_amount(raw: Any) -> tuple[float | None, str | None]:
    """Return (amount, share_class_code) from cells like ``278 ао``."""
    text = _clean_text(raw).lower().replace(",", ".")
    if not text:
        return None, None
    match = _AMOUNT_SHARE_RE.search(text)
    if match is None:
        return None, None
    amount_raw = match.group("amount").replace(" ", "")
    try:
        amount = float(amount_raw)
    except ValueError:
        return None, None
    if amount <= 0:
        return None, None
    cls = (match.group("cls") or "").lower()
    if cls in {"ао", "ao"}:
        share = "common"
    elif cls in {"ап", "ap"}:
        share = "preferred"
    else:
        share = None
    return amount, share


def lukoil_period_key(period_raw: Any, year_raw: Any) -> PeriodKey | None:
    text = _clean_text(period_raw).lower().replace("ё", "е")
    year_text = _clean_text(year_raw)
    year_match = re.search(r"(20\d{2}|19\d{2})", text) or re.search(
        r"(20\d{2}|19\d{2})", year_text
    )
    if year_match is None:
        return None
    year = int(year_match.group(1))
    if "девяти" in text or "9 м" in text or "9м" in text:
        return PeriodKey("M9", year)
    if "нераспределен" in text:
        return PeriodKey("EXTRA", year)
    return PeriodKey("FY", year)


def parse_lukoil_declared_sheet(
    payload: bytes,
    *,
    expected_share_class: str = "common",
) -> list[dict[str, Any]]:
    """Parse Lukoil single-sheet declared dividends workbook."""
    rows = _sheet_rows(payload)
    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        if i == 0 or not row or row[0] is None:
            continue
        year_raw = _clean_text(row[0])
        if not re.match(r"^\d{4}", year_raw):
            continue
        amount, share = parse_lukoil_amount(row[2] if len(row) > 2 else None)
        if amount is None:
            continue
        if share is not None and share != expected_share_class:
            continue
        if share is None and expected_share_class != "common":
            continue
        record = parse_russian_date(row[4] if len(row) > 4 else None)
        if record is None:
            continue
        period_raw = row[1] if len(row) > 1 else None
        key = lukoil_period_key(period_raw, year_raw)
        if key is None:
            continue
        agm = parse_agm_dot_date(_clean_text(period_raw))
        out.append(
            {
                "period_raw": _clean_text(period_raw),
                "period_key": key,
                "year_raw": year_raw,
                "amount_per_share": amount,
                "record_date": record,
                "shareholder_approval_date": agm,
                "share_class": share or expected_share_class,
            }
        )
    return out


def lukoil_rows_to_event_refs(
    rows: Sequence[Mapping[str, Any]],
    *,
    issuer_id: int | None,
    instrument_id: int | None,
    secid: str,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[DividendEventRef]:
    events: list[DividendEventRef] = []
    for row in rows:
        amount = row.get("amount_per_share")
        record = row.get("record_date")
        approval = row.get("shareholder_approval_date")
        if amount is None or record is None:
            continue
        if date_from is not None and record < date_from:
            continue
        if date_to is not None and record > date_to:
            continue
        if approval is not None:
            known_at = approval
            known_quality = KNOWN_AT_QUALITY_MEETING_DATE_PROXY
            known_basis = "agm_decision_date_in_period_text"
        else:
            known_at = record
            known_quality = KNOWN_AT_QUALITY_RECORD_DATE_PROXY
            known_basis = "record_date_conservative_proxy"
        period_key: PeriodKey = row["period_key"]
        meta = {
            "known_at_quality": known_quality,
            "known_at_basis": known_basis,
            "known_at_note": (
                "Lukoil IR sheet lacks disclosure timestamps; "
                "AGM date used when present in period text, else record_date "
                "as a conservative late PIT proxy."
            ),
            "secid": secid,
            "period_raw": row.get("period_raw"),
            "period_key": period_key.label(),
            "year_raw": row.get("year_raw"),
            "workbook_format": "lukoil_declared_single",
            "share_class": row.get("share_class") or "common",
            "entitlement_eligible": True,
            "source_url": LUKOIL_DECLARED_URL,
        }
        events.append(
            DividendEventRef(
                known_at=known_at,
                status=DividendStatus.APPROVED,
                source=SOURCE_ISSUER_IR_XLS_V1,
                issuer_id=issuer_id,
                instrument_id=instrument_id,
                shareholder_approval_date=approval,
                record_date=record,
                amount_per_share=float(amount),
                currency="RUB",
                metadata=meta,
            )
        )
    return events
