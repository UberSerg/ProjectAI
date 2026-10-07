"""CLI for Intraday Market Intelligence (Agent A).

Examples:

  python -m app.modules.intelligence.intraday.cli audit
  python -m app.modules.intelligence.intraday.cli ingest --symbols SBER,LKOH,MGNT --from 2026-10-01
  python -m app.modules.intelligence.intraday.cli refresh --symbols SBER --lookback-days 3
  python -m app.modules.intelligence.intraday.cli aggregate --symbols SBER --as-of 2026-10-06
  python -m app.modules.intelligence.intraday.cli smoke --symbols SBER,LKOH,MGNT
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.infrastructure.db.session import core_session
from app.modules.intelligence.intraday.application.service import (
    aggregate_as_of,
    aggregate_range,
    ingest_interval_candles,
    mapping_summary,
    smoke_live,
)
from app.modules.intelligence.intraday.constants import PRIMARY_INTERVAL
from app.modules.intelligence.isolation import production_isolation_report

MSK = ZoneInfo("Europe/Moscow")
DEFAULT_SMOKE_OUT = Path(".tmp/agents/a_intraday_smoke.json")
AUDIT_DOC = Path("docs/intelligence/moex_intraday_audit.md")


def _print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _symbols(raw: str | None) -> list[str]:
    if not raw:
        return ["SBER", "LKOH", "MGNT"]
    return [part.strip().upper() for part in raw.split(",") if part.strip()]


def _parse_date(raw: str | None, default: date) -> date:
    if not raw:
        return default
    return date.fromisoformat(raw)


def _audit_payload() -> dict[str, Any]:
    return {
        "schema": "MoexIntradayAuditV1",
        "provider": "MOEX ISS",
        "endpoint": (
            "/iss/engines/stock/markets/shares/boards/{board}/securities/{secid}/candles.json"
        ),
        "primary_interval": PRIMARY_INTERVAL,
        "moex_interval_codes": {"1m": 1, "10m": 10, "60m": 60, "1d": 24},
        "rejected_intervals": {
            "15m": "interval=15 returns empty on TQBR (do not invent)",
            "4h": "interval=4 returns empty",
            "1w": "interval=7 returns empty on this endpoint for equities sample",
        },
        "storage": "market.candles.timeframe (e.g. 60m) — no separate candle table",
        "timezone": "candles.begin/end are Moscow wall time; stored as timestamptz UTC",
        "volume_semantics": {
            "volume": "shares/lots traded in bar",
            "value": "RUB turnover in bar (used for VWAP when available at fetch time)",
        },
        "pagination": "start += 500 while page length == 500",
        "ticks": False,
        "order_book_history": False,
        "audit_doc": str(AUDIT_DOC).replace("\\", "/"),
        "production_isolation": production_isolation_report(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Intraday Market Intelligence — MOEX 60m + PIT features")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("audit", help="Print structured MOEX intraday capability audit")

    ingest_p = sub.add_parser("ingest", help="Bounded backfill of interval candles into market.candles")
    ingest_p.add_argument("--symbols", type=str, default="SBER,LKOH,MGNT")
    ingest_p.add_argument("--from", dest="from_date", type=str, default=None)
    ingest_p.add_argument("--till", dest="till_date", type=str, default=None)
    ingest_p.add_argument("--interval", type=str, default=PRIMARY_INTERVAL)
    ingest_p.add_argument("--incremental", action="store_true")
    ingest_p.add_argument("--dry-run", action="store_true")

    refresh_p = sub.add_parser("refresh", help="Incremental refresh from latest stored bar")
    refresh_p.add_argument("--symbols", type=str, default="SBER,LKOH,MGNT")
    refresh_p.add_argument("--lookback-days", type=int, default=3)
    refresh_p.add_argument("--interval", type=str, default=PRIMARY_INTERVAL)
    refresh_p.add_argument("--dry-run", action="store_true")

    agg_p = sub.add_parser("aggregate", help="PIT daily IntradayFeatureSnapshotV1 aggregation")
    agg_p.add_argument("--symbols", type=str, default="SBER,LKOH,MGNT")
    agg_p.add_argument("--as-of", type=str, default=None)
    agg_p.add_argument("--from", dest="from_date", type=str, default=None)
    agg_p.add_argument("--till", dest="till_date", type=str, default=None)
    agg_p.add_argument("--interval", type=str, default=PRIMARY_INTERVAL)
    agg_p.add_argument("--no-persist", action="store_true")

    smoke_p = sub.add_parser("smoke", help="Real MOEX smoke for bounded symbols → JSON proof")
    smoke_p.add_argument("--symbols", type=str, default="SBER,LKOH,MGNT")
    smoke_p.add_argument("--lookback-days", type=int, default=5)
    smoke_p.add_argument("--interval", type=str, default=PRIMARY_INTERVAL)
    smoke_p.add_argument("--out", type=Path, default=DEFAULT_SMOKE_OUT)
    smoke_p.add_argument("--no-persist-snapshots", action="store_true")

    map_p = sub.add_parser("mappings", help="Show board/SECID resolution for symbols")
    map_p.add_argument("--symbols", type=str, default="SBER,LKOH,MGNT")

    args = parser.parse_args(argv)
    today = datetime.now(MSK).date()

    if args.cmd == "audit":
        _print(_audit_payload())
        return 0

    with core_session() as session:
        if args.cmd == "mappings":
            _print({"mappings": mapping_summary(session, _symbols(args.symbols))})
            return 0

        if args.cmd == "ingest":
            from_date = _parse_date(args.from_date, today - timedelta(days=10))
            till_date = _parse_date(args.till_date, today)
            results = ingest_interval_candles(
                session,
                _symbols(args.symbols),
                from_date=from_date,
                till_date=till_date,
                interval=args.interval,
                incremental=bool(args.incremental),
            )
            if args.dry_run:
                session.rollback()
            _print(
                {
                    "dry_run": bool(args.dry_run),
                    "results": [r.to_dict() for r in results],
                }
            )
            return 0 if all(r.error is None for r in results) else 2

        if args.cmd == "refresh":
            from_date = today - timedelta(days=max(1, int(args.lookback_days)))
            results = ingest_interval_candles(
                session,
                _symbols(args.symbols),
                from_date=from_date,
                till_date=today,
                interval=args.interval,
                incremental=True,
            )
            if args.dry_run:
                session.rollback()
            _print(
                {
                    "dry_run": bool(args.dry_run),
                    "results": [r.to_dict() for r in results],
                }
            )
            return 0 if all(r.error is None for r in results) else 2

        if args.cmd == "aggregate":
            symbols = _symbols(args.symbols)
            persist = not args.no_persist
            if args.as_of:
                as_of = date.fromisoformat(args.as_of)
                items = aggregate_as_of(
                    session, symbols, as_of, interval=args.interval, persist=persist
                )
                _print({"as_of": as_of.isoformat(), "results": [i.to_dict() for i in items]})
                return 0 if all(i.error is None for i in items) else 2
            from_date = _parse_date(args.from_date, today - timedelta(days=5))
            till_date = _parse_date(args.till_date, today)
            items = aggregate_range(
                session,
                symbols,
                from_date,
                till_date,
                interval=args.interval,
                persist=persist,
            )
            _print({"from": from_date.isoformat(), "till": till_date.isoformat(), "results": items})
            return 0

        if args.cmd == "smoke":
            payload = smoke_live(
                session,
                _symbols(args.symbols),
                lookback_days=int(args.lookback_days),
                interval=args.interval,
                persist_candles=True,
                persist_snapshots=not args.no_persist_snapshots,
            )
            payload["audit"] = _audit_payload()
            payload["generated_at"] = datetime.now(MSK).isoformat()
            out_path: Path = args.out
            if not out_path.is_absolute():
                # Prefer repo root (.tmp/agents/...) when cwd is backend/
                candidates = [
                    Path.cwd() / out_path,
                    Path.cwd().parent / out_path,
                ]
                out_path = candidates[0]
                for cand in candidates:
                    if (cand.parent.exists() or cand.parent.parent.exists()):
                        out_path = cand
                        break
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            _print(
                {
                    "wrote": str(out_path),
                    "symbols": len(payload.get("snapshots") or []),
                    "mode": payload.get("mode"),
                }
            )
            errors = [
                s.get("error")
                for s in payload.get("snapshots") or []
                if s.get("error") and s.get("snapshot") is None
            ]
            return 0 if not errors else 2

    return 1


if __name__ == "__main__":
    sys.exit(main())
