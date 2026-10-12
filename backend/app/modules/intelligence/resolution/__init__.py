"""High-precision company/issuer association for intelligence source documents."""

from app.modules.intelligence.resolution.decide import (
    BASIS_INN,
    BASIS_ISIN,
    BASIS_NAME,
    BASIS_OGRN,
    BASIS_SECID,
    BASIS_UNMAPPED,
    CONFIDENCE_CONFLICT,
    CONFIDENCE_EXACT,
    CONFIDENCE_HIGH,
    CONFIDENCE_NONE,
    RESOLVER_VERSION,
    CompanyResolution,
    ResolutionCandidate,
    resolve_company,
)
from app.modules.intelligence.resolution.session import (
    apply_company_resolution,
    load_resolution_candidates,
    resolve_source_document,
)

__all__ = [
    "BASIS_INN",
    "BASIS_ISIN",
    "BASIS_NAME",
    "BASIS_OGRN",
    "BASIS_SECID",
    "BASIS_UNMAPPED",
    "CONFIDENCE_CONFLICT",
    "CONFIDENCE_EXACT",
    "CONFIDENCE_HIGH",
    "CONFIDENCE_NONE",
    "RESOLVER_VERSION",
    "CompanyResolution",
    "ResolutionCandidate",
    "apply_company_resolution",
    "load_resolution_candidates",
    "resolve_company",
    "resolve_source_document",
]
