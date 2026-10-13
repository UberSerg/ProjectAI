"""Bounded MOEX ISS sample for the historical data swarm.

MOEX-01 is the TQBR board catalogue, first page only (at most 100 rows).
MOEX-04 is EOD history for at most three pilot securities and at most 30
trading days each. Securities are resolved by ticker through Instrument
Master or ISS. Database primary keys are never read or stored.

ISS daily history is the official series and does not carry a separate
publication timestamp, so candle artifacts are PIT_PROXY. The trade date is
the period and event date. ``first_observed_at`` is the time of this fetch.

HTTP goes through the existing market clients (``MarketHttpClient``,
``MoexIssProvider``, ``parse_board_securities_payload``). This module does
not paginate the board list and does not write decision-memory tables.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from app.infrastructure.market.http_client import MarketHttpClient
from app.infrastructure.market.moex_iss import MoexIssProvider, parse_moex_history
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
from app.modules.market.application.instrument_search import resolve_instrument_ref
from app.modules.market.application.moex_board_securities import (
    parse_board_securities_payload,
)

SOURCE_PACKAGE = "MOEX-MARKET"
CATALOGUE_SOURCE_ID = "MOEX-01"
CANDLE_SOURCE_ID = "MOEX-04"
CATALOGUE_PARSER_VERSION = "moex_market_catalogue_v1"
CANDLE_PARSER_VERSION = "moex_market_eod_v1"
CATALOGUE_NORMALIZATION = "moex_catalogue_v1"
CANDLE_NORMALIZATION = "moex_eod_v1"
PILOT_SYMBOLS = ("SBER", "LKOH", "MGNT")
MAX_SECURITIES = 3
MAX_TRADING_DAYS = 30
CATALOGUE_PAGE_LIMIT = 100
BOARD = "TQBR"
MARKET = "shares"

ISS_HISTORY_PIT_EVIDENCE = (
    "ISS history is the official series without a separate publication timestamp; "
    "trade date is the period/event date, not known_at"
)
ISS_CATALOGUE_EVIDENCE = (
    "ISS board securities list is an official current snapshot without a separate "
    "publication timestamp; it is not a historical membership series"
)

_CATALOGUE_COLUMNS = (
    "SECID,SHORTNAME,SECNAME,ISIN,LOTSIZE,SECTYPE,STATUS,FACEUNIT,CURRENCYID,TYPENAME"
)


@dataclass(frozen=True, slots=True)
class ResolvedSecurity:
    secid: str
    board: str
    resolved_via: str
    isin: str | None = None
    name: str | None = None


def bounded_weekday_window(start: date, end: date, limit: int) -> tuple[date, date] | None:
    """Last ``limit`` weekdays inside ``[start, end]``, capped at 30.

    Weekends are not trading sessions. A public holiday can still sit inside
    the window, so the ISS row count is at most this many weekdays.
    """
    capped = min(limit, MAX_TRADING_DAYS)
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


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _from_instrument_master(instrument: object) -> ResolvedSecurity | None:
    """Use the master row's ticker and board. Never read the database id."""
    if instrument is None:
        return None
    board = (getattr(instrument, "primary_board", None) or "").strip().upper()
    secid = (getattr(instrument, "symbol", None) or "").strip().upper()
    if not secid or not board:
        return None
    isin_raw = getattr(instrument, "isin", None)
    isin = str(isin_raw).strip() if isin_raw else ""
    return ResolvedSecurity(
        secid=secid,
        board=board,
        resolved_via="instrument_master",
        isin=isin or None,
        name=getattr(instrument, "name", None),
    )


def _span_label(first_trade: date | None, last_trade: date | None) -> str | None:
    if first_trade is None or last_trade is None:
        return None
    return f"{first_trade.isoformat()}/{last_trade.isoformat()}"


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


class MoexMarketSource:
    """HistoricalSource for the MOEX equity pilot sample."""

    source_id = SOURCE_PACKAGE

    def __init__(
        self,
        *,
        session: Session | None = None,
        http: MarketHttpClient | None = None,
        clock: Callable[[], datetime] | None = None,
        raw_dir: Path | None = None,
        symbols: tuple[str, ...] = PILOT_SYMBOLS,
    ) -> None:
        cleaned = tuple(dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip()))
        self.symbols = cleaned[:MAX_SECURITIES] or PILOT_SYMBOLS
        self._session = session
        self._http = http
        self._iss: MoexIssProvider | None = None
        self._clock = clock or (lambda: datetime.now(UTC))
        self.raw_dir = raw_dir
        self._raw: dict[str, bytes] = {}
        self.catalogue_artifact: HistoricalArtifact | None = None
        self._catalogue_report: CoverageReport | None = None
        self._resolved: tuple[ResolvedSecurity, ...] = ()
        self._candle_span: tuple[date, date] | None = None
        self.catalogue_rows = 0
        self.catalogue_response_rows = 0
        self.candle_rows: dict[str, int] = {}

    def discover(self) -> CoverageReport:
        """Prove MOEX-01: one TQBR securities page, at most 100 rows."""
        if self._catalogue_report is not None:
            return self._catalogue_report
        observed_at = self._now()
        url, payload = self._fetch_catalogue_page()
        parsed_rows = parse_board_securities_payload(json.loads(payload), market=MARKET, board=BOARD)
        self.catalogue_response_rows = len(parsed_rows)
        rows = parsed_rows[:CATALOGUE_PAGE_LIMIT]
        self.catalogue_rows = len(rows)
        digest = _sha256(payload)
        reference = self._dump("tqbr-securities-page1.json", payload)
        fetch_status = FetchStatus.OK if rows else FetchStatus.EMPTY
        quality = RecordQuality.ACCEPTED if rows else RecordQuality.UNRESOLVED
        artifact = HistoricalArtifact(
            source_id=CATALOGUE_SOURCE_ID,
            source_url=url,
            external_document_id="TQBR:page1",
            document_type="instrument_catalogue",
            content_hash=digest,
            parser_version=CATALOGUE_PARSER_VERSION,
            fetch_status=fetch_status,
            first_observed_at=observed_at,
            title="MOEX ISS TQBR securities, first page",
            entity_identifiers={"board": BOARD, "market": MARKET, "engine": "stock"},
            published_at=None,
            published_at_precision=PublishedAtPrecision.UNKNOWN,
            historical_availability_evidence=ISS_CATALOGUE_EVIDENCE,
            historical_pit_quality=PitQuality.RESEARCH_ONLY,
            raw_artifact_reference=reference,
            quality_status=quality,
            limitations=(
                "tqbr_first_page_only",
                "limit_100",
                "current_snapshot_not_historical_membership",
            ),
        )
        self.catalogue_artifact = artifact
        self._catalogue_report = CoverageReport(
            source_id=CATALOGUE_SOURCE_ID,
            status=AdapterStatus.READY if rows else AdapterStatus.PARTIAL,
            earliest=None,
            latest=None,
            formats=("iss_json",),
            limitations=("tqbr_first_page_only", "limit_100", f"row_count={len(rows)}"),
        )
        return self._catalogue_report

    def inspect_coverage(self) -> CoverageReport:
        if self._candle_span is None:
            return CoverageReport(
                source_id=CANDLE_SOURCE_ID,
                status=AdapterStatus.PENDING,
                earliest=None,
                latest=None,
                formats=("iss_json",),
                limitations=(
                    "eod_sample_not_fetched",
                    "at_most_3_securities",
                    "at_most_30_trading_days",
                ),
            )
        return CoverageReport(
            source_id=CANDLE_SOURCE_ID,
            status=AdapterStatus.READY,
            earliest=self._candle_span[0],
            latest=self._candle_span[1],
            formats=("iss_json",),
            limitations=(
                "pilot_sample_not_full_history",
                "pit_proxy_no_separate_publication_timestamp",
                "at_most_3_securities",
                "at_most_30_trading_days",
            ),
        )

    def fetch_sample(self, *, limit: int = 30) -> tuple[HistoricalArtifact, ...]:
        end = self._now().date()
        start = end - timedelta(days=70)
        return self.fetch_range(start=start, end=end, limit=limit)

    def fetch_range(
        self, *, start: date, end: date, limit: int
    ) -> tuple[HistoricalArtifact, ...]:
        window = bounded_weekday_window(start, end, limit)
        if window is None:
            return ()
        window_start, window_end = window
        observed_at = self._now()
        resolved = self.resolve_securities()
        artifacts: list[HistoricalArtifact] = []
        trade_dates: list[date] = []
        for security in resolved:
            artifact, dates = self._fetch_one_candle_series(
                security,
                start=window_start,
                end=window_end,
                observed_at=observed_at,
            )
            artifacts.append(artifact)
            trade_dates.extend(dates)
        if trade_dates:
            self._candle_span = (min(trade_dates), max(trade_dates))
        return tuple(artifacts)

    def parse(
        self, artifact: HistoricalArtifact, raw: bytes
    ) -> tuple[ParsedObservation, ...]:
        if artifact.document_type == "instrument_catalogue":
            observations = self._parse_catalogue(artifact, raw)
        elif artifact.document_type == "eod_candle_series":
            observations = self._parse_candles(artifact, raw)
        else:
            return ()
        if _sha256(raw) != artifact.content_hash:
            return tuple(
                replace(
                    obs,
                    quality_status=RecordQuality.QUARANTINE,
                    limitations=obs.limitations + ("content_hash_mismatch",),
                )
                for obs in observations
            )
        return observations

    def validate(
        self, observations: tuple[ParsedObservation, ...]
    ) -> tuple[ParsedObservation, ...]:
        checked: list[ParsedObservation] = []
        for obs in observations:
            errors = obs.quality_errors()
            if not errors:
                checked.append(obs)
                continue
            checked.append(
                replace(
                    obs,
                    quality_status=RecordQuality.QUARANTINE,
                    limitations=obs.limitations + errors,
                )
            )
        return tuple(checked)

    def resolve_securities(self) -> tuple[ResolvedSecurity, ...]:
        if self._resolved:
            return self._resolved
        found: list[ResolvedSecurity] = []
        for symbol in self.symbols[:MAX_SECURITIES]:
            found.append(self._resolve_one(symbol))
        self._resolved = tuple(found)
        return self._resolved

    def raw_for(self, artifact: HistoricalArtifact) -> bytes:
        return self._raw[artifact.content_hash]

    def _resolve_one(self, symbol: str) -> ResolvedSecurity:
        if self._session is not None:
            instrument = resolve_instrument_ref(self._session, symbol)
            resolved = _from_instrument_master(instrument)
            if resolved is not None:
                return resolved
        return self._resolve_via_iss(symbol)

    def _resolve_via_iss(self, symbol: str) -> ResolvedSecurity:
        boards, raw = self._provider().fetch_security_boards(symbol)
        self._dump(f"iss-boards-{symbol}.json", raw)
        tqbr = next((row for row in boards if row.board.upper() == BOARD), None)
        if tqbr is None:
            raise LookupError(f"MOEX ISS has no TQBR board for {symbol}")
        secid = (tqbr.secid or symbol).strip().upper()
        return ResolvedSecurity(secid=secid, board=BOARD, resolved_via="iss")

    def _fetch_catalogue_page(self) -> tuple[str, bytes]:
        provider = self._provider()
        url = (
            f"{provider.base_url}/iss/engines/stock/markets/{MARKET}"
            f"/boards/{BOARD}/securities.json"
        )
        response = provider.client.get(
            url,
            params={
                "iss.meta": "off",
                "iss.only": "securities",
                "securities.start": 0,
                "limit": CATALOGUE_PAGE_LIMIT,
                "securities.columns": _CATALOGUE_COLUMNS,
            },
        )
        return url, response.content

    def _fetch_one_candle_series(
        self,
        security: ResolvedSecurity,
        *,
        start: date,
        end: date,
        observed_at: datetime,
    ) -> tuple[HistoricalArtifact, tuple[date, ...]]:
        provider = self._provider()
        result = provider.fetch_daily_candles(
            security.secid, start, end, board=security.board
        )
        if len(result.raw_payloads) != 1:
            raise RuntimeError(
                f"expected one ISS history page for {security.secid}, got {len(result.raw_payloads)}"
            )
        payload = result.raw_payloads[0]
        bars = parse_moex_history(json.loads(payload))
        if len(bars) > MAX_TRADING_DAYS:
            raise RuntimeError(
                f"ISS returned {len(bars)} sessions for {security.secid}; pilot cap is {MAX_TRADING_DAYS}"
            )
        trade_dates = tuple(bar.timestamp.date() for bar in bars)
        digest = _sha256(payload)
        reference = self._dump(f"eod-{security.secid}.json", payload)
        identifiers = {
            "secid": security.secid,
            "board": security.board,
            "resolved_via": security.resolved_via,
        }
        if security.isin:
            identifiers["isin"] = security.isin
        last_trade = trade_dates[-1] if trade_dates else None
        first_trade = trade_dates[0] if trade_dates else None
        self.candle_rows[security.secid] = len(bars)
        url = candle_endpoint(provider.base_url, security.secid, security.board)
        artifact = HistoricalArtifact(
            source_id=CANDLE_SOURCE_ID,
            source_url=url,
            external_document_id=f"{security.board}:{security.secid}:{start.isoformat()}:{end.isoformat()}",
            document_type="eod_candle_series",
            content_hash=digest,
            parser_version=CANDLE_PARSER_VERSION,
            fetch_status=FetchStatus.OK if bars else FetchStatus.EMPTY,
            first_observed_at=observed_at,
            title=security.name or security.secid,
            entity_identifiers=identifiers,
            reporting_period=_span_label(first_trade, last_trade),
            period_end=last_trade,
            event_date=last_trade,
            published_at=None,
            published_at_precision=PublishedAtPrecision.PERIOD_ONLY,
            historical_availability_evidence=ISS_HISTORY_PIT_EVIDENCE,
            historical_pit_quality=PitQuality.PIT_PROXY,
            raw_artifact_reference=reference,
            quality_status=RecordQuality.ACCEPTED if bars else RecordQuality.UNRESOLVED,
            limitations=(
                "pit_proxy_iss_history_without_publication_timestamp",
                "trade_date_is_period_not_known_at",
                "sample_capped_at_30_trading_days",
                "close_prefers_legalcloseprice",
            ),
        )
        return artifact, trade_dates

    def _parse_catalogue(
        self, artifact: HistoricalArtifact, raw: bytes
    ) -> tuple[ParsedObservation, ...]:
        rows = parse_board_securities_payload(json.loads(raw), market=MARKET, board=BOARD)
        observations: list[ParsedObservation] = []
        for row in rows[:CATALOGUE_PAGE_LIMIT]:
            identity = {"secid": row.secid, "board": row.board}
            if row.isin:
                identity["isin"] = row.isin
            observations.append(
                ParsedObservation(
                    metric_id="market.catalogue.security",
                    source_id=CATALOGUE_SOURCE_ID,
                    content_hash=artifact.content_hash,
                    normalization_version=CATALOGUE_NORMALIZATION,
                    quality_status=RecordQuality.ACCEPTED,
                    value=float(row.lotsize) if row.lotsize is not None else None,
                    unit="lot",
                    currency=row.currency,
                    evidence=f"ISS securities.SECID={row.secid} board={row.board}",
                    issuer_identity=identity,
                    extra={
                        "name": row.name,
                        "sec_type": row.sec_type,
                        "is_traded": row.is_traded,
                    },
                )
            )
        return tuple(observations)

    def _parse_candles(
        self, artifact: HistoricalArtifact, raw: bytes
    ) -> tuple[ParsedObservation, ...]:
        secid = artifact.entity_identifiers.get("secid", "")
        board = artifact.entity_identifiers.get("board", BOARD)
        bars = sorted(parse_moex_history(json.loads(raw)), key=lambda bar: bar.timestamp)
        observations: list[ParsedObservation] = []
        for bar in bars:
            trade_date = bar.timestamp.date()
            limitations: tuple[str, ...] = ()
            if bar.close == 0:
                limitations = ("explicit_zero",)
            identity = {"secid": secid, "board": board}
            observations.append(
                ParsedObservation(
                    metric_id="market.eod.close",
                    source_id=CANDLE_SOURCE_ID,
                    content_hash=artifact.content_hash,
                    normalization_version=CANDLE_NORMALIZATION,
                    quality_status=RecordQuality.ACCEPTED,
                    value=float(bar.close),
                    unit="RUB" if board == BOARD else None,
                    currency="RUB" if board == BOARD else None,
                    period=trade_date.isoformat(),
                    period_end=trade_date,
                    evidence=(
                        "ISS history TRADEDATE is the period/event date, not known_at; "
                        "value is CLOSE with LEGALCLOSEPRICE preferred by the existing parser"
                    ),
                    limitations=limitations,
                    issuer_identity=identity,
                    extra={
                        "trade_date": trade_date.isoformat(),
                        "open": _decimal_text(bar.open),
                        "high": _decimal_text(bar.high),
                        "low": _decimal_text(bar.low),
                        "close": _decimal_text(bar.close),
                        "volume": _decimal_text(bar.volume),
                    },
                )
            )
        return tuple(observations)

    def _provider(self) -> MoexIssProvider:
        if self._iss is None:
            self._iss = MoexIssProvider(client=self._http or MarketHttpClient())
            self._http = self._iss.client
        return self._iss

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


def catalogue_endpoint(base_url: str) -> str:
    root = base_url.rstrip("/")
    return f"{root}/iss/engines/stock/markets/{MARKET}/boards/{BOARD}/securities.json"


def candle_endpoint(base_url: str, secid: str, board: str = BOARD) -> str:
    root = base_url.rstrip("/")
    market = "index" if board in {"SNDX", "RTSI"} else "shares"
    return (
        f"{root}/iss/history/engines/stock/markets/{market}"
        f"/boards/{board}/securities/{secid}.json"
    )
