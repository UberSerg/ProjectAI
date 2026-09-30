"""Personal Decision Memory V1 — capture, idempotency, links, forward outcomes.

DB tests need both Core and Memory databases with migrations applied; they skip
otherwise. Everything runs inside rolled-back transactions and never touches
live MOEX / CBR / Redis.
"""

from __future__ import annotations

import importlib.util
import inspect
import re
from collections.abc import Generator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.domain.ports.intraday_market import IntradayQuote, MarketSessionStatus, QuoteFreshness
from app.infrastructure.market.models import Base as CoreBase
from app.infrastructure.market.models import Candle, Instrument, InstrumentSource
from app.modules.market.application.intraday_cache import IntradayQuoteCache
from app.modules.market.infrastructure.ru_trading_calendar import get_moex_equity_trading_calendar
from app.modules.memory.application import decision_memory_service as svc
from app.modules.memory.application.decision_memory_service import (
    ConflictError,
    DecisionMemoryValidationError,
    NotFoundError,
    capture_decision,
    confirm_operation_link,
    find_existing_capture,
    get_decision,
    get_summary,
    list_decisions,
    list_possible_operation_matches,
    refresh_outcomes,
    unlink_operation_link,
)
from app.modules.memory.domain.decision_memory import (
    ENGINE_VERSION,
    HORIZONS,
    canonical_hash,
    canonical_json,
    decision_fingerprint,
    directional_alignment,
    normalize_new_cash,
    request_fingerprint,
)
from app.modules.memory.infrastructure.base import MemoryBase
from app.modules.memory.infrastructure.models import (
    PersonalDecisionAction,
    PersonalDecisionOperationLink,
    PersonalDecisionOutcome,
    PersonalDecisionRecord,
)
from app.modules.portfolio.application.daily_personal_decision_service import (
    ENGINE_VERSION as DAILY_ENGINE_VERSION,
)
from app.modules.portfolio.application.personal_portfolio_service import (
    get_or_create_test_portfolio,
    journal_operation_count,
)
from app.modules.portfolio.application.user_portfolio_service import reset_portfolio
from app.modules.portfolio.infrastructure.models import ManualPortfolio, PersonalOperation

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Monday 2026-09-21 20:00 MSK.
CAPTURE_NOW = datetime(2026, 9, 21, 17, 0, tzinfo=UTC)
BASELINE_DAY = date(2026, 9, 21)


# --------------------------------------------------------------------------- fixtures


class _NoRedis:
    """Deterministic empty quote cache backend."""

    def get(self, key: str) -> None:
        return None

    def set(self, *args: Any, **kwargs: Any) -> bool:
        return True


def _cache() -> IntradayQuoteCache:
    return IntradayQuoteCache(client=_NoRedis(), ttl_seconds=1)


@pytest.fixture
def core_tx() -> Generator[Session, None, None]:
    try:
        from app.core.config import get_settings
        from app.infrastructure.db.session import get_core_engine

        get_settings.cache_clear()
        connection = get_core_engine().connect()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"core database unavailable: {exc}")
    transaction = connection.begin()
    session = Session(bind=connection, autoflush=False, expire_on_commit=False)
    try:
        try:
            session.execute(text("SELECT 1 FROM portfolio.personal_operations LIMIT 0"))
        except Exception:
            pytest.skip("core migrations not applied")
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def mem_tx() -> Generator[Session, None, None]:
    try:
        from app.core.config import get_settings
        from app.infrastructure.db.session import get_memory_engine

        get_settings.cache_clear()
        connection = get_memory_engine().connect()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"memory database unavailable: {exc}")
    transaction = connection.begin()
    session = Session(bind=connection, autoflush=False, expire_on_commit=False)
    try:
        try:
            session.execute(text("SELECT 1 FROM memory.personal_decision_records LIMIT 0"))
        except Exception:
            pytest.skip("memory migration 20260930_0002 not applied")
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _portfolio(core: Session, name: str) -> ManualPortfolio:
    portfolio = get_or_create_test_portfolio(core, name=name)
    core.flush()
    return portfolio


def _instrument(
    core: Session, symbol: str, *, close: Decimal | None = Decimal("100"), asset_class: str = "equity"
) -> Instrument:
    inst = Instrument(
        symbol=symbol,
        name=symbol,
        asset_class=asset_class,
        exchange="MOEX",
        currency="RUB",
        is_active=True,
        support_level="FULL",
        primary_board="TQBR",
    )
    core.add(inst)
    core.flush()
    core.add(
        InstrumentSource(
            instrument_id=inst.id,
            source="MOEX_ISS",
            external_id=symbol,
            board="TQBR",
            source_metadata={"LOTSIZE": 1},
        )
    )
    core.flush()
    if close is not None:
        _candle(core, inst, BASELINE_DAY, close)
    return inst


def _candle(core: Session, inst: Instrument, day: date, close: Decimal, *, source: str = "TEST") -> None:
    core.add(
        Candle(
            instrument_id=inst.id,
            timeframe="1d",
            timestamp=datetime(day.year, day.month, day.day, tzinfo=UTC),
            open=close,
            high=close,
            low=close,
            close=close,
            volume=Decimal("1000"),
            source=source,
        )
    )
    core.flush()


def _op(
    core: Session,
    portfolio: ManualPortfolio,
    inst: Instrument,
    side: str,
    when: datetime,
    key: str,
    *,
    status: str = "ACTIVE",
) -> PersonalOperation:
    row = PersonalOperation(
        portfolio_id=portfolio.id,
        operation_type=side,
        status=status,
        occurred_at=when,
        instrument_id=inst.id,
        lots=Decimal("1"),
        units=Decimal("1"),
        price=Decimal("100"),
        amount=Decimal("100"),
        idempotency_key=key,
    )
    core.add(row)
    core.flush()
    return row


def _act(action: str, symbol: str | None, **extra: Any) -> dict[str, Any]:
    return {
        "id": f"{action}:{symbol or 'portfolio'}:X",
        "priority": "MEDIUM",
        "action": action,
        "symbol": symbol,
        "title": action,
        "rationale": "test",
        "reason_codes": ["X"],
        "facts": [],
        "current_weight": 0.1,
        "target_weight": 0.2,
        "lots_delta": 1,
        "units_delta": 1.0,
        "estimated_notional": 100.0,
        "href": None,
        "limitations": [],
        **extra,
    }


def _payload(portfolio: ManualPortfolio, actions: list[dict[str, Any]], **over: Any) -> dict[str, Any]:
    body = {
        "engine_version": ENGINE_VERSION,
        "as_of": "2026-09-21",
        "status": "READY",
        "headline": "test",
        "portfolio": {"id": portfolio.id, "name": portfolio.name},
        "actions": actions,
        "context": {"candidate_source": "TEST_CANDIDATE", "candidate_id": "c1"},
        "new_cash_plan": {"estimated_broker_fee_rub": "12.5000"},
        "data_quality": {"quantity": Decimal("1.50"), "day": date(2026, 9, 21)},
        **over,
    }
    body["decision_fingerprint"] = decision_fingerprint(body)
    return body


def _capture(
    mem: Session,
    core: Session,
    portfolio: ManualPortfolio,
    actions: list[dict[str, Any]],
    *,
    key: str = "k1",
    new_cash: Decimal | None = None,
    now: datetime = CAPTURE_NOW,
    expected_fingerprint: str | None = None,
    quote_cache: IntradayQuoteCache | None = None,
    **payload_over: Any,
) -> dict[str, Any]:
    payload = _payload(portfolio, actions, **payload_over)
    return capture_decision(
        mem,
        core,
        portfolio_id=portfolio.id,
        decision_payload=payload,
        idempotency_key=key,
        new_cash_rub=new_cash,
        expected_decision_fingerprint=expected_fingerprint or payload["decision_fingerprint"],
        now=now,
        quote_cache=quote_cache if quote_cache is not None else _cache(),
    )


def _quote(
    *,
    secid: str,
    board: str = "TQBR",
    trading_date: date,
    observed_at: datetime,
    last: float | None = 100.0,
    prev: float | None = None,
    freshness: QuoteFreshness = QuoteFreshness.LIVE,
    market_status: MarketSessionStatus = MarketSessionStatus.OPEN,
    source_timestamp: datetime | None = None,
) -> IntradayQuote:
    return IntradayQuote(
        secid=secid,
        board=board,
        trading_date=trading_date,
        observed_at=observed_at,
        source_timestamp=source_timestamp,
        market_status=market_status,
        open_price=None,
        last_price=last,
        bid=None,
        ask=None,
        previous_close=prev,
        volume=None,
        source="MOEX_ISS",
        freshness=freshness,
        quality="TEST",
        instrument_id=None,
    )


def _cache_with(*quotes: IntradayQuote) -> IntradayQuoteCache:
    cache = _cache()
    for q in quotes:
        cache.set(q)
    return cache


def _nth_session(start: date, n: int) -> date:
    cal = get_moex_equity_trading_calendar()
    cursor = start
    for _ in range(n):
        cursor = cal.next_trading_day(cursor)  # type: ignore[assignment]
    return cursor


def _dt(value: str | None) -> datetime:
    assert value is not None
    return datetime.fromisoformat(value)


def _n_records(mem: Session, pid: int) -> int:
    return int(
        mem.scalar(
            select(func.count()).select_from(PersonalDecisionRecord).where(PersonalDecisionRecord.portfolio_id == pid)
        )
        or 0
    )


def _n_actions(mem: Session, pid: int) -> int:
    return int(
        mem.scalar(
            select(func.count())
            .select_from(PersonalDecisionAction)
            .join(PersonalDecisionRecord, PersonalDecisionRecord.id == PersonalDecisionAction.decision_record_id)
            .where(PersonalDecisionRecord.portfolio_id == pid)
        )
        or 0
    )


def _n_outcomes(mem: Session, pid: int) -> int:
    return int(
        mem.scalar(
            select(func.count())
            .select_from(PersonalDecisionOutcome)
            .join(PersonalDecisionAction, PersonalDecisionAction.id == PersonalDecisionOutcome.decision_action_id)
            .join(PersonalDecisionRecord, PersonalDecisionRecord.id == PersonalDecisionAction.decision_record_id)
            .where(PersonalDecisionRecord.portfolio_id == pid)
        )
        or 0
    )


def _n_links(mem: Session, pid: int) -> int:
    return int(
        mem.scalar(
            select(func.count())
            .select_from(PersonalDecisionOperationLink)
            .where(PersonalDecisionOperationLink.portfolio_id == pid)
        )
        or 0
    )


# --------------------------------------------------------------------------- pure domain


def test_engine_constant_is_stable_and_shared() -> None:
    assert ENGINE_VERSION == "PERSONAL_DAILY_DECISION_V2"
    assert DAILY_ENGINE_VERSION == ENGINE_VERSION
    assert HORIZONS == (5, 20, 60)


def test_canonical_json_is_order_independent_and_handles_decimal_date() -> None:
    a = {"b": Decimal("1.50"), "a": [date(2026, 9, 21), {"z": 1, "y": 2}]}
    b = {"a": [date(2026, 9, 21), {"y": 2, "z": 1}], "b": Decimal("1.50")}
    assert canonical_json(a) == canonical_json(b)
    assert canonical_hash(a) == canonical_hash(b)
    assert canonical_hash(a) != canonical_hash({**a, "b": Decimal("1.51")})
    assert "2026-09-21" in canonical_json(a)


def test_request_fingerprint_normalizes_new_cash() -> None:
    a = request_fingerprint(1, None, "fp-a")
    b = request_fingerprint(1, Decimal("0"), "fp-a")
    c = request_fingerprint(1, Decimal("0.0000"), "fp-a")
    assert a == b == c
    assert request_fingerprint(1, Decimal("5"), "fp-a") != a
    assert request_fingerprint(1, None, "fp-b") != a
    assert normalize_new_cash(Decimal("5")) == Decimal("5.0000")
    with pytest.raises(ValueError):
        normalize_new_cash(Decimal("NaN"))


def test_decision_fingerprint_ignores_key_order_and_self_field() -> None:
    from app.modules.portfolio.domain.decision_identity import decision_fingerprint as portfolio_fp

    left = {"b": 1, "a": Decimal("1.5"), "day": date(2026, 9, 21)}
    right = {"a": Decimal("1.5"), "day": date(2026, 9, 21), "b": 1}
    assert decision_fingerprint(left) == decision_fingerprint(right)
    assert decision_fingerprint(left) == portfolio_fp(left)
    stamped = {**left, "decision_fingerprint": "should-not-matter"}
    assert decision_fingerprint(stamped) == decision_fingerprint(left)


def test_directional_alignment_only_for_increase_reduce() -> None:
    assert directional_alignment("CONSIDER_INCREASE", Decimal("0.01")) == "ALIGNED"
    assert directional_alignment("CONSIDER_INCREASE", Decimal("0")) == "NOT_ALIGNED"
    assert directional_alignment("CONSIDER_INCREASE", Decimal("-0.01")) == "NOT_ALIGNED"
    assert directional_alignment("CONSIDER_REDUCE", Decimal("-0.01")) == "ALIGNED"
    assert directional_alignment("CONSIDER_REDUCE", Decimal("0.01")) == "NOT_ALIGNED"
    for other in ("REVIEW", "HOLD", "KEEP_CASH", "SETUP", "DATA_QUALITY"):
        assert directional_alignment(other, Decimal("0.5")) is None


# --------------------------------------------------------------------------- structure / boundaries


def test_memory_tables_are_only_in_memory_metadata() -> None:
    assert {t.name for t in MemoryBase.metadata.tables.values()} == {
        "personal_decision_records",
        "personal_decision_actions",
        "personal_decision_operation_links",
        "personal_decision_outcomes",
    }
    assert all(t.schema == "memory" for t in MemoryBase.metadata.tables.values())
    assert not any(t.schema == "memory" for t in CoreBase.metadata.tables.values())
    assert not any(t.name.startswith("personal_decision") for t in CoreBase.metadata.tables.values())


def test_no_cross_db_foreign_keys_in_memory_models() -> None:
    for table in MemoryBase.metadata.tables.values():
        for fk in table.foreign_keys:
            assert fk.column.table.schema == "memory", f"{table.name} -> {fk.column.table}"


def test_migration_chain_and_no_cross_schema_references() -> None:
    path = BACKEND_ROOT / "migrations" / "memory" / "versions" / "20260930_0002_personal_decision_memory.py"
    spec = importlib.util.spec_from_file_location("pdm_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "20260930_0002"
    assert module.down_revision == "20260321_0001"
    source = path.read_text(encoding="utf-8")
    references = re.findall(r"REFERENCES\s+(\S+?)\(", source)
    assert references, "expected in-schema foreign keys"
    assert all(ref.startswith("memory.personal_decision_") for ref in references), references
    assert "REFERENCES memory.decisions" not in source
    assert "WHERE active" in source


def test_get_daily_decision_stays_read_only_and_capture_is_post_only() -> None:
    from app.api.v1 import decision_memory as api
    from app.api.v1 import personal_portfolios
    from app.modules.portfolio.application import daily_personal_decision_service

    assert "capture" not in inspect.getsource(personal_portfolios.get_daily_decision)
    assert "decision_memory" not in inspect.getsource(personal_portfolios).lower()
    assert "decision_memory" not in inspect.getsource(daily_personal_decision_service)
    assert "memory_session" not in inspect.getsource(daily_personal_decision_service)

    routes = [r for r in api.router.routes if hasattr(r, "methods")]
    capture_routes = [r for r in routes if r.path.endswith("/decision-memory/capture")]
    assert len(capture_routes) == 1
    assert capture_routes[0].methods == {"POST"}
    have = {(m, r.path) for r in routes for m in r.methods}
    assert {
        ("GET", "/{portfolio_id}/decision-memory"),
        ("GET", "/{portfolio_id}/decision-memory/summary"),
        ("GET", "/{portfolio_id}/decision-memory/{decision_id}"),
        ("GET", "/{portfolio_id}/decision-memory/actions/{action_id}/possible-matches"),
        ("POST", "/{portfolio_id}/decision-memory/actions/{action_id}/links"),
        ("POST", "/{portfolio_id}/decision-memory/outcomes/refresh"),
        ("DELETE", "/{portfolio_id}/decision-memory/links/{link_id}"),
    } <= have
    paths = [r.path for r in routes]
    # Literal routes must be declared before the ``{decision_id}`` catch-all.
    assert paths.index("/{portfolio_id}/decision-memory/summary") < paths.index(
        "/{portfolio_id}/decision-memory/{decision_id}"
    )

    router_source = (BACKEND_ROOT / "app" / "api" / "v1" / "router.py").read_text(encoding="utf-8")
    assert 'decision_memory_router, prefix="/personal-portfolios"' in router_source


def test_capture_body_has_no_captured_at() -> None:
    from app.api.v1.decision_memory import CaptureBody

    assert set(CaptureBody.model_fields) == {"new_cash_rub", "expected_decision_fingerprint"}
    parsed = CaptureBody.model_validate(
        {"new_cash_rub": 1, "expected_decision_fingerprint": "abc", "captured_at": "2020-01-01T00:00:00Z"}
    )
    assert parsed.new_cash_rub == 1
    assert parsed.expected_decision_fingerprint == "abc"
    assert not hasattr(parsed, "captured_at") or "captured_at" not in CaptureBody.model_fields


# --------------------------------------------------------------------------- capture


def test_capture_happy_path_freezes_payload_baseline_and_outcomes(mem_tx, core_tx) -> None:
    pf = _portfolio(core_tx, "pdm-happy")
    inc = _instrument(core_tx, "PDMHA", close=Decimal("100"))
    red = _instrument(core_tx, "PDMHB", close=Decimal("50"))
    ops_before = journal_operation_count(core_tx, pf.id)

    out = _capture(
        mem_tx,
        core_tx,
        pf,
        [
            _act("CONSIDER_INCREASE", "PDMHA"),
            _act("CONSIDER_REDUCE", "PDMHB"),
            _act("REVIEW", None),
        ],
        new_cash=Decimal("30000"),
    )

    assert out["idempotent_replay"] is False
    assert out["portfolio_id"] == pf.id
    assert out["portfolio_name_snapshot"] == pf.name
    assert out["engine_version"] == "PERSONAL_DAILY_DECISION_V2"
    assert _dt(out["captured_at"]) == CAPTURE_NOW
    assert out["decision_as_of"] == "2026-09-21"
    assert out["new_cash_rub"] == "30000.0000"
    assert out["hash_verified"] is True
    assert out["candidate_provenance"]["candidate_source"] == "TEST_CANDIDATE"
    assert out["broker_fee_provenance"]["estimated_broker_fee_rub"] == "12.5000"
    assert len(out["actions"]) == 3

    by_sym = {a["symbol"]: a for a in out["actions"]}
    a = by_sym["PDMHA"]
    assert a["instrument_id"] == inc.id
    assert a["baseline"]["status"] == "AVAILABLE"
    assert Decimal(a["baseline"]["price"]) == Decimal("100")
    assert a["baseline"]["market_date"] == "2026-09-21"
    assert a["baseline"]["price_source"] == "EOD_CLOSE"
    assert _dt(a["baseline"]["observed_at"]) == datetime(2026, 9, 21, tzinfo=UTC)
    assert by_sym["PDMHB"]["instrument_id"] == red.id
    assert [o["horizon_sessions"] for o in a["outcomes"]] == [5, 20, 60]
    assert all(o["status"] == "PENDING" for o in a["outcomes"])
    assert a["outcomes"][0]["target_session_date"] == _nth_session(BASELINE_DAY, 5).isoformat()
    assert a["outcomes"][1]["target_session_date"] == _nth_session(BASELINE_DAY, 20).isoformat()
    assert a["outcomes"][2]["target_session_date"] == _nth_session(BASELINE_DAY, 60).isoformat()
    assert all(o["return_type"] == "PRICE_RETURN" for o in a["outcomes"])

    portfolio_level = by_sym[None]
    assert portfolio_level["baseline"]["status"] == "UNAVAILABLE"
    assert [o["status"] for o in portfolio_level["outcomes"]] == ["BASELINE_UNAVAILABLE"] * 3

    assert _n_outcomes(mem_tx, pf.id) == 9
    assert _n_actions(mem_tx, pf.id) == 3
    # Advisory memory must never write to the journal or mutate cash/capital.
    assert journal_operation_count(core_tx, pf.id) == ops_before
    core_tx.refresh(pf)
    assert pf.cash_rub == Decimal("0")
    assert pf.total_contributed_rub == Decimal("0")
    assert core_tx.scalar(
        select(func.count()).select_from(PersonalOperation).where(
            PersonalOperation.portfolio_id == pf.id,
            PersonalOperation.operation_type == "DEPOSIT",
        )
    ) == 0


def test_capture_is_idempotent_and_replay_adds_no_rows(mem_tx, core_tx) -> None:
    pf = _portfolio(core_tx, "pdm-idem")
    _instrument(core_tx, "PDMIA")
    actions = [_act("CONSIDER_INCREASE", "PDMIA")]
    first = _capture(mem_tx, core_tx, pf, actions, key="same-key")
    fp = first["decision_payload"]["decision_fingerprint"]
    rows = (_n_records(mem_tx, pf.id), _n_actions(mem_tx, pf.id), _n_outcomes(mem_tx, pf.id))

    later = CAPTURE_NOW + timedelta(hours=3)
    # Retry must resend the original displayed fingerprint even if a rebuilt payload differs.
    second = _capture(
        mem_tx, core_tx, pf, actions, key="same-key", now=later, expected_fingerprint=fp, headline="changed"
    )

    assert second["idempotent_replay"] is True
    assert second["id"] == first["id"]
    assert second["captured_at"] == first["captured_at"]
    assert second["canonical_hash"] == first["canonical_hash"]
    assert rows == (_n_records(mem_tx, pf.id), _n_actions(mem_tx, pf.id), _n_outcomes(mem_tx, pf.id))
    replay = find_existing_capture(
        mem_tx, portfolio_id=pf.id, idempotency_key="same-key", new_cash_rub=None, expected_decision_fingerprint=fp
    )
    assert replay is not None and replay["id"] == first["id"]
    assert (
        find_existing_capture(
            mem_tx, portfolio_id=pf.id, idempotency_key="other", new_cash_rub=None, expected_decision_fingerprint=fp
        )
        is None
    )


def test_same_key_different_parameters_is_conflict(mem_tx, core_tx) -> None:
    pf = _portfolio(core_tx, "pdm-conflict")
    first = _capture(mem_tx, core_tx, pf, [], key="kc", new_cash=Decimal("100"))
    fp = first["decision_payload"]["decision_fingerprint"]
    with pytest.raises(ConflictError) as exc:
        _capture(mem_tx, core_tx, pf, [], key="kc", new_cash=Decimal("200"), expected_fingerprint=fp)
    assert exc.value.http_status == 409
    assert exc.value.code == "IDEMPOTENCY_KEY_REUSED"
    with pytest.raises(ConflictError):
        find_existing_capture(
            mem_tx, portfolio_id=pf.id, idempotency_key="kc", new_cash_rub=None, expected_decision_fingerprint=fp
        )
    # Numerically equal value in another spelling is the same request.
    again = _capture(mem_tx, core_tx, pf, [], key="kc", new_cash=Decimal("100.0000"), expected_fingerprint=fp)
    assert again["idempotent_replay"] is True
    # Same key + different displayed fingerprint is also a conflict.
    with pytest.raises(ConflictError) as exc2:
        _capture(mem_tx, core_tx, pf, [], key="kc", new_cash=Decimal("100"), expected_fingerprint="other-fp")
    assert exc2.value.code == "IDEMPOTENCY_KEY_REUSED"


def test_same_key_is_scoped_per_portfolio(mem_tx, core_tx) -> None:
    p1 = _portfolio(core_tx, "pdm-scope-1")
    p2 = _portfolio(core_tx, "pdm-scope-2")
    a = _capture(mem_tx, core_tx, p1, [], key="shared")
    b = _capture(mem_tx, core_tx, p2, [], key="shared")
    assert a["id"] != b["id"]
    assert b["idempotent_replay"] is False


@pytest.mark.parametrize("key", ["", "   ", "\t\n"])
def test_empty_idempotency_key_rejected(mem_tx, core_tx, key) -> None:
    pf = _portfolio(core_tx, "pdm-nokey")
    with pytest.raises(DecisionMemoryValidationError) as exc:
        _capture(mem_tx, core_tx, pf, [], key=key)
    assert exc.value.code == "IDEMPOTENCY_KEY_REQUIRED"
    assert _n_records(mem_tx, pf.id) == 0


def test_overlong_idempotency_key_rejected(mem_tx, core_tx) -> None:
    pf = _portfolio(core_tx, "pdm-longkey")
    with pytest.raises(DecisionMemoryValidationError):
        _capture(mem_tx, core_tx, pf, [], key="k" * 500)


def test_negative_new_cash_rejected(mem_tx, core_tx) -> None:
    pf = _portfolio(core_tx, "pdm-neg")
    with pytest.raises(DecisionMemoryValidationError) as exc:
        _capture(mem_tx, core_tx, pf, [], new_cash=Decimal("-1"))
    assert exc.value.code == "NEW_CASH_NEGATIVE"


def test_captured_at_is_server_utc_and_naive_now_rejected(mem_tx, core_tx) -> None:
    pf = _portfolio(core_tx, "pdm-clock")
    msk = datetime(2026, 9, 21, 20, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    out = _capture(mem_tx, core_tx, pf, [], key="tz", now=msk)
    assert _dt(out["captured_at"]) == CAPTURE_NOW  # same instant, normalized to UTC
    with pytest.raises(DecisionMemoryValidationError):
        _capture(mem_tx, core_tx, pf, [], key="naive", now=datetime(2026, 9, 21, 17, 0))


def test_default_clock_is_server_now(mem_tx, core_tx) -> None:
    pf = _portfolio(core_tx, "pdm-defclock")
    before = datetime.now(UTC)
    payload = _payload(pf, [])
    out = capture_decision(
        mem_tx,
        core_tx,
        portfolio_id=pf.id,
        decision_payload=payload,
        idempotency_key="defclock",
        new_cash_rub=None,
        expected_decision_fingerprint=payload["decision_fingerprint"],
        quote_cache=_cache(),
    )
    after = datetime.now(UTC)
    assert before <= datetime.fromisoformat(out["captured_at"]) <= after


def test_wrong_engine_or_portfolio_payload_rejected(mem_tx, core_tx) -> None:
    pf = _portfolio(core_tx, "pdm-badpayload")
    other = _portfolio(core_tx, "pdm-badpayload-other")
    with pytest.raises(DecisionMemoryValidationError) as exc:
        _capture(mem_tx, core_tx, pf, [], key="e1", engine_version="2")
    assert exc.value.code == "ENGINE_VERSION_MISMATCH"
    bad_pf_payload = _payload(pf, [])
    bad_pf_payload["portfolio"] = {"id": other.id}
    with pytest.raises(DecisionMemoryValidationError) as exc2:
        capture_decision(
            mem_tx,
            core_tx,
            portfolio_id=pf.id,
            decision_payload=bad_pf_payload,
            idempotency_key="e2",
            new_cash_rub=None,
            expected_decision_fingerprint=bad_pf_payload["decision_fingerprint"],
            now=CAPTURE_NOW,
            quote_cache=_cache(),
        )
    assert exc2.value.code == "PORTFOLIO_MISMATCH"
    with pytest.raises(DecisionMemoryValidationError):
        capture_decision(
            mem_tx,
            core_tx,
            portfolio_id=pf.id,
            decision_payload={"engine_version": ENGINE_VERSION, "actions": "nope"},  # type: ignore[arg-type]
            idempotency_key="e3",
            new_cash_rub=None,
            expected_decision_fingerprint="x",
            now=CAPTURE_NOW,
        )
    assert _n_records(mem_tx, pf.id) == 0


def test_unknown_portfolio_not_found(mem_tx, core_tx) -> None:
    with pytest.raises(NotFoundError):
        capture_decision(
            mem_tx,
            core_tx,
            portfolio_id=999_999_999,
            decision_payload={"engine_version": ENGINE_VERSION, "actions": [], "decision_fingerprint": "x"},
            idempotency_key="nf",
            new_cash_rub=None,
            expected_decision_fingerprint="x",
            now=CAPTURE_NOW,
        )


def test_stored_payload_is_detached_and_hash_detects_tampering(mem_tx, core_tx) -> None:
    pf = _portfolio(core_tx, "pdm-hash")
    payload = _payload(pf, [_act("REVIEW", None)])
    out = capture_decision(
        mem_tx,
        core_tx,
        portfolio_id=pf.id,
        decision_payload=payload,
        idempotency_key="h1",
        new_cash_rub=None,
        expected_decision_fingerprint=payload["decision_fingerprint"],
        now=CAPTURE_NOW,
        quote_cache=_cache(),
    )
    payload["headline"] = "mutated after capture"
    payload["actions"].clear()
    stored = get_decision(mem_tx, pf.id, out["id"])
    assert stored["decision_payload"]["headline"] == "test"
    assert len(stored["decision_payload"]["actions"]) == 1
    assert stored["hash_verified"] is True
    assert stored["decision_payload"]["data_quality"]["quantity"] == "1.50"

    record = mem_tx.get(PersonalDecisionRecord, out["id"])
    record.decision_payload = {**record.decision_payload, "headline": "tampered"}
    mem_tx.flush()
    assert get_decision(mem_tx, pf.id, out["id"])["hash_verified"] is False


# --------------------------------------------------------------------------- baselines (Point-in-Time)


def test_baseline_ignores_candles_after_capture_time(mem_tx, core_tx) -> None:
    pf = _portfolio(core_tx, "pdm-pit")
    inst = _instrument(core_tx, "PDMPIT", close=Decimal("100"))
    _candle(core_tx, inst, date(2026, 9, 22), Decimal("999"))  # future relative to capture
    out = _capture(mem_tx, core_tx, pf, [_act("CONSIDER_INCREASE", "PDMPIT")])
    base = out["actions"][0]["baseline"]
    assert base["price"] == "100.000000"
    assert base["market_date"] == "2026-09-21"

    early = CAPTURE_NOW - timedelta(days=5)  # before any candle exists
    out2 = _capture(mem_tx, core_tx, pf, [_act("CONSIDER_INCREASE", "PDMPIT")], key="pit2", now=early)
    assert out2["actions"][0]["baseline"]["status"] == "UNAVAILABLE"
    assert [o["status"] for o in out2["actions"][0]["outcomes"]] == ["BASELINE_UNAVAILABLE"] * 3


def test_unavailable_baselines_do_not_invent_prices(mem_tx, core_tx) -> None:
    pf = _portfolio(core_tx, "pdm-nobase")
    _instrument(core_tx, "PDMNOPX", close=None)
    _instrument(core_tx, "PDMBOND", asset_class="bond")
    out = _capture(
        mem_tx,
        core_tx,
        pf,
        [
            _act("CONSIDER_INCREASE", "PDMNOPX"),
            _act("REVIEW", "PDMBOND"),
            _act("REVIEW", "NOSUCHSYMBOL"),
        ],
    )
    for action in out["actions"]:
        assert action["baseline"]["status"] == "UNAVAILABLE"
        assert action["baseline"]["price"] is None
        assert all(o["status"] == "BASELINE_UNAVAILABLE" for o in action["outcomes"])
    by_sym = {a["symbol"]: a for a in out["actions"]}
    assert by_sym["PDMNOPX"]["instrument_id"] is not None
    assert by_sym["NOSUCHSYMBOL"]["instrument_id"] is None
    assert by_sym["PDMBOND"]["outcomes"][0]["provenance"]["reason"] == "ASSET_CLASS_NOT_SUPPORTED"


def test_zero_last_quote_falls_back_or_unavailable(mem_tx, core_tx) -> None:
    pf = _portfolio(core_tx, "pdm-zero")
    _instrument(core_tx, "PDMZERO", close=None)
    cache = _cache_with(
        _quote(secid="PDMZERO", trading_date=BASELINE_DAY, observed_at=CAPTURE_NOW - timedelta(minutes=5), last=0.0)
    )
    out = _capture(mem_tx, core_tx, pf, [_act("CONSIDER_INCREASE", "PDMZERO")], quote_cache=cache)
    assert out["actions"][0]["baseline"]["status"] == "UNAVAILABLE"


def test_intraday_baseline_uses_quote_trading_date_not_capture_calendar(mem_tx, core_tx) -> None:
    """Quote trading_date may differ from capture MSK calendar day; do not relabel."""
    pf = _portfolio(core_tx, "pdm-live")
    _instrument(core_tx, "PDMLIVE", close=None)
    capture_at = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)
    observed = datetime(2026, 9, 25, 15, 30, tzinfo=UTC)
    cache = _cache_with(
        _quote(
            secid="PDMLIVE",
            trading_date=date(2026, 9, 25),
            observed_at=observed,
            last=123.45,
            source_timestamp=observed,
        )
    )
    out = _capture(
        mem_tx, core_tx, pf, [_act("CONSIDER_INCREASE", "PDMLIVE")], now=capture_at, quote_cache=cache
    )
    base = out["actions"][0]["baseline"]
    assert base["price"] == "123.45"
    assert base["price_source"] == "INTRADAY_LAST"
    assert base["market_date"] == "2026-09-25"
    assert _dt(base["observed_at"]) == observed
    assert base["provenance"]["quote_trading_date"] == "2026-09-25"
    assert base["provenance"]["captured_at"] == capture_at.isoformat()
    assert _dt(out["captured_at"]) == capture_at
    assert _dt(out["captured_at"]) != _dt(base["observed_at"])
    assert (
        out["actions"][0]["outcomes"][0]["target_session_date"]
        == _nth_session(date(2026, 9, 25), 5).isoformat()
    )


def test_previous_close_baseline_uses_quote_session(mem_tx, core_tx) -> None:
    pf = _portfolio(core_tx, "pdm-prev")
    _instrument(core_tx, "PDMPREV", close=None)
    capture_at = datetime(2026, 9, 28, 6, 0, tzinfo=UTC)
    observed = datetime(2026, 9, 25, 20, 0, tzinfo=UTC)
    cache = _cache_with(
        _quote(
            secid="PDMPREV",
            trading_date=date(2026, 9, 25),
            observed_at=observed,
            last=None,
            prev=88.5,
            freshness=QuoteFreshness.STALE,
            market_status=MarketSessionStatus.CLOSED,
        )
    )
    out = _capture(
        mem_tx, core_tx, pf, [_act("CONSIDER_INCREASE", "PDMPREV")], now=capture_at, quote_cache=cache
    )
    base = out["actions"][0]["baseline"]
    assert base["price_source"] == "PREVIOUS_CLOSE"
    assert base["market_date"] == "2026-09-25"
    assert Decimal(base["price"]) == Decimal("88.5")
    assert base["provenance"]["quote_freshness"] == "STALE"


def test_future_quote_observed_at_is_rejected(mem_tx, core_tx) -> None:
    pf = _portfolio(core_tx, "pdm-futureq")
    _instrument(core_tx, "PDMFUT", close=Decimal("50"))
    cache = _cache_with(
        _quote(
            secid="PDMFUT",
            trading_date=BASELINE_DAY,
            observed_at=CAPTURE_NOW + timedelta(hours=2),
            last=999.0,
        )
    )
    out = _capture(mem_tx, core_tx, pf, [_act("CONSIDER_INCREASE", "PDMFUT")], quote_cache=cache)
    base = out["actions"][0]["baseline"]
    assert base["price_source"] == "EOD_CLOSE"
    assert Decimal(base["price"]) == Decimal("50")
    assert base["market_date"] == "2026-09-21"


def test_quote_without_trading_date_falls_back_to_eod(mem_tx, core_tx) -> None:
    pf = _portfolio(core_tx, "pdm-nodate")
    _instrument(core_tx, "PDMND", close=Decimal("41"))
    q = IntradayQuote(
        secid="PDMND",
        board="TQBR",
        trading_date=None,
        observed_at=CAPTURE_NOW - timedelta(minutes=1),
        source_timestamp=None,
        market_status=MarketSessionStatus.OPEN,
        open_price=None,
        last_price=77.0,
        bid=None,
        ask=None,
        previous_close=None,
        volume=None,
        source="MOEX_ISS",
        freshness=QuoteFreshness.LIVE,
        quality="TEST",
    )
    out = _capture(
        mem_tx, core_tx, pf, [_act("CONSIDER_INCREASE", "PDMND")], quote_cache=_cache_with(q)
    )
    assert out["actions"][0]["baseline"]["price_source"] == "EOD_CLOSE"
    assert Decimal(out["actions"][0]["baseline"]["price"]) == Decimal("41")


def test_stale_preopen_quote_keeps_its_session(mem_tx, core_tx) -> None:
    pf = _portfolio(core_tx, "pdm-preopen")
    _instrument(core_tx, "PDMPO", close=None)
    observed = datetime(2026, 9, 25, 7, 0, tzinfo=UTC)
    cache = _cache_with(
        _quote(
            secid="PDMPO",
            trading_date=date(2026, 9, 25),
            observed_at=observed,
            last=None,
            prev=12.0,
            freshness=QuoteFreshness.SESSION_NOT_STARTED,
            market_status=MarketSessionStatus.PREOPEN,
        )
    )
    out = _capture(
        mem_tx,
        core_tx,
        pf,
        [_act("CONSIDER_INCREASE", "PDMPO")],
        now=datetime(2026, 9, 28, 5, 0, tzinfo=UTC),
        quote_cache=cache,
    )
    base = out["actions"][0]["baseline"]
    assert base["market_date"] == "2026-09-25"
    assert base["provenance"]["quote_market_status"] == "PREOPEN"
    assert base["price_source"] == "PREVIOUS_CLOSE"


# --------------------------------------------------------------------------- reads / scoping


def test_reads_are_portfolio_scoped(mem_tx, core_tx) -> None:
    p1 = _portfolio(core_tx, "pdm-read-1")
    p2 = _portfolio(core_tx, "pdm-read-2")
    d1 = _capture(mem_tx, core_tx, p1, [_act("REVIEW", None)], key="r1")
    _capture(mem_tx, core_tx, p1, [], key="r2", now=CAPTURE_NOW + timedelta(days=1))
    _capture(mem_tx, core_tx, p2, [], key="r3")

    listed = list_decisions(mem_tx, p1.id, 50)
    assert listed["count"] == 2
    assert [i["captured_at"] for i in listed["items"]] == sorted(
        (i["captured_at"] for i in listed["items"]), reverse=True
    )
    assert all("decision_payload" not in i for i in listed["items"])
    assert list_decisions(mem_tx, p1.id, 1)["count"] == 1
    assert list_decisions(mem_tx, p1.id, 0)["count"] == 1  # limit clamped to >= 1

    assert get_decision(mem_tx, p1.id, d1["id"])["id"] == d1["id"]
    with pytest.raises(NotFoundError):
        get_decision(mem_tx, p2.id, d1["id"])
    with pytest.raises(NotFoundError):
        get_decision(mem_tx, p1.id, 999_999_999)


def test_stale_displayed_fingerprint_is_rejected_without_memory_row(mem_tx, core_tx) -> None:
    pf = _portfolio(core_tx, "pdm-fp-stale")
    _instrument(core_tx, "PDMFP")
    displayed = _payload(pf, [_act("CONSIDER_INCREASE", "PDMFP")], headline="shown")
    shown_fp = displayed["decision_fingerprint"]
    rebuilt = _payload(pf, [_act("CONSIDER_INCREASE", "PDMFP")], headline="changed-after-show")
    assert rebuilt["decision_fingerprint"] != shown_fp
    with pytest.raises(ConflictError) as exc:
        capture_decision(
            mem_tx,
            core_tx,
            portfolio_id=pf.id,
            decision_payload=rebuilt,
            idempotency_key="stale-ui",
            new_cash_rub=None,
            expected_decision_fingerprint=shown_fp,
            now=CAPTURE_NOW,
            quote_cache=_cache(),
        )
    assert exc.value.code == "DECISION_CHANGED"
    assert "Обновите расчёт" in exc.value.message
    assert _n_records(mem_tx, pf.id) == 0


def test_matching_fingerprint_captures_exact_displayed_payload(mem_tx, core_tx) -> None:
    pf = _portfolio(core_tx, "pdm-fp-ok")
    _instrument(core_tx, "PDMFO")
    displayed = _payload(pf, [_act("CONSIDER_INCREASE", "PDMFO")], headline="exact")
    out = capture_decision(
        mem_tx,
        core_tx,
        portfolio_id=pf.id,
        decision_payload=displayed,
        idempotency_key="exact",
        new_cash_rub=None,
        expected_decision_fingerprint=displayed["decision_fingerprint"],
        now=CAPTURE_NOW,
        quote_cache=_cache(),
    )
    assert out["decision_payload"]["headline"] == "exact"
    assert out["decision_payload"]["decision_fingerprint"] == displayed["decision_fingerprint"]
    assert out["hash_verified"] is True


def test_idempotent_replay_even_if_current_decision_would_differ(mem_tx, core_tx) -> None:
    pf = _portfolio(core_tx, "pdm-fp-replay")
    _instrument(core_tx, "PDMFR")
    first_payload = _payload(pf, [_act("CONSIDER_INCREASE", "PDMFR")], headline="v1")
    first = capture_decision(
        mem_tx,
        core_tx,
        portfolio_id=pf.id,
        decision_payload=first_payload,
        idempotency_key="replay-key",
        new_cash_rub=None,
        expected_decision_fingerprint=first_payload["decision_fingerprint"],
        now=CAPTURE_NOW,
        quote_cache=_cache(),
    )
    changed = _payload(pf, [_act("CONSIDER_INCREASE", "PDMFR")], headline="v2-now")
    replay = find_existing_capture(
        mem_tx,
        portfolio_id=pf.id,
        idempotency_key="replay-key",
        new_cash_rub=None,
        expected_decision_fingerprint=first_payload["decision_fingerprint"],
    )
    assert replay is not None
    assert replay["id"] == first["id"]
    assert replay["decision_payload"]["headline"] == "v1"
    assert changed["decision_fingerprint"] != first_payload["decision_fingerprint"]


# --------------------------------------------------------------------------- outcomes


def _sym(name: str) -> str:
    return name.replace("-", "").upper()[-8:]


def _capture_two(mem: Session, core: Session, name: str):
    pf = _portfolio(core, name)
    inc = _instrument(core, f"{_sym(name)}I", close=Decimal("100"))
    red = _instrument(core, f"{_sym(name)}R", close=Decimal("100"))
    out = _capture(
        mem,
        core,
        pf,
        [
            _act("CONSIDER_INCREASE", inc.symbol),
            _act("CONSIDER_REDUCE", red.symbol),
            _act("REVIEW", None),
        ],
    )
    return pf, inc, red, out


def _outcomes_by_symbol(out_or_decision: dict[str, Any]) -> dict[Any, dict[int, dict[str, Any]]]:
    return {a["symbol"]: {o["horizon_sessions"]: o for o in a["outcomes"]} for a in out_or_decision["actions"]}


def test_refresh_leaves_unmatured_horizon_pending(mem_tx, core_tx) -> None:
    pf, _inc, _red, out = _capture_two(mem_tx, core_tx, "pdm-out-pend")
    target = _nth_session(BASELINE_DAY, 5)
    # Same calendar day as target: the session is not finished, so it must not be used.
    res = refresh_outcomes(
        mem_tx, core_tx, pf.id, now=datetime(target.year, target.month, target.day, 9, 0, tzinfo=UTC)
    )
    assert res["ready"] == 0
    assert res["still_pending"] == 6
    dec = get_decision(mem_tx, pf.id, out["id"])
    for horizons in _outcomes_by_symbol(dec).values():
        assert horizons[5]["status"] in {"PENDING", "BASELINE_UNAVAILABLE"}


def test_refresh_ready_price_return_and_alignment(mem_tx, core_tx) -> None:
    pf, inc, red, out = _capture_two(mem_tx, core_tx, "pdm-out-ready")
    target = _nth_session(BASELINE_DAY, 5)
    _candle(core_tx, inc, target, Decimal("110"))
    _candle(core_tx, red, target, Decimal("90"))
    now = datetime(target.year, target.month, target.day, 12, 0, tzinfo=UTC) + timedelta(days=1)

    res = refresh_outcomes(mem_tx, core_tx, pf.id, now=now)
    assert res["ready"] == 2
    assert res["data_unavailable"] == 0

    outcomes = _outcomes_by_symbol(get_decision(mem_tx, pf.id, out["id"]))
    o_inc = outcomes[inc.symbol][5]
    assert o_inc["status"] == "READY"
    assert Decimal(o_inc["forward_return"]) == Decimal("0.1")
    assert o_inc["return_type"] == "PRICE_RETURN"
    assert o_inc["directional_alignment"] == "ALIGNED"
    assert o_inc["observed_session_date"] == target.isoformat()
    assert Decimal(o_inc["observed_price"]) == Decimal("110")
    assert o_inc["provenance"]["adjusted_for_dividends_or_splits"] is False
    o_red = outcomes[red.symbol][5]
    assert Decimal(o_red["forward_return"]) == Decimal("-0.1")
    assert o_red["directional_alignment"] == "ALIGNED"
    assert outcomes[inc.symbol][20]["status"] == "PENDING"
    assert outcomes[None][5]["status"] == "BASELINE_UNAVAILABLE"


def test_refresh_not_aligned_and_non_directional_has_no_alignment(mem_tx, core_tx) -> None:
    pf = _portfolio(core_tx, "pdm-out-na")
    up = _instrument(core_tx, "PDMNAUP", close=Decimal("100"))
    rev = _instrument(core_tx, "PDMNAREV", close=Decimal("100"))
    down = _instrument(core_tx, "PDMNADN", close=Decimal("100"))
    out = _capture(
        mem_tx,
        core_tx,
        pf,
        [
            _act("CONSIDER_REDUCE", up.symbol),
            _act("REVIEW", rev.symbol),
            _act("CONSIDER_INCREASE", down.symbol),
        ],
    )
    target = _nth_session(BASELINE_DAY, 5)
    _candle(core_tx, up, target, Decimal("120"))
    _candle(core_tx, rev, target, Decimal("120"))
    _candle(core_tx, down, target, Decimal("80"))
    refresh_outcomes(
        mem_tx, core_tx, pf.id, now=datetime.combine(target + timedelta(days=2), datetime.min.time(), tzinfo=UTC)
    )
    outcomes = _outcomes_by_symbol(get_decision(mem_tx, pf.id, out["id"]))
    assert outcomes[up.symbol][5]["directional_alignment"] == "NOT_ALIGNED"
    assert outcomes[down.symbol][5]["directional_alignment"] == "NOT_ALIGNED"
    assert outcomes[rev.symbol][5]["status"] == "READY"
    assert outcomes[rev.symbol][5]["directional_alignment"] is None


def test_refresh_missing_candle_is_data_unavailable_then_recovers(mem_tx, core_tx) -> None:
    pf, inc, _red, out = _capture_two(mem_tx, core_tx, "pdm-out-gap")
    target = _nth_session(BASELINE_DAY, 5)
    now = datetime.combine(target + timedelta(days=2), datetime.min.time(), tzinfo=UTC)

    first = refresh_outcomes(mem_tx, core_tx, pf.id, now=now)
    assert first["ready"] == 0
    assert first["data_unavailable"] == 2
    outcomes = _outcomes_by_symbol(get_decision(mem_tx, pf.id, out["id"]))
    assert outcomes[inc.symbol][5]["status"] == "DATA_UNAVAILABLE"
    assert outcomes[inc.symbol][5]["forward_return"] is None
    assert outcomes[inc.symbol][5]["refreshed_at"] is not None

    _candle(core_tx, inc, target, Decimal("101"))
    second = refresh_outcomes(mem_tx, core_tx, pf.id, now=now + timedelta(hours=1))
    assert second["ready"] == 1
    assert second["data_unavailable"] == 1
    outcomes = _outcomes_by_symbol(get_decision(mem_tx, pf.id, out["id"]))
    assert outcomes[inc.symbol][5]["status"] == "READY"


def test_refresh_is_idempotent_and_ready_is_final(mem_tx, core_tx) -> None:
    pf, inc, _red, out = _capture_two(mem_tx, core_tx, "pdm-out-idem")
    target = _nth_session(BASELINE_DAY, 5)
    _candle(core_tx, inc, target, Decimal("110"))
    now = datetime.combine(target + timedelta(days=2), datetime.min.time(), tzinfo=UTC)
    refresh_outcomes(mem_tx, core_tx, pf.id, now=now)
    snap1 = _outcomes_by_symbol(get_decision(mem_tx, pf.id, out["id"]))[inc.symbol][5]

    # A later, different candle for the same session must not rewrite a READY outcome.
    _candle(core_tx, inc, target, Decimal("500"), source="LATE")
    again = refresh_outcomes(mem_tx, core_tx, pf.id, now=now + timedelta(days=1))
    snap2 = _outcomes_by_symbol(get_decision(mem_tx, pf.id, out["id"]))[inc.symbol][5]
    assert snap1 == snap2
    assert again["ready"] == 0
    assert _n_outcomes(mem_tx, pf.id) == 9


def test_refresh_is_portfolio_scoped_and_global_mode(mem_tx, core_tx) -> None:
    p1, inc1, _r1, _o1 = _capture_two(mem_tx, core_tx, "pdm-out-sc1")
    p2, inc2, _r2, o2 = _capture_two(mem_tx, core_tx, "pdm-out-sc2")
    target = _nth_session(BASELINE_DAY, 5)
    _candle(core_tx, inc1, target, Decimal("110"))
    _candle(core_tx, inc2, target, Decimal("110"))
    now = datetime.combine(target + timedelta(days=2), datetime.min.time(), tzinfo=UTC)

    refresh_outcomes(mem_tx, core_tx, p1.id, now=now)
    untouched = _outcomes_by_symbol(get_decision(mem_tx, p2.id, o2["id"]))[inc2.symbol][5]
    assert untouched["status"] == "PENDING"

    result = refresh_outcomes(mem_tx, core_tx, None, now=now)
    assert result["portfolio_id"] is None
    assert _outcomes_by_symbol(get_decision(mem_tx, p2.id, o2["id"]))[inc2.symbol][5]["status"] == "READY"


def test_summary_counts_and_small_sample_warning(mem_tx, core_tx) -> None:
    pf, inc, red, _out = _capture_two(mem_tx, core_tx, "pdm-summary")
    target = _nth_session(BASELINE_DAY, 5)
    _candle(core_tx, inc, target, Decimal("110"))
    _candle(core_tx, red, target, Decimal("110"))
    refresh_outcomes(
        mem_tx, core_tx, pf.id, now=datetime.combine(target + timedelta(days=2), datetime.min.time(), tzinfo=UTC)
    )

    summary = get_summary(mem_tx, pf.id)
    assert summary["decisions_count"] == 1
    assert summary["actions_count"] == 3
    assert summary["engine_version"] == ENGINE_VERSION
    h5 = summary["horizons"][0]
    assert h5["horizon_sessions"] == 5
    assert h5["status_counts"]["READY"] == 2
    assert h5["status_counts"]["BASELINE_UNAVAILABLE"] == 1
    assert h5["directional_ready_count"] == 2
    assert h5["aligned_count"] == 1  # INCREASE up = aligned, REDUCE up = not aligned
    assert h5["not_aligned_count"] == 1
    assert h5["alignment_rate"] == "0.5000"
    assert h5["sample_warning"] is True
    assert "NOT_PORTFOLIO_PERFORMANCE" in summary["limitations"]
    # V1: descriptive horizon counts only — no marketed accuracy / win-rate KPI.
    assert "accuracy" not in summary
    assert "win_rate" not in summary
    assert "kraken_accuracy" not in summary
    assert get_summary(mem_tx, 999_999_998)["decisions_count"] == 0


# --------------------------------------------------------------------------- operation links


def _linkable(mem: Session, core: Session, name: str):
    pf = _portfolio(core, name)
    inst = _instrument(core, f"{_sym(name)}L")
    other = _instrument(core, f"{_sym(name)}O")
    out = _capture(mem, core, pf, [_act("CONSIDER_INCREASE", inst.symbol), _act("REVIEW", other.symbol)])
    action = next(a for a in out["actions"] if a["symbol"] == inst.symbol)
    review = next(a for a in out["actions"] if a["symbol"] == other.symbol)
    return pf, inst, other, action, review


def test_possible_matches_window_direction_and_instrument(mem_tx, core_tx) -> None:
    pf, inst, other, action, _review = _linkable(mem_tx, core_tx, "pdm-match")
    stranger = _portfolio(core_tx, "pdm-match-stranger")
    t0 = CAPTURE_NOW
    good1 = _op(core_tx, pf, inst, "BUY", t0 + timedelta(hours=1), "m-good1")
    good2 = _op(core_tx, pf, inst, "BUY", t0 + timedelta(days=1), "m-good2")
    _op(core_tx, pf, inst, "BUY", t0 - timedelta(hours=1), "m-before")
    _op(core_tx, pf, inst, "SELL", t0 + timedelta(hours=2), "m-side")
    _op(core_tx, pf, other, "BUY", t0 + timedelta(hours=2), "m-instr")
    _op(core_tx, pf, inst, "BUY", t0 + timedelta(hours=3), "m-cancelled", status="CANCELLED")
    _op(core_tx, stranger, inst, "BUY", t0 + timedelta(hours=3), "m-foreign")
    _op(core_tx, pf, inst, "BUY", t0 + timedelta(days=30), "m-future")

    # A later capture closes the window of the first decision.
    second_capture = t0 + timedelta(days=3)
    _capture(mem_tx, core_tx, pf, [], key="k2", now=second_capture)
    _op(core_tx, pf, inst, "BUY", second_capture + timedelta(hours=1), "m-after-next")

    now = t0 + timedelta(days=10)
    res = list_possible_operation_matches(mem_tx, core_tx, pf.id, action["id"], now=now)
    assert res["window"]["upper_bound"] == "NEXT_CAPTURE"
    assert [m["personal_operation_id"] for m in res["matches"]] == [good1.id, good2.id]
    assert all(m["label"] == "POSSIBLE_MATCH" for m in res["matches"])
    assert all(m["already_linked"] is False for m in res["matches"])


def test_possible_matches_upper_bound_is_now_without_next_capture(mem_tx, core_tx) -> None:
    pf, inst, _other, action, _review = _linkable(mem_tx, core_tx, "pdm-match-now")
    inside = _op(core_tx, pf, inst, "BUY", CAPTURE_NOW + timedelta(hours=1), "n-in")
    _op(core_tx, pf, inst, "BUY", CAPTURE_NOW + timedelta(days=5), "n-out")
    res = list_possible_operation_matches(mem_tx, core_tx, pf.id, action["id"], now=CAPTURE_NOW + timedelta(days=1))
    assert res["window"]["upper_bound"] == "NOW"
    assert [m["personal_operation_id"] for m in res["matches"]] == [inside.id]


def test_non_directional_or_unresolved_actions_have_no_matches(mem_tx, core_tx) -> None:
    pf, inst, _other, _action, review = _linkable(mem_tx, core_tx, "pdm-match-nd")
    _op(core_tx, pf, inst, "BUY", CAPTURE_NOW + timedelta(hours=1), "nd-op")
    res = list_possible_operation_matches(mem_tx, core_tx, pf.id, review["id"], now=CAPTURE_NOW + timedelta(days=1))
    assert res["matches"] == []
    assert res["reason"] == "ACTION_NOT_LINKABLE"


def test_matches_and_links_are_portfolio_scoped(mem_tx, core_tx) -> None:
    pf, inst, _other, action, _review = _linkable(mem_tx, core_tx, "pdm-link-scope")
    stranger = _portfolio(core_tx, "pdm-link-scope-x")
    op = _op(core_tx, pf, inst, "BUY", CAPTURE_NOW + timedelta(hours=1), "ls-op")
    with pytest.raises(NotFoundError):
        list_possible_operation_matches(mem_tx, core_tx, stranger.id, action["id"], now=CAPTURE_NOW)
    with pytest.raises(NotFoundError):
        confirm_operation_link(
            mem_tx,
            core_tx,
            portfolio_id=stranger.id,
            decision_action_id=action["id"],
            personal_operation_id=op.id,
            now=CAPTURE_NOW + timedelta(days=1),
        )


def test_confirm_link_success_is_idempotent_and_creates_no_operation(mem_tx, core_tx) -> None:
    pf, inst, _other, action, _review = _linkable(mem_tx, core_tx, "pdm-link-ok")
    op = _op(core_tx, pf, inst, "BUY", CAPTURE_NOW + timedelta(hours=1), "lk-op")
    ops_before = journal_operation_count(core_tx, pf.id)
    now = CAPTURE_NOW + timedelta(days=1)

    link = confirm_operation_link(
        mem_tx, core_tx, portfolio_id=pf.id, decision_action_id=action["id"], personal_operation_id=op.id, now=now
    )
    assert link["active"] is True
    assert link["link_source"] == "USER_CONFIRMED"
    assert link["already_linked"] is False
    assert _dt(link["linked_at"]) == now
    assert link["personal_operation_id"] == op.id

    again = confirm_operation_link(
        mem_tx, core_tx, portfolio_id=pf.id, decision_action_id=action["id"], personal_operation_id=op.id, now=now
    )
    assert again["id"] == link["id"]
    assert again["already_linked"] is True
    assert _n_links(mem_tx, pf.id) == 1
    assert journal_operation_count(core_tx, pf.id) == ops_before

    matches = list_possible_operation_matches(mem_tx, core_tx, pf.id, action["id"], now=now)
    assert matches["matches"][0]["already_linked"] is True
    assert get_summary(mem_tx, pf.id)["linked_actions_count"] == 1


def test_confirm_link_rejects_incompatible_operations(mem_tx, core_tx) -> None:
    pf, inst, other, action, review = _linkable(mem_tx, core_tx, "pdm-link-bad")
    stranger = _portfolio(core_tx, "pdm-link-bad-x")
    now = CAPTURE_NOW + timedelta(days=2)
    t = CAPTURE_NOW + timedelta(hours=1)
    cases = {
        "before": _op(core_tx, pf, inst, "BUY", CAPTURE_NOW - timedelta(hours=1), "b-before"),
        "side": _op(core_tx, pf, inst, "SELL", t, "b-side"),
        "instrument": _op(core_tx, pf, other, "BUY", t, "b-instr"),
        "cancelled": _op(core_tx, pf, inst, "BUY", t, "b-canc", status="CANCELLED"),
        "future": _op(core_tx, pf, inst, "BUY", now + timedelta(days=1), "b-future"),
    }
    for label, op in cases.items():
        with pytest.raises(DecisionMemoryValidationError) as exc:
            confirm_operation_link(
                mem_tx,
                core_tx,
                portfolio_id=pf.id,
                decision_action_id=action["id"],
                personal_operation_id=op.id,
                now=now,
            )
        assert exc.value.code == "OPERATION_NOT_COMPATIBLE", label

    foreign = _op(core_tx, stranger, inst, "BUY", t, "b-foreign")
    with pytest.raises(NotFoundError):
        confirm_operation_link(
            mem_tx,
            core_tx,
            portfolio_id=pf.id,
            decision_action_id=action["id"],
            personal_operation_id=foreign.id,
            now=now,
        )
    with pytest.raises(NotFoundError):
        confirm_operation_link(
            mem_tx,
            core_tx,
            portfolio_id=pf.id,
            decision_action_id=action["id"],
            personal_operation_id=999_999_999,
            now=now,
        )
    good = _op(core_tx, pf, inst, "BUY", t, "b-good")
    with pytest.raises(DecisionMemoryValidationError):  # REVIEW is not linkable
        confirm_operation_link(
            mem_tx, core_tx, portfolio_id=pf.id, decision_action_id=review["id"], personal_operation_id=good.id, now=now
        )
    assert _n_links(mem_tx, pf.id) == 0


def test_unlink_is_soft_idempotent_and_allows_relink(mem_tx, core_tx) -> None:
    pf, inst, _other, action, _review = _linkable(mem_tx, core_tx, "pdm-unlink")
    op = _op(core_tx, pf, inst, "BUY", CAPTURE_NOW + timedelta(hours=1), "ul-op")
    now = CAPTURE_NOW + timedelta(days=1)
    link = confirm_operation_link(
        mem_tx, core_tx, portfolio_id=pf.id, decision_action_id=action["id"], personal_operation_id=op.id, now=now
    )
    later = now + timedelta(hours=1)
    unlinked = unlink_operation_link(mem_tx, portfolio_id=pf.id, link_id=link["id"], now=later)
    assert unlinked["active"] is False
    assert _dt(unlinked["unlinked_at"]) == later
    # Journal operation untouched, link row preserved.
    assert core_tx.get(PersonalOperation, op.id).status == "ACTIVE"
    assert _n_links(mem_tx, pf.id) == 1

    repeat = unlink_operation_link(mem_tx, portfolio_id=pf.id, link_id=link["id"], now=later + timedelta(hours=5))
    assert _dt(repeat["unlinked_at"]) == later  # unchanged by repeated DELETE

    relinked = confirm_operation_link(
        mem_tx, core_tx, portfolio_id=pf.id, decision_action_id=action["id"], personal_operation_id=op.id, now=later
    )
    assert relinked["id"] != link["id"]
    assert relinked["active"] is True
    assert _n_links(mem_tx, pf.id) == 2

    stranger = _portfolio(core_tx, "pdm-unlink-x")
    with pytest.raises(NotFoundError):
        unlink_operation_link(mem_tx, portfolio_id=stranger.id, link_id=relinked["id"])
    with pytest.raises(NotFoundError):
        unlink_operation_link(mem_tx, portfolio_id=pf.id, link_id=999_999_999)


def test_active_link_uniqueness_is_enforced_by_database(mem_tx, core_tx) -> None:
    from sqlalchemy.exc import IntegrityError

    pf, _inst, _other, action, _review = _linkable(mem_tx, core_tx, "pdm-link-uq")
    with pytest.raises(IntegrityError), mem_tx.begin_nested():
        for _ in range(2):
            mem_tx.add(
                PersonalDecisionOperationLink(
                    decision_action_id=action["id"],
                    portfolio_id=pf.id,
                    personal_operation_id=777,
                    linked_at=CAPTURE_NOW,
                    active=True,
                )
            )
        mem_tx.flush()
    assert _n_links(mem_tx, pf.id) == 0


def test_core_portfolio_reset_does_not_delete_decision_memory(mem_tx, core_tx) -> None:
    """Retention: Core reset wipes bookkeeping only; Memory evidence survives."""
    pf = _portfolio(core_tx, "pdm-reset-keep")
    inst = _instrument(core_tx, "PDMRK")
    pf.cash_rub = Decimal("5000")
    pf.total_contributed_rub = Decimal("5000")
    core_tx.flush()
    captured = _capture(mem_tx, core_tx, pf, [_act("CONSIDER_INCREASE", inst.symbol)], key="reset-keep")
    hash_before = captured["canonical_hash"]
    n_before = (_n_records(mem_tx, pf.id), _n_actions(mem_tx, pf.id), _n_outcomes(mem_tx, pf.id))

    reset_portfolio(core_tx, pf)

    core_tx.refresh(pf)
    assert pf.cash_rub == Decimal("0")
    assert pf.total_contributed_rub == Decimal("0")
    detail = get_decision(mem_tx, pf.id, captured["id"])
    assert detail["canonical_hash"] == hash_before
    assert detail["hash_verified"] is True
    assert (_n_records(mem_tx, pf.id), _n_actions(mem_tx, pf.id), _n_outcomes(mem_tx, pf.id)) == n_before


def test_service_does_not_import_shadow_or_broker_execution() -> None:
    src = Path(inspect.getsourcefile(svc) or "").read_text(encoding="utf-8")
    assert "app.modules.shadow" not in src
    assert "from app.modules.shadow" not in src
    assert "broker_execution" not in src
    assert "execute_order" not in src
    assert "create_personal_operation" not in src
    assert "compute_fee" not in src
    assert "run_shadow" not in src
