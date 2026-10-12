"""Historical ingestion must not touch live decision memory."""

from __future__ import annotations

FORBIDDEN_WRITE_TARGETS: frozenset[str] = frozenset(
    {
        "intelligence.prospective_captures",
        "intelligence.signal_outputs",
        "intelligence.committee_decisions",
        "shadow.orders",
        "broker.executions",
    }
)


def assert_research_only_target(table_name: str) -> None:
    if table_name in FORBIDDEN_WRITE_TARGETS:
        raise PermissionError(
            f"historical ingestion cannot write {table_name}"
        )
