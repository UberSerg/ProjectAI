"""Allowlisted endpoints probed for DISC-01, DISC-02, and NEWS-02.

Direct HTTP only. These URLs are not fetched at import time.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.intelligence.news.registry import get_source

HEADLINE_LIMIT = 20

# Official ISS feed already registered for production news ingest.
MOEX_SITENEWS_URL = get_source("moex_sitenews").feed_url
# Documented MOEX RSS export. The file is multi-megabyte; readers must stop at 20 items.
MOEX_RSS_EXPORT_URL = "https://www.moex.com/export/news.aspx?cat=100"
MOEX_LEGACY_RSS_URL = "https://www.moex.com/ru/news/rss.aspx"


@dataclass(frozen=True, slots=True)
class ProbeTarget:
    task_id: str
    name: str
    url: str
    expects_machine_feed: bool


PROBE_TARGETS: tuple[ProbeTarget, ...] = (
    ProbeTarget("DISC-01", "portal-home", "https://www.e-disclosure.ru/", False),
    ProbeTarget("DISC-01", "portal-apex", "https://e-disclosure.ru/", False),
    ProbeTarget("DISC-01", "company-page", "https://www.e-disclosure.ru/portal/company.aspx?id=17", False),
    ProbeTarget("DISC-01", "files-page", "https://www.e-disclosure.ru/portal/files.aspx?id=17", False),
    ProbeTarget("DISC-01", "event-page", "https://www.e-disclosure.ru/portal/event.aspx?EventId=1", False),
    ProbeTarget("DISC-02", "api-root", "https://www.e-disclosure.ru/api/", True),
    ProbeTarget("DISC-02", "api-host", "https://api.e-disclosure.ru/", True),
    ProbeTarget("DISC-02", "cfapi-host", "https://cfapi.e-disclosure.ru/", True),
    ProbeTarget("DISC-02", "rss-root", "https://www.e-disclosure.ru/rss", True),
    ProbeTarget("DISC-02", "portal-rss", "https://www.e-disclosure.ru/portal/rss.aspx", True),
    ProbeTarget("DISC-02", "prime-home", "https://disclosure.1prime.ru/", True),
    ProbeTarget("NEWS-02", "moex-sitenews", f"{MOEX_SITENEWS_URL}?limit={HEADLINE_LIMIT}&iss.meta=off", True),
    ProbeTarget("NEWS-02", "moex-rss-export", MOEX_RSS_EXPORT_URL, True),
    ProbeTarget("NEWS-02", "moex-legacy-rss", MOEX_LEGACY_RSS_URL, True),
)
