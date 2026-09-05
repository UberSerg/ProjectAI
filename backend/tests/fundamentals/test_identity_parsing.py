"""MOEX ISS issuer identity parsing must resolve exactly or refuse to resolve."""

from __future__ import annotations

import json
from pathlib import Path

from app.modules.fundamentals.domain.types import MappingStatus
from app.modules.fundamentals.infrastructure.moex_issuer_provider import (
    parse_securities_search,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PAYLOAD = json.loads((FIXTURES / "moex_securities_search.json").read_text(encoding="utf-8"))


def test_exact_secid_match_resolves_the_issuer() -> None:
    identity = parse_securities_search(PAYLOAD, "SBER")

    assert identity.mapping_status is MappingStatus.MAPPED
    assert identity.moex_emitent_id == 1234
    assert identity.inn == "7707083893"
    assert identity.okpo == "00032537"
    assert identity.isin == "RU0009029540"


def test_search_hit_for_a_different_secid_is_not_borrowed() -> None:
    """The payload contains SBER and SBERP; a query for an absent SECID stays UNMAPPED."""
    identity = parse_securities_search(PAYLOAD, "SBERX")

    assert identity.mapping_status is MappingStatus.UNMAPPED
    assert identity.reason == "NO_EXACT_SECID_MATCH"
    assert identity.moex_emitent_id is None


def test_missing_emitent_id_is_unmapped_not_guessed() -> None:
    payload = {
        "securities": {
            "columns": ["secid", "isin", "type", "emitent_id", "emitent_title"],
            "data": [["ZZTEST", "RU000TEST001", "common_share", None, "Тест"]],
        }
    }
    identity = parse_securities_search(payload, "ZZTEST")

    assert identity.mapping_status is MappingStatus.UNMAPPED
    assert identity.reason == "NO_EMITENT_ID"
    assert identity.isin == "RU000TEST001"


def test_conflicting_issuers_for_one_secid_are_ambiguous() -> None:
    payload = {
        "securities": {
            "columns": ["secid", "emitent_id", "emitent_title"],
            "data": [["ZZTEST", 1, "Первый"], ["ZZTEST", 2, "Второй"]],
        }
    }
    identity = parse_securities_search(payload, "ZZTEST")

    assert identity.mapping_status is MappingStatus.AMBIGUOUS
    assert identity.reason == "MULTIPLE_EMITENT_IDS"
    assert identity.moex_emitent_id is None


def test_empty_payload_is_unmapped() -> None:
    identity = parse_securities_search({}, "SBER")

    assert identity.mapping_status is MappingStatus.UNMAPPED
    assert identity.moex_emitent_id is None
