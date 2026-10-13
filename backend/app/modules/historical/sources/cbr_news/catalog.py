"""Official CBR list endpoints for press and regulatory news.

Discovery used the public pages only. Item URLs are identifiers, not fetch targets.
"""

from __future__ import annotations

from dataclasses import dataclass

ITEM_CAP = 20
PARSER_VERSION = "cbr_news_v1"


@dataclass(frozen=True, slots=True)
class FeedSpec:
    source_id: str
    list_url: str
    discovered_from: str
    document_type: str
    label: str


SPECS: dict[str, FeedSpec] = {
    "CBR-10": FeedSpec(
        source_id="CBR-10",
        list_url="https://www.cbr.ru/rss/RssPress",
        discovered_from="https://www.cbr.ru/development/RSS/",
        document_type="press_headline",
        label="Пресс-релизы Банка России",
    ),
    "CBR-11": FeedSpec(
        source_id="CBR-11",
        list_url="https://www.cbr.ru/rss/navr",
        discovered_from="https://www.cbr.ru/analytics/na_vr/",
        document_type="regulatory_headline",
        label="Официальное опубликование нормативных актов Банка России",
    ),
}
