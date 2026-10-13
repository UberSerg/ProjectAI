"""Pilot entity resolution. Identifiers come from in-repo maps only."""

from app.modules.historical.application.enrich import (
    INDUSTRIAL_RATIO_CODES,
    industrial_ratio_allowed,
)
from app.modules.historical.application.entities import (
    industrial_ratio_allowed as entity_gate,
)
from app.modules.historical.application.entities import (
    linked_identifiers,
    pilot_issuers,
    resolve,
)
from app.modules.historical.sources.fns.adapter import PILOT_INN, PILOT_SECID
from app.modules.historical.sources.moex_corporate_actions.source import EXACT_ISIN
from app.modules.historical.sources.moex_market.source import PILOT_SYMBOLS
from app.modules.intelligence.banks.providers import CBR_CREDIT_ORG_BY_SECID

_FNS = "backend/app/modules/historical/sources/fns/adapter.py:PILOT_INN"
_CBR = "backend/app/modules/intelligence/banks/providers.py:CBR_CREDIT_ORG_BY_SECID"
_MOEX = "backend/app/modules/historical/sources/moex_market/source.py:PILOT_SYMBOLS"


def test_identifier_map_is_the_three_pilots_from_existing_constants() -> None:
    assert entity_gate is industrial_ratio_allowed
    pilots = {pilot.key: pilot for pilot in pilot_issuers()}
    assert tuple(pilots) == PILOT_SYMBOLS

    lkoh = pilots["LKOH"]
    assert lkoh.secid == PILOT_SECID == "LKOH"
    assert lkoh.inn == PILOT_INN == "7708004767"
    assert lkoh.inn_source == "fns"
    assert lkoh.isin == EXACT_ISIN["LKOH"]
    assert lkoh.issuer_kind == "INDUSTRIAL"
    assert lkoh.regnum is None

    sber_ref = CBR_CREDIT_ORG_BY_SECID["SBER"]
    sber = pilots["SBER"]
    assert sber.regnum == sber_ref.regnum == "1481"
    assert sber.inn == sber_ref.inn == "7707083893"
    assert sber.ogrn == sber_ref.ogrn == "1027700132195"
    assert sber.inn_source == "cbr"
    assert sber.isin == EXACT_ISIN["SBER"]
    assert sber.issuer_kind == "BANK_FI"

    mgnt = pilots["MGNT"]
    assert mgnt.secid == "MGNT"
    assert mgnt.inn is None
    assert mgnt.ogrn is None
    assert mgnt.regnum is None
    assert mgnt.isin is None
    assert mgnt.issuer_kind == "INDUSTRIAL"

    links = linked_identifiers()
    inns = {(item.issuer_key, item.value, item.source) for item in links if item.field == "inn"}
    assert ("LKOH", PILOT_INN, _FNS) in inns
    assert ("SBER", sber_ref.inn, _CBR) in inns
    assert all(item.source == _MOEX for item in links if item.field == "secid" and item.issuer_key == "MGNT")
    assert "2309085638" not in {item.value for item in links}


def test_lkoh_matches_on_fns_inn_and_moex_secid() -> None:
    by_inn = resolve({"inn": PILOT_INN})
    by_secid = resolve({"secid": PILOT_SECID})
    both = resolve({"inn": PILOT_INN, "secid": "lkoh"})

    for result in (by_inn, by_secid, both):
        assert result.status == "match"
        assert result.issuer_key == "LKOH"
        assert result.identity["inn"] == PILOT_INN
        assert result.identity["secid"] == "LKOH"
        assert result.identity["issuer_kind"] == "INDUSTRIAL"
        assert result.ratio_refused is False
        assert industrial_ratio_allowed(result.identity) is True

    ebitda = resolve({"secid": "LKOH"}, requested_ratio="EBITDA")
    assert ebitda.status == "match"
    assert ebitda.ratio_refused is False
    assert ebitda.requested_ratios == ("EBITDA",)


def test_mgnt_matches_without_an_invented_inn() -> None:
    payload = {"secid": "MGNT"}
    result = resolve(payload, requested_ratio="REVENUE")

    assert payload == {"secid": "MGNT"}
    assert result.status == "match"
    assert result.issuer_key == "MGNT"
    assert "inn" not in result.identity
    assert result.identity["issuer_kind"] == "INDUSTRIAL"
    assert result.ratio_refused is False
    assert industrial_ratio_allowed(result.identity) is True
    assert resolve({"secid": "MGNT"}, requested_ratio="TOTAL_DEBT").ratio_refused is False


def test_unknown_inn_stays_unresolved() -> None:
    known = {item.value for item in linked_identifiers() if item.field == "inn"}
    unknown = "0000000000"
    assert unknown not in known

    result = resolve({"inn": unknown})
    assert result.status == "unresolved"
    assert result.reason == "unknown_identifier"
    assert result.issuer_key is None
    assert result.identity == {}
    assert result.conflict_keys == ()


def test_inn_and_secid_from_different_issuers_conflict() -> None:
    result = resolve({"inn": PILOT_INN, "secid": "SBER"})
    assert result.status == "conflict"
    assert result.reason == "identifiers_belong_to_different_issuers"
    assert result.conflict_keys == ("LKOH", "SBER")
    assert result.issuer_key is None
    assert result.identity == {}

    other = resolve({"inn": CBR_CREDIT_ORG_BY_SECID["SBER"].inn, "secid": "MGNT"})
    assert other.status == "conflict"
    assert other.conflict_keys == ("MGNT", "SBER")

    held = resolve({"inn": PILOT_INN, "secid": "MGNT"})
    assert held.status == "conflict"
    assert held.conflict_keys == ("LKOH", "MGNT")


def test_sber_industrial_ratio_request_is_refused() -> None:
    by_regnum = resolve({"regnum": "1481"})
    assert by_regnum.status == "match"
    assert by_regnum.issuer_key == "SBER"
    assert by_regnum.identity["issuer_kind"] == "BANK_FI"
    assert by_regnum.identity["regnum"] == "1481"
    assert industrial_ratio_allowed(by_regnum.identity) is False

    same = resolve(
        {
            "secid": "SBER",
            "inn": CBR_CREDIT_ORG_BY_SECID["SBER"].inn or "",
            "regnum": "1481",
        }
    )
    assert same.status == "match"
    assert same.issuer_key == "SBER"

    for code in sorted(INDUSTRIAL_RATIO_CODES):
        refused = resolve({"secid": "SBER", "metric_id": code})
        assert refused.status == "match"
        assert refused.issuer_key == "SBER"
        assert refused.ratio_refused is True
        assert refused.reason == "industrial_ratio_refused"
        assert refused.requested_ratios == (code,)
        assert industrial_ratio_allowed(refused.identity) is False

    net_profit = resolve({"secid": "SBER"}, requested_ratio="NET_PROFIT")
    assert net_profit.status == "match"
    assert net_profit.ratio_refused is False


def test_outside_the_pilot_map_stays_unresolved() -> None:
    assert resolve({}).status == "unresolved"
    assert resolve({"secid": "SBERP"}).status == "unresolved"
    assert resolve({"secid": "GAZP"}).status == "unresolved"
    assert resolve({"secid": "MGNT", "inn": "0000000000"}).status == "unresolved"
