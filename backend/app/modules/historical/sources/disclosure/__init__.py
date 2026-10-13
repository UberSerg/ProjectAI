"""Disclosure and MOEX headline access for the historical data swarm.

DISC-01 / DISC-02 refuse anti-bot shells and do not parse them as filings.
NEWS-02 keeps MOEX headline metadata (title, url, published_at) and never backdates.
"""

from app.modules.historical.sources.disclosure.classify import (
    AccessVerdict,
    classify_disclosure_payload,
    is_antibot_shell,
    parse_filings,
)
from app.modules.historical.sources.disclosure.headlines import (
    HEADLINE_LIMIT,
    HeadlineBatch,
    headlines_from_moex_rss,
    headlines_from_moex_sitenews,
)

__all__ = [
    "HEADLINE_LIMIT",
    "AccessVerdict",
    "HeadlineBatch",
    "classify_disclosure_payload",
    "headlines_from_moex_rss",
    "headlines_from_moex_sitenews",
    "is_antibot_shell",
    "parse_filings",
]
