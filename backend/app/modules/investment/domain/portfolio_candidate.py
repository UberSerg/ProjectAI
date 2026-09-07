"""Portfolio Candidate V1 — research orchestration types (no parallel trading rules)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import uuid4

CANDIDATE_VERSION = "PORTFOLIO_CANDIDATE_V1"


class PortfolioCandidateStatus(StrEnum):
    READY_FOR_RESEARCH = "READY_FOR_RESEARCH"
    PARTIAL = "PARTIAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    BLOCKED_BY_RISK = "BLOCKED_BY_RISK"
    STALE = "STALE"


@dataclass(frozen=True)
class SleeveMoney:
    target_weight: float
    actual_weight: float
    target_rub: Decimal
    actual_rub: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_weight": self.target_weight,
            "actual_weight": self.actual_weight,
            "target_rub": str(self.target_rub),
            "actual_rub": str(self.actual_rub),
            "difference_rub": str(self.actual_rub - self.target_rub),
        }


@dataclass(frozen=True)
class CashBreakdown:
    strategic_target_rub: Decimal
    strategic_target_weight: float
    lot_remainder_rub: Decimal
    total_cash_rub: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategic_target_rub": str(self.strategic_target_rub),
            "strategic_target_weight": self.strategic_target_weight,
            "lot_remainder_rub": str(self.lot_remainder_rub),
            "total_cash_rub": str(self.total_cash_rub),
            "note_ru": (
                "Целевой Cash — осознанное решение. Остаток из-за лотов — техническое округление."
            ),
        }


@dataclass(frozen=True)
class CandidatePosition:
    symbol: str
    display_name: str
    sleeve: str
    asset_class: str
    lots: int
    units: int
    reference_price: Decimal
    estimated_notional: Decimal
    estimated_fees: Decimal
    target_weight: float
    actual_weight: float
    risk_status: str
    executable: bool
    reason_ru: str
    warnings_ru: tuple[str, ...] = ()
    credit_status: str | None = None
    liquidity_status: str | None = None
    confidence_label_ru: str | None = None
    instrument_id: int | None = None
    selection_rank: int | None = None
    lot_size: int | None = None
    eligibility: str | None = None
    bond_type: str | None = None
    dirty_price: Decimal | None = None
    nkd: Decimal | None = None
    coupon_rate: float | None = None
    maturity_date: str | None = None
    yield_value: float | None = None
    signal_semantic: str | None = None
    signal_value: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "reference_price",
            "estimated_notional",
            "estimated_fees",
            "dirty_price",
            "nkd",
        ):
            if payload.get(key) is not None:
                payload[key] = str(payload[key])
        payload["warnings_ru"] = list(self.warnings_ru)
        return payload


@dataclass(frozen=True)
class RejectedCandidate:
    symbol: str
    display_name: str
    sleeve: str
    opportunity_hint: str | None
    risk_status: str
    reason_ru: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def human_confidence_label(level: str | None) -> str:
    raw = (level or "UNKNOWN").upper()
    mapping = {
        "HIGH": "Высокое",
        "MEDIUM": "Среднее",
        "LOW": "Низкое",
        "UNKNOWN": "Недостаточно данных",
        "INSUFFICIENT_SAMPLE": "Недостаточно данных",
    }
    return mapping.get(raw, "Недостаточно данных")


def classify_candidate_status(
    *,
    gate_status: str,
    has_positions: bool,
    stale: bool,
    insufficient: bool,
) -> PortfolioCandidateStatus:
    if stale:
        return PortfolioCandidateStatus.STALE
    if insufficient:
        return PortfolioCandidateStatus.INSUFFICIENT_DATA
    gate = gate_status.upper()
    if gate == "BLOCKED":
        return PortfolioCandidateStatus.BLOCKED_BY_RISK
    if gate in {"INSUFFICIENT_DATA"}:
        return PortfolioCandidateStatus.INSUFFICIENT_DATA
    if not has_positions and gate == "RESEARCH_ONLY":
        return PortfolioCandidateStatus.PARTIAL
    if gate in {"APPROVED", "APPROVED_WITH_WARNINGS", "RESEARCH_ONLY"}:
        return (
            PortfolioCandidateStatus.READY_FOR_RESEARCH
            if has_positions or gate != "BLOCKED"
            else PortfolioCandidateStatus.PARTIAL
        )
    return PortfolioCandidateStatus.PARTIAL


def build_sleeve_money(
    *,
    capital: Decimal,
    target_weight: float,
    actual_rub: Decimal,
) -> SleeveMoney:
    target_rub = (capital * Decimal(str(target_weight))).quantize(Decimal("0.01"))
    actual_weight = float(actual_rub / capital) if capital > 0 else 0.0
    return SleeveMoney(
        target_weight=target_weight,
        actual_weight=actual_weight,
        target_rub=target_rub,
        actual_rub=actual_rub.quantize(Decimal("0.01")),
    )


def diff_candidates(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    if previous is None:
        return {
            "has_previous": False,
            "summary_ru": "Это первый сохранённый кандидат портфеля.",
            "changes": [],
        }
    changes: list[dict[str, Any]] = []
    prev_alloc = previous.get("allocation") or {}
    cur_alloc = current.get("allocation") or {}
    for key, label in (
        ("equity", "Акции"),
        ("fixed_income", "Облигации"),
        ("cash", "Деньги"),
    ):
        prev_w = (prev_alloc.get(key) or {}).get("target_weight")
        cur_w = (cur_alloc.get(key) or {}).get("target_weight")
        if prev_w is not None and cur_w is not None and abs(float(prev_w) - float(cur_w)) > 1e-9:
            changes.append(
                {
                    "kind": "allocation_weight",
                    "sleeve": key,
                    "label_ru": label,
                    "from": prev_w,
                    "to": cur_w,
                    "text_ru": f"{label}: {float(prev_w) * 100:.0f}% → {float(cur_w) * 100:.0f}%",
                }
            )
    prev_pos = {p.get("symbol"): p for p in previous.get("positions") or []}
    cur_pos = {p.get("symbol"): p for p in current.get("positions") or []}
    prev_syms = set(prev_pos)
    cur_syms = set(cur_pos)
    for sym in sorted(prev_syms - cur_syms):
        changes.append(
            {
                "kind": "position_removed",
                "symbol": sym,
                "text_ru": f"Позиция {sym} исключена.",
            }
        )
    for sym in sorted(cur_syms - prev_syms):
        changes.append(
            {
                "kind": "position_added",
                "symbol": sym,
                "text_ru": f"Позиция {sym} добавлена.",
            }
        )
    for sym in sorted(prev_syms & cur_syms):
        prev_lots = int(prev_pos[sym].get("lots") or 0)
        cur_lots = int(cur_pos[sym].get("lots") or 0)
        if prev_lots != cur_lots:
            changes.append(
                {
                    "kind": "lots_changed",
                    "symbol": sym,
                    "from": prev_lots,
                    "to": cur_lots,
                    "text_ru": f"{sym}: {prev_lots} → {cur_lots} лот(ов).",
                }
            )
        prev_status = prev_pos[sym].get("risk_status")
        cur_status = cur_pos[sym].get("risk_status")
        if prev_status and cur_status and prev_status != cur_status:
            changes.append(
                {
                    "kind": "risk_status_changed",
                    "symbol": sym,
                    "from": prev_status,
                    "to": cur_status,
                    "text_ru": f"{sym}: Risk Gate {prev_status} → {cur_status}.",
                }
            )
    prev_cash = float(((previous.get("cash") or {}).get("total_cash_rub")) or 0)
    cur_cash = float(((current.get("cash") or {}).get("total_cash_rub")) or 0)
    if abs(prev_cash - cur_cash) > 0.5:
        changes.append(
            {
                "kind": "cash_changed",
                "from": prev_cash,
                "to": cur_cash,
                "text_ru": f"Cash: {prev_cash:,.0f} → {cur_cash:,.0f} ₽",
            }
        )
    prev_h = previous.get("benchmark", {}).get("cbr_hurdle_annual")
    cur_h = current.get("benchmark", {}).get("cbr_hurdle_annual")
    if prev_h is not None and cur_h is not None and abs(float(prev_h) - float(cur_h)) > 1e-9:
        changes.append(
            {
                "kind": "hurdle",
                "from": prev_h,
                "to": cur_h,
                "text_ru": f"CBR hurdle: {float(prev_h) * 100:.2f}% → {float(cur_h) * 100:.2f}%",
            }
        )
    return {
        "has_previous": True,
        "previous_candidate_id": previous.get("candidate_id"),
        "summary_ru": (
            "Изменения относительно прошлого кандидата."
            if changes
            else "Существенных изменений относительно прошлого кандидата нет."
        ),
        "changes": changes,
    }


def new_candidate_id() -> str:
    return f"pc_{uuid4().hex[:12]}"


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def parse_as_of(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
