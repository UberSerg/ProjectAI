"""CLI: ``python -m app.modules.investment.cli <command>``."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from decimal import Decimal

from app.infrastructure.db.session import core_session
from app.modules.investment.application.services import (
    CbrHurdleProvider,
    fixed_income_readiness,
    key_rate_audit,
)
from app.modules.investment.domain.allocation import (
    AllocationCandidate,
    AssetSleeve,
    allocate_integer_lots,
)
from app.modules.investment.infrastructure.moex_bonds import MoexBondClient


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Investment Foundation V0 research tools")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("key-rate-audit")
    fi = commands.add_parser("fixed-income-audit")
    fi.add_argument("--live", action="store_true")
    fi.add_argument("--limit", type=int, default=20)
    allocation = commands.add_parser("allocation-preview")
    allocation.add_argument("--capital", type=Decimal, default=Decimal("100000"))
    args = parser.parse_args(argv)

    if args.command == "key-rate-audit":
        with core_session() as session:
            quote = CbrHurdleProvider(session).quote(__import__("datetime").date.today())
        _print(key_rate_audit([asdict(quote)] if quote else []))
    elif args.command == "fixed-income-audit":
        if args.live:
            _print(MoexBondClient().audit(limit=args.limit))
        else:
            with core_session() as session:
                _print(fixed_income_readiness(session))
    elif args.command == "allocation-preview":
        result = allocate_integer_lots(
            [
                AllocationCandidate(
                    "SBER",
                    AssetSleeve.EQUITY_ALPHA,
                    Decimal("300"),
                    10,
                    Decimal("0.6"),
                ),
                AllocationCandidate(
                    "OFZ",
                    AssetSleeve.FIXED_INCOME,
                    Decimal("950"),
                    1,
                    Decimal("0.4"),
                ),
            ],
            capital=args.capital,
        )
        _print(asdict(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
