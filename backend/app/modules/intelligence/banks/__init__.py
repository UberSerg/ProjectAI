"""Bank / FI fundamentals for Intelligence Stack V1.

Industrial FNS RAS ratios are unsupported for banks. This package builds
``FundamentalSnapshotV1`` with ``issuer_kind=BANK_FI`` and honest provider
status (PARTIAL / NOT_AVAILABLE). It never falls back to industrial metrics.
"""

from app.modules.intelligence.banks.classification import (
    BANK_FI_SECIDS,
    is_bank_fi_secid,
)
from app.modules.intelligence.banks.providers import (
    PROVIDER_STATUSES,
    bank_source_registry,
)
from app.modules.intelligence.banks.service import (
    build_bank_fi_fundamental_snapshot,
    provider_status_report,
)

__all__ = [
    "BANK_FI_SECIDS",
    "PROVIDER_STATUSES",
    "bank_source_registry",
    "build_bank_fi_fundamental_snapshot",
    "is_bank_fi_secid",
    "provider_status_report",
]
