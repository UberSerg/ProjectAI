"""CBR-05 banking-sector statistical reviews. One catalog probe, no SOAP forms."""

from app.modules.historical.sources.cbr_reviews.source import (
    MAX_ROWS,
    PROBED_HTTP_STATUS,
    PROBED_ON,
    SOURCE_ID,
    SOURCE_URL,
    CbrReviewsSource,
)

__all__ = [
    "MAX_ROWS",
    "PROBED_HTTP_STATUS",
    "PROBED_ON",
    "SOURCE_ID",
    "SOURCE_URL",
    "CbrReviewsSource",
]
