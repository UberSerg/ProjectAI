"""Multi-Portfolio V2 — collection, DRAFT setup, activate, reset, delete."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.infrastructure.market.models import Instrument
from app.modules.portfolio.application.personal_portfolio_service import (
    PersonalPortfolioError,
    get_personal_summary,
    load_personal_snapshot,
    project_portfolio,
    rebuild_ledger_from_journal,
)
from app.modules.portfolio.domain.lots import LotValidationError, assert_lot_compatible
from app.modules.portfolio.domain.personal_ledger import ZERO, money, units_q
from app.modules.portfolio.infrastructure.models import (
    ManualPortfolio,
    ManualPosition,
    PersonalOperation,
)

LIFECYCLE_DRAFT = "DRAFT"
LIFECYCLE_ACTIVE = "ACTIVE"
OPENING_SOURCE = "OPENING_SNAPSHOT"
NAME_MAX_LEN = 120


def _now() -> datetime:
    return datetime.now(UTC)


def _normalize_name(name: str | None) -> str:
    return (name or "").strip()


def _validate_name(name: str) -> str:
    cleaned = _normalize_name(name)
    if not cleaned:
        raise PersonalPortfolioError(
            "PORTFOLIO_NAME_REQUIRED",
            "Укажите название портфеля.",
            http_status=400,
        )
    if len(cleaned) > NAME_MAX_LEN:
        raise PersonalPortfolioError(
            "PORTFOLIO_NAME_REQUIRED",
            f"Название слишком длинное (максимум {NAME_MAX_LEN} символов).",
            http_status=400,
        )
    return cleaned


def get_portfolio(
    session: Session,
    portfolio_id: int,
    *,
    allow_test: bool = False,
) -> ManualPortfolio:
    row = session.scalar(
        select(ManualPortfolio)
        .options(selectinload(ManualPortfolio.positions))
        .where(ManualPortfolio.id == portfolio_id)
    )
    if row is None:
        raise PersonalPortfolioError(
            "PORTFOLIO_NOT_FOUND",
            "Портфель не найден.",
            http_status=404,
        )
    if row.is_test and not allow_test:
        raise PersonalPortfolioError(
            "PORTFOLIO_NOT_FOUND",
            "Портфель не найден.",
            http_status=404,
        )
    return row


def require_draft(portfolio: ManualPortfolio) -> None:
    if (portfolio.status or "").upper() != LIFECYCLE_DRAFT:
        raise PersonalPortfolioError(
            "PORTFOLIO_NOT_DRAFT",
            (
                "Этот портфель уже ведёт историю операций. "
                "Для изменения состава используйте операции или сбросьте портфель."
            ),
            http_status=409,
        )


def require_active(portfolio: ManualPortfolio) -> None:
    if (portfolio.status or "").upper() != LIFECYCLE_ACTIVE:
        raise PersonalPortfolioError(
            "PORTFOLIO_NOT_ACTIVE",
            "Сначала начните учёт для этого портфеля.",
            http_status=409,
        )


def list_user_portfolios(session: Session, *, include_test: bool = False) -> list[dict[str, Any]]:
    q = select(ManualPortfolio).order_by(
        ManualPortfolio.updated_at.desc().nullslast(),
        ManualPortfolio.id.desc(),
    )
    if not include_test:
        q = q.where(ManualPortfolio.is_test.is_(False))
    rows = list(session.scalars(q).all())
    cards: list[dict[str, Any]] = []
    for row in rows:
        snap = load_personal_snapshot(session, row)
        pos_count = len(snap.positions)
        cards.append(
            {
                "id": int(row.id),
                "name": row.name,
                "description": row.note,
                "lifecycle_state": (row.status or LIFECYCLE_DRAFT).upper(),
                "cash_rub": str(snap.cash_rub),
                "known_nav_rub": str(snap.known_nav_rub),
                "positions_count": pos_count,
                "valuation_partial": snap.valuation_partial,
                "valuation_label": snap.valuation_label,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "is_test": bool(row.is_test),
            }
        )
    return cards


def create_user_portfolio(
    session: Session,
    *,
    name: str,
    description: str | None = None,
    is_test: bool = False,
) -> ManualPortfolio:
    cleaned = _validate_name(name)
    row = ManualPortfolio(
        name=cleaned,
        source="MANUAL",
        base_currency="RUB",
        cash_rub=ZERO,
        status=LIFECYCLE_DRAFT,
        note=(description or "").strip() or None,
        is_test=is_test,
        version=1,
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError as exc:
        raise PersonalPortfolioError(
            "PORTFOLIO_NAME_EXISTS",
            "Портфель с таким названием уже существует.",
            http_status=409,
        ) from exc
    return row


def rename_user_portfolio(
    session: Session,
    portfolio: ManualPortfolio,
    *,
    name: str | None = None,
    description: str | None = ...,  # type: ignore[assignment]
) -> ManualPortfolio:
    if name is not None:
        portfolio.name = _validate_name(name)
    if description is not ...:
        portfolio.note = (description or "").strip() or None
    portfolio.updated_at = _now()
    portfolio.version = int(portfolio.version or 1) + 1
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        raise PersonalPortfolioError(
            "PORTFOLIO_NAME_EXISTS",
            "Портфель с таким названием уже существует.",
            http_status=409,
        ) from exc
    return portfolio


def delete_user_portfolio(session: Session, portfolio: ManualPortfolio) -> dict[str, Any]:
    pid = int(portfolio.id)
    name = portfolio.name
    # Explicit child deletes then portfolio (CASCADE would also work).
    session.execute(
        PersonalOperation.__table__.delete().where(PersonalOperation.portfolio_id == pid)
    )
    session.execute(ManualPosition.__table__.delete().where(ManualPosition.portfolio_id == pid))
    # Drop ORM identity for already-deleted children to avoid SA cascade mismatch warning.
    session.expire(portfolio, ["positions"])
    session.delete(portfolio)
    session.flush()
    return {"status": "DELETED", "id": pid, "name": name}


def set_draft_cash(session: Session, portfolio: ManualPortfolio, cash_rub: Decimal) -> ManualPortfolio:
    require_draft(portfolio)
    if cash_rub < ZERO:
        raise PersonalPortfolioError("INVALID_AMOUNT", "Кэш не может быть отрицательным")
    portfolio.cash_rub = money(cash_rub)
    portfolio.updated_at = _now()
    portfolio.version = int(portfolio.version or 1) + 1
    session.flush()
    return portfolio


def _resolve_lot_size(session: Session, instrument: Instrument) -> int | None:
    from app.modules.portfolio.application.personal_portfolio_service import _resolve_lot_size as _rl

    return _rl(session, instrument)


def add_draft_position(
    session: Session,
    portfolio: ManualPortfolio,
    *,
    instrument_id: int,
    units: Decimal | None = None,
    lots: Decimal | None = None,
    average_price: Decimal | None = None,
    cost_basis_total_rub: Decimal | None = None,
    note: str | None = None,
    non_standard_lot: bool = False,
) -> ManualPosition:
    """Add/replace a DRAFT position.

    Equities/funds: optional ``average_price`` = RUB per unit.
    Bonds: optional ``cost_basis_total_rub`` = total RUB spent (never MOEX %).
    Stored as per-unit ``average_price`` when known; ``None`` when unknown.
    """
    require_draft(portfolio)
    instrument = session.get(Instrument, instrument_id)
    if instrument is None:
        raise PersonalPortfolioError("INSTRUMENT_NOT_FOUND", "Инструмент не найден", http_status=404)

    asset = (instrument.asset_class or "").lower()
    lot_size = _resolve_lot_size(session, instrument)
    resolved_units = units_q(units) if units is not None else ZERO
    if lots is not None and Decimal(str(lots)) > ZERO:
        if lot_size is None:
            raise PersonalPortfolioError(
                "LOT_SIZE_UNKNOWN",
                "Размер лота неизвестен — укажите количество штук.",
            )
        from app.modules.portfolio.domain.personal_ledger import lots_to_units

        resolved_units = lots_to_units(Decimal(str(lots)), lot_size)
    if resolved_units <= ZERO:
        raise PersonalPortfolioError("INVALID_UNITS", "Количество должно быть больше нуля")
    try:
        assert_lot_compatible(resolved_units, lot_size, non_standard_lot=non_standard_lot)
    except LotValidationError as exc:
        raise PersonalPortfolioError(exc.code, str(exc)) from exc

    stored_avg: Decimal | None = None
    if asset == "bond":
        if cost_basis_total_rub is not None:
            total = money(cost_basis_total_rub)
            if total < ZERO:
                raise PersonalPortfolioError("INVALID_AMOUNT", "Себестоимость не может быть отрицательной")
            stored_avg = money(total / resolved_units) if resolved_units > ZERO else None
        # Ignore average_price for bonds — prevents %/RUB confusion.
    else:
        if average_price is not None:
            px = money(average_price)
            if px < ZERO:
                raise PersonalPortfolioError("INVALID_PRICE", "Себестоимость не может быть отрицательной")
            stored_avg = px
        elif cost_basis_total_rub is not None:
            total = money(cost_basis_total_rub)
            if total < ZERO:
                raise PersonalPortfolioError("INVALID_AMOUNT", "Себестоимость не может быть отрицательной")
            stored_avg = money(total / resolved_units)

    existing = session.scalar(
        select(ManualPosition).where(
            ManualPosition.portfolio_id == portfolio.id,
            ManualPosition.instrument_id == instrument_id,
        )
    )
    if existing is not None:
        existing.units = resolved_units
        existing.average_price = stored_avg
        existing.note = note
        existing.non_standard_lot = non_standard_lot
        existing.updated_at = _now()
        pos = existing
    else:
        pos = ManualPosition(
            portfolio_id=portfolio.id,
            instrument_id=instrument_id,
            units=resolved_units,
            average_price=stored_avg,
            note=note,
            non_standard_lot=non_standard_lot,
        )
        session.add(pos)
    portfolio.updated_at = _now()
    portfolio.version = int(portfolio.version or 1) + 1
    session.flush()
    return pos


def patch_draft_position(
    session: Session,
    portfolio: ManualPortfolio,
    position_id: int,
    *,
    units: Decimal | None = None,
    lots: Decimal | None = None,
    average_price: Decimal | None = None,
    cost_basis_total_rub: Decimal | None = None,
    clear_cost_basis: bool = False,
    note: str | None = ...,  # type: ignore[assignment]
    non_standard_lot: bool | None = None,
) -> ManualPosition:
    require_draft(portfolio)
    pos = session.get(ManualPosition, position_id)
    if pos is None or pos.portfolio_id != portfolio.id:
        raise PersonalPortfolioError("POSITION_NOT_FOUND", "Позиция не найдена", http_status=404)
    instrument = session.get(Instrument, pos.instrument_id)
    if instrument is None:
        raise PersonalPortfolioError("INSTRUMENT_NOT_FOUND", "Инструмент не найден", http_status=404)

    asset = (instrument.asset_class or "").lower()
    lot_size = _resolve_lot_size(session, instrument)
    resolved_units = units_q(pos.units)
    if lots is not None:
        from app.modules.portfolio.domain.personal_ledger import lots_to_units

        if lot_size is None:
            raise PersonalPortfolioError("LOT_SIZE_UNKNOWN", "Размер лота неизвестен")
        resolved_units = lots_to_units(Decimal(str(lots)), lot_size)
    elif units is not None:
        resolved_units = units_q(units)
    if resolved_units <= ZERO:
        raise PersonalPortfolioError("INVALID_UNITS", "Количество должно быть больше нуля")
    try:
        assert_lot_compatible(
            resolved_units,
            lot_size,
            non_standard_lot=bool(non_standard_lot if non_standard_lot is not None else pos.non_standard_lot),
        )
    except LotValidationError as exc:
        raise PersonalPortfolioError(exc.code, str(exc)) from exc

    pos.units = resolved_units
    if clear_cost_basis:
        pos.average_price = None
    elif asset == "bond" and cost_basis_total_rub is not None:
        total = money(cost_basis_total_rub)
        if total < ZERO:
            raise PersonalPortfolioError("INVALID_AMOUNT", "Себестоимость не может быть отрицательной")
        pos.average_price = money(total / resolved_units)
    elif average_price is not None and asset != "bond":
        px = money(average_price)
        if px < ZERO:
            raise PersonalPortfolioError("INVALID_PRICE", "Себестоимость не может быть отрицательной")
        pos.average_price = px
    elif cost_basis_total_rub is not None and asset != "bond":
        total = money(cost_basis_total_rub)
        pos.average_price = money(total / resolved_units)
    if note is not ...:
        pos.note = note
    if non_standard_lot is not None:
        pos.non_standard_lot = non_standard_lot
    pos.updated_at = _now()
    portfolio.updated_at = _now()
    portfolio.version = int(portfolio.version or 1) + 1
    session.flush()
    return pos


def delete_draft_position(session: Session, portfolio: ManualPortfolio, position_id: int) -> dict[str, Any]:
    require_draft(portfolio)
    pos = session.get(ManualPosition, position_id)
    if pos is None or pos.portfolio_id != portfolio.id:
        raise PersonalPortfolioError("POSITION_NOT_FOUND", "Позиция не найдена", http_status=404)
    pid = int(pos.id)
    session.delete(pos)
    portfolio.updated_at = _now()
    portfolio.version = int(portfolio.version or 1) + 1
    session.flush()
    return {"status": "DELETED", "id": pid}


def clear_draft_portfolio(session: Session, portfolio: ManualPortfolio) -> ManualPortfolio:
    require_draft(portfolio)
    session.execute(
        ManualPosition.__table__.delete().where(ManualPosition.portfolio_id == portfolio.id)
    )
    portfolio.cash_rub = ZERO
    portfolio.total_contributed_rub = ZERO
    portfolio.total_withdrawn_rub = ZERO
    portfolio.realized_pnl_rub = ZERO
    portfolio.updated_at = _now()
    portfolio.version = int(portfolio.version or 1) + 1
    session.flush()
    return portfolio


def activate_portfolio(session: Session, portfolio: ManualPortfolio) -> dict[str, Any]:
    """DRAFT snapshot → OPENING_* journal → ACTIVE. Allows unknown / bond basis."""
    if (portfolio.status or "").upper() == LIFECYCLE_ACTIVE:
        # Idempotent
        if session.scalar(
            select(func.count())
            .select_from(PersonalOperation)
            .where(PersonalOperation.portfolio_id == portfolio.id)
        ):
            rebuilt = rebuild_ledger_from_journal(session, int(portfolio.id))
            project_portfolio(session, portfolio, rebuilt)
        return get_personal_summary(session, portfolio, owner=True)

    require_draft(portfolio)
    positions = list(
        session.scalars(
            select(ManualPosition).where(ManualPosition.portfolio_id == portfolio.id)
        ).all()
    )
    cutover_at = _now()
    try:
        with session.begin_nested():
            cash = money(portfolio.cash_rub)
            if cash > ZERO:
                key = f"opening:{portfolio.id}:cash"
                if (
                    session.scalar(
                        select(PersonalOperation.id).where(
                            PersonalOperation.portfolio_id == portfolio.id,
                            PersonalOperation.idempotency_key == key,
                        )
                    )
                    is None
                ):
                    session.add(
                        PersonalOperation(
                            portfolio_id=portfolio.id,
                            operation_type="OPENING_CASH",
                            status="ACTIVE",
                            occurred_at=cutover_at,
                            amount=cash,
                            commission=ZERO,
                            currency="RUB",
                            source=OPENING_SOURCE,
                            note="Opening cash",
                            idempotency_key=key,
                        )
                    )

            for pos in positions:
                key = f"opening:{portfolio.id}:position:{pos.instrument_id}"
                if (
                    session.scalar(
                        select(PersonalOperation.id).where(
                            PersonalOperation.portfolio_id == portfolio.id,
                            PersonalOperation.idempotency_key == key,
                        )
                    )
                    is not None
                ):
                    continue
                session.add(
                    PersonalOperation(
                        portfolio_id=portfolio.id,
                        operation_type="OPENING_POSITION",
                        status="ACTIVE",
                        occurred_at=cutover_at,
                        instrument_id=int(pos.instrument_id),
                        units=units_q(pos.units),
                        price=money(pos.average_price) if pos.average_price is not None else None,
                        commission=ZERO,
                        currency="RUB",
                        source=OPENING_SOURCE,
                        note=f"Opening position #{pos.id}",
                        idempotency_key=key,
                    )
                )
            session.flush()
            rebuilt = rebuild_ledger_from_journal(session, int(portfolio.id))
            project_portfolio(session, portfolio, rebuilt)
            portfolio.status = LIFECYCLE_ACTIVE
            portfolio.updated_at = _now()
            session.flush()
    except IntegrityError as exc:
        # Concurrent activate — if already ACTIVE with ops, return summary.
        session.refresh(portfolio)
        if (portfolio.status or "").upper() == LIFECYCLE_ACTIVE:
            return get_personal_summary(session, portfolio, owner=True)
        raise PersonalPortfolioError(
            "IDEMPOTENCY_CONFLICT",
            "Конфликт активации. Повторите запрос.",
            http_status=409,
        ) from exc

    return get_personal_summary(session, portfolio, owner=True)


def reset_portfolio(session: Session, portfolio: ManualPortfolio) -> dict[str, Any]:
    """Destructive: wipe journal + positions, cash→0, lifecycle→DRAFT. Idempotent."""
    pid = int(portfolio.id)
    session.execute(
        PersonalOperation.__table__.delete().where(PersonalOperation.portfolio_id == pid)
    )
    session.execute(ManualPosition.__table__.delete().where(ManualPosition.portfolio_id == pid))
    portfolio.cash_rub = ZERO
    portfolio.total_contributed_rub = ZERO
    portfolio.total_withdrawn_rub = ZERO
    portfolio.realized_pnl_rub = ZERO
    portfolio.status = LIFECYCLE_DRAFT
    portfolio.updated_at = _now()
    portfolio.version = int(portfolio.version or 1) + 1
    session.flush()
    return get_personal_summary(session, portfolio, owner=True)
