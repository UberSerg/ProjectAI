"""Source adapters map allowlisted feeds → SourceDocumentV1 drafts."""

from app.modules.intelligence.news.adapters.base import AdapterResult, FetchedDocument
from app.modules.intelligence.news.adapters.cbr_rss import CbrRssAdapter
from app.modules.intelligence.news.adapters.moex_sitenews import MoexSitenewsAdapter

ADAPTERS = {
    "cbr_rss": CbrRssAdapter(),
    "moex_sitenews": MoexSitenewsAdapter(),
}

__all__ = [
    "ADAPTERS",
    "AdapterResult",
    "CbrRssAdapter",
    "FetchedDocument",
    "MoexSitenewsAdapter",
]
