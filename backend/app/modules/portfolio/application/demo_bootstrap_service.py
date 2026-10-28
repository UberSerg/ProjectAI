"""Opt-in DEMO/TEST portfolio bootstrap for Investor Journey MVP.

Reuses ``is_test`` isolation. Resolves equities by symbol only (never hardcodes
instrument ids). Does not invent market prices or candles — missing EOD marks
yield partial coverage with explicit warnings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.infrastructure.market.models import Instrument
from app.modules.portfolio.application.personal_portfolio_service import (
    PersonalPortfolioError,
    _resolve_lot_size,
)
from app.modules.portfolio.application.user_portfolio_service import (
    activate_portfolio,
    add_draft_position,
    clear_draft_portfolio,
    create_user_portfolio,
    delete_user_portfolio,
    reset_portfolio,
    set_draft_cash,
)
from app.modules.portfolio.domain.personal_ledger import ZERO, money, units_q
from app.modules.portfolio.domain.valuation import latest_eod_close
from app.modules.portfolio.infrastructure.models import ManualPortfolio, ManualPosition

DEMO_PORTFOLIO_NAME = "DEMO — Investor Journey V1"
DEMO_NOTE = (
    "DEMO/TEST — Investor Journey V1 seed. "
    "Not a real-money book. Isolated via is_test unless --ui-visible."
)
DEMO_SYMBOLS: tuple[str, ...] = ("SBER", "LKOH", "MGNT")
DEFAULT_CASH_RUB = Decimal("500000")
FALLBACK_UNITS_WHEN_LOT_UNKNOWN = Decimal("10")


@dataclass
class DemoBootstrapResult:
    status: str
    portfolio_id: int | None
    name: str
    is_test: bool
    lifecycle_state: str | None
    cash_rub: str | None
    positions: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created: bool = False
    activated: bool = False
    reset: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "portfolio_id": self.portfolio_id,
            "name": self.name,
            "is_test": self.is_test,
            "lifecycle_state": self.lifecycle_state,
            "cash_rub": self.cash_rub,
            "positions": self.positions,
            "skipped": self.skipped,
            "warnings": self.warnings,
            "created": self.created,
            "activated": self.activated,
            "reset": self.reset,
            "api_hint": (
                "List/open with ?test=true when is_test=true "
                "(GET /api/v1/personal-portfolios?test=true)."
                if self.is_test
                else "Visible in default portfolio collection (is_test=false, DEMO-labeled)."
            ),
        }


def _require_confirm(confirm: bool) -> None:
    if not confirm:
        raise PersonalPortfolioError(
            "DEMO_CONFIRM_REQUIRED",
            "Opt-in required: pass confirm=True / CLI --confirm. "
            "DEMO bootstrap mutates a labeled DEMO/TEST portfolio only.",
            http_status=400,
        )


def _unique_instruments_by_symbol(session: Session, symbols: list[str]) -> dict[str, Instrument]:
    wanted = sorted({s.upper() for s in symbols if s})
    if not wanted:
        return {}
    rows = list(session.scalars(select(Instrument).where(func.upper(Instrument.symbol).in_(wanted))))
    grouped: dict[str, list[Instrument]] = {}
    for inst in rows:
        grouped.setdefault(inst.symbol.upper(), []).append(inst)
    return {symbol: items[0] for symbol, items in grouped.items() if len(items) == 1}


def find_demo_portfolio(
    session: Session,
    *,
    name: str = DEMO_PORTFOLIO_NAME,
) -> ManualPortfolio | None:
    return session.scalar(
        select(ManualPortfolio)
        .options(selectinload(ManualPortfolio.positions))
        .where(ManualPortfolio.name == name)
        .order_by(ManualPortfolio.id.asc())
        .limit(1)
    )


def demo_status(session: Session, *, name: str = DEMO_PORTFOLIO_NAME) -> dict[str, Any]:
    row = find_demo_portfolio(session, name=name)
    if row is None:
        return {
            "status": "ABSENT",
            "name": name,
            "portfolio_id": None,
            "is_test": None,
            "lifecycle_state": None,
            "positions_count": 0,
        }
    return {
        "status": "PRESENT",
        "name": row.name,
        "portfolio_id": int(row.id),
        "is_test": bool(row.is_test),
        "lifecycle_state": (row.status or "DRAFT").upper(),
        "cash_rub": str(money(row.cash_rub or ZERO)),
        "positions_count": len(list(row.positions or [])),
        "note": row.note,
    }


def bootstrap_demo_portfolio(
    session: Session,
    *,
    confirm: bool,
    reset: bool = False,
    activate: bool = True,
    ui_visible: bool = False,
    cash_rub: Decimal = DEFAULT_CASH_RUB,
    symbols: tuple[str, ...] | list[str] = DEMO_SYMBOLS,
    name: str = DEMO_PORTFOLIO_NAME,
) -> DemoBootstrapResult:
    """Create or refresh the DEMO book. Idempotent when already seeded+ACTIVE.

    Partial coverage is OK: unresolved symbols / missing EOD / unknown lots are
    reported in ``skipped`` / ``warnings`` — never silent fake prices.
    """
    _require_confirm(confirm)
    cash = money(cash_rub)
    if cash < ZERO:
        raise PersonalPortfolioError("INVALID_AMOUNT", "cash_rub must be >= 0")

    wanted = [s.upper().strip() for s in symbols if s and str(s).strip()]
    if not wanted:
        raise PersonalPortfolioError("DEMO_SYMBOLS_REQUIRED", "Provide at least one symbol")

    is_test = not ui_visible
    created = False
    did_reset = False
    portfolio = find_demo_portfolio(session, name=name)

    if portfolio is not None and bool(portfolio.is_test) != is_test:
        # Keep isolation contract stable for an existing book; warn rather than flip.
        is_test = bool(portfolio.is_test)
        warnings_pre = [
            "Existing DEMO book is_test flag preserved "
            f"(requested ui_visible={ui_visible})."
        ]
    else:
        warnings_pre = []

    if portfolio is None:
        portfolio = create_user_portfolio(
            session,
            name=name,
            description=DEMO_NOTE,
            is_test=is_test,
        )
        created = True
    elif reset:
        reset_portfolio(session, portfolio)
        session.refresh(portfolio)
        did_reset = True
    elif (portfolio.status or "").upper() == "ACTIVE":
        # Idempotent no-op when already active (unless reset).
        positions = [
            {
                "instrument_id": int(p.instrument_id),
                "units": str(units_q(p.units)),
                "average_price": str(p.average_price) if p.average_price is not None else None,
            }
            for p in (portfolio.positions or [])
        ]
        result = DemoBootstrapResult(
            status="ALREADY_READY",
            portfolio_id=int(portfolio.id),
            name=portfolio.name,
            is_test=bool(portfolio.is_test),
            lifecycle_state="ACTIVE",
            cash_rub=str(money(portfolio.cash_rub or ZERO)),
            positions=positions,
            warnings=warnings_pre
            + ["Portfolio already ACTIVE — no mutation (pass reset=True to rebuild)."],
            created=False,
            activated=False,
            reset=False,
        )
        return result

    # Ensure DEMO labeling on note; rebuild draft snapshot from symbols.
    portfolio.note = DEMO_NOTE
    session.flush()
    if (portfolio.status or "").upper() == "DRAFT":
        clear_draft_portfolio(session, portfolio)

    skipped: list[dict[str, Any]] = []
    warnings = list(warnings_pre)
    catalog = _unique_instruments_by_symbol(session, wanted)
    for symbol in wanted:
        if symbol not in catalog:
            # Ambiguous duplicates also treated as unresolved (never pick an id).
            rows = list(
                session.scalars(select(Instrument).where(func.upper(Instrument.symbol) == symbol))
            )
            reason = "SYMBOL_AMBIGUOUS" if len(rows) > 1 else "SYMBOL_NOT_IN_MASTER"
            skipped.append({"symbol": symbol, "reason": reason})
            warnings.append(f"{symbol}: skipped ({reason})")

    set_draft_cash(session, portfolio, cash)

    seeded: list[dict[str, Any]] = []
    for symbol, instrument in catalog.items():
        if (instrument.asset_class or "").lower() == "bond":
            skipped.append({"symbol": symbol, "reason": "BOND_NOT_IN_DEMO_SEED"})
            warnings.append(f"{symbol}: skipped (bond not part of DEMO equity seed)")
            continue
        close, close_ts = latest_eod_close(session, int(instrument.id))
        if close is None or close <= ZERO:
            skipped.append({"symbol": symbol, "reason": "EOD_PRICE_MISSING", "instrument_id": int(instrument.id)})
            warnings.append(f"{symbol}: skipped (no EOD close — refusing fake price)")
            continue

        lot_size = _resolve_lot_size(session, instrument)
        non_standard = False
        if lot_size is not None and lot_size > 0:
            units = units_q(Decimal(lot_size))  # 1 exchange lot
            lots_arg: Decimal | None = Decimal("1")
            units_arg: Decimal | None = None
        else:
            units = units_q(FALLBACK_UNITS_WHEN_LOT_UNKNOWN)
            lots_arg = None
            units_arg = units
            non_standard = True
            warnings.append(
                f"{symbol}: LOT_SIZE_UNKNOWN — seeded {units} units with non_standard_lot"
            )

        pos = add_draft_position(
            session,
            portfolio,
            instrument_id=int(instrument.id),
            units=units_arg,
            lots=lots_arg,
            average_price=money(close),
            note=f"DEMO seed @ EOD {close_ts or 'unknown'}",
            non_standard_lot=non_standard,
        )
        seeded.append(
            {
                "symbol": symbol,
                "instrument_id": int(instrument.id),
                "position_id": int(pos.id),
                "units": str(units_q(pos.units)),
                "lot_size": lot_size,
                "average_price": str(money(close)),
                "eod_as_of": close_ts,
                "non_standard_lot": non_standard,
            }
        )

    activated = False
    if activate:
        summary = activate_portfolio(session, portfolio)
        activated = True
        lifecycle = str(summary.get("portfolio", {}).get("lifecycle_state") or "ACTIVE")
        cash_out = str(summary.get("summary", {}).get("cash_rub") or money(portfolio.cash_rub or ZERO))
    else:
        session.refresh(portfolio)
        lifecycle = (portfolio.status or "DRAFT").upper()
        cash_out = str(money(portfolio.cash_rub or ZERO))

    return DemoBootstrapResult(
        status="BOOTSTRAPPED" if created or did_reset or seeded else "PARTIAL",
        portfolio_id=int(portfolio.id),
        name=portfolio.name,
        is_test=bool(portfolio.is_test),
        lifecycle_state=lifecycle,
        cash_rub=cash_out,
        positions=seeded,
        skipped=skipped,
        warnings=warnings,
        created=created,
        activated=activated,
        reset=did_reset,
    )


def reset_demo_portfolio(
    session: Session,
    *,
    confirm: bool,
    name: str = DEMO_PORTFOLIO_NAME,
    delete: bool = False,
) -> dict[str, Any]:
    """Reversible teardown: wipe to empty DRAFT, optionally hard-delete."""
    _require_confirm(confirm)
    portfolio = find_demo_portfolio(session, name=name)
    if portfolio is None:
        return {"status": "ABSENT", "name": name, "deleted": False}
    if delete:
        out = delete_user_portfolio(session, portfolio)
        return {"status": "DELETED", "name": name, **out}
    summary = reset_portfolio(session, portfolio)
    return {
        "status": "RESET",
        "name": name,
        "portfolio_id": int(portfolio.id),
        "lifecycle_state": "DRAFT",
        "cash_rub": str(money(portfolio.cash_rub or ZERO)),
        "positions_count": int(
            session.scalar(
                select(func.count())
                .select_from(ManualPosition)
                .where(ManualPosition.portfolio_id == portfolio.id)
            )
            or 0
        ),
        "summary_status": summary.get("portfolio", {}).get("lifecycle_state"),
    }
