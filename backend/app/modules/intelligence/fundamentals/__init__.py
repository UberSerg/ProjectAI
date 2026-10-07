"""Industrial fundamental intelligence — FundamentalSnapshotV1 over FNS RAS facts."""

from app.modules.intelligence.fundamentals.persistence import (
    persist_fundamental_snapshot,
)
from app.modules.intelligence.fundamentals.persistence import (
    schema_ready as fundamental_snapshots_schema_ready,
)
from app.modules.intelligence.fundamentals.service import (
    IndustrialFundamentalService,
    build_fundamental_snapshot,
)

__all__ = [
    "IndustrialFundamentalService",
    "build_fundamental_snapshot",
    "fundamental_snapshots_schema_ready",
    "persist_fundamental_snapshot",
]
