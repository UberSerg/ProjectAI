"""Personal Decision Memory V1 — capture, advisory links, forward outcomes.

Two databases are involved and never mixed in one SQL statement:

* ``core_session``  — read-only: portfolio, instruments, candles, personal operations.
* ``memory_session`` — the only place where anything is written.

Commit / rollback is the caller's responsibility (``memory_session()`` context).
Nothing here creates ``PersonalOperation`` rows, talks to a broker, or mutates
Shadow / FeeEngine / Daily Decision logic. ``captured_at`` always comes from the
server clock (``now`` is injectable for tests only, never from an API client).

Retention policy (V1):
* Core ``reset_portfolio`` / holdings wipe does **not** delete Memory records —
  captured decisions remain immutable evidence (no cross-DB CASCADE exists).
* Portfolio hard-delete does **not** auto-purge Memory either; intentional Memory
  cleanup is out of scope for V1 (no orphan-scanning destructive job).
* Cross-portfolio reads/links are rejected in application code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.infrastructure.market.models import Candle, Instrument
from app.modules.market.application.intraday_cache import IntradayQuoteCache
from app.modules.market.domain.trading_calendar import MoexEquityTradingCalendar
from app.modules.market.infrastructure.ru_trading_calendar import get_moex_equity_trading_calendar
from app.modules.memory.domain.decision_memory import (
    BASELINE_AVAILABLE,
    BASELINE_UNAVAILABLE,
    ENGINE_VERSION,
    HORIZONS,
    LABEL_POSSIBLE_MATCH,
    LINK_SOURCE_USER_CONFIRMED,
    OUTCOME_BASELINE_UNAVAILABLE,
    OUTCOME_DATA_UNAVAILABLE,
    OUTCOME_PENDING,
    OUTCOME_READY,
    RETURN_TYPE_PRICE,
    canonical_hash,
    canonical_json,
    directional_alignment,
    normalize_new_cash,
    operation_side_for_action,
    price_return,
    request_fingerprint,
)
from app.modules.memory.infrastructure.models import (
    PersonalDecisionAction,
    PersonalDecisionOperationLink,
    PersonalDecisionOutcome,
    PersonalDecisionRecord,
)
from app.modules.portfolio.domain.valuation import equity_mark
from app.modules.portfolio.infrastructure.models import (
    BrokerAccount,
    FeeProfile,
    ManualPortfolio,
    PersonalOperation,
)

MSK = ZoneInfo("Europe/Moscow")

MAX_IDEMPOTENCY_KEY_LEN = 200
MAX_LIST_LIMIT = 200
DEFAULT_LIST_LIMIT = 50
MAX_MATCHES = 50
SAMPLE_WARNING_MIN = 30

SUPPORTED_BASELINE_ASSET_CLASSES = frozenset({"equity", "fund"})
PRICE_BASIS = "RAW_UNADJUSTED_CLOSE"

DISCLAIMER = (
    "Память решений фиксирует рекомендацию и цены для последующей оценки. "
    "Это не подтверждение сделки, не доходность портфеля и не гарантия результата."
)


class DecisionMemoryError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


class ConflictError(DecisionMemoryError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, http_status=409)


class NotFoundError(DecisionMemoryError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, http_status=404)


class DecisionMemoryValidationError(DecisionMemoryError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, http_status=422)


# --------------------------------------------------------------------------- helpers


def _utc_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise DecisionMemoryValidationError("NAIVE_DATETIME", "Время должно быть с часовым поясом (timezone-aware).")
    return now.astimezone(UTC)


def _iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _num(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _dec(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


def _clean_key(idempotency_key: str | None) -> str:
    key = (idempotency_key or "").strip()
    if not key:
        raise DecisionMemoryValidationError("IDEMPOTENCY_KEY_REQUIRED", "Требуется непустой заголовок Idempotency-Key.")
    if len(key) > MAX_IDEMPOTENCY_KEY_LEN:
        raise DecisionMemoryValidationError(
            "IDEMPOTENCY_KEY_TOO_LONG",
            f"Idempotency-Key длиннее {MAX_IDEMPOTENCY_KEY_LEN} символов.",
        )
    return key


def _fingerprint(portfolio_id: int, new_cash_rub: Decimal | None) -> str:
    try:
        if new_cash_rub is not None and normalize_new_cash(new_cash_rub) < 0:
            raise DecisionMemoryValidationError("NEW_CASH_NEGATIVE", "new_cash_rub не может быть отрицательным.")
        return request_fingerprint(portfolio_id, new_cash_rub)
    except (ValueError, InvalidOperation) as exc:
        raise DecisionMemoryValidationError("NEW_CASH_INVALID", "new_cash_rub должен быть конечным числом.") from exc


def _parse_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _json_roundtrip(value: Any) -> Any:
    """JSONB-safe copy of ``value`` using the same rules as the canonical hash."""
    return json.loads(canonical_json(value))


def _nth_session_after(calendar: MoexEquityTradingCalendar, start: date, n: int) -> date | None:
    cursor = start
    for _ in range(n):
        nxt = calendar.next_trading_day(cursor, inclusive=False)
        if nxt is None:
            return None
        cursor = nxt
    return cursor


# --------------------------------------------------------------------------- baseline


@dataclass(slots=True)
class _Baseline:
    status: str
    price: Decimal | None = None
    market_date: date | None = None
    source: str | None = None
    observed_at: datetime | None = None
    reason: str | None = None


def _resolve_instrument(core_session: Session, symbol: str | None) -> tuple[Instrument | None, str | None]:
    if not symbol:
        return None, "NO_SYMBOL"
    rows = list(
        core_session.scalars(select(Instrument).where(func.upper(Instrument.symbol) == symbol.strip().upper())).all()
    )
    if not rows:
        return None, "INSTRUMENT_NOT_FOUND"
    if len(rows) == 1:
        return rows[0], None
    preferred = [r for r in rows if r.is_active and (r.exchange or "").upper() == "MOEX"]
    if len(preferred) == 1:
        return preferred[0], None
    return None, "INSTRUMENT_AMBIGUOUS"


def _eod_close_asof(core_session: Session, instrument_id: int, asof: datetime) -> tuple[Decimal, datetime] | None:
    """Latest 1d close known at ``asof`` (Point-in-Time: no candles after capture)."""
    row = core_session.execute(
        select(Candle.close, Candle.timestamp)
        .where(
            Candle.instrument_id == instrument_id,
            Candle.timeframe == "1d",
            Candle.timestamp <= asof,
        )
        .order_by(Candle.timestamp.desc(), Candle.ingested_at.desc(), Candle.id.desc())
        .limit(1)
    ).first()
    if row is None or row[0] is None:
        return None
    return Decimal(str(row[0])), row[1]


def _freeze_baseline(
    core_session: Session,
    instrument: Instrument | None,
    *,
    unresolved_reason: str | None,
    captured_at: datetime,
    calendar: MoexEquityTradingCalendar,
    quote_cache: IntradayQuoteCache | None,
) -> _Baseline:
    if instrument is None:
        return _Baseline(BASELINE_UNAVAILABLE, reason=unresolved_reason or "INSTRUMENT_NOT_FOUND")
    asset = (instrument.asset_class or "").lower()
    if asset not in SUPPORTED_BASELINE_ASSET_CLASSES:
        return _Baseline(BASELINE_UNAVAILABLE, reason="ASSET_CLASS_NOT_SUPPORTED")

    msk_today = captured_at.astimezone(MSK).date()
    # Never fetch from MOEX during capture: capture must not warm/mutate caches.
    price, source, _quality = equity_mark(core_session, instrument, cache=quote_cache, allow_fetch=False)

    market_date: date | None
    observed_at: datetime | None
    if price is not None and source == "INTRADAY_LAST":
        market_date = msk_today if calendar.is_trading_day(msk_today) else calendar.previous_trading_day(msk_today)
        observed_at = captured_at
    elif price is not None and source == "PREVIOUS_CLOSE":
        market_date = calendar.previous_trading_day(msk_today)
        observed_at = captured_at
    else:
        # EOD fallback (or no mark at all): re-read bounded by ``captured_at``.
        eod = _eod_close_asof(core_session, int(instrument.id), captured_at)
        if eod is None:
            return _Baseline(BASELINE_UNAVAILABLE, reason="NO_PRICE")
        price, observed_at = eod
        source = "EOD_CLOSE"
        market_date = observed_at.date()

    if price is None or price <= 0 or market_date is None:
        return _Baseline(BASELINE_UNAVAILABLE, reason="NO_PRICE")
    return _Baseline(
        BASELINE_AVAILABLE,
        price=price,
        market_date=market_date,
        source=source,
        observed_at=observed_at,
    )


# --------------------------------------------------------------------------- serialization


def _serialize_outcome(row: PersonalDecisionOutcome) -> dict[str, Any]:
    return {
        "id": row.id,
        "decision_action_id": row.decision_action_id,
        "horizon_sessions": row.horizon_sessions,
        "status": row.status,
        "target_session_date": _iso(row.target_session_date),
        "observed_session_date": _iso(row.observed_session_date),
        "baseline_price": _num(row.baseline_price),
        "observed_price": _num(row.observed_price),
        "return_type": row.return_type,
        "forward_return": _num(row.forward_return),
        "directional_alignment": row.directional_alignment,
        "provenance": row.provenance or {},
        "refreshed_at": _iso(row.refreshed_at),
    }


def _serialize_link(row: PersonalDecisionOperationLink) -> dict[str, Any]:
    return {
        "id": row.id,
        "decision_action_id": row.decision_action_id,
        "portfolio_id": row.portfolio_id,
        "personal_operation_id": row.personal_operation_id,
        "link_source": row.link_source,
        "linked_at": _iso(row.linked_at),
        "unlinked_at": _iso(row.unlinked_at),
        "active": bool(row.active),
    }


def _serialize_action(row: PersonalDecisionAction) -> dict[str, Any]:
    return {
        "id": row.id,
        "decision_record_id": row.decision_record_id,
        "original_action_id": row.original_action_id,
        "action": row.action,
        "priority": row.priority,
        "symbol": row.symbol,
        "instrument_id": row.instrument_id,
        "reason_codes": row.reason_codes or [],
        "target_weight": _num(row.target_weight),
        "current_weight": _num(row.current_weight),
        "lots_delta": _num(row.lots_delta),
        "units_delta": _num(row.units_delta),
        "estimated_notional": _num(row.estimated_notional),
        "limitations": row.limitations or [],
        "action_payload": row.action_payload,
        "baseline": {
            "status": row.baseline_status,
            "price": _num(row.baseline_price),
            "market_date": _iso(row.baseline_market_date),
            "price_source": row.baseline_price_source,
            "observed_at": _iso(row.baseline_observed_at),
        },
        "links": [_serialize_link(x) for x in row.links],
        "outcomes": [_serialize_outcome(x) for x in row.outcomes],
    }


def _serialize_record(
    row: PersonalDecisionRecord,
    *,
    include_payload: bool,
    include_actions: bool = True,
) -> dict[str, Any]:
    payload = row.decision_payload or {}
    out: dict[str, Any] = {
        "id": row.id,
        "portfolio_id": row.portfolio_id,
        "portfolio_name_snapshot": row.portfolio_name_snapshot,
        "captured_at": _iso(row.captured_at),
        "decision_as_of": _iso(row.decision_as_of),
        "engine_version": row.engine_version,
        "new_cash_rub": _num(row.new_cash_rub),
        "status": payload.get("status"),
        "headline": payload.get("headline"),
        "canonical_hash": row.canonical_hash,
        "hash_verified": canonical_hash(payload) == row.canonical_hash,
        "idempotency_key": row.idempotency_key,
        "candidate_provenance": row.candidate_provenance or {},
        "broker_fee_provenance": row.broker_fee_provenance or {},
        "created_at": _iso(row.created_at),
        "disclaimer": DISCLAIMER,
    }
    if include_payload:
        out["decision_payload"] = payload
    if include_actions:
        out["actions"] = [_serialize_action(a) for a in row.actions]
    return out


# --------------------------------------------------------------------------- capture


def _load_record_full(memory_session: Session, record_id: int) -> PersonalDecisionRecord:
    row = memory_session.scalar(
        select(PersonalDecisionRecord)
        .options(
            selectinload(PersonalDecisionRecord.actions).selectinload(PersonalDecisionAction.links),
            selectinload(PersonalDecisionRecord.actions).selectinload(PersonalDecisionAction.outcomes),
        )
        .where(PersonalDecisionRecord.id == record_id)
        .execution_options(populate_existing=True)
    )
    if row is None:  # pragma: no cover - defensive
        raise NotFoundError("DECISION_NOT_FOUND", "Решение не найдено.")
    return row


def _existing_by_key(memory_session: Session, portfolio_id: int, key: str) -> PersonalDecisionRecord | None:
    return memory_session.scalar(
        select(PersonalDecisionRecord).where(
            PersonalDecisionRecord.portfolio_id == portfolio_id,
            PersonalDecisionRecord.idempotency_key == key,
        )
    )


def _replay_or_conflict(memory_session: Session, existing: PersonalDecisionRecord, fingerprint: str) -> dict[str, Any]:
    if existing.request_fingerprint != fingerprint:
        raise ConflictError(
            "IDEMPOTENCY_KEY_REUSED",
            "Этот Idempotency-Key уже использован с другими параметрами запроса.",
        )
    out = _serialize_record(_load_record_full(memory_session, int(existing.id)), include_payload=True)
    out["idempotent_replay"] = True
    return out


def find_existing_capture(
    memory_session: Session,
    *,
    portfolio_id: int,
    idempotency_key: str,
    new_cash_rub: Decimal | None,
) -> dict[str, Any] | None:
    """Replay lookup used by the API before rebuilding the (expensive) daily decision."""
    key = _clean_key(idempotency_key)
    fingerprint = _fingerprint(portfolio_id, new_cash_rub)
    existing = _existing_by_key(memory_session, portfolio_id, key)
    if existing is None:
        return None
    return _replay_or_conflict(memory_session, existing, fingerprint)


def _validate_payload(portfolio_id: int, payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DecisionMemoryValidationError("INVALID_DECISION_PAYLOAD", "Некорректное решение.")
    if payload.get("engine_version") != ENGINE_VERSION:
        raise DecisionMemoryValidationError(
            "ENGINE_VERSION_MISMATCH",
            f"Ожидается engine_version={ENGINE_VERSION}.",
        )
    actions = payload.get("actions")
    if not isinstance(actions, list) or any(not isinstance(a, dict) for a in actions):
        raise DecisionMemoryValidationError("INVALID_DECISION_PAYLOAD", "Список действий некорректен.")
    for a in actions:
        if not str(a.get("id") or "").strip() or not str(a.get("action") or "").strip():
            raise DecisionMemoryValidationError("INVALID_DECISION_PAYLOAD", "У действия отсутствует id или action.")
    pid = (payload.get("portfolio") or {}).get("id")
    if pid is not None and int(pid) != int(portfolio_id):
        raise DecisionMemoryValidationError("PORTFOLIO_MISMATCH", "Решение относится к другому портфелю.")
    return payload


def _fee_provenance(core_session: Session, portfolio: ManualPortfolio, payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "broker_account_id": portfolio.broker_account_id,
        "estimated_broker_fee_rub": (payload.get("new_cash_plan") or {}).get("estimated_broker_fee_rub"),
    }
    if portfolio.broker_account_id is not None:
        account = core_session.get(BrokerAccount, portfolio.broker_account_id)
        if account is not None:
            profile = core_session.get(FeeProfile, account.fee_profile_id)
            out.update(
                {
                    "broker_code": account.broker_code,
                    "tariff_name": account.tariff_name,
                    "fee_profile_id": account.fee_profile_id,
                    "fee_profile_code": profile.code if profile else None,
                    "fee_profile_version": profile.version if profile else None,
                }
            )
    return out


def _candidate_provenance(payload: dict[str, Any]) -> dict[str, Any]:
    ctx = payload.get("context") or {}
    return {
        key: ctx.get(key)
        for key in (
            "candidate_source",
            "candidate_id",
            "candidate_as_of",
            "candidate_stale",
            "candidate_freshness_known",
            "candidate_age_days",
        )
    }


def capture_decision(
    memory_session: Session,
    core_session: Session,
    *,
    portfolio_id: int,
    decision_payload: dict[str, Any],
    idempotency_key: str,
    new_cash_rub: Decimal | None,
    now: datetime | None = None,
    quote_cache: IntradayQuoteCache | None = None,
) -> dict[str, Any]:
    """Freeze an already-built Daily Personal Decision into Memory DB.

    Idempotent per ``(portfolio_id, idempotency_key)``. Caller commits.
    """
    key = _clean_key(idempotency_key)
    fingerprint = _fingerprint(portfolio_id, new_cash_rub)

    existing = _existing_by_key(memory_session, portfolio_id, key)
    if existing is not None:
        return _replay_or_conflict(memory_session, existing, fingerprint)

    captured_at = _utc_now(now)
    payload = _validate_payload(portfolio_id, decision_payload)

    portfolio = core_session.get(ManualPortfolio, portfolio_id)
    if portfolio is None:
        raise NotFoundError("PORTFOLIO_NOT_FOUND", "Портфель не найден.")

    stored_payload = _json_roundtrip(payload)
    calendar = get_moex_equity_trading_calendar()

    record = PersonalDecisionRecord(
        portfolio_id=portfolio_id,
        portfolio_name_snapshot=portfolio.name,
        captured_at=captured_at,
        decision_as_of=_parse_date(payload.get("as_of")),
        engine_version=ENGINE_VERSION,
        new_cash_rub=normalize_new_cash(new_cash_rub) if new_cash_rub is not None else None,
        decision_payload=stored_payload,
        canonical_hash=canonical_hash(stored_payload),
        idempotency_key=key,
        request_fingerprint=fingerprint,
        candidate_provenance=_json_roundtrip(_candidate_provenance(payload)),
        broker_fee_provenance=_json_roundtrip(_fee_provenance(core_session, portfolio, payload)),
    )

    try:
        with memory_session.begin_nested():
            memory_session.add(record)
            memory_session.flush()
            for raw in stored_payload["actions"]:
                _add_action(
                    memory_session,
                    core_session,
                    record=record,
                    raw=raw,
                    captured_at=captured_at,
                    calendar=calendar,
                    quote_cache=quote_cache,
                )
            memory_session.flush()
    except IntegrityError:
        # Concurrent capture with the same key: the other transaction won.
        again = _existing_by_key(memory_session, portfolio_id, key)
        if again is None:
            raise
        return _replay_or_conflict(memory_session, again, fingerprint)

    out = _serialize_record(_load_record_full(memory_session, int(record.id)), include_payload=True)
    out["idempotent_replay"] = False
    return out


def _add_action(
    memory_session: Session,
    core_session: Session,
    *,
    record: PersonalDecisionRecord,
    raw: dict[str, Any],
    captured_at: datetime,
    calendar: MoexEquityTradingCalendar,
    quote_cache: IntradayQuoteCache | None,
) -> None:
    symbol = (str(raw["symbol"]).strip().upper() if raw.get("symbol") else None) or None
    instrument, unresolved = _resolve_instrument(core_session, symbol)
    baseline = _freeze_baseline(
        core_session,
        instrument,
        unresolved_reason=unresolved,
        captured_at=captured_at,
        calendar=calendar,
        quote_cache=quote_cache,
    )
    action = PersonalDecisionAction(
        decision_record_id=record.id,
        original_action_id=str(raw["id"]),
        action=str(raw["action"]),
        priority=raw.get("priority"),
        symbol=symbol,
        instrument_id=int(instrument.id) if instrument is not None else None,
        reason_codes=list(raw.get("reason_codes") or []),
        target_weight=_dec(raw.get("target_weight")),
        current_weight=_dec(raw.get("current_weight")),
        lots_delta=_dec(raw.get("lots_delta")),
        units_delta=_dec(raw.get("units_delta")),
        estimated_notional=_dec(raw.get("estimated_notional")),
        limitations=list(raw.get("limitations") or []),
        action_payload=raw,
        baseline_price=baseline.price,
        baseline_market_date=baseline.market_date,
        baseline_price_source=baseline.source,
        baseline_observed_at=baseline.observed_at,
        baseline_status=baseline.status,
    )
    memory_session.add(action)
    memory_session.flush()

    for horizon in HORIZONS:
        if baseline.status == BASELINE_AVAILABLE and baseline.market_date is not None:
            outcome = PersonalDecisionOutcome(
                decision_action_id=action.id,
                horizon_sessions=horizon,
                status=OUTCOME_PENDING,
                target_session_date=_nth_session_after(calendar, baseline.market_date, horizon),
                baseline_price=baseline.price,
                return_type=RETURN_TYPE_PRICE,
                provenance={
                    "calendar_version": calendar.version,
                    "baseline_price_source": baseline.source,
                    "price_basis": PRICE_BASIS,
                },
            )
        else:
            outcome = PersonalDecisionOutcome(
                decision_action_id=action.id,
                horizon_sessions=horizon,
                status=OUTCOME_BASELINE_UNAVAILABLE,
                return_type=RETURN_TYPE_PRICE,
                provenance={"reason": baseline.reason or "NO_BASELINE"},
            )
        memory_session.add(outcome)


# --------------------------------------------------------------------------- reads


def list_decisions(memory_session: Session, portfolio_id: int, limit: int = DEFAULT_LIST_LIMIT) -> dict[str, Any]:
    limit = max(1, min(int(limit), MAX_LIST_LIMIT))
    rows = list(
        memory_session.scalars(
            select(PersonalDecisionRecord)
            .options(selectinload(PersonalDecisionRecord.actions))
            .where(PersonalDecisionRecord.portfolio_id == portfolio_id)
            .order_by(PersonalDecisionRecord.captured_at.desc(), PersonalDecisionRecord.id.desc())
            .limit(limit)
        ).all()
    )
    items = []
    for row in rows:
        item = _serialize_record(row, include_payload=False, include_actions=False)
        item["actions_count"] = len(row.actions)
        items.append(item)
    return {"portfolio_id": portfolio_id, "items": items, "count": len(items)}


def get_decision(memory_session: Session, portfolio_id: int, decision_id: int) -> dict[str, Any]:
    row = memory_session.scalar(
        select(PersonalDecisionRecord).where(
            PersonalDecisionRecord.id == decision_id,
            PersonalDecisionRecord.portfolio_id == portfolio_id,
        )
    )
    if row is None:
        raise NotFoundError("DECISION_NOT_FOUND", "Решение не найдено.")
    return _serialize_record(_load_record_full(memory_session, int(row.id)), include_payload=True)


def _load_action(
    memory_session: Session, portfolio_id: int, action_id: int
) -> tuple[PersonalDecisionAction, PersonalDecisionRecord]:
    row = memory_session.execute(
        select(PersonalDecisionAction, PersonalDecisionRecord)
        .join(
            PersonalDecisionRecord,
            PersonalDecisionRecord.id == PersonalDecisionAction.decision_record_id,
        )
        .where(
            PersonalDecisionAction.id == action_id,
            PersonalDecisionRecord.portfolio_id == portfolio_id,
        )
    ).first()
    if row is None:
        raise NotFoundError("DECISION_ACTION_NOT_FOUND", "Действие решения не найдено.")
    return row[0], row[1]


# --------------------------------------------------------------------------- operation links


def _operation_window(
    memory_session: Session, record: PersonalDecisionRecord, now: datetime
) -> tuple[datetime, datetime, str]:
    """[captured_at, upper): next capture of the same portfolio, else ``now``."""
    next_capture = memory_session.scalar(
        select(func.min(PersonalDecisionRecord.captured_at)).where(
            PersonalDecisionRecord.portfolio_id == record.portfolio_id,
            (PersonalDecisionRecord.captured_at > record.captured_at)
            | ((PersonalDecisionRecord.captured_at == record.captured_at) & (PersonalDecisionRecord.id > record.id)),
        )
    )
    if next_capture is not None and next_capture <= now:
        return record.captured_at, next_capture, "NEXT_CAPTURE"
    return record.captured_at, now, "NOW"


def _operation_matches_action(
    op: PersonalOperation,
    action: PersonalDecisionAction,
    *,
    lower: datetime,
    upper: datetime,
    upper_inclusive: bool,
) -> str | None:
    """Return a human-readable rejection reason, or ``None`` when compatible."""
    side = operation_side_for_action(action.action)
    if side is None:
        return "Для этого типа действия связь с операцией не поддерживается."
    if action.instrument_id is None:
        return "Инструмент действия не определён."
    if op.status != "ACTIVE":
        return "Операция отменена или заменена."
    if op.operation_type != side:
        return "Направление операции не совпадает с рекомендацией."
    if op.instrument_id != action.instrument_id:
        return "Инструмент операции не совпадает с рекомендацией."
    occurred = op.occurred_at if op.occurred_at.tzinfo else op.occurred_at.replace(tzinfo=UTC)
    if occurred < lower:
        return "Операция произошла раньше фиксации решения."
    if occurred > upper or (occurred == upper and not upper_inclusive):
        return "Операция вне окна между фиксацией решения и следующей фиксацией."
    return None


def list_possible_operation_matches(
    memory_session: Session,
    core_session: Session,
    portfolio_id: int,
    decision_action_id: int,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Advisory candidates only (label POSSIBLE_MATCH). Never creates a link."""
    current = _utc_now(now)
    action, record = _load_action(memory_session, portfolio_id, decision_action_id)
    lower, upper, upper_kind = _operation_window(memory_session, record, current)
    base: dict[str, Any] = {
        "decision_action_id": action.id,
        "action": action.action,
        "window": {"from": _iso(lower), "to": _iso(upper), "upper_bound": upper_kind},
        "matches": [],
        "reason": None,
        "disclaimer": DISCLAIMER,
    }
    side = operation_side_for_action(action.action)
    if side is None:
        base["reason"] = "ACTION_NOT_LINKABLE"
        return base
    if action.instrument_id is None:
        base["reason"] = "INSTRUMENT_UNRESOLVED"
        return base

    stmt = (
        select(PersonalOperation)
        .where(
            PersonalOperation.portfolio_id == portfolio_id,
            PersonalOperation.status == "ACTIVE",
            PersonalOperation.operation_type == side,
            PersonalOperation.instrument_id == action.instrument_id,
            PersonalOperation.occurred_at >= lower,
            PersonalOperation.occurred_at <= upper,
        )
        .order_by(PersonalOperation.occurred_at.asc(), PersonalOperation.id.asc())
        .limit(MAX_MATCHES)
    )
    if upper_kind == "NEXT_CAPTURE":
        stmt = stmt.where(PersonalOperation.occurred_at < upper)
    ops = list(core_session.scalars(stmt).all())

    linked_ids = set(
        memory_session.scalars(
            select(PersonalDecisionOperationLink.personal_operation_id).where(
                PersonalDecisionOperationLink.decision_action_id == action.id,
                PersonalDecisionOperationLink.active.is_(True),
            )
        ).all()
    )
    base["matches"] = [
        {
            "label": LABEL_POSSIBLE_MATCH,
            "personal_operation_id": op.id,
            "operation_type": op.operation_type,
            "occurred_at": _iso(op.occurred_at),
            "instrument_id": op.instrument_id,
            "lots": _num(op.lots),
            "units": _num(op.units),
            "price": _num(op.price),
            "amount": _num(op.amount),
            "commission": _num(op.commission),
            "already_linked": op.id in linked_ids,
        }
        for op in ops
    ]
    return base


def confirm_operation_link(
    memory_session: Session,
    core_session: Session,
    *,
    portfolio_id: int,
    decision_action_id: int,
    personal_operation_id: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """User-confirmed advisory link. Idempotent for an already active pair. Caller commits."""
    current = _utc_now(now)
    action, record = _load_action(memory_session, portfolio_id, decision_action_id)

    op = core_session.get(PersonalOperation, personal_operation_id)
    if op is None or int(op.portfolio_id) != int(portfolio_id):
        raise NotFoundError("OPERATION_NOT_FOUND", "Операция не найдена в этом портфеле.")

    lower, upper, upper_kind = _operation_window(memory_session, record, current)
    reason = _operation_matches_action(op, action, lower=lower, upper=upper, upper_inclusive=upper_kind == "NOW")
    if reason is not None:
        raise DecisionMemoryValidationError("OPERATION_NOT_COMPATIBLE", reason)

    active = memory_session.scalar(
        select(PersonalDecisionOperationLink).where(
            PersonalDecisionOperationLink.decision_action_id == action.id,
            PersonalDecisionOperationLink.personal_operation_id == personal_operation_id,
            PersonalDecisionOperationLink.active.is_(True),
        )
    )
    if active is not None:
        out = _serialize_link(active)
        out["already_linked"] = True
        return out

    link = PersonalDecisionOperationLink(
        decision_action_id=action.id,
        portfolio_id=portfolio_id,
        personal_operation_id=personal_operation_id,
        link_source=LINK_SOURCE_USER_CONFIRMED,
        linked_at=current,
        active=True,
    )
    try:
        with memory_session.begin_nested():
            memory_session.add(link)
            memory_session.flush()
    except IntegrityError:
        again = memory_session.scalar(
            select(PersonalDecisionOperationLink).where(
                PersonalDecisionOperationLink.decision_action_id == action.id,
                PersonalDecisionOperationLink.personal_operation_id == personal_operation_id,
                PersonalDecisionOperationLink.active.is_(True),
            )
        )
        if again is None:
            raise
        out = _serialize_link(again)
        out["already_linked"] = True
        return out
    out = _serialize_link(link)
    out["already_linked"] = False
    return out


def unlink_operation_link(
    memory_session: Session,
    *,
    portfolio_id: int,
    link_id: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Soft-unlink (history kept). Idempotent. Never touches the journal operation."""
    current = _utc_now(now)
    link = memory_session.scalar(
        select(PersonalDecisionOperationLink).where(
            PersonalDecisionOperationLink.id == link_id,
            PersonalDecisionOperationLink.portfolio_id == portfolio_id,
        )
    )
    if link is None:
        raise NotFoundError("LINK_NOT_FOUND", "Связь не найдена.")
    if link.active:
        link.active = False
        link.unlinked_at = current
        memory_session.flush()
    return _serialize_link(link)


# --------------------------------------------------------------------------- outcomes


def _observed_close(core_session: Session, instrument_id: int, session_date: date) -> tuple[Decimal, str] | None:
    start = datetime(session_date.year, session_date.month, session_date.day, tzinfo=UTC)
    row = core_session.execute(
        select(Candle.close, Candle.source)
        .where(
            Candle.instrument_id == instrument_id,
            Candle.timeframe == "1d",
            Candle.timestamp >= start,
            Candle.timestamp < start + timedelta(days=1),
        )
        .order_by(Candle.ingested_at.desc(), Candle.id.desc())
        .limit(1)
    ).first()
    if row is None or row[0] is None:
        return None
    close = Decimal(str(row[0]))
    if close <= 0:
        return None
    return close, str(row[1])


def refresh_outcomes(
    memory_session: Session,
    core_session: Session,
    portfolio_id: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate matured horizons. READY rows are final; PENDING/DATA_UNAVAILABLE are re-checked.

    A horizon matures only when its target session is strictly before today (MSK),
    so an unfinished session is never used. Price return is raw close-to-close
    (no dividend / split adjustment). Caller commits.
    """
    current = _utc_now(now)
    today_msk = current.astimezone(MSK).date()
    calendar = get_moex_equity_trading_calendar()

    stmt = (
        select(PersonalDecisionOutcome, PersonalDecisionAction)
        .join(
            PersonalDecisionAction,
            PersonalDecisionAction.id == PersonalDecisionOutcome.decision_action_id,
        )
        .join(
            PersonalDecisionRecord,
            PersonalDecisionRecord.id == PersonalDecisionAction.decision_record_id,
        )
        .where(
            PersonalDecisionOutcome.status.in_([OUTCOME_PENDING, OUTCOME_DATA_UNAVAILABLE]),
            PersonalDecisionAction.baseline_status == BASELINE_AVAILABLE,
        )
        .order_by(PersonalDecisionOutcome.id)
    )
    if portfolio_id is not None:
        stmt = stmt.where(PersonalDecisionRecord.portfolio_id == portfolio_id)

    counters = {"evaluated": 0, "ready": 0, "data_unavailable": 0, "still_pending": 0}
    for outcome, action in memory_session.execute(stmt).all():
        counters["evaluated"] += 1
        baseline = action.baseline_price
        if action.instrument_id is None or action.baseline_market_date is None or baseline is None or baseline <= 0:
            outcome.status = OUTCOME_BASELINE_UNAVAILABLE
            outcome.refreshed_at = current
            continue

        target = outcome.target_session_date or _nth_session_after(
            calendar, action.baseline_market_date, outcome.horizon_sessions
        )
        if target is None or target >= today_msk:
            outcome.target_session_date = target
            counters["still_pending"] += 1
            continue
        outcome.target_session_date = target

        observed = _observed_close(core_session, int(action.instrument_id), target)
        outcome.refreshed_at = current
        if observed is None:
            outcome.status = OUTCOME_DATA_UNAVAILABLE
            counters["data_unavailable"] += 1
            continue

        close, candle_source = observed
        fwd = price_return(Decimal(str(baseline)), close)
        outcome.status = OUTCOME_READY
        outcome.observed_session_date = target
        outcome.baseline_price = baseline
        outcome.observed_price = close
        outcome.return_type = RETURN_TYPE_PRICE
        outcome.forward_return = fwd
        outcome.directional_alignment = directional_alignment(action.action, fwd)
        outcome.provenance = {
            **(outcome.provenance or {}),
            "calendar_version": calendar.version,
            "candle_source": candle_source,
            "price_basis": PRICE_BASIS,
            "adjusted_for_dividends_or_splits": False,
        }
        counters["ready"] += 1

    memory_session.flush()
    return {
        "portfolio_id": portfolio_id,
        "refreshed_at": _iso(current),
        **counters,
    }


# --------------------------------------------------------------------------- summary


def get_summary(memory_session: Session, portfolio_id: int) -> dict[str, Any]:
    records = memory_session.scalar(
        select(func.count())
        .select_from(PersonalDecisionRecord)
        .where(PersonalDecisionRecord.portfolio_id == portfolio_id)
    )
    rows = memory_session.execute(
        select(PersonalDecisionOutcome, PersonalDecisionAction.action)
        .join(
            PersonalDecisionAction,
            PersonalDecisionAction.id == PersonalDecisionOutcome.decision_action_id,
        )
        .join(
            PersonalDecisionRecord,
            PersonalDecisionRecord.id == PersonalDecisionAction.decision_record_id,
        )
        .where(PersonalDecisionRecord.portfolio_id == portfolio_id)
    ).all()
    actions_count = memory_session.scalar(
        select(func.count())
        .select_from(PersonalDecisionAction)
        .join(
            PersonalDecisionRecord,
            PersonalDecisionRecord.id == PersonalDecisionAction.decision_record_id,
        )
        .where(PersonalDecisionRecord.portfolio_id == portfolio_id)
    )
    linked_actions = memory_session.scalar(
        select(func.count(func.distinct(PersonalDecisionOperationLink.decision_action_id))).where(
            PersonalDecisionOperationLink.portfolio_id == portfolio_id,
            PersonalDecisionOperationLink.active.is_(True),
        )
    )

    horizons: list[dict[str, Any]] = []
    for horizon in HORIZONS:
        subset = [(o, a) for o, a in rows if o.horizon_sessions == horizon]
        by_status = {
            s: sum(1 for o, _ in subset if o.status == s)
            for s in (
                OUTCOME_PENDING,
                OUTCOME_READY,
                OUTCOME_DATA_UNAVAILABLE,
                OUTCOME_BASELINE_UNAVAILABLE,
            )
        }
        ready = [(o, a) for o, a in subset if o.status == OUTCOME_READY and o.forward_return is not None]
        directional = [o for o, _ in ready if o.directional_alignment is not None]
        aligned = sum(1 for o in directional if o.directional_alignment == "ALIGNED")
        mean_ret = sum((Decimal(str(o.forward_return)) for o, _ in ready), Decimal("0")) / len(ready) if ready else None
        horizons.append(
            {
                "horizon_sessions": horizon,
                "status_counts": by_status,
                "ready_count": len(ready),
                "directional_ready_count": len(directional),
                "aligned_count": aligned,
                "not_aligned_count": len(directional) - aligned,
                "alignment_rate": (
                    format((Decimal(aligned) / Decimal(len(directional))).quantize(Decimal("0.0001")), "f")
                    if directional
                    else None
                ),
                "mean_price_return": (
                    format(mean_ret.quantize(Decimal("0.00000001")), "f") if mean_ret is not None else None
                ),
                "sample_warning": len(directional) < SAMPLE_WARNING_MIN,
            }
        )
    return {
        "portfolio_id": portfolio_id,
        "engine_version": ENGINE_VERSION,
        "decisions_count": int(records or 0),
        "actions_count": int(actions_count or 0),
        "linked_actions_count": int(linked_actions or 0),
        "return_type": RETURN_TYPE_PRICE,
        "horizons": horizons,
        "limitations": [
            "PRICE_RETURN_UNADJUSTED_FOR_DIVIDENDS_AND_SPLITS",
            "NOT_PORTFOLIO_PERFORMANCE",
            "SMALL_SAMPLE_NOT_STATISTICAL_EVIDENCE",
            "LINKS_ARE_ADVISORY_USER_CONFIRMED",
        ],
        "disclaimer": DISCLAIMER,
    }
