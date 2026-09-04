"""CLI for Shadow Portfolio V0."""

from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy import select

from app.infrastructure.db.session import core_session
from app.modules.shadow.application.service import (
    advance_all_shadow_portfolios,
    advance_shadow_portfolio,
    initialize_shadow_portfolios,
)
from app.modules.shadow.infrastructure.models import (
    ShadowFill,
    ShadowOrder,
    ShadowPortfolio,
    ShadowPortfolioSpec,
)


def _portfolio_status(session, portfolio_id: int | None = None) -> list[dict]:
    q = (
        select(ShadowPortfolio, ShadowPortfolioSpec)
        .join(ShadowPortfolioSpec, ShadowPortfolio.spec_id == ShadowPortfolioSpec.id)
        .order_by(ShadowPortfolio.id)
    )
    if portfolio_id is not None:
        q = q.where(ShadowPortfolio.id == portfolio_id)
    out = []
    for portfolio, spec in session.execute(q).all():
        pending = session.scalars(
            select(ShadowOrder).where(
                ShadowOrder.portfolio_id == portfolio.id, ShadowOrder.status == "PENDING"
            )
        ).all()
        fills = session.scalars(
            select(ShadowFill).where(ShadowFill.portfolio_id == portfolio.id)
        ).all()
        out.append(
            {
                "id": portfolio.id,
                "name": spec.name,
                "status": portfolio.status,
                "activated_at": portfolio.activated_at.isoformat() if portfolio.activated_at else None,
                "first_forward_batch_id": portfolio.first_forward_batch_id,
                "first_forward_as_of_date": (
                    portfolio.first_forward_as_of_date.isoformat()
                    if portfolio.first_forward_as_of_date
                    else None
                ),
                "cash": portfolio.cash,
                "nav_approx_cash_only_if_no_mtm": portfolio.cash,
                "positions": portfolio.positions,
                "pending_orders": len(pending),
                "fills": len(fills),
                "risk_mode": portfolio.risk_mode,
                "exposure_cap": portfolio.exposure_cap,
                "last_processed_market_date": (
                    portfolio.last_processed_market_date.isoformat()
                    if portfolio.last_processed_market_date
                    else None
                ),
                "last_decision_iso_week": portfolio.last_decision_iso_week,
                "policy": spec.policy_name,
                "risk": spec.risk_name,
                "kind": "FORWARD_SHADOW",
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Shadow Portfolio V0 (forward-only)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    init_p = sub.add_parser("init", help="Initialize both Shadow portfolios from latest Forward batch")
    init_p.add_argument("--batch-id", type=int, default=None)
    sub.add_parser("advance", help="Advance all Shadow portfolios")
    adv = sub.add_parser("advance-one", help="Advance one portfolio by id")
    adv.add_argument("portfolio_id", type=int)
    st = sub.add_parser("status", help="Inspect Shadow portfolio status")
    st.add_argument("--portfolio-id", type=int, default=None)
    args = parser.parse_args(argv)

    with core_session() as session:
        if args.cmd == "init":
            results = initialize_shadow_portfolios(session, first_batch_id=args.batch_id)
            session.commit()
            payload = [
                {"portfolio_id": r.portfolio_id, "name": r.name, "status": r.status, **r.summary}
                for r in results
            ]
        elif args.cmd == "advance":
            results = advance_all_shadow_portfolios(session)
            session.commit()
            payload = [
                {"portfolio_id": r.portfolio_id, "name": r.name, "status": r.status, **r.summary}
                for r in results
            ]
        elif args.cmd == "advance-one":
            r = advance_shadow_portfolio(session, args.portfolio_id)
            session.commit()
            payload = {"portfolio_id": r.portfolio_id, "name": r.name, "status": r.status, **r.summary}
        else:
            payload = _portfolio_status(session, args.portfolio_id)
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
