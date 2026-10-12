"""CBR CreditOrgInfo SOAP parsers for SBER bank fundamentals.

Official surface: https://www.cbr.ru/development/WSCO/
Endpoint: https://www.cbr.ru/CreditInfoWebServ/CreditOrgInfo.asmx

Proved on 2026-10-12 for regnum 1481 (no CAPTCHA):
- Data123FormFullXML line 000 — regulatory own funds, thousand RUB
- Data135FormFullXML code Н1.0 — mandatory ratio, percent
- Data102FormXML symbol 61101 — RAS profit after tax, thousand RUB

Not proved:
- Data101FullXML / Data101FullExV2XML return an empty FD table for regnum 1481.
  The RegNumToIntCode value does not fit SOAP xsd:int (HTTP 500) and the Ex
  method returns NotFound. Assets, loan book, and deposits are not emitted.
- Payloads have report dates only. known_at is CURRENT_ONLY when the caller
  supplies an observation date. period_end is not known_at.

Live fetch is optional. Unit tests must pass XML fixtures and must not call it.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

PARSER_VERSION = "cbr_creditorginfo_soap_v1"
KNOWN_AT_POLICY = "CURRENT_ONLY"
PROVIDER_ID = "CBR_CREDITORGINFO_SOAP"

SOAP_URL = "https://www.cbr.ru/CreditInfoWebServ/CreditOrgInfo.asmx"
SOAP_NS = "http://web.cbr.ru/"
DOC_URL = "https://www.cbr.ru/development/WSCO/"

F123_CAPITAL_CODE = "000"
F123_CAPITAL_NAME_PREFIX = "Собственные средства (капитал)"
F135_ADEQUACY_CODE = "Н1.0"
F102_PROFIT_SYMBOL = "61101"
# Exact name from Form102IndicatorsEnumXML latest symset on 2026-10-12,
# cross-checked to the public form 0409102 HTML row for the same symbol.
F102_PROFIT_NAME = (
    "Прибыль после налогообложения (символ 01000 минус символ 03000 "
    "либо символ 01000 плюс символ 04000 либо символ 04000 минус символ 02000)"
)

_BASE_LIMITATIONS: tuple[str, ...] = (
    "known_at_policy_CURRENT_ONLY",
    "period_end_is_not_known_at",
    "not_ifrs",
    "equity_is_form123_regulatory_own_funds_not_ifrs_equity",
    "net_profit_is_form102_symbol_61101_ras_not_ifrs",
    "capital_adequacy_is_n1_0_percent",
    "unit_thousand_rub_from_html_caption_not_in_soap_payload",
    "form101_soap_empty_assets_loans_deposits_not_proved",
    "credorg_number_is_regnum_intcode_overflows_soap_int",
    "inn_not_in_creditinfo_payload",
    "partial_metric_contract_not_ready",
)


@dataclass(frozen=True, slots=True)
class CbrSoapParseResult:
    metrics: dict[str, Any]
    period_end: date | None
    limitations: tuple[str, ...]
    facts: tuple[dict[str, Any], ...]
    parser_version: str = PARSER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "metrics": self.metrics,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "limitations": list(self.limitations),
            "facts": list(self.facts),
            "parser_version": self.parser_version,
            "known_at_policy": KNOWN_AT_POLICY,
            "provider_id": PROVIDER_ID,
        }


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def _text(value: str | None) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())


def _children(element: ET.Element) -> dict[str, str]:
    return {_local(child.tag): _text(child.text) for child in list(element)}


def _parse_iso_date(value: str | None) -> date | None:
    raw = _text(value)
    if not raw:
        return None
    if len(raw) == 8 and raw.isdigit():
        return date(int(raw[0:4]), int(raw[4:6]), int(raw[6:8]))
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        return None


def _parse_int(value: str | None) -> int | None:
    raw = _text(value).replace(" ", "")
    if not raw or not raw.lstrip("-").isdigit():
        return None
    return int(raw)


def _first(root: ET.Element, tag: str) -> str | None:
    for element in root.iter():
        if _local(element.tag) == tag and element.text and element.text.strip():
            return _text(element.text)
    return None


def _parse_root(xml: str) -> ET.Element | None:
    raw = (xml or "").strip()
    if not raw:
        return None
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        return None


def latest_f102_symbol_name(enum_xml: str, symbol: str) -> str | None:
    """Name of ``symbol`` on the highest symset present in an indicator enum."""
    root = _parse_root(enum_xml)
    if root is None:
        return None
    best_set: int | None = None
    best_name: str | None = None
    for element in root.iter():
        if _local(element.tag) != "SIND":
            continue
        fields = _children(element)
        if fields.get("symbol") != symbol:
            continue
        try:
            symset = int(fields.get("symset") or "")
        except ValueError:
            continue
        if best_set is None or symset >= best_set:
            best_set = symset
            best_name = fields.get("name") or ""
    return best_name


def _identity_ok(
    identity_xml: str | None,
    *,
    expected_regnum: str,
    expected_ogrn: str,
) -> tuple[bool, dict[str, Any], str | None]:
    if identity_xml is None:
        return False, {"checked": False}, "identity_xml_required"
    root = _parse_root(identity_xml)
    if root is None:
        return False, {"checked": True}, "identity_xml_unparseable"
    regnum = None
    ogrn = None
    int_code = None
    title = None
    for element in root.iter():
        if _local(element.tag) != "CO":
            continue
        fields = _children(element)
        regnum = fields.get("RegNumber")
        ogrn = fields.get("MainRegNumber")
        int_code = fields.get("IntCode")
        title = fields.get("OrgName")
        break
    fact = {
        "checked": True,
        "regnum": regnum,
        "ogrn": ogrn,
        "int_code": int_code,
        "title": title,
        "inn_present": False,
    }
    if regnum != expected_regnum or ogrn != expected_ogrn:
        return False, fact, "cbr_identity_mismatch"
    return True, fact, None


def _form123_equity(xml: str) -> tuple[dict[str, Any] | None, date | None, str | None]:
    root = _parse_root(xml)
    if root is None:
        return None, None, "form123_xml_unparseable"
    on_date: date | None = None
    for element in root.iter():
        if _local(element.tag) == "F123DATA":
            on_date = _parse_iso_date(element.attrib.get("OnDate"))
            break
    found: dict[str, Any] | None = None
    for element in root.iter():
        if _local(element.tag) != "F123":
            continue
        fields = _children(element)
        if fields.get("CODE") != F123_CAPITAL_CODE:
            continue
        name = fields.get("NAME") or ""
        if not name.startswith(F123_CAPITAL_NAME_PREFIX):
            return None, on_date, "form123_line_000_definition_mismatch"
        value = _parse_int(fields.get("VALUE"))
        if value is None:
            return None, on_date, "form123_line_000_value_missing"
        if found is not None:
            return None, on_date, "form123_line_000_ambiguous"
        found = {
            "value": value,
            "unit": "thousand_rub",
            "form": "0409123",
            "field": "000",
            "definition": name,
            "period_end": on_date.isoformat() if on_date else None,
        }
    if found is None:
        return None, on_date, "form123_line_000_missing"
    if on_date is None:
        return None, None, "form123_ondate_missing"
    return found, on_date, None


def _form135_adequacy(xml: str) -> tuple[dict[str, Any] | None, date | None, str | None]:
    root = _parse_root(xml)
    if root is None:
        return None, None, "form135_xml_unparseable"
    on_date: date | None = None
    for element in root.iter():
        if _local(element.tag) == "F135DATA":
            on_date = _parse_iso_date(element.attrib.get("OnDate"))
            break
    found: dict[str, Any] | None = None
    for element in root.iter():
        if _local(element.tag) != "F135_3":
            continue
        fields = _children(element)
        if fields.get("C3") != F135_ADEQUACY_CODE:
            continue
        raw = fields.get("V3") or ""
        if not raw:
            continue
        normalized = raw.replace(" ", "").replace(",", ".")
        if normalized.count(".") > 1 or not normalized.replace(".", "", 1).isdigit():
            return None, on_date, "form135_n1_0_value_unparseable"
        if found is not None and found["value"] != normalized:
            return None, on_date, "form135_n1_0_ambiguous"
        found = {
            "value": normalized,
            "unit": "percent",
            "form": "0409135",
            "field": F135_ADEQUACY_CODE,
            "definition": (
                "Раздел 3 формы 0409135: фактическое значение норматива "
                "с кратким наименованием Н1.0, процент"
            ),
            "period_end": on_date.isoformat() if on_date else None,
        }
    if found is None:
        return None, on_date, "form135_n1_0_missing"
    if on_date is None:
        return None, None, "form135_ondate_missing"
    return found, on_date, None


def _form102_profit(
    xml: str,
    *,
    anchor: date,
    definition_checked: bool,
) -> tuple[dict[str, Any] | None, str | None]:
    root = _parse_root(xml)
    if root is None:
        return None, "form102_xml_unparseable"
    matched: int | None = None
    for element in root.iter():
        if _local(element.tag) != "FDF":
            continue
        fields = _children(element)
        observed = _parse_iso_date(fields.get("DT"))
        if observed != anchor:
            continue
        value = _parse_int(fields.get("val"))
        if value is None:
            return None, "form102_symbol_61101_value_missing"
        if matched is not None and matched != value:
            return None, "form102_symbol_61101_ambiguous"
        matched = value
    if matched is None:
        return None, "form102_symbol_61101_missing_on_period_end"
    return (
        {
            "value": matched,
            "unit": "thousand_rub",
            "form": "0409102",
            "field": F102_PROFIT_SYMBOL,
            "definition": F102_PROFIT_NAME,
            "definition_checked": definition_checked,
            "period_end": anchor.isoformat(),
        },
        None,
    )


def parse_cbr_soap_metrics(
    *,
    form123_xml: str | None = None,
    form135_xml: str | None = None,
    form102_xml: str | None = None,
    form102_enum_xml: str | None = None,
    identity_xml: str | None = None,
    expected_regnum: str,
    expected_ogrn: str,
) -> CbrSoapParseResult:
    """Pure parser. Does not fetch and does not set known_at."""
    limitations = list(_BASE_LIMITATIONS)
    identity_ok, identity_fact, identity_limit = _identity_ok(
        identity_xml,
        expected_regnum=expected_regnum,
        expected_ogrn=expected_ogrn,
    )
    if identity_limit:
        limitations.append(identity_limit)
    facts: list[dict[str, Any]] = [
        {
            "fact": "cbr_soap_lineage",
            "provider_id": PROVIDER_ID,
            "parser_version": PARSER_VERSION,
            "known_at_policy": KNOWN_AT_POLICY,
            "period_end_is_not_known_at": True,
            "credorg_number_parameter": "regnum",
            "expected_regnum": expected_regnum,
            "expected_ogrn": expected_ogrn,
            "identity": identity_fact,
            "documentation_url": DOC_URL,
        }
    ]
    if not identity_ok:
        return CbrSoapParseResult(
            metrics={},
            period_end=None,
            limitations=tuple(limitations),
            facts=tuple(facts),
        )

    metrics: dict[str, Any] = {}
    equity, equity_date, equity_limit = (None, None, None)
    adequacy, adequacy_date, adequacy_limit = (None, None, None)
    if form123_xml:
        equity, equity_date, equity_limit = _form123_equity(form123_xml)
        if equity_limit:
            limitations.append(equity_limit)
    if form135_xml:
        adequacy, adequacy_date, adequacy_limit = _form135_adequacy(form135_xml)
        if adequacy_limit:
            limitations.append(adequacy_limit)

    anchor: date | None
    if equity_date and adequacy_date and equity_date != adequacy_date:
        limitations.append("form123_form135_period_end_mismatch")
        anchor = None
        equity = None
        adequacy = None
    else:
        anchor = equity_date or adequacy_date

    if equity is not None and equity_date is not None:
        metrics["EQUITY"] = equity
    if adequacy is not None and adequacy_date is not None:
        metrics["CAPITAL_ADEQUACY"] = adequacy

    definition_checked = False
    if form102_xml:
        if form102_enum_xml:
            observed_name = latest_f102_symbol_name(form102_enum_xml, F102_PROFIT_SYMBOL)
            if observed_name == F102_PROFIT_NAME:
                definition_checked = True
            else:
                limitations.append("f102_symbol_61101_definition_mismatch")
                form102_xml = None
        else:
            limitations.append("f102_definition_pinned_not_rechecked")
        if form102_xml and anchor is not None:
            profit, profit_limit = _form102_profit(
                form102_xml,
                anchor=anchor,
                definition_checked=definition_checked,
            )
            if profit_limit:
                limitations.append(profit_limit)
            elif profit is not None:
                metrics["NET_PROFIT"] = profit
        elif form102_xml and anchor is None:
            limitations.append("form102_not_emitted_without_anchor_period")

    period_end = anchor if metrics else None
    facts[0]["metrics"] = sorted(metrics)
    facts[0]["period_end"] = period_end.isoformat() if period_end else None
    return CbrSoapParseResult(
        metrics=metrics,
        period_end=period_end,
        limitations=tuple(dict.fromkeys(limitations)),
        facts=tuple(facts),
    )


def _soap_call(action: str, body_inner: str, *, timeout_s: float) -> str:
    import httpx

    envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        'xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        f"<soap:Body>{body_inner}</soap:Body></soap:Envelope>"
    )
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": f'"{SOAP_NS}{action}"',
        "User-Agent": "ProjectAI-Kraken-Intelligence/1.0 (+bank fundamentals audit)",
        "Accept": "text/xml",
    }
    with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
        response = client.post(SOAP_URL, content=envelope.encode("utf-8"), headers=headers)
        response.raise_for_status()
        return response.text


def fetch_cbr_soap_bundle(
    *,
    regnum: str,
    timeout_s: float = 60.0,
) -> dict[str, str]:
    """Optional live fetch. Not used by unit tests.

    Form methods receive the registration number. The internal code from
    RegNumToIntCode is used only for CreditInfo, which accepts a double.
    """
    reg = regnum.strip()
    int_code_xml = _soap_call(
        "RegNumToIntCode",
        f'<RegNumToIntCode xmlns="{SOAP_NS}"><RegNumber>{reg}</RegNumber></RegNumToIntCode>',
        timeout_s=timeout_s,
    )
    int_root = _parse_root(int_code_xml)
    int_code = _first(int_root, "RegNumToIntCodeResult") if int_root is not None else None
    if not int_code or not int_code.isdigit():
        raise ValueError("RegNumToIntCode did not return an integer internal code")
    identity_xml = _soap_call(
        "CreditInfoByIntCodeExXML",
        (
            f'<CreditInfoByIntCodeExXML xmlns="{SOAP_NS}">'
            f"<InternalCodes><double>{int_code}</double></InternalCodes>"
            "</CreditInfoByIntCodeExXML>"
        ),
        timeout_s=timeout_s,
    )
    max_date_xml = _soap_call(
        "GetFormsMaxDate",
        f'<GetFormsMaxDate xmlns="{SOAP_NS}"><code>123</code></GetFormsMaxDate>',
        timeout_s=timeout_s,
    )
    max_root = _parse_root(max_date_xml)
    max_raw = _first(max_root, "GetFormsMaxDateResult") if max_root is not None else None
    on_date = _parse_iso_date(max_raw)
    if on_date is None:
        raise ValueError("GetFormsMaxDate did not return a form 123 date")
    on_stamp = f"{on_date.isoformat()}T00:00:00"
    form123_xml = _soap_call(
        "Data123FormFullXML",
        (
            f'<Data123FormFullXML xmlns="{SOAP_NS}">'
            f"<CredorgNumber>{reg}</CredorgNumber><OnDate>{on_stamp}</OnDate>"
            "</Data123FormFullXML>"
        ),
        timeout_s=timeout_s,
    )
    form135_xml = _soap_call(
        "Data135FormFullXML",
        (
            f'<Data135FormFullXML xmlns="{SOAP_NS}">'
            f"<CredorgNumber>{reg}</CredorgNumber><OnDate>{on_stamp}</OnDate>"
            "</Data135FormFullXML>"
        ),
        timeout_s=timeout_s,
    )
    form102_xml = _soap_call(
        "Data102FormXML",
        (
            f'<Data102FormXML xmlns="{SOAP_NS}">'
            f"<CredorgNumber>{reg}</CredorgNumber>"
            f"<SymbCode>{F102_PROFIT_SYMBOL}</SymbCode>"
            f"<DateFrom>{on_date.year}-01-01T00:00:00</DateFrom>"
            f"<DateTo>{on_stamp}</DateTo>"
            "</Data102FormXML>"
        ),
        timeout_s=timeout_s,
    )
    return {
        "identity": identity_xml,
        "form123": form123_xml,
        "form135": form135_xml,
        "form102": form102_xml,
    }
