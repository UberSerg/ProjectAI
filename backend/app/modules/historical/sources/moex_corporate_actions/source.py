"""Bounded MOEX dividend / corporate-action sample for SBER and LKOH.

The documented dividend feed is ``/iss/cci/corp-actions/dividends``. A live probe
on 2026-10-12 returned the subscriber gate, not rows. The public
``/iss/securities/{SECID}/dividends`` path is the security description. Equity
bondization for these two tickers is empty. Candle history under a dividends
suffix is not used.

Registry close (``recorddate`` / ``registryclosedate``) is stored as ``event_date``.
An announcement timestamp is stored as ``published_at`` only when that field is
actually present. ``first_observed_at`` is the fetch clock.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any, Protocol

from app.modules.fundamentals.application.dividend_provider import NotReadyDividendProvider
from app.modules.historical.application.adapter import CoverageReport
from app.modules.historical.domain.evidence import (
    AdapterStatus,
    FetchStatus,
    HistoricalArtifact,
    ParsedObservation,
    PitQuality,
    PublishedAtPrecision,
    RecordQuality,
)
from app.modules.investment.domain.cashflows import (
    MOEX_BONDIZATION_KNOWN_AT_QUALITY,
    parse_bondization_schedule,
)
from app.modules.investment.domain.currency import MoexCurrencyField, normalize_moex_currency_token

SOURCE_ID = "MOEX-06"
PARSER_VERSION = "moex_ca_v1"
SAMPLE_CAP = 40
ISS_BASE = "https://iss.moex.com/iss"
PRIMARY_PATH = "/cci/corp-actions/dividends.json"
SYMBOLS: tuple[str, ...] = ("SBER", "LKOH")

# ISINs observed on the ISS security description for these exact SECIDs.
EXACT_ISIN: dict[str, str] = {
    "SBER": "RU0009029540",
    "LKOH": "RU0009024277",
}

REGISTRY_CLOSE_KEYS = ("registryclosedate", "recorddate", "registry_close_date")
ANNOUNCEMENT_TS_KEYS = ("announcement_timestamp", "publication_timestamp", "published_at")
ANNOUNCEMENT_DATE_KEYS = ("announcementdate", "announcement_date", "declaredate", "publication_date")
PAYMENT_KEYS = ("coupondate", "paymentdate", "payment_date")
DIVIDEND_BLOCKS = ("dividends", "cci_corp_actions_dividends")
SUBSCRIBER_MARKERS = ("подписчикам", "available only to")


class Transport(Protocol):
    def get(self, url: str, params: Mapping[str, str]) -> FetchResponse: ...


@dataclass(frozen=True, slots=True)
class FetchResponse:
    status_code: int
    content_type: str
    content: bytes


@dataclass(frozen=True, slots=True)
class _MappedRow:
    block: str
    index: int
    secid: str | None
    registry_close: date | None
    announcement_at: datetime | None
    announcement_precision: PublishedAtPrecision
    payment_date: date | None
    amount: float | None
    currency: str | None
    quality: RecordQuality
    pit: PitQuality
    limitations: tuple[str, ...]
    evidence: str | None


def fixture_bytes(name: str) -> bytes:
    from pathlib import Path

    return (Path(__file__).resolve().parent / "fixtures" / name).read_bytes()


def content_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


class MoexCorporateActionsSource:
    """HistoricalSource for a bounded SBER/LKOH corporate-action sample."""

    source_id = SOURCE_ID

    def __init__(
        self,
        *,
        transport: Transport | None = None,
        clock: Callable[[], datetime] | None = None,
        symbols: tuple[str, ...] = SYMBOLS,
    ) -> None:
        self._transport = transport or HttpTransport()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._symbols = symbols

    def discover(self) -> CoverageReport:
        return self.inspect_coverage()

    def inspect_coverage(self) -> CoverageReport:
        artifacts = self.fetch_sample(limit=SAMPLE_CAP)
        dated = [item.event_date for item in artifacts if item.event_date is not None]
        statuses = {item.fetch_status for item in artifacts}
        if not artifacts:
            status = AdapterStatus.BLOCKED
        elif any(item.quality_status == RecordQuality.ACCEPTED for item in artifacts):
            status = AdapterStatus.PARTIAL
        elif FetchStatus.FORBIDDEN in statuses or FetchStatus.UNSUPPORTED in statuses:
            status = AdapterStatus.BLOCKED
        elif FetchStatus.OK in statuses:
            status = AdapterStatus.PARTIAL
        elif statuses <= {FetchStatus.EMPTY}:
            status = AdapterStatus.BLOCKED
        else:
            status = AdapterStatus.FAILED
        limitations = tuple(dict.fromkeys(note for item in artifacts for note in item.limitations))
        return CoverageReport(
            source_id=self.source_id,
            status=status,
            earliest=min(dated) if dated else None,
            latest=max(dated) if dated else None,
            formats=("json", "html"),
            limitations=limitations,
        )

    def fetch_sample(self, *, limit: int = 30) -> tuple[HistoricalArtifact, ...]:
        budget = _cap(limit)
        artifacts: list[HistoricalArtifact] = []
        for symbol in self._symbols:
            if budget <= 0:
                break
            produced = self._fetch_symbol(symbol, budget=budget)
            artifacts.extend(produced)
            budget -= len(produced)
        return tuple(artifacts)

    def fetch_range(self, *, start: date, end: date, limit: int) -> tuple[HistoricalArtifact, ...]:
        """Keep rows whose registry close falls inside the window.

        Blockers and rows without a registry close are omitted. The announcement
        timestamp is not the window key.
        """
        budget = _cap(limit)
        selected: list[HistoricalArtifact] = []
        for artifact in self.fetch_sample(limit=SAMPLE_CAP):
            if artifact.quality_status == RecordQuality.UNRESOLVED:
                continue
            if artifact.event_date is None:
                continue
            if start <= artifact.event_date <= end:
                selected.append(artifact)
            if len(selected) >= budget:
                break
        return tuple(selected)

    def parse(self, artifact: HistoricalArtifact, raw: bytes) -> tuple[ParsedObservation, ...]:
        observed_at = artifact.first_observed_at
        rows = _rows_for_artifact(artifact, raw, observed_at=observed_at)
        return tuple(_observation(artifact, row) for row in rows)

    def validate(self, observations: tuple[ParsedObservation, ...]) -> tuple[ParsedObservation, ...]:
        checked: list[ParsedObservation] = []
        for observation in observations:
            errors = observation.quality_errors()
            if errors and observation.quality_status == RecordQuality.ACCEPTED:
                checked.append(
                    ParsedObservation(
                        metric_id=observation.metric_id,
                        source_id=observation.source_id,
                        content_hash=observation.content_hash,
                        normalization_version=observation.normalization_version,
                        quality_status=RecordQuality.QUARANTINE,
                        value=observation.value,
                        unit=observation.unit,
                        currency=observation.currency,
                        period=observation.period,
                        period_end=observation.period_end,
                        reporting_standard=observation.reporting_standard,
                        issuer_identity=dict(observation.issuer_identity),
                        evidence=observation.evidence,
                        limitations=observation.limitations + errors,
                        extra=dict(observation.extra),
                    )
                )
            else:
                checked.append(observation)
        return tuple(checked)

    def _fetch_symbol(self, symbol: str, *, budget: int) -> tuple[HistoricalArtifact, ...]:
        requested = _exact_symbol(symbol)
        observed_at = _aware(self._clock())
        primary = self._transport.get(
            f"{ISS_BASE}{PRIMARY_PATH}",
            {"security": symbol, "start": "0", "iss.meta": "off"},
        )
        primary_rows = _dividend_rows(primary.content, requested=requested, observed_at=observed_at)
        if primary_rows:
            return _artifacts_from_rows(
                symbol=symbol,
                url=f"{ISS_BASE}{PRIMARY_PATH}?security={symbol}",
                body=primary.content,
                fetch_status=FetchStatus.OK,
                rows=primary_rows[:budget],
                observed_at=observed_at,
                extra_limitations=_truncation(len(primary_rows), budget),
            )
        description = self._transport.get(
            f"{ISS_BASE}/securities/{symbol}/dividends.json",
            {"iss.meta": "off"},
        )
        bondization = self._transport.get(
            f"{ISS_BASE}/securities/{symbol}/bondization.json",
            {"iss.meta": "off"},
        )
        bond_rows = _bondization_rows(bondization.content, requested=requested, observed_at=observed_at)
        if bond_rows:
            return _artifacts_from_rows(
                symbol=symbol,
                url=f"{ISS_BASE}/securities/{symbol}/bondization.json",
                body=bondization.content,
                fetch_status=FetchStatus.OK,
                rows=bond_rows[:budget],
                observed_at=observed_at,
                extra_limitations=(
                    _primary_limitation(primary),
                    *_truncation(len(bond_rows), budget),
                ),
            )
        limitations = (
            _primary_limitation(primary),
            _description_limitation(description.content),
            _bondization_empty_limitation(bondization.content),
            "announcement_timestamp_absent",
            "registry_close_absent",
            "first_observed_at_is_fetch_clock",
        )
        return (
            _blocker(
                symbol=symbol,
                url=f"{ISS_BASE}{PRIMARY_PATH}?security={symbol}",
                body=primary.content,
                fetch_status=_primary_status(primary),
                observed_at=observed_at,
                limitations=tuple(note for note in limitations if note),
            ),
        )


class HttpTransport:
    def get(self, url: str, params: Mapping[str, str]) -> FetchResponse:
        import httpx

        with httpx.Client(timeout=40.0, follow_redirects=True, trust_env=False) as client:
            response = client.get(url, params=dict(params))
        return FetchResponse(
            status_code=response.status_code,
            content_type=response.headers.get("content-type", ""),
            content=response.content,
        )


def _cap(limit: int) -> int:
    return max(0, min(int(limit), SAMPLE_CAP))


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _exact_symbol(symbol: str) -> str | None:
    token = (symbol or "").strip().upper()
    if token in EXACT_ISIN:
        return token
    return None


def _load_json(body: bytes) -> Any | None:
    try:
        return json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _blocks(payload: Any) -> dict[str, Any]:
    found: dict[str, Any] = {}
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, dict) and ("columns" in value or "data" in value):
                found[str(key)] = value
            elif isinstance(value, list) and str(key) in {"coupons", "amortizations", "offers", *DIVIDEND_BLOCKS}:
                found[str(key)] = value
    elif isinstance(payload, list):
        for part in payload:
            found.update(_blocks(part))
    return found


def _table_rows(block: Any) -> list[dict[str, Any]]:
    if isinstance(block, dict) and "columns" in block:
        columns = [str(column) for column in (block.get("columns") or [])]
        return [
            {column: value for column, value in zip(columns, row, strict=False)} for row in (block.get("data") or [])
        ]
    if isinstance(block, list) and block and isinstance(block[0], dict):
        return [dict(row) for row in block]
    return []


def _lower_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key).strip().lower(): value for key, value in row.items()}


def _subscriber_gate(body: bytes) -> bool:
    text = body.decode("utf-8", errors="ignore").casefold()
    return any(marker.casefold() in text for marker in SUBSCRIBER_MARKERS)


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace("Z", "+00:00")
    if "T" not in text and " " not in text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _first_present(row: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _secid(row: Mapping[str, Any]) -> str | None:
    raw = row.get("secid")
    if raw in (None, ""):
        return None
    return str(raw).strip().upper()


def _isin(row: Mapping[str, Any]) -> str | None:
    raw = row.get("isin")
    if raw in (None, ""):
        return None
    return str(raw).strip().upper()


def _amount(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _currency(row: Mapping[str, Any]) -> str | None:
    if row.get("faceunit") not in (None, ""):
        resolved = normalize_moex_currency_token(str(row["faceunit"]), field=MoexCurrencyField.FACEUNIT)
    elif row.get("currencyid") not in (None, ""):
        resolved = normalize_moex_currency_token(str(row["currencyid"]), field=MoexCurrencyField.CURRENCYID)
    else:
        return None
    if resolved.canonical == "UNKNOWN":
        return None
    return resolved.canonical


def _identity(row: Mapping[str, Any], requested: str | None) -> RecordQuality:
    secid = _secid(row)
    if requested is None or secid is None or secid != requested or secid not in EXACT_ISIN:
        return RecordQuality.UNRESOLVED
    isin = _isin(row)
    if isin is not None and isin != EXACT_ISIN[secid]:
        return RecordQuality.UNRESOLVED
    return RecordQuality.ACCEPTED


def _dates(
    row: Mapping[str, Any],
) -> tuple[date | None, datetime | None, PublishedAtPrecision, date | None, tuple[str, ...]]:
    notes: list[str] = []
    present = [
        _parse_date(row.get(key)) for key in REGISTRY_CLOSE_KEYS if key in row and row.get(key) not in (None, "")
    ]
    unique_registry = {item for item in present if item is not None}
    if len(unique_registry) > 1:
        notes.append("conflicting_registry_close_dates")
        registry = None
    else:
        registry = next(iter(unique_registry), None)

    timestamp = _parse_timestamp(_first_present(row, ANNOUNCEMENT_TS_KEYS))
    announcement_date = _parse_date(_first_present(row, ANNOUNCEMENT_DATE_KEYS))
    if timestamp is not None and announcement_date is not None and timestamp.date() != announcement_date:
        notes.append("conflicting_announcement_dates")
        return registry, None, PublishedAtPrecision.UNKNOWN, _payment(row), tuple(notes)
    if timestamp is not None:
        return registry, timestamp, PublishedAtPrecision.TIMESTAMP, _payment(row), tuple(notes)
    if announcement_date is not None:
        published = datetime.combine(announcement_date, time.min, tzinfo=UTC)
        return registry, published, PublishedAtPrecision.DATE_ONLY, _payment(row), tuple(notes)
    notes.append("announcement_timestamp_absent")
    return registry, None, PublishedAtPrecision.UNKNOWN, _payment(row), tuple(notes)


def _payment(row: Mapping[str, Any]) -> date | None:
    return _parse_date(_first_present(row, PAYMENT_KEYS))


def _pit(precision: PublishedAtPrecision, *, identity: RecordQuality) -> PitQuality:
    if identity == RecordQuality.UNRESOLVED:
        return PitQuality.RESEARCH_ONLY
    if precision == PublishedAtPrecision.UNKNOWN:
        return PitQuality.RESEARCH_ONLY
    return PitQuality.PIT_PROXY


def _map_generic_row(
    row: Mapping[str, Any],
    *,
    block: str,
    index: int,
    requested: str | None,
    amount: float | None,
    currency: str | None,
    observed_at: datetime,
    extra_limitations: tuple[str, ...] = (),
) -> _MappedRow:
    lowered = _lower_row(row)
    identity = _identity(lowered, requested)
    registry, announcement, precision, payment, date_notes = _dates(lowered)
    limitations = list(date_notes)
    limitations.extend(extra_limitations)
    quality = identity
    if identity != RecordQuality.UNRESOLVED:
        if registry is None:
            quality = RecordQuality.QUARANTINE
            limitations.append("registry_close_absent")
        elif amount is None:
            quality = RecordQuality.QUARANTINE
            limitations.append("amount_absent")
        elif amount == 0:
            limitations.append("explicit_zero")
        if precision == PublishedAtPrecision.UNKNOWN:
            limitations.append("pit_research_only_without_announcement")
        else:
            limitations.append("pit_proxy_announcement_not_verified_as_pit")
    else:
        limitations.append("exact_secid_required")
    if announcement is not None and observed_at < announcement:
        limitations.append("first_observed_at_precedes_published_at")
        quality = RecordQuality.UNRESOLVED
    evidence = None
    if quality == RecordQuality.ACCEPTED and registry is not None:
        evidence = f"{block}:{requested}:{registry.isoformat()}"
    pit_identity = identity if quality != RecordQuality.UNRESOLVED else RecordQuality.UNRESOLVED
    pit_precision = precision if quality != RecordQuality.UNRESOLVED else PublishedAtPrecision.UNKNOWN
    return _MappedRow(
        block=block,
        index=index,
        secid=_secid(lowered),
        registry_close=registry,
        announcement_at=announcement,
        announcement_precision=precision,
        payment_date=payment,
        amount=amount,
        currency=currency,
        quality=quality,
        pit=_pit(pit_precision, identity=pit_identity),
        limitations=tuple(dict.fromkeys(limitations)),
        evidence=evidence,
    )


def _dividend_rows(body: bytes, *, requested: str | None, observed_at: datetime) -> tuple[_MappedRow, ...]:
    if _subscriber_gate(body):
        return ()
    payload = _load_json(body)
    if payload is None:
        return ()
    blocks = _blocks(payload)
    if _is_candle_history(blocks) or _is_security_description(blocks):
        return ()
    mapped: list[_MappedRow] = []
    for name in DIVIDEND_BLOCKS:
        if name not in blocks:
            continue
        for index, row in enumerate(_table_rows(blocks[name])):
            lowered = _lower_row(row)
            mapped.append(
                _map_generic_row(
                    lowered,
                    block=name,
                    index=index,
                    requested=requested,
                    amount=_amount(lowered.get("value")),
                    currency=_currency(lowered),
                    observed_at=observed_at,
                )
            )
    return tuple(mapped)


def _bondization_rows(body: bytes, *, requested: str | None, observed_at: datetime) -> tuple[_MappedRow, ...]:
    payload = _load_json(body)
    if payload is None:
        return ()
    blocks = _blocks(payload)
    if not any(name in blocks for name in ("coupons", "amortizations", "offers")):
        return ()
    coupons = _table_rows(blocks.get("coupons"))
    amortizations = _table_rows(blocks.get("amortizations"))
    offers = _table_rows(blocks.get("offers"))
    schedule = parse_bondization_schedule(coupons=coupons, amortizations=amortizations, offers=offers)
    known_at_note = (f"bondization_known_at:{MOEX_BONDIZATION_KNOWN_AT_QUALITY.value}",)
    parsed_coupons = {_stable(coupon.raw): coupon for coupon in schedule.coupons}
    parsed_amorts = {_stable(item.raw): item for item in schedule.amortizations}
    parsed_offers = {_stable(item.raw): item for item in schedule.offers}
    mapped: list[_MappedRow] = []
    for index, row in enumerate(coupons):
        parsed = parsed_coupons.get(_stable(row))
        amount = float(parsed.amount) if parsed is not None and parsed.amount is not None else None
        currency = parsed.currency if parsed is not None else None
        mapped.append(
            _map_generic_row(
                row,
                block="coupons",
                index=index,
                requested=requested,
                amount=amount,
                currency=currency,
                observed_at=observed_at,
                extra_limitations=known_at_note,
            )
        )
    for index, row in enumerate(amortizations):
        parsed = parsed_amorts.get(_stable(row))
        amount = float(parsed.amount) if parsed is not None and parsed.amount is not None else None
        mapped.append(
            _map_generic_row(
                row,
                block="amortizations",
                index=index,
                requested=requested,
                amount=amount,
                currency=None,
                observed_at=observed_at,
                extra_limitations=known_at_note,
            )
        )
    for index, row in enumerate(offers):
        parsed = parsed_offers.get(_stable(row))
        amount = float(parsed.price) if parsed is not None and parsed.price is not None else None
        mapped.append(
            _map_generic_row(
                row,
                block="offers",
                index=index,
                requested=requested,
                amount=amount,
                currency=None,
                observed_at=observed_at,
                extra_limitations=known_at_note,
            )
        )
    return tuple(mapped)


def _stable(row: Mapping[str, Any]) -> str:
    return json.dumps(row, sort_keys=True, ensure_ascii=False, default=str)


def _is_security_description(blocks: Mapping[str, Any]) -> bool:
    if any(name in blocks for name in DIVIDEND_BLOCKS):
        return False
    return "description" in blocks


def _is_candle_history(blocks: Mapping[str, Any]) -> bool:
    history = blocks.get("history")
    if not isinstance(history, dict):
        return False
    columns = {str(column).upper() for column in (history.get("columns") or [])}
    return "TRADEDATE" in columns and "CLOSE" in columns


def _description_limitation(body: bytes) -> str:
    if _subscriber_gate(body):
        return "securities_dividends_subscriber_gate"
    payload = _load_json(body)
    blocks = _blocks(payload) if payload is not None else {}
    if _is_candle_history(blocks):
        return "history_dividends_endpoint_returns_candles"
    if _is_security_description(blocks):
        reasons = NotReadyDividendProvider().readiness()["reasons"]
        reason = "moex_iss_securities_dividends_rejected"
        if reason not in reasons:
            reason = str(reasons[0]) if reasons else reason
        columns = []
        description = blocks.get("description")
        if isinstance(description, dict):
            columns = [str(column) for column in (description.get("columns") or [])]
        column_note = ",".join(columns) if columns else "none"
        return f"{reason};description_columns:{column_note}"
    return "securities_dividends_unrecognized"


def _bondization_empty_limitation(body: bytes) -> str:
    payload = _load_json(body)
    if payload is None:
        return "bondization_unreadable"
    blocks = _blocks(payload)
    counts = {name: len(_table_rows(blocks.get(name))) for name in ("coupons", "amortizations", "offers")}
    if counts and all(value == 0 for value in counts.values()):
        return "bondization_empty_coupons=0,amortizations=0,offers=0"
    if not counts:
        return "bondization_blocks_absent"
    return "bondization_rows_present"


def _primary_status(response: FetchResponse) -> FetchStatus:
    if response.status_code in {401, 403} or _subscriber_gate(response.content):
        return FetchStatus.FORBIDDEN
    if response.status_code == 404:
        return FetchStatus.UNSUPPORTED
    if response.status_code >= 400:
        return FetchStatus.FAILED
    if _load_json(response.content) is None:
        return FetchStatus.FAILED
    return FetchStatus.EMPTY


def _primary_limitation(response: FetchResponse) -> str:
    if _subscriber_gate(response.content):
        return "cci_corp_actions_dividends_subscriber_only"
    if response.status_code == 404:
        return "cci_corp_actions_dividends_not_found"
    if _primary_status(response) == FetchStatus.EMPTY:
        return "cci_corp_actions_dividends_no_rows"
    return f"cci_corp_actions_dividends_http_{response.status_code}"


def _truncation(available: int, budget: int) -> tuple[str, ...]:
    if available > budget:
        return (f"truncated_to_{budget}",)
    return ()


def _blocker(
    *,
    symbol: str,
    url: str,
    body: bytes,
    fetch_status: FetchStatus,
    observed_at: datetime,
    limitations: tuple[str, ...],
) -> HistoricalArtifact:
    return HistoricalArtifact(
        source_id=SOURCE_ID,
        source_url=url,
        external_document_id=f"{symbol}:cci-corp-actions-dividends:no-rows",
        document_type="moex_dividend_corporate_action",
        content_hash=content_hash(body),
        parser_version=PARSER_VERSION,
        fetch_status=fetch_status,
        first_observed_at=observed_at,
        title=f"{symbol} MOEX dividend sample",
        entity_identifiers={"requested_secid": symbol},
        event_date=None,
        published_at=None,
        published_at_precision=PublishedAtPrecision.UNKNOWN,
        historical_availability_evidence=None,
        historical_pit_quality=PitQuality.RESEARCH_ONLY,
        raw_artifact_reference=url,
        quality_status=RecordQuality.UNRESOLVED,
        limitations=limitations,
    )


def _artifacts_from_rows(
    *,
    symbol: str,
    url: str,
    body: bytes,
    fetch_status: FetchStatus,
    rows: list[_MappedRow] | tuple[_MappedRow, ...],
    observed_at: datetime,
    extra_limitations: tuple[str, ...],
) -> tuple[HistoricalArtifact, ...]:
    digest = content_hash(body)
    artifacts: list[HistoricalArtifact] = []
    for row in rows:
        artifacts.append(
            HistoricalArtifact(
                source_id=SOURCE_ID,
                source_url=url,
                external_document_id=f"{symbol}:{row.block}:{row.index}",
                document_type="moex_dividend_corporate_action",
                content_hash=digest,
                parser_version=PARSER_VERSION,
                fetch_status=fetch_status,
                first_observed_at=observed_at,
                title=f"{symbol} {row.block} {row.index}",
                entity_identifiers={"requested_secid": symbol, "secid": row.secid or ""},
                event_date=row.registry_close,
                published_at=row.announcement_at,
                published_at_precision=row.announcement_precision,
                historical_availability_evidence=(
                    "announcement_field_present_not_independently_verified" if row.announcement_at is not None else None
                ),
                historical_pit_quality=row.pit,
                raw_artifact_reference=url,
                quality_status=row.quality,
                limitations=row.limitations
                + extra_limitations
                + (f"source_row_index:{row.index}", f"source_block:{row.block}"),
            )
        )
    return tuple(artifacts)


def _rows_for_artifact(artifact: HistoricalArtifact, raw: bytes, *, observed_at: datetime) -> tuple[_MappedRow, ...]:
    requested = _exact_symbol(artifact.entity_identifiers.get("requested_secid", ""))
    block = _limitation_value(artifact.limitations, "source_block")
    index_text = _limitation_value(artifact.limitations, "source_row_index")
    if "bondization.json" in artifact.source_url:
        rows = _bondization_rows(raw, requested=requested, observed_at=observed_at)
    else:
        rows = _dividend_rows(raw, requested=requested, observed_at=observed_at)
    if index_text is None:
        return rows[:SAMPLE_CAP]
    index = int(index_text)
    return tuple(row for row in rows if row.block == (block or row.block) and row.index == index)


def _limitation_value(limitations: tuple[str, ...], prefix: str) -> str | None:
    needle = f"{prefix}:"
    for item in limitations:
        if item.startswith(needle):
            return item.split(":", 1)[1]
    return None


def _observation(artifact: HistoricalArtifact, row: _MappedRow) -> ParsedObservation:
    identity: dict[str, str] = {}
    if row.quality != RecordQuality.UNRESOLVED and row.secid:
        identity["secid"] = row.secid
    metric = {
        "dividends": "corporate_action.dividend",
        "cci_corp_actions_dividends": "corporate_action.dividend",
        "coupons": "corporate_action.coupon",
        "amortizations": "corporate_action.amortization",
        "offers": "corporate_action.offer",
    }.get(row.block, "corporate_action.unknown")
    return ParsedObservation(
        metric_id=metric,
        source_id=SOURCE_ID,
        content_hash=artifact.content_hash,
        normalization_version=PARSER_VERSION,
        quality_status=row.quality,
        value=row.amount,
        unit="per_share" if metric == "corporate_action.dividend" else None,
        currency=row.currency,
        issuer_identity=identity,
        evidence=row.evidence,
        limitations=row.limitations,
        extra={
            "registry_close_date": row.registry_close.isoformat() if row.registry_close else None,
            "announcement_at": row.announcement_at.isoformat() if row.announcement_at else None,
            "payment_date": row.payment_date.isoformat() if row.payment_date else None,
            "requested_secid": artifact.entity_identifiers.get("requested_secid"),
            "pit": row.pit.value,
        },
    )
