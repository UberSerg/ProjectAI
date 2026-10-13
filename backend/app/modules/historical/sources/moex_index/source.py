"""One public ISS window of IMOEX index history.

MOEX-05 fetches a single bounded window, at most 100 sessions, and does not
paginate. CLOSE is the index level. TRADEDATE is the session period: it is
stored as period_end and event_date, never as published_at.

The public history payload has no publication timestamp. RECALC_DATE and
TRADE_SESSION_DATE are not publication times, so the sample is PIT_PROXY.
A real publication timestamp upgrades the artifact only when it can be stored
without collapsing into the trade date.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.infrastructure.market.http_client import MarketHttpClient
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

SOURCE_ID = "MOEX-05"
PARSER_VERSION = "moex_index_history_v1"
NORMALIZATION_VERSION = "moex_index_close_v1"
SECID = "IMOEX"
BOARD = "SNDX"
MAX_SESSIONS = 100
PILOT_FROM = date(2026, 9, 1)
PILOT_TILL = date(2026, 10, 13)

ISS_INDEX_PIT_EVIDENCE = (
    "ISS index history is the official IMOEX series without a publication timestamp; "
    "TRADEDATE is period_end and event_date, not published_at"
)
PUBLICATION_TIMESTAMP_COLUMNS = frozenset(
    {
        "PUBLISHED_AT",
        "PUBLICATION_TIMESTAMP",
        "SYSTIME",
        "UPDATED_AT",
        "UPDATE_TIME",
    }
)


@dataclass(frozen=True, slots=True)
class IndexSession:
    trade_date: date
    close: Decimal


def bounded_weekday_window(start: date, end: date, limit: int) -> tuple[date, date] | None:
    """Last ``limit`` weekdays inside ``[start, end]``, never more than 100."""
    capped = min(max(limit, 0), MAX_SESSIONS)
    if capped <= 0 or end < start:
        return None
    chosen: list[date] = []
    cursor = end
    while cursor >= start and len(chosen) < capped:
        if cursor.weekday() < 5:
            chosen.append(cursor)
        cursor -= timedelta(days=1)
    if not chosen:
        return None
    return chosen[-1], chosen[0]


def index_history_url(base_url: str) -> str:
    root = base_url.rstrip("/")
    return f"{root}/iss/history/engines/stock/markets/index" f"/boards/{BOARD}/securities/{SECID}.json"


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _parse_timestamp(value: object) -> datetime | None:
    """A date-only cell is not a publication timestamp."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    if len(text) <= 10:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _rows(payload: Mapping[str, Any]) -> tuple[list[Any], list[list[Any]]]:
    history = payload.get("history") or {}
    columns = list(history.get("columns") or [])
    data = [list(row) for row in history.get("data") or []]
    return columns, data


def _mapping(columns: list[Any], values: list[Any]) -> dict[str, Any]:
    return {str(column).upper(): value for column, value in zip(columns, values, strict=False)}


def read_history_cursor(payload: Mapping[str, Any]) -> tuple[int, int, int] | None:
    block = payload.get("history.cursor") or {}
    columns = [str(item).upper() for item in block.get("columns") or []]
    data = block.get("data") or []
    if not data or not columns:
        return None
    row = {columns[index]: data[0][index] for index in range(min(len(columns), len(data[0])))}
    if not {"INDEX", "TOTAL", "PAGESIZE"} <= set(row):
        return None
    return int(row["INDEX"]), int(row["TOTAL"]), int(row["PAGESIZE"])


def assert_single_window(payload: Mapping[str, Any], row_count: int) -> None:
    """Accept one ISS page only. A larger history is not fetched."""
    if row_count > MAX_SESSIONS:
        raise RuntimeError(
            f"ISS index history returned {row_count} rows; cap is {MAX_SESSIONS} and pagination is refused"
        )
    cursor = read_history_cursor(payload)
    if cursor is None:
        return
    index, total, _pagesize = cursor
    if index != 0:
        raise RuntimeError("refusing an ISS index history page that is not the first page")
    if total > MAX_SESSIONS:
        raise RuntimeError(f"ISS index window contains {total} sessions; cap is {MAX_SESSIONS}")
    if total != row_count:
        raise RuntimeError(f"ISS index page has {row_count} rows of {total}; refusing to paginate")


def parse_index_sessions(payload: Mapping[str, Any]) -> tuple[IndexSession, ...]:
    columns, data = _rows(payload)
    sessions: list[IndexSession] = []
    for values in data:
        row = _mapping(columns, values)
        trade_raw = row.get("TRADEDATE")
        close = _decimal(row.get("CLOSE"))
        if trade_raw in (None, "") or close is None:
            continue
        sessions.append(
            IndexSession(
                trade_date=date.fromisoformat(str(trade_raw)[:10]),
                close=close,
            )
        )
    return tuple(sorted(sessions, key=lambda item: item.trade_date))


def publication_timestamps(payload: Mapping[str, Any]) -> tuple[datetime, ...]:
    columns, data = _rows(payload)
    found: list[datetime] = []
    for values in data:
        row = _mapping(columns, values)
        for name in PUBLICATION_TIMESTAMP_COLUMNS:
            parsed = _parse_timestamp(row.get(name))
            if parsed is not None:
                found.append(parsed)
    return tuple(found)


def resolve_pit(
    *,
    period_end: date | None,
    timestamps: tuple[datetime, ...],
) -> tuple[PitQuality, datetime | None, PublishedAtPrecision, str, tuple[str, ...]]:
    limits = (
        "trade_date_is_period_end_not_published_at",
        "one_bounded_window",
        "cap_100_sessions",
        "no_pagination",
        "close_is_iss_close_column",
    )
    if not timestamps:
        return (
            PitQuality.PIT_PROXY,
            None,
            PublishedAtPrecision.PERIOD_ONLY,
            ISS_INDEX_PIT_EVIDENCE,
            limits + ("pit_proxy_no_publication_timestamp",),
        )
    latest = max(timestamps)
    if period_end is not None and latest.date() == period_end:
        return (
            PitQuality.PIT_PROXY,
            None,
            PublishedAtPrecision.PERIOD_ONLY,
            ISS_INDEX_PIT_EVIDENCE,
            limits + ("publication_timestamp_collides_with_period_end",),
        )
    evidence = (
        "ISS index history included a publication timestamp distinct from TRADEDATE; "
        "the value is read as UTC because the payload has no offset"
    )
    return (
        PitQuality.PIT_VERIFIED,
        latest,
        PublishedAtPrecision.TIMESTAMP,
        evidence,
        limits + ("publication_timestamp_assumed_utc",),
    )


class MoexIndexSource:
    """HistoricalSource for one IMOEX window from public ISS."""

    source_id = SOURCE_ID

    def __init__(
        self,
        *,
        http: MarketHttpClient | None = None,
        clock: Callable[[], datetime] | None = None,
        raw_dir: Path | None = None,
        base_url: str | None = None,
    ) -> None:
        self._http = http
        self._clock = clock or (lambda: datetime.now(UTC))
        self.raw_dir = raw_dir
        self._base_url = base_url
        self._raw: dict[str, bytes] = {}
        self._fetched: dict[tuple[date, date, int], tuple[HistoricalArtifact, ...]] = {}
        self._span: tuple[date, date] | None = None
        self.last_http_status: int | None = None
        self.session_count = 0

    def discover(self) -> CoverageReport:
        self.fetch_sample()
        return self.inspect_coverage()

    def inspect_coverage(self) -> CoverageReport:
        if self._span is None:
            return CoverageReport(
                source_id=SOURCE_ID,
                status=AdapterStatus.PENDING,
                earliest=None,
                latest=None,
                formats=("iss_json",),
                limitations=("index_sample_not_fetched", "imoex_only", "cap_100_sessions"),
            )
        return CoverageReport(
            source_id=SOURCE_ID,
            status=AdapterStatus.READY,
            earliest=self._span[0],
            latest=self._span[1],
            formats=("iss_json",),
            limitations=(
                "pilot_sample_not_full_history",
                "imoex_only",
                "one_bounded_window",
                "cap_100_sessions",
                "pit_proxy_no_separate_publication_timestamp",
            ),
        )

    def fetch_sample(self, *, limit: int = MAX_SESSIONS) -> tuple[HistoricalArtifact, ...]:
        return self.fetch_range(start=PILOT_FROM, end=PILOT_TILL, limit=limit)

    def fetch_range(self, *, start: date, end: date, limit: int) -> tuple[HistoricalArtifact, ...]:
        window = bounded_weekday_window(start, end, limit)
        if window is None:
            return ()
        window_start, window_end = window
        cache_key = (window_start, window_end, min(max(limit, 0), MAX_SESSIONS))
        cached = self._fetched.get(cache_key)
        if cached is not None:
            return cached
        observed_at = self._now()
        url = index_history_url(self._base_url_value())
        response = self._client().get(
            url,
            params={
                "from": window_start.isoformat(),
                "till": window_end.isoformat(),
                "start": 0,
                "iss.meta": "off",
            },
        )
        self.last_http_status = response.status_code
        payload_bytes = response.content
        payload = json.loads(payload_bytes, parse_float=Decimal)
        _columns, data = _rows(payload)
        assert_single_window(payload, len(data))
        sessions = tuple(
            item for item in parse_index_sessions(payload) if window_start <= item.trade_date <= window_end
        )
        if len(sessions) > MAX_SESSIONS:
            raise RuntimeError(f"parsed {len(sessions)} IMOEX sessions; cap is {MAX_SESSIONS}")
        self.session_count = len(sessions)
        first_trade = sessions[0].trade_date if sessions else None
        last_trade = sessions[-1].trade_date if sessions else None
        if first_trade is not None and last_trade is not None:
            self._span = (first_trade, last_trade)
        quality, published_at, precision, evidence, limits = resolve_pit(
            period_end=last_trade,
            timestamps=publication_timestamps(payload),
        )
        digest = _sha256(payload_bytes)
        reference = self._dump("imoex-sndx-window.json", payload_bytes)
        artifact = HistoricalArtifact(
            source_id=SOURCE_ID,
            source_url=url,
            external_document_id=(f"{BOARD}:{SECID}:{window_start.isoformat()}:{window_end.isoformat()}"),
            document_type="index_history",
            content_hash=digest,
            parser_version=PARSER_VERSION,
            fetch_status=FetchStatus.OK if sessions else FetchStatus.EMPTY,
            first_observed_at=observed_at,
            title=SECID,
            entity_identifiers={"secid": SECID, "board": BOARD},
            reporting_period=(
                None
                if first_trade is None or last_trade is None
                else f"{first_trade.isoformat()}/{last_trade.isoformat()}"
            ),
            period_end=last_trade,
            event_date=last_trade,
            published_at=published_at,
            published_at_precision=precision,
            historical_availability_evidence=evidence,
            historical_pit_quality=quality,
            raw_artifact_reference=reference,
            quality_status=RecordQuality.ACCEPTED if sessions else RecordQuality.UNRESOLVED,
            limitations=limits,
        )
        if artifact.chronology_errors():
            raise RuntimeError("IMOEX artifact failed chronology: " + ", ".join(artifact.chronology_errors()))
        stored = (artifact,)
        self._fetched[cache_key] = stored
        return stored

    def parse(self, artifact: HistoricalArtifact, raw: bytes) -> tuple[ParsedObservation, ...]:
        if artifact.document_type != "index_history":
            return ()
        payload = json.loads(raw, parse_float=Decimal)
        sessions = parse_index_sessions(payload)
        observations = tuple(self._observation(artifact, session) for session in sessions)
        if _sha256(raw) != artifact.content_hash:
            return tuple(
                replace(
                    item,
                    quality_status=RecordQuality.QUARANTINE,
                    limitations=item.limitations + ("content_hash_mismatch",),
                )
                for item in observations
            )
        return observations

    def validate(self, observations: tuple[ParsedObservation, ...]) -> tuple[ParsedObservation, ...]:
        checked: list[ParsedObservation] = []
        for item in observations:
            errors = item.quality_errors()
            if not errors:
                checked.append(item)
                continue
            checked.append(
                replace(
                    item,
                    quality_status=RecordQuality.QUARANTINE,
                    limitations=item.limitations + errors,
                )
            )
        return tuple(checked)

    def raw_for(self, artifact: HistoricalArtifact) -> bytes:
        return self._raw[artifact.content_hash]

    def _observation(self, artifact: HistoricalArtifact, session: IndexSession) -> ParsedObservation:
        limitations: tuple[str, ...] = ()
        if session.close == 0:
            limitations = ("explicit_zero",)
        return ParsedObservation(
            metric_id="market.index.close",
            source_id=SOURCE_ID,
            content_hash=artifact.content_hash,
            normalization_version=NORMALIZATION_VERSION,
            quality_status=RecordQuality.ACCEPTED,
            value=float(session.close),
            unit="point",
            period=session.trade_date.isoformat(),
            period_end=session.trade_date,
            evidence=("ISS history CLOSE on TRADEDATE; TRADEDATE is period_end, not published_at"),
            limitations=limitations,
            issuer_identity={"secid": SECID, "board": BOARD},
            extra={
                "trade_date": session.trade_date.isoformat(),
                "close": format(session.close, "f"),
            },
        )

    def _client(self) -> MarketHttpClient:
        if self._http is None:
            self._http = MarketHttpClient()
        return self._http

    def _base_url_value(self) -> str:
        if self._base_url:
            return self._base_url.rstrip("/")
        return get_settings().moex_base_url.rstrip("/")

    def _now(self) -> datetime:
        current = self._clock()
        if current.tzinfo is None:
            return current.replace(tzinfo=UTC)
        return current.astimezone(UTC)

    def _dump(self, filename: str, payload: bytes) -> str | None:
        digest = _sha256(payload)
        self._raw[digest] = payload
        if self.raw_dir is None:
            return None
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        path = self.raw_dir / filename
        path.write_bytes(payload)
        return path.as_posix()
