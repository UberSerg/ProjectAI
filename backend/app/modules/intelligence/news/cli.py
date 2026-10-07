"""CLI: python -m app.modules.intelligence.news.cli [--sources a,b] [--smoke-json PATH]."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.infrastructure.db.session import core_session
from app.modules.intelligence.news.ingest import ingest_allowlisted_sources
from app.modules.intelligence.news.registry import list_sources


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest allowlisted news sources")
    parser.add_argument(
        "--sources",
        default="",
        help="Comma-separated source_ids (default: all enabled allowlist)",
    )
    parser.add_argument(
        "--smoke-json",
        default="",
        help="Write smoke summary JSON to this path",
    )
    parser.add_argument("--list", action="store_true", help="List allowlisted sources and exit")
    args = parser.parse_args(argv)

    if args.list:
        for src in list_sources(enabled_only=False):
            print(f"{src.source_id}\t{src.provider}\t{src.adapter}\t{src.feed_url}")
        return 0

    source_ids = [s.strip() for s in args.sources.split(",") if s.strip()] or None
    started = datetime.now(UTC)
    with core_session() as session:
        results = ingest_allowlisted_sources(session, source_ids=source_ids)
        session.commit()

    payload = {
        "agent": "D",
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "sources_requested": source_ids or [s.source_id for s in list_sources()],
        "results": [r.to_dict() for r in results],
        "ok": all(r.ok for r in results),
        "totals": {
            "fetched": sum(r.fetched for r in results),
            "inserted": sum(r.inserted for r in results),
            "revised": sum(r.revised for r in results),
            "duplicates": sum(r.duplicates for r in results),
        },
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if args.smoke_json:
        path = Path(args.smoke_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path}")
    print(text)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
