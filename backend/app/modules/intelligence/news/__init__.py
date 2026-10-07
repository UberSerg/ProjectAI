"""News / RSS / disclosure ingestion for Intelligence Stack V1.

Allowlisted sources only. Persists into ``intelligence.source_documents``.
Does not mutate Candidate / Shadow / Daily Decision / broker paths.
"""

from app.modules.intelligence.news.ingest import (
    IngestResult,
    ingest_allowlisted_sources,
    ingest_source,
)
from app.modules.intelligence.news.registry import (
    SourceDefinition,
    get_source,
    list_sources,
)

__all__ = [
    "IngestResult",
    "SourceDefinition",
    "get_source",
    "ingest_allowlisted_sources",
    "ingest_source",
    "list_sources",
]
