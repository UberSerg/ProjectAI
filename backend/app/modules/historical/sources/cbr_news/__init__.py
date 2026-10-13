"""CBR press and regulatory news list metadata."""

from app.modules.historical.sources.cbr_news.catalog import ITEM_CAP, SPECS
from app.modules.historical.sources.cbr_news.source import CbrNewsSource, NewsAccess, access_from_response

__all__ = ["ITEM_CAP", "SPECS", "CbrNewsSource", "NewsAccess", "access_from_response"]
