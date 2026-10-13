"""Bounded MOEX ISS bond sample for the historical data swarm.

MOEX-08 is one public bond board, TQOB then TQCB only if TQOB is empty or
HTML, first page only, at most 100 securities. It also fetches one bond's
recent history, at most 30 sessions, when that public history document is JSON.

The catalogue request goes through ``MoexBondClient``. This module does not
compute yields: ISS yield columns may sit in the raw document and are not
copied into observations. A missing close stays missing.

ISS board lists and daily history have no separate publication timestamp.
The catalogue is RESEARCH_ONLY. History is PIT_PROXY: the trade date is the
period and event date, and ``first_observed_at`` is the fetch clock.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

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
from app.modules.investment.domain.currency import resolve_nominal_currency
from app.modules.investment.infrastructure.moex_bonds import BOARDS, MoexBondClient

SOURCE_ID = "MOEX-08"
CATALOGUE_PARSER_VERSION = "moex_bonds_catalogue_v1"
HISTORY_PARSER_VERSION = "moex_bonds_history_v1"
CATALOGUE_NORMALIZATION = "moex_bond_catalogue_v1"
HISTORY_NORMALIZATION = "moex_bond_eod_v1"
CATALOGUE_CAP = 100
MAX_SESSIONS = 30
MARKET = "bonds"

ISS_CATALOGUE_EVIDENCE = (
    "ISS bond board securities list is an official current snapshot without a separate "
    "publication timestamp; it is not a historical membership series"
)
ISS_HISTORY_PIT_EVIDENCE = (
    "ISS bond history is the official series without a separate publication timestamp; "
    "trade date is the period/event date, not known_at"
)

_PRICE_FIELDS = ("LEGALCLOSEPRICE", "CLOSE")


@dataclass(frozen=True, slots=True)
class _Session:
    trade_date: date
    price_field: str
    close: Decimal
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    exchange_close: Decimal | None
    legal_close: Decimal | None
    volume: Decimal | None
    face_currency: str | None
    faceunit_raw: str | None
    secid: str


class _RecordingClient:
    """Forwards GET to the injected client and keeps the last response."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.last: httpx.Response | None = None

    def get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        response = self._inner.get(url, params=params)
        self.last = response
        return response

    def close(self) -> None:
        close = getattr(self._inner, "close", None)
        if close is not None:
            close()


def bounded_weekday_window(start: date, end: date, limit: int) -> tuple[date, date] | None:
    """Last ``limit`` weekdays inside ``[start, end]``, capped at 30."""
    capped = min(limit, MAX_SESSIONS)
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


def catalogue_endpoint(base_url: str, board: str) -> str:
    root = base_url.rstrip("/")
    return f"{root}/engines/stock/markets/{MARKET}/boards/{board}/securities.json"


def history_endpoint(base_url: str, board: str, secid: str) -> str:
    root = base_url.rstrip("/")
    return (
        f"{root}/history/engines/stock/markets/{MARKET}/boards/{board}/securities/{secid}.json"
    )


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def _body_problem(response: httpx.Response | None) -> str | None:
    if response is None:
        return "no_response"
    if response.status_code != 200:
        return "http_error"
    body = response.content or b""
    if not body.strip():
        return "empty_body"
    content_type = (response.headers.get("content-type") or "").lower()
    if "html" in content_type or body.lstrip().startswith(b"<"):
        return "html_body"
    return None


def _statuses(response: httpx.Response | None, problem: str | None) -> tuple[FetchStatus, AdapterStatus]:
    if problem is None:
        return FetchStatus.OK, AdapterStatus.READY
    if response is None or problem == "no_response":
        return FetchStatus.FAILED, AdapterStatus.FAILED
    if problem in {"empty_body", "empty_catalogue", "empty_history"}:
        return FetchStatus.EMPTY, AdapterStatus.BLOCKED
    if problem in {"html_body", "non_json"}:
        return FetchStatus.UNSUPPORTED, AdapterStatus.BLOCKED
    return FetchStatus.FAILED, AdapterStatus.BLOCKED


def _http_limits(response: httpx.Response | None, problem: str | None) -> tuple[str, ...]:
    items: list[str] = []
    if response is not None:
        items.append(f"http_status={response.status_code}")
    if problem:
        items.append(problem)
    return tuple(items)


def _table_rows(payload: dict[str, Any], block: str) -> list[dict[str, Any]]:
    table = payload.get(block) or {}
    if not isinstance(table, dict):
        return []
    columns = table.get("columns") or []
    data = table.get("data") or []
    return [{str(column): value for column, value in zip(columns, row, strict=False)} for row in data]


def catalogue_rows(payload: dict[str, Any], *, limit: int = CATALOGUE_CAP) -> list[dict[str, Any]]:
    """Securities block only. Marketdata, including YIELD, is ignored."""
    kept: list[dict[str, Any]] = []
    for row in _table_rows(payload, "securities"):
        secid = str(row.get("SECID") or "").strip().upper()
        if not secid:
            continue
        copied = dict(row)
        copied["SECID"] = secid
        kept.append(copied)
        if len(kept) >= limit:
            break
    return kept


def _face(row: dict[str, Any]) -> tuple[str | None, str | None]:
    raw = row.get("FACEUNIT")
    text = str(raw).strip() if raw not in (None, "") else None
    resolved = resolve_nominal_currency(face_unit=text, currency_id=row.get("CURRENCYID"))
    if resolved.canonical == "UNKNOWN":
        return None, text
    return resolved.canonical, text


def _pick_price(row: dict[str, Any]) -> tuple[str, Decimal] | None:
    for field in _PRICE_FIELDS:
        if field not in row or row[field] in (None, ""):
            continue
        parsed = _decimal(row[field])
        if parsed is not None:
            return field, parsed
    return None


def history_sessions(payload: dict[str, Any]) -> tuple[list[_Session], int]:
    """Priced sessions from ISS history. Yield columns are not read.

    The integer is how many history rows had a trade date but no close.
    """
    sessions: list[_Session] = []
    omitted = 0
    for row in _table_rows(payload, "history"):
        trade_raw = row.get("TRADEDATE")
        if not trade_raw:
            continue
        try:
            trade_date = date.fromisoformat(str(trade_raw)[:10])
        except ValueError:
            omitted += 1
            continue
        picked = _pick_price(row)
        if picked is None:
            omitted += 1
            continue
        field, close = picked
        face_currency, faceunit_raw = _face(row)
        secid = str(row.get("SECID") or "").strip().upper()
        sessions.append(
            _Session(
                trade_date=trade_date,
                price_field=field,
                close=close,
                open=_decimal(row.get("OPEN")) if "OPEN" in row else None,
                high=_decimal(row.get("HIGH")) if "HIGH" in row else None,
                low=_decimal(row.get("LOW")) if "LOW" in row else None,
                exchange_close=_decimal(row.get("CLOSE")) if "CLOSE" in row else None,
                legal_close=_decimal(row.get("LEGALCLOSEPRICE")) if "LEGALCLOSEPRICE" in row else None,
                volume=_decimal(row.get("VOLUME")) if "VOLUME" in row else None,
                face_currency=face_currency,
                faceunit_raw=faceunit_raw,
                secid=secid,
            )
        )
    sessions.sort(key=lambda item: item.trade_date)
    return sessions, omitted


def _cursor_total(payload: dict[str, Any]) -> int | None:
    cursor = payload.get("history.cursor") or {}
    if not isinstance(cursor, dict):
        return None
    columns = cursor.get("columns") or []
    data = cursor.get("data") or []
    if not data or "TOTAL" not in columns:
        return None
    try:
        return int(data[0][columns.index("TOTAL")])
    except (TypeError, ValueError, IndexError):
        return None


def _span_label(first_trade: date | None, last_trade: date | None) -> str | None:
    if first_trade is None or last_trade is None:
        return None
    return f"{first_trade.isoformat()}/{last_trade.isoformat()}"


class MoexBondsSource:
    """HistoricalSource for one MOEX bond-board page and one bond history."""

    source_id = SOURCE_ID

    def __init__(
        self,
        *,
        http: Any | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._owns = http is None
        inner = http or httpx.Client(
            timeout=60.0,
            follow_redirects=True,
            trust_env=False,
            headers={"User-Agent": "ProjectAI-FixedIncomeCashflowV1/1.0"},
        )
        self._http = _RecordingClient(inner)
        self._bond = MoexBondClient(client=self._http, auto_close=False)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._raw: dict[str, bytes] = {}
        self._catalogue_report: CoverageReport | None = None
        self.catalogue_artifact: HistoricalArtifact | None = None
        self.history_artifact: HistoricalArtifact | None = None
        self.boards_requested: list[str] = []
        self.board: str | None = None
        self.secid: str | None = None
        self.isin: str | None = None
        self.faceunit: str | None = None
        self.catalogue_url: str | None = None
        self.catalogue_http_status: int | None = None
        self.catalogue_content_type: str | None = None
        self.catalogue_response_rows = 0
        self.catalogue_rows = 0
        self.catalogue_body: bytes | None = None
        self.history_url: str | None = None
        self.history_http_status: int | None = None
        self.history_content_type: str | None = None
        self.history_rows = 0
        self.history_response_rows = 0
        self.history_cursor_total: int | None = None
        self.history_request_from: date | None = None
        self.history_request_till: date | None = None
        self.first_trade: date | None = None
        self.last_trade: date | None = None
        self.history_body: bytes | None = None
        self._history_blocked: tuple[str, ...] | None = None

    def close(self) -> None:
        if self._owns:
            self._http.close()
            self._owns = False

    def discover(self) -> CoverageReport:
        """Prove one bond-board page, TQOB or TQCB, at most 100 rows."""
        if self._catalogue_report is not None:
            return self._catalogue_report
        observed_at = self._now()
        failures: list[str] = []
        last_problem = "no_response"
        chosen: tuple[str, httpx.Response, list[dict[str, Any]]] | None = None
        for board in BOARDS:
            response, rows, problem = self._fetch_board(board)
            self._remember_catalogue_response(board, response)
            if problem is None and rows:
                chosen = (board, response, rows)
                break
            last_problem = problem or "no_response"
            failures.extend(f"{board}:{item}" for item in _http_limits(response, problem))
        if chosen is None:
            fetch_status, adapter_status = _statuses(self._http.last, last_problem)
            artifact = self._catalogue_artifact(
                board=self.board or BOARDS[-1],
                response=self._http.last,
                observed_at=observed_at,
                fetch_status=fetch_status,
                quality=RecordQuality.UNRESOLVED,
                limitations=tuple(failures) or ("no_response",),
            )
            self.catalogue_artifact = artifact
            self._catalogue_report = CoverageReport(
                source_id=SOURCE_ID,
                status=adapter_status,
                earliest=None,
                latest=None,
                formats=("iss_json", "html"),
                limitations=artifact.limitations,
            )
            return self._catalogue_report
        board, response, rows = chosen
        self.board = board
        self.catalogue_rows = len(rows)
        self.secid = rows[0]["SECID"]
        isin = str(rows[0].get("ISIN") or "").strip()
        self.isin = isin or None
        self.faceunit = str(rows[0].get("FACEUNIT") or "").strip() or None
        limitations = (
            "http_status=200",
            f"{board.lower()}_first_page_only",
            "limit_100",
            f"row_count={len(rows)}",
            "current_snapshot_not_historical_membership",
            "marketdata_yield_not_used",
            "yields_not_computed",
            *failures,
        )
        artifact = self._catalogue_artifact(
            board=board,
            response=response,
            observed_at=observed_at,
            fetch_status=FetchStatus.OK,
            quality=RecordQuality.ACCEPTED,
            limitations=limitations,
        )
        self.catalogue_artifact = artifact
        self._catalogue_report = CoverageReport(
            source_id=SOURCE_ID,
            status=AdapterStatus.READY,
            earliest=None,
            latest=None,
            formats=("iss_json",),
            limitations=limitations,
        )
        return self._catalogue_report

    def inspect_coverage(self) -> CoverageReport:
        if self._history_blocked is not None:
            return CoverageReport(
                source_id=SOURCE_ID,
                status=AdapterStatus.BLOCKED,
                earliest=None,
                latest=None,
                formats=("iss_json", "html"),
                limitations=self._history_blocked,
            )
        artifact = self.history_artifact
        if artifact is None:
            return CoverageReport(
                source_id=SOURCE_ID,
                status=AdapterStatus.PENDING,
                earliest=None,
                latest=None,
                formats=("iss_json",),
                limitations=("history_sample_not_fetched", "one_bond", "at_most_30_sessions"),
            )
        if artifact.fetch_status != FetchStatus.OK:
            return CoverageReport(
                source_id=SOURCE_ID,
                status=AdapterStatus.BLOCKED,
                earliest=None,
                latest=None,
                formats=("iss_json", "html"),
                limitations=artifact.limitations,
            )
        return CoverageReport(
            source_id=SOURCE_ID,
            status=AdapterStatus.READY,
            earliest=self.first_trade,
            latest=self.last_trade,
            formats=("iss_json",),
            limitations=artifact.limitations,
        )

    def fetch_sample(self, *, limit: int = 30) -> tuple[HistoricalArtifact, ...]:
        end = self._now().date()
        start = end - timedelta(days=70)
        return self.fetch_range(start=start, end=end, limit=limit)

    def fetch_range(self, *, start: date, end: date, limit: int) -> tuple[HistoricalArtifact, ...]:
        report = self.discover()
        if report.status != AdapterStatus.READY or not self.secid or not self.board:
            self._history_blocked = report.limitations
            return ()
        window = bounded_weekday_window(start, end, limit)
        if window is None:
            return ()
        return (self._fetch_history(window[0], window[1]),)

    def parse(self, artifact: HistoricalArtifact, raw: bytes) -> tuple[ParsedObservation, ...]:
        if artifact.fetch_status != FetchStatus.OK:
            return ()
        if artifact.document_type == "instrument_catalogue":
            observations = self._parse_catalogue(artifact, raw)
        elif artifact.document_type == "eod_candle_series":
            observations = self._parse_history(artifact, raw)
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

    def validate(self, observations: tuple[ParsedObservation, ...]) -> tuple[ParsedObservation, ...]:
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

    def raw_for(self, artifact: HistoricalArtifact) -> bytes:
        return self._raw[artifact.content_hash]

    def _fetch_board(
        self, board: str
    ) -> tuple[httpx.Response | None, list[dict[str, Any]], str | None]:
        self.boards_requested.append(board)
        try:
            client_rows = self._bond.fetch_board_rows(board, limit=CATALOGUE_CAP)
        except httpx.HTTPStatusError:
            response = self._http.last
            return response, [], _body_problem(response) or "http_error"
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            response = self._http.last
            return response, [], _body_problem(response) or "non_json"
        response = self._http.last
        problem = _body_problem(response)
        if problem is not None or response is None:
            return response, [], problem or "no_response"
        try:
            payload = json.loads(response.content)
        except json.JSONDecodeError:
            return response, [], "non_json"
        if not isinstance(payload, dict):
            return response, [], "non_json"
        rows = catalogue_rows(payload)
        if client_rows and rows:
            client_secid = str(client_rows[0].get("SECID") or "").strip().upper()
            if client_secid and client_secid != rows[0]["SECID"]:
                raise RuntimeError(
                    f"MoexBondClient first SECID {client_secid} differs from raw parser {rows[0]['SECID']}"
                )
        if not rows:
            return response, [], "empty_catalogue"
        return response, rows, None

    def _remember_catalogue_response(self, board: str, response: httpx.Response | None) -> None:
        self.board = board
        self.catalogue_url = catalogue_endpoint(self._bond.base_url, board)
        if response is None:
            return
        self.catalogue_http_status = response.status_code
        self.catalogue_content_type = response.headers.get("content-type")
        self.catalogue_body = response.content
        try:
            payload = json.loads(response.content)
        except json.JSONDecodeError:
            return
        if isinstance(payload, dict):
            self.catalogue_response_rows = len(_table_rows(payload, "securities"))

    def _fetch_history(self, start: date, end: date) -> HistoricalArtifact:
        assert self.board is not None
        assert self.secid is not None
        observed_at = self._now()
        url = history_endpoint(self._bond.base_url, self.board, self.secid)
        self.history_url = url
        self.history_request_from = start
        self.history_request_till = end
        response = self._http.get(
            url,
            params={
                "from": start.isoformat(),
                "till": end.isoformat(),
                "start": 0,
                "iss.meta": "off",
            },
        )
        self.history_http_status = response.status_code
        self.history_content_type = response.headers.get("content-type")
        self.history_body = response.content
        problem = _body_problem(response)
        payload: dict[str, Any] | None = None
        if problem is None:
            try:
                loaded = json.loads(response.content)
            except json.JSONDecodeError:
                problem = "non_json"
            else:
                if not isinstance(loaded, dict):
                    problem = "non_json"
                else:
                    payload = loaded
        sessions: list[_Session] = []
        omitted = 0
        capped = False
        if payload is not None and problem is None:
            self.history_cursor_total = _cursor_total(payload)
            self.history_response_rows = len(_table_rows(payload, "history"))
            sessions, omitted = history_sessions(payload)
            if len(sessions) > MAX_SESSIONS:
                sessions = sessions[-MAX_SESSIONS:]
                capped = True
            if not sessions:
                problem = "empty_history"
        fetch_status = _statuses(response, problem)[0]
        digest = _sha256(response.content)
        self._raw[digest] = response.content
        self.history_rows = len(sessions)
        self.first_trade = sessions[0].trade_date if sessions else None
        self.last_trade = sessions[-1].trade_date if sessions else None
        limitations = _http_limits(response, problem)
        if problem is None:
            limitations = (
                *limitations,
                "one_bond",
                "single_history_page",
                "at_most_30_sessions",
                "pit_proxy_iss_history_without_publication_timestamp",
                "trade_date_is_period_not_known_at",
                "yields_not_computed",
                "close_prefers_legalcloseprice",
                f"row_count={len(sessions)}",
            )
            if capped:
                limitations = (*limitations, "kept_last_30_sessions")
            if omitted:
                limitations = (*limitations, f"sessions_without_close_omitted={omitted}")
            if self.history_cursor_total is not None and self.history_cursor_total > len(sessions):
                limitations = (*limitations, "history_cursor_total_not_paged")
        identifiers = {
            "secid": self.secid,
            "board": self.board,
            "market": MARKET,
            "resolved_via": "iss_board_catalogue",
        }
        if self.isin:
            identifiers["isin"] = self.isin
        artifact = HistoricalArtifact(
            source_id=SOURCE_ID,
            source_url=url,
            external_document_id=f"{self.board}:{self.secid}:{start.isoformat()}:{end.isoformat()}",
            document_type="eod_candle_series",
            content_hash=digest,
            parser_version=HISTORY_PARSER_VERSION,
            fetch_status=fetch_status,
            first_observed_at=observed_at,
            title=self.secid,
            entity_identifiers=identifiers,
            reporting_period=_span_label(self.first_trade, self.last_trade),
            period_end=self.last_trade,
            event_date=self.last_trade,
            published_at=None,
            published_at_precision=(
                PublishedAtPrecision.PERIOD_ONLY if sessions else PublishedAtPrecision.UNKNOWN
            ),
            historical_availability_evidence=ISS_HISTORY_PIT_EVIDENCE if sessions else None,
            historical_pit_quality=PitQuality.PIT_PROXY if sessions else PitQuality.RESEARCH_ONLY,
            raw_artifact_reference=None,
            quality_status=RecordQuality.ACCEPTED if sessions else RecordQuality.UNRESOLVED,
            limitations=limitations,
        )
        self.history_artifact = artifact
        if fetch_status != FetchStatus.OK:
            self._history_blocked = limitations
        return artifact

    def _catalogue_artifact(
        self,
        *,
        board: str,
        response: httpx.Response | None,
        observed_at: datetime,
        fetch_status: FetchStatus,
        quality: RecordQuality,
        limitations: tuple[str, ...],
    ) -> HistoricalArtifact:
        body = response.content if response is not None else b""
        digest = _sha256(body)
        self._raw[digest] = body
        url = catalogue_endpoint(self._bond.base_url, board)
        self.catalogue_url = url
        return HistoricalArtifact(
            source_id=SOURCE_ID,
            source_url=url,
            external_document_id=f"{board}:page1",
            document_type="instrument_catalogue",
            content_hash=digest,
            parser_version=CATALOGUE_PARSER_VERSION,
            fetch_status=fetch_status,
            first_observed_at=observed_at,
            title=f"MOEX ISS {board} securities, first page",
            entity_identifiers={"board": board, "market": MARKET, "engine": "stock"},
            published_at=None,
            published_at_precision=PublishedAtPrecision.UNKNOWN,
            historical_availability_evidence=ISS_CATALOGUE_EVIDENCE if fetch_status == FetchStatus.OK else None,
            historical_pit_quality=PitQuality.RESEARCH_ONLY,
            quality_status=quality,
            limitations=limitations,
        )

    def _parse_catalogue(
        self, artifact: HistoricalArtifact, raw: bytes
    ) -> tuple[ParsedObservation, ...]:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return ()
        if not isinstance(payload, dict):
            return ()
        observations: list[ParsedObservation] = []
        for row in catalogue_rows(payload):
            face_currency, faceunit_raw = _face(row)
            identity = {"secid": row["SECID"], "board": artifact.entity_identifiers.get("board", "")}
            isin = str(row.get("ISIN") or "").strip()
            if isin:
                identity["isin"] = isin
            extra: dict[str, Any] = {}
            name = str(row.get("SHORTNAME") or row.get("SECNAME") or "").strip()
            if name:
                extra["name"] = name
            sec_type = str(row.get("SECTYPE") or "").strip()
            if sec_type:
                extra["sec_type"] = sec_type
            if face_currency:
                extra["face_currency"] = face_currency
            if faceunit_raw:
                extra["faceunit_raw"] = faceunit_raw
            maturity = row.get("MATDATE")
            if maturity not in (None, ""):
                extra["maturity_date"] = str(maturity)[:10]
            lot = _decimal(row.get("LOTSIZE")) if "LOTSIZE" in row else None
            limitations: tuple[str, ...] = ("yields_not_computed",)
            if lot == 0:
                limitations = (*limitations, "explicit_zero")
            observations.append(
                ParsedObservation(
                    metric_id="market.catalogue.security",
                    source_id=SOURCE_ID,
                    content_hash=artifact.content_hash,
                    normalization_version=CATALOGUE_NORMALIZATION,
                    quality_status=RecordQuality.ACCEPTED,
                    value=float(lot) if lot is not None else None,
                    unit="lot",
                    currency=None,
                    evidence=f"ISS securities.SECID={row['SECID']} board={identity['board']}",
                    issuer_identity=identity,
                    extra=extra,
                    limitations=limitations,
                )
            )
        return tuple(observations)

    def _parse_history(
        self, artifact: HistoricalArtifact, raw: bytes
    ) -> tuple[ParsedObservation, ...]:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return ()
        if not isinstance(payload, dict):
            return ()
        sessions, _omitted = history_sessions(payload)
        if len(sessions) > MAX_SESSIONS:
            sessions = sessions[-MAX_SESSIONS:]
        secid = artifact.entity_identifiers.get("secid", "")
        board = artifact.entity_identifiers.get("board", "")
        observations: list[ParsedObservation] = []
        for session in sessions:
            identity = {"secid": session.secid or secid, "board": board}
            isin = artifact.entity_identifiers.get("isin")
            if isin:
                identity["isin"] = isin
            extra: dict[str, Any] = {
                "trade_date": session.trade_date.isoformat(),
                "price_field": session.price_field,
                "close": _decimal_text(session.close),
            }
            for label, amount in (
                ("open", session.open),
                ("high", session.high),
                ("low", session.low),
                ("legalcloseprice", session.legal_close),
                ("exchange_close", session.exchange_close),
                ("volume", session.volume),
            ):
                text = _decimal_text(amount)
                if text is not None:
                    extra[label] = text
            if session.face_currency:
                extra["face_currency"] = session.face_currency
            if session.faceunit_raw:
                extra["faceunit_raw"] = session.faceunit_raw
            limitations: tuple[str, ...] = ("yields_not_computed",)
            if session.close == 0:
                limitations = (*limitations, "explicit_zero")
            if session.price_field != "LEGALCLOSEPRICE":
                limitations = (*limitations, "close_used_because_legalcloseprice_absent")
            observations.append(
                ParsedObservation(
                    metric_id="market.bond.eod.close",
                    source_id=SOURCE_ID,
                    content_hash=artifact.content_hash,
                    normalization_version=HISTORY_NORMALIZATION,
                    quality_status=RecordQuality.ACCEPTED,
                    value=float(session.close),
                    unit="percent_of_face",
                    currency=None,
                    period=session.trade_date.isoformat(),
                    period_end=session.trade_date,
                    evidence=(
                        "ISS history TRADEDATE is the period/event date, not known_at; "
                        "value is LEGALCLOSEPRICE when present, otherwise CLOSE; "
                        "percent of face; yield is not computed"
                    ),
                    limitations=limitations,
                    issuer_identity=identity,
                    extra=extra,
                )
            )
        return tuple(observations)

    def _now(self) -> datetime:
        current = self._clock()
        if current.tzinfo is None:
            return current.replace(tzinfo=UTC)
        return current.astimezone(UTC)
