"""Fundamental & Event Intelligence V1 constants and the module kill switch."""

from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings

# Default OFF. Nothing in this module runs on a schedule; the Celery task no-ops
# unless this flag is turned on, and even then it only syncs identity and events.
FUNDAMENTALS_UPDATE_ENABLED = False

MODULE_NAME = "fundamentals"
SCHEMA = "fundamentals"

# Providers recorded in fundamentals.ingestion_runs.provider.
PROVIDER_SOURCE_AUDIT = "SOURCE_AUDIT"
PROVIDER_MOEX_IDENTITY = "MOEX_ISS_IDENTITY"
PROVIDER_CORPORATE_EVENTS = "MARKET_CORPORATE_ACTIONS"
PROVIDER_REPORTS = "FINANCIAL_REPORTS"
PROVIDER_DIVIDENDS = "DIVIDENDS"
PROVIDER_EDISCLOSURE_GATEWAY = "EDISCLOSURE_GATEWAY"
PROVIDER_GIR_BO = "GIR_BO"

# MOEX ISS security search: the only endpoint the live audit accepted. It answers
# issuer identity (emitent_id / emitent_title / emitent_inn / isin / type) and nothing else.
MOEX_SECURITIES_SEARCH_PATH = "/iss/securities.json"

# Instruments we try to map. Indices have no issuer.
MAPPED_ASSET_CLASSES: tuple[str, ...] = ("equity",)

DEFAULT_ARTIFACT_DIR = Path(".tmp/fundamentals-v1")


def fundamentals_update_enabled() -> bool:
    """Runtime flag; falls back to the module default when the setting is absent."""
    return bool(
        getattr(get_settings(), "fundamentals_update_enabled", FUNDAMENTALS_UPDATE_ENABLED)
    )
