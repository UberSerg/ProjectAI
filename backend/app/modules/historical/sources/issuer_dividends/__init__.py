"""IR-05 issuer dividend archive. Does not write prospective memory."""

from app.modules.historical.sources.issuer_dividends.source import (
    EVENT_CAP,
    SOURCE_ID,
    IssuerDividendsSource,
)

__all__ = ["EVENT_CAP", "SOURCE_ID", "IssuerDividendsSource"]
