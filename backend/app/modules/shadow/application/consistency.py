"""Shadow portfolio consistency checks (V1 + lot-aware V2)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

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
        positions = portfolio.positions or {}
        if isinstance(positions, dict):
            for key, row in positions.items():
                if not isinstance(row, dict):
                    continue
                qty = float(row.get("quantity") or 0)
                if abs(qty) < 1e-12:
                    continue
                if lot_aware:
                    # Fractional units forbidden
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
                        issues.append(
                            ConsistencyIssue(
                                "BLOCKER",
                                "MISSING_LOT_SIZE",
                                pid,
                                f"instrument={key}",
                            )
                        )
                    elif int(round(qty)) % ls != 0:
                        issues.append(
                            ConsistencyIssue(
                                "BLOCKER",
                                "UNITS_NOT_DIVISIBLE_BY_LOT",
                                pid,
                                f"instrument={key} quantity={qty} lot_size={ls}",
                            )
                        )

        # Duplicate fills per order
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
                        f"order_id={oid} fill_count={n}",
                    )
                )

        # Fill without order
        if fill_rows:
            order_ids = {int(f.order_id) for f in fill_rows}
            existing = set(
                session.scalars(select(ShadowOrder.id).where(ShadowOrder.id.in_(order_ids))).all()
            )
            for oid in order_ids:
                if oid not in existing:
                    issues.append(
                        ConsistencyIssue(
                            "BLOCKER",
                            "FILL_WITHOUT_ORDER",
                            pid,
                            f"order_id={oid}",
                        )
                    )

        # FILLED order without fill row
        filled_orders = list(
            session.scalars(
                select(ShadowOrder).where(
                    ShadowOrder.portfolio_id == pid,
                    ShadowOrder.status == "FILLED",
                )
            )
        )
        for order in filled_orders:
            n = session.scalar(
                select(func.count()).select_from(ShadowFill).where(ShadowFill.order_id == order.id)
            )
            if int(n or 0) == 0:
                issues.append(
                    ConsistencyIssue(
                        "WARNING",
                        "FILLED_ORDER_MISSING_FILL",
                        pid,
                        f"order_id={order.id}",
                    )
                )

    return issues
