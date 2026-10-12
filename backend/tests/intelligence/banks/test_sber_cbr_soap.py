"""SBER CBR SOAP fixtures: partial metrics, no industrial ratios, no network."""

from __future__ import annotations

from datetime import date

from app.modules.intelligence.banks.cbr_soap import F102_PROFIT_NAME
from app.modules.intelligence.banks.metrics import INDUSTRIAL_RATIO_CODES
from app.modules.intelligence.banks.service import build_bank_fi_fundamental_snapshot
from app.modules.intelligence.banks.snapshot import assert_no_industrial_fallback

_IDENTITY = """
<CO>
  <IntCode>1315037838265</IntCode>
  <RegNumber>1481</RegNumber>
  <MainRegNumber>1027700132195</MainRegNumber>
  <OrgName>ПАО Сбербанк</OrgName>
</CO>
"""

_FORM123 = """
<F123DATA OnDate="20260901">
  <F123><CODE>000</CODE><NAME>Собственные средства (капитал), итого, в том числе:</NAME><VALUE>8092364887</VALUE></F123>
  <F123><CODE>102</CODE><NAME>Базовый капитал, итого</NAME><VALUE>6241437805</VALUE></F123>
</F123DATA>
"""

_FORM135 = """
<F135DATA OnDate="20260901">
  <F135_3><C3>Н1.1</C3><V3>10.115</V3></F135_3>
  <F135_3><C3>Н1.0</C3><V3>13.095</V3></F135_3>
  <F135_3><C3>Н1.3</C3><V3></V3></F135_3>
</F135DATA>
"""

_FORM102 = """
<F102DATAFULL>
  <FDF><DT>2026-08-01T00:00:00+03:00</DT><val>1163640131</val></FDF>
  <FDF><DT>2026-09-01T00:00:00+03:00</DT><val>1332707281</val></FDF>
</F102DATAFULL>
"""

_ENUM = f"""
<IndicatorsEnum102>
  <SIND><symset>1</symset><symbol>61101</symbol><name>OLD</name></SIND>
  <SIND><symset>75</symset><symbol>61101</symbol><name>{F102_PROFIT_NAME}</name></SIND>
</IndicatorsEnum102>
"""

_FIXTURES = {
    "identity": _IDENTITY,
    "form123": _FORM123,
    "form135": _FORM135,
    "form102": _FORM102,
    "form102_enum": _ENUM,
}


def test_sber_soap_snapshot_is_partial_and_not_industrial() -> None:
    snap = build_bank_fi_fundamental_snapshot(
        secid="SBER",
        instrument_id=42,
        as_of=date(2026, 10, 12),
        known_at=date(2026, 10, 12),
        cbr_soap_fixtures=_FIXTURES,
        bank_metrics={"REVENUE": 1, "EBITDA": 2, "TOTAL_DEBT": 3},
    )
    assert snap.issuer_kind == "BANK_FI"
    assert snap.status == "PARTIAL"
    assert snap.status != "READY"
    assert snap.provider == "CBR_CREDITORGINFO_SOAP"
    assert snap.period_end == date(2026, 9, 1)
    assert snap.known_at == date(2026, 10, 12)
    assert snap.known_at != snap.period_end
    assert snap.metrics["EQUITY"]["value"] == 8092364887
    assert snap.metrics["EQUITY"]["unit"] == "thousand_rub"
    assert snap.metrics["EQUITY"]["field"] == "000"
    assert snap.metrics["CAPITAL_ADEQUACY"]["value"] == "13.095"
    assert snap.metrics["CAPITAL_ADEQUACY"]["unit"] == "percent"
    assert snap.metrics["CAPITAL_ADEQUACY"]["field"] == "Н1.0"
    assert snap.metrics["NET_PROFIT"]["value"] == 1332707281
    assert snap.metrics["NET_PROFIT"]["value"] != 1163640131 + 1332707281
    assert "TOTAL_ASSETS" not in snap.metrics
    assert "LOAN_BOOK" not in snap.metrics
    assert "DEPOSITS" not in snap.metrics
    assert set(INDUSTRIAL_RATIO_CODES).isdisjoint(snap.metrics)
    assert "REVENUE" not in snap.metrics
    assert_no_industrial_fallback(snap)
    assert "known_at_policy_CURRENT_ONLY" in snap.limitations
    assert "period_end_is_not_known_at" in snap.limitations
    assert "not_ifrs" in snap.limitations
    assert "form101_soap_empty_assets_loans_deposits_not_proved" in snap.limitations
    assert "INDUSTRIAL_FNS_FALLBACK_FORBIDDEN" in snap.limitations
    lineage = next(f for f in snap.facts_used if f.get("fact") == "cbr_soap_lineage")
    assert lineage["parser_version"] == "cbr_creditorginfo_soap_v1"
    assert lineage["known_at_policy"] == "CURRENT_ONLY"
    assert lineage["period_end_is_not_known_at"] is True


def test_sber_soap_does_not_invent_known_at_from_period_end() -> None:
    snap = build_bank_fi_fundamental_snapshot(
        secid="SBER",
        cbr_soap_fixtures=_FIXTURES,
    )
    assert snap.period_end == date(2026, 9, 1)
    assert snap.known_at is None


def test_sber_soap_rejects_mismatched_identity_and_renamed_capital_line() -> None:
    bad_identity = _IDENTITY.replace("1027700132195", "0000000000000")
    snap = build_bank_fi_fundamental_snapshot(
        secid="SBER",
        cbr_soap_fixtures={**_FIXTURES, "identity": bad_identity},
    )
    assert snap.status in {"PARTIAL", "NOT_AVAILABLE"}
    assert snap.metrics == {}
    assert "cbr_identity_mismatch" in snap.limitations
    assert_no_industrial_fallback(snap)

    renamed = _FORM123.replace(
        "Собственные средства (капитал), итого, в том числе:",
        "Уставный капитал",
    )
    snap_renamed = build_bank_fi_fundamental_snapshot(
        secid="SBER",
        cbr_soap_fixtures={**_FIXTURES, "form123": renamed},
    )
    assert "EQUITY" not in snap_renamed.metrics
    assert "form123_line_000_definition_mismatch" in snap_renamed.limitations
    assert snap_renamed.metrics["CAPITAL_ADEQUACY"]["value"] == "13.095"


def test_sber_soap_rejects_unconfirmed_profit_symbol() -> None:
    bad_enum = _ENUM.replace(F102_PROFIT_NAME, "Какой-то другой символ")
    snap = build_bank_fi_fundamental_snapshot(
        secid="SBER",
        cbr_soap_fixtures={**_FIXTURES, "form102_enum": bad_enum},
    )
    assert "NET_PROFIT" not in snap.metrics
    assert "f102_symbol_61101_definition_mismatch" in snap.limitations
    assert snap.metrics["EQUITY"]["value"] == 8092364887
    assert set(INDUSTRIAL_RATIO_CODES).isdisjoint(snap.metrics)
