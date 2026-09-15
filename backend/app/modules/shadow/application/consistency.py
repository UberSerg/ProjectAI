"""Shadow portfolio consistency checks (V1 + lot-aware V2)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Instrument
from app.modules.investment.application.equity_lot_size import resolve_equity_lot_sizes
from app.modules.shadow.application.lot_aware import is_lot_aware_spec
from app.modules.shadow.infrastructure.models import (
    ShadowFill,
    ShadowOrder,
    ShadowPortfolio,
    ShadowPortfolioSpec,
)


@dataclass(frozen=True, slots=True)
class ConsistencyIssue:
    severity: str  # BLOCKER | WARNING
    code: str
    portfolio_id: int | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "portfolio_id": self.portfolio_id,
            "detail": self.detail,
        }


def check_shadow_consistency(
    session: Session,
    *,
    portfolio_ids: Sequence[int] | None = None,
    repair_lot_sizes: bool = False,
) -> list[ConsistencyIssue]:
    issues: list[ConsistencyIssue] = []
    q = select(ShadowPortfolio, ShadowPortfolioSpec).join(
        ShadowPortfolioSpec, ShadowPortfolio.spec_id == ShadowPortfolioSpec.id
    )
    if portfolio_ids is not None:
        q = q.where(ShadowPortfolio.id.in_(list(portfolio_ids)))
    rows = list(session.execute(q.order_by(ShadowPortfolio.id)).all())

    for portfolio, spec in rows:
        pid = int(portfolio.id)
        if float(portfolio.cash) < -1e-6:
            issues.append(
                ConsistencyIssue(
                    "BLOCKER",
                    "NEGATIVE_CASH",
                    pid,
                    f"cash={portfolio.cash}",
                )
            )

        lot_aware = is_lot_aware_spec(spec)
        if lot_aware and repair_lot_sizes:
            from app.modules.shadow.application.service import (
                repair_missing_position_lot_sizes,
            )

            repair_missing_position_lot_sizes(session, portfolio)

        positions = portfolio.positions or {}
        if isinstance(positions, dict):
            missing_ids: list[int] = []
            for key, row in positions.items():
                if not isinstance(row, dict):
                    continue
                qty = float(row.get("quantity") or 0)
                if abs(qty) < 1e-12:
                    continue
                if not lot_aware:
                    continue
                if abs(qty - round(qty)) > 1e-6:
                    issues.append(
                        ConsistencyIssue(
                            "BLOCKER",
                            "FRACTIONAL_UNITS",
                            pid,
                            f"instrument={key} quantity={qty}",
                        )
                    )
                lot_size = row.get("lot_size")
                try:
                    ls = int(lot_size) if lot_size is not None else 0
                except (TypeError, ValueError):
                    ls = 0
                if ls <= 0:
                    missing_ids.append(int(row.get("instrument_id") or key))
                elif int(round(qty)) % ls != 0:
                    issues.append(
                        ConsistencyIssue(
                            "BLOCKER",
                            "UNITS_NOT_DIVISIBLE_BY_LOT",
                            pid,
                            f"instrument={key} quantity={qty} lot_size={ls}",
                        )
                    )
            if missing_ids and lot_aware:
                instruments = list(
                    session.scalars(
                        select(Instrument).where(Instrument.id.in_(sorted(set(missing_ids))))
                    )
                )
                resolved = resolve_equity_lot_sizes(session, instruments, fetch_missing=False)
                for iid in missing_ids:
                    hit = resolved.get(iid)
                    if hit is not None and hit.lot_size and hit.lot_size > 0:
                        issues.append(
                            ConsistencyIssue(
                                "WARNING",
                                "MISSING_LOT_SIZE_ON_POSITION_ROW",
                                pid,
                                f"instrument={iid} master_lot_size={hit.lot_size}",
                            )
                        )
                    else:
                        issues.append(
                            ConsistencyIssue(
                                "BLOCKER",
                                "MISSING_LOT_SIZE",
                                pid,
                                f"instrument={iid}",
                            )
                        )

        fill_rows = list(
            session.scalars(select(ShadowFill).where(ShadowFill.portfolio_id == pid))
        )
        seen_orders: dict[int, int] = {}
        for fill in fill_rows:
            oid = int(fill.order_id)
            seen_orders[oid] = seen_orders.get(oid, 0) + 1
        for oid, n in seen_orders.items():
            if n > 1:
                issues.append(
                    ConsistencyIssue(
                        "BLOCKER",
                        "DUPLICATE_FILL",
                        pid,
                        f"order_id={oid} fills={n}",
                    )
                )

        pending = list(
            session.scalars(
                select(ShadowOrder).where(
                    ShadowOrder.portfolio_id == pid, ShadowOrder.status == "PENDING"
                )
            )
        )
        for order in pending:
            if order.side != "SELL":
                continue
            qty = 0.0
            if isinstance(positions, dict):
                row = positions.get(str(order.instrument_id)) or {}
                qty = float(row.get("quantity") or 0) if isinstance(row, dict) else 0.0
            if qty <= 1e-12:
                issues.append(
                    ConsistencyIssue(
                        "WARNING",
                        "PENDING_SELL_WITHOUT_POSITION",
                        pid,
                        f"order_id={order.id} ticker={order.ticker}",
                    )
                )

    return issues
