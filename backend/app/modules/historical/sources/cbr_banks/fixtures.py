"""SBER CreditOrgInfo SOAP fixture copied from the intelligence unit test.

Origin label: ``fixture_not_live``. These bytes are the curated unit-test
fixture, not a live archive snapshot, and must not be reported as READY
live history.
"""

from __future__ import annotations

from app.modules.intelligence.banks.cbr_soap import F102_PROFIT_NAME

ORIGIN_FIXTURE_NOT_LIVE = "fixture_not_live"
ORIGIN_LIVE = "live"
ORIGIN_INJECTED_FIXTURE = "injected_fixture"

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

# Same keys and XML as backend/tests/intelligence/banks/test_sber_cbr_soap.py.
SBER_SOAP_FIXTURE_NOT_LIVE: dict[str, str] = {
    "identity": _IDENTITY,
    "form123": _FORM123,
    "form135": _FORM135,
    "form102": _FORM102,
    "form102_enum": _ENUM,
}
