"""Regression: FNS GIR BO not-indexed INNs stay explicit UNMAPPED (no name guess)."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.modules.fundamentals.infrastructure.fns_gir_bo_provider import (
    FNS_GIR_BO_NOT_INDEXED_INNS,
    SUPPORT_UNMAPPED,
    resolve_fns_identity,
)


def test_rosn_gmkn_marked_not_indexed_not_fuzzy():
    client = MagicMock()
    client.search_by_inn.return_value = []
    for inn in ("7706107510", "8401005730"):
        assert inn in FNS_GIR_BO_NOT_INDEXED_INNS
        res = resolve_fns_identity(client, inn=inn, secid="ROSN" if inn.startswith("7706") else "GMKN")
        assert res.support_status == SUPPORT_UNMAPPED
        assert res.reason == "FNS_GIR_BO_NOT_INDEXED"
        assert res.org is None


def test_empty_inn_other_symbol_still_generic_empty():
    client = MagicMock()
    client.search_by_inn.return_value = []
    res = resolve_fns_identity(client, inn="1234567890", secid="XXXX")
    assert res.reason == "FNS_INN_SEARCH_EMPTY"
