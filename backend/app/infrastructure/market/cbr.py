"""Central Bank of Russia official series provider."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from xml.etree import ElementTree

from app.core.config import get_settings
from app.domain.ports.market_data import (
    MarketDataProvider,
    ProviderFetchResult,
    SeriesPoint,
)
from app.infrastructure.market.http_client import MarketHttpClient

FX_CODES = {
    "USD_RUB_CBR": "R01235",
    "EUR_RUB_CBR": "R01239",
    "CNY_RUB_CBR": "R01375",
}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _number(text: str | None) -> Decimal:
    return Decimal((text or "0").replace(" ", "").replace(",", "."))


def parse_cbr_fx(payload: bytes | str) -> list[SeriesPoint]:
    root = ElementTree.fromstring(payload)
    result: list[SeriesPoint] = []
    for node in root.iter():
        if _local_name(node.tag) != "Record":
            continue
        attrs = {_local_name(key): value for key, value in node.attrib.items()}
        values = {_local_name(child.tag): child.text for child in node}
        raw_date = attrs.get("Date") or values.get("Date")
        if not raw_date or not values.get("Value"):
            continue
        nominal = _number(values.get("Nominal") or "1")
        result.append(
            SeriesPoint(
                timestamp=datetime.combine(
                    datetime.strptime(raw_date[:10], "%d.%m.%Y").date(),
                    datetime.min.time(),
                    UTC,
                ),
                value=_number(values["Value"]) / nominal,
            )
        )
    return result


def parse_cbr_soap(payload: bytes | str) -> list[SeriesPoint]:
    root = ElementTree.fromstring(payload)
    result: list[SeriesPoint] = []
    for node in root.iter():
        children = {_local_name(child.tag).lower(): child.text for child in node}
        date_text = next(
            (children[key] for key in ("date", "dt", "d0") if children.get(key)), None
        )
        value_text = next(
            (
                children[key]
                for key in ("rate", "value", "ruonia", "keyrate")
                if children.get(key)
            ),
            None,
        )
        if not date_text or value_text is None:
            continue
        parsed_date = datetime.fromisoformat(date_text.replace("Z", "+00:00"))
        result.append(
            SeriesPoint(
                timestamp=datetime.combine(parsed_date.date(), datetime.min.time(), UTC),
                value=_number(value_text),
            )
        )
    unique = {point.timestamp: point for point in result}
    return [unique[key] for key in sorted(unique)]


class CbrProvider(MarketDataProvider):
    source = "CBR"
    soap_url = "DailyInfoWebServ/DailyInfo.asmx"

    def __init__(self, client: MarketHttpClient | None = None, base_url: str | None = None) -> None:
        self.client = client or MarketHttpClient()
        self.base_url = (base_url or get_settings().cbr_base_url).rstrip("/")

    def fetch_daily_candles(
        self, external_id: str, start_date: date, end_date: date, *, board: str = ""
    ) -> ProviderFetchResult:
        raise ValueError("CBR publishes official series, not exchange OHLC candles")

    def fetch_series(
        self, external_id: str, start_date: date, end_date: date
    ) -> ProviderFetchResult:
        if external_id in FX_CODES or external_id in FX_CODES.values():
            code = FX_CODES.get(external_id, external_id)
            response = self.client.get(
                f"{self.base_url}/scripts/XML_dynamic.asp",
                params={
                    "date_req1": start_date.strftime("%d/%m/%Y"),
                    "date_req2": end_date.strftime("%d/%m/%Y"),
                    "VAL_NM_RQ": code,
                },
            )
            points = parse_cbr_fx(response.content)
        elif external_id in {"KEY_RATE", "RUONIA"}:
            method = "KeyRateXML" if external_id == "KEY_RATE" else "RuoniaXML"
            envelope = self._soap_envelope(method, start_date, end_date)
            response = self.client.post(
                f"{self.base_url}/{self.soap_url}",
                content=envelope,
                headers={
                    "Content-Type": "text/xml; charset=utf-8",
                    "SOAPAction": f"http://web.cbr.ru/{method}",
                },
            )
            points = parse_cbr_soap(response.content)
        else:
            raise ValueError(f"Unsupported CBR series: {external_id}")
        return ProviderFetchResult(
            source=self.source,
            records=tuple(points),
            raw_payloads=(response.content,),
            metadata={"external_id": external_id},
        )

    @staticmethod
    def _soap_envelope(method: str, start_date: date, end_date: date) -> bytes:
        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
            'xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
            f'<soap:Body><{method} xmlns="http://web.cbr.ru/">'
            f"<fromDate>{start_date.isoformat()}</fromDate>"
            f"<ToDate>{end_date.isoformat()}</ToDate>"
            f"</{method}></soap:Body></soap:Envelope>"
        ).encode()

    parse_fx = staticmethod(parse_cbr_fx)
    parse_soap = staticmethod(parse_cbr_soap)
