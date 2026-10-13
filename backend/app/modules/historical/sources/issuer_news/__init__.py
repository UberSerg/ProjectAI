"""Official issuer press metadata (LKOH) and a pure news dedup key."""

from app.modules.historical.sources.issuer_news.dedup import (
    DEDUP_KEY_FIELDS,
    IssuerNewsDedupKey,
    issuer_news_dedup_key,
)
from app.modules.historical.sources.issuer_news.fetch import (
    IssuerNewsProbe,
    ListingPageFetch,
    assert_listing_url,
    fetch_lukoil_press_metadata,
)
from app.modules.historical.sources.issuer_news.listing import (
    ISSUER,
    LISTING_URL,
    MAX_ITEMS,
    SOURCE_DISCOVERY,
    SOURCE_METADATA,
    IssuerNewsBatch,
    news_01_coverage,
    parse_lukoil_press_listing,
    parse_lukoil_press_pages,
)

__all__ = [
    "DEDUP_KEY_FIELDS",
    "ISSUER",
    "LISTING_URL",
    "MAX_ITEMS",
    "SOURCE_DISCOVERY",
    "SOURCE_METADATA",
    "IssuerNewsBatch",
    "IssuerNewsDedupKey",
    "IssuerNewsProbe",
    "ListingPageFetch",
    "assert_listing_url",
    "fetch_lukoil_press_metadata",
    "issuer_news_dedup_key",
    "news_01_coverage",
    "parse_lukoil_press_listing",
    "parse_lukoil_press_pages",
]
