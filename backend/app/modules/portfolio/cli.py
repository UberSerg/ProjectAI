"""CLI — DEMO/TEST Investor Journey portfolio bootstrap (opt-in)."""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation

from app.infrastructure.db.session import core_session
from app.modules.portfolio.application.demo_bootstrap_service import (
    DEMO_PORTFOLIO_NAME,
    DEMO_SYMBOLS,
    bootstrap_demo_portfolio,
    demo_status,
    reset_demo_portfolio,
)
from app.modules.portfolio.application.personal_portfolio_service import PersonalPortfolioError


def _parse_cash(raw: str) -> Decimal:
    try:
        value = Decimal(str(raw).strip().replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError) as exc:
        raise SystemExit(f"Invalid --cash-rub: {raw}") from exc
    if value < 0:
        raise SystemExit("--cash-rub must be >= 0")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "DEMO/TEST Investor Journey portfolio helpers. "
            "Mutating commands require --confirm. Never invents market prices."
        )
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    boot = sub.add_parser(
        "demo-bootstrap",
        help=f"Create/refresh '{DEMO_PORTFOLIO_NAME}' with {', '.join(DEMO_SYMBOLS)} when resolvable",
    )
    boot.add_argument(
        "--confirm",
        action="store_true",
        help="Required opt-in — without this flag the command refuses to mutate",
    )
    boot.add_argument(
        "--reset",
        action="store_true",
        help="Wipe existing DEMO book to DRAFT then re-seed (reversible rebuild)",
    )
    boot.add_argument(
        "--no-activate",
        action="store_true",
        help="Leave book in DRAFT after seeding (default: activate journal)",
    )
    boot.add_argument(
        "--ui-visible",
        action="store_true",
        help=(
            "Create with is_test=false so the book appears in the default UI collection. "
            "Still DEMO-labeled. Default is is_test=true (hidden unless ?test=true)."
        ),
    )
    boot.add_argument("--cash-rub", default="500000", help="Opening cash RUB (default 500000)")
    boot.add_argument(
        "--symbols",
        default=",".join(DEMO_SYMBOLS),
        help=f"Comma-separated symbols (default {','.join(DEMO_SYMBOLS)})",
    )
    boot.add_argument("--name", default=DEMO_PORTFOLIO_NAME, help="Portfolio display name")
    boot.add_argument(
        "--reclaim-legacy",
        action="store_true",
        help=(
            "Opt-in: stamp durable source=DEMO_INVESTOR_JOURNEY_V1 onto a prior MVP seed "
            "that only had the DEMO note (never stamps ordinary personal books)."
        ),
    )

    st = sub.add_parser("demo-status", help="Show DEMO portfolio presence (read-only)")
    st.add_argument("--name", default=DEMO_PORTFOLIO_NAME)

    rst = sub.add_parser(
        "demo-reset",
        help="Reset DEMO book to empty DRAFT, or --delete to remove it",
    )
    rst.add_argument("--confirm", action="store_true", help="Required opt-in")
    rst.add_argument("--delete", action="store_true", help="Hard-delete the DEMO portfolio")
    rst.add_argument("--name", default=DEMO_PORTFOLIO_NAME)
    rst.add_argument(
        "--reclaim-legacy",
        action="store_true",
        help="Opt-in reclaim of prior MVP DEMO note seeds before reset/delete",
    )

    args = parser.parse_args(argv)

    try:
        with core_session() as session:
            if args.cmd == "demo-status":
                payload = demo_status(session, name=args.name)
            elif args.cmd == "demo-bootstrap":
                symbols = tuple(s.strip().upper() for s in str(args.symbols).split(",") if s.strip())
                result = bootstrap_demo_portfolio(
                    session,
                    confirm=bool(args.confirm),
                    reset=bool(args.reset),
                    activate=not bool(args.no_activate),
                    ui_visible=bool(args.ui_visible),
                    cash_rub=_parse_cash(args.cash_rub),
                    symbols=symbols,
                    name=args.name,
                    reclaim_legacy=bool(args.reclaim_legacy),
                )
                payload = result.to_dict()
            elif args.cmd == "demo-reset":
                payload = reset_demo_portfolio(
                    session,
                    confirm=bool(args.confirm),
                    name=args.name,
                    delete=bool(args.delete),
                    reclaim_legacy=bool(args.reclaim_legacy),
                )
            else:
                parser.error(f"unknown command {args.cmd}")
                return 2
    except PersonalPortfolioError as exc:
        print(json.dumps({"error": exc.code, "message": exc.message}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
