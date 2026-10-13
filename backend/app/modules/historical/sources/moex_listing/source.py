"""Bounded MOEX ISS probe for listing windows and boards.

MOEX-02 asks for historical identifiers and listing changes. The public
listing table has ``history_from`` and ``history_till`` only. It has no
``listed_from``, ``listed_till``, list/delist event, or previous SECID.
That stream stays BLOCKED and RESEARCH_ONLY.

MOEX-03 reads the shares board dictionary and one security's boards block
(``iss.only=boards``). ``listed_from`` and ``listed_till`` are emitted only
from that boards payload. The description block is not a listing event.

``first_observed_at`` is the fetch clock. Window dates stay in row extras.
``period_end`` is left empty so it cannot stand in for the clock.
At most 100 rows are kept from each table. No second page is requested.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

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

SOURCE_PACKAGE = "MOEX-LISTING"
LISTING_SOURCE_ID = "MOEX-02"
BOARDS_SOURCE_ID = "MOEX-03"
LISTING_PARSER = "moex_listing_history_v1"
BOARD_CATALOGUE_PARSER = "moex_board_catalogue_v1"
SECURITY_BOARDS_PARSER = "moex_security_boards_v1"
LISTING_NORMALIZATION = "moex_listing_history_v1"
BOARDS_NORMALIZATION = "moex_boards_v1"
ROW_CAP = 100
PILOT_SECID = "SBER"
ISS_BASE = "https://iss.moex.com"

LISTING_URL = f"{ISS_BASE}/iss/history/engines/stock/markets/shares/listing.json"
BOARD_CATALOGUE_URL = f"{ISS_BASE}/iss/engines/stock/markets/shares/boards.json"
SECURITY_BOARDS_URL = f"{ISS_BASE}/iss/securities/{PILOT_SECID}.json"

LISTING_COLUMNS = (
    "SECID",
    "SHORTNAME",
    "NAME",
    "BOARDID",
    "decimals",
    "history_from",
    "history_till",
)
ABSENT_LISTING_COLUMNS = (
    "listed_from",
    "listed_till",
    "listdate",
    "delistdate",
    "ISIN",
    "old_secid",
)

LISTING_PIT_EVIDENCE = (
    "ISS listing history columns are SECID, SHORTNAME, NAME, BOARDID, decimals, "
    "history_from, history_till. listed_from, listed_till, and identifier-change "
    "columns are absent. history_from and history_till are window bounds, not "
    "list/delist events and not known_at"
)
BOARD_PIT_EVIDENCE = (
    "ISS shares boards.json has no secid and no list dates. "
    "ISS securities boards (iss.only=boards) includes listed_from and listed_till "
    "when those columns are present. There is no publication timestamp. "
    "listed_till on a traded board is a snapshot bound, not a delisting event. "
    "The description block is not a listing event"
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _as_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _iso(value: object) -> str | None:
    parsed = _as_date(value)
    if parsed is None:
        return None
    return parsed.isoformat()


def _text(value: object) -> str:
    if value in (None, ""):
        return ""
    return str(value).strip()


def _table(payload: Mapping[str, Any], block: str) -> tuple[list[dict[str, Any]], int]:
    table = payload.get(block) or {}
    if not isinstance(table, dict):
        return [], 0
    columns = table.get("columns") or []
    data = table.get("data") or []
    if not isinstance(columns, list) or not isinstance(data, list):
        return [], 0
    rows = [dict(zip(columns, values, strict=False)) for values in data[:ROW_CAP]]
    return rows, len(data)


def _board_id(row: Mapping[str, Any]) -> str:
    return _text(row.get("BOARDID") or row.get("boardid")).upper()


def _secid(row: Mapping[str, Any]) -> str:
    return _text(row.get("SECID") or row.get("secid")).upper()


class MoexListingSource:
    """HistoricalSource for the bounded MOEX listing and board probe."""

    source_id = SOURCE_PACKAGE

    def __init__(
        self,
        *,
        http: MarketHttpClient | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._http = http
        self._clock = clock or (lambda: datetime.now(UTC))
        self._cache: dict[str, bytes] = {}
        self._artifacts: tuple[HistoricalArtifact, ...] | None = None
        self._artifact_cap: int | None = None
        self._parse_cap = ROW_CAP

    def discover(self) -> CoverageReport:
        self.fetch_sample(limit=ROW_CAP)
        return CoverageReport(
            source_id=LISTING_SOURCE_ID,
            status=AdapterStatus.BLOCKED,
            earliest=None,
            latest=None,
            formats=("iss_json",),
            limitations=_listing_limitations(),
        )

    def inspect_coverage(self) -> CoverageReport:
        self.fetch_sample(limit=ROW_CAP)
        return CoverageReport(
            source_id=BOARDS_SOURCE_ID,
            status=AdapterStatus.PARTIAL,
            earliest=None,
            latest=None,
            formats=("iss_json",),
            limitations=_board_limitations(),
        )

    def fetch_sample(self, *, limit: int = ROW_CAP) -> tuple[HistoricalArtifact, ...]:
        cap = _cap(limit)
        self._parse_cap = cap
        if self._artifacts is not None and self._artifact_cap == cap:
            return self._artifacts
        observed_at = self._now()
        listing = self._listing_artifact(observed_at, cap)
        catalogue = self._catalogue_artifact(observed_at, cap)
        boards = self._security_boards_artifact(observed_at, cap)
        self._artifact_cap = cap
        self._artifacts = (listing, catalogue, boards)
        return self._artifacts

    def fetch_range(self, *, start: date, end: date, limit: int) -> tuple[HistoricalArtifact, ...]:
        """Return nothing. These payloads are snapshots, not dated events.

        Selecting rows by ``history_till`` or ``listed_till`` would treat a
        window bound as an event date. ``end`` is not written to
        ``first_observed_at``.
        """
        del start, end, limit
        return ()

    def parse(self, artifact: HistoricalArtifact, raw: bytes) -> tuple[ParsedObservation, ...]:
        if artifact.document_type == "security_description":
            return ()
        payload = _load_object(raw)
        if payload is None:
            return ()
        if _description_only(payload):
            return ()
        if artifact.document_type == "listing_history_page":
            observations = _listing_observations(artifact, payload)
        elif artifact.document_type == "board_catalogue":
            observations = _catalogue_observations(artifact, payload)
        elif artifact.document_type == "security_boards":
            observations = _security_board_observations(artifact, payload)
        else:
            return ()
        observations = observations[: self._parse_cap]
        if _sha256(raw) != artifact.content_hash:
            return tuple(_quarantine(item, "content_hash_mismatch") for item in observations)
        return observations

    def validate(self, observations: tuple[ParsedObservation, ...]) -> tuple[ParsedObservation, ...]:
        checked: list[ParsedObservation] = []
        for item in observations:
            errors = item.quality_errors()
            if not errors:
                checked.append(item)
                continue
            checked.append(_quarantine(item, *errors))
        return tuple(checked)

    def _listing_artifact(self, observed_at: datetime, cap: int) -> HistoricalArtifact:
        payload = self._get(LISTING_URL, {"iss.meta": "off", "start": "0"})
        rows, total = _table(_json(payload), "securities")
        kept = rows[:cap]
        return _page_artifact(
            source_id=LISTING_SOURCE_ID,
            url=LISTING_URL,
            document_id="shares:listing:page1",
            document_type="listing_history_page",
            parser_version=LISTING_PARSER,
            payload=payload,
            observed_at=observed_at,
            title="MOEX ISS shares listing history, first page",
            entity_identifiers={"engine": "stock", "market": "shares"},
            evidence=LISTING_PIT_EVIDENCE,
            quality=RecordQuality.UNRESOLVED,
            row_count=len(kept),
            response_rows=total,
            limitations=_listing_limitations(truncated=total > cap),
        )

    def _catalogue_artifact(self, observed_at: datetime, cap: int) -> HistoricalArtifact:
        payload = self._get(BOARD_CATALOGUE_URL, {"iss.meta": "off"})
        rows, total = _table(_json(payload), "boards")
        kept = rows[:cap]
        return _page_artifact(
            source_id=BOARDS_SOURCE_ID,
            url=BOARD_CATALOGUE_URL,
            document_id="shares:boards",
            document_type="board_catalogue",
            parser_version=BOARD_CATALOGUE_PARSER,
            payload=payload,
            observed_at=observed_at,
            title="MOEX ISS shares board dictionary",
            entity_identifiers={"engine": "stock", "market": "shares"},
            evidence=BOARD_PIT_EVIDENCE,
            quality=RecordQuality.ACCEPTED if kept else RecordQuality.UNRESOLVED,
            row_count=len(kept),
            response_rows=total,
            limitations=_board_limitations(truncated=total > cap),
        )

    def _security_boards_artifact(self, observed_at: datetime, cap: int) -> HistoricalArtifact:
        payload = self._get(
            SECURITY_BOARDS_URL,
            {"iss.meta": "off", "iss.only": "boards"},
        )
        rows, total = _table(_json(payload), "boards")
        kept = rows[:cap]
        return _page_artifact(
            source_id=BOARDS_SOURCE_ID,
            url=SECURITY_BOARDS_URL,
            document_id=f"{PILOT_SECID}:boards",
            document_type="security_boards",
            parser_version=SECURITY_BOARDS_PARSER,
            payload=payload,
            observed_at=observed_at,
            title=f"MOEX ISS {PILOT_SECID} board windows",
            entity_identifiers={"secid": PILOT_SECID, "engine": "stock"},
            evidence=BOARD_PIT_EVIDENCE,
            quality=RecordQuality.ACCEPTED if kept else RecordQuality.UNRESOLVED,
            row_count=len(kept),
            response_rows=total,
            limitations=_board_limitations(truncated=total > cap) + ("pilot_secid_sber_only",),
        )

    def _get(self, url: str, params: dict[str, str]) -> bytes:
        key = url + "?" + "&".join(f"{name}={value}" for name, value in sorted(params.items()))
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        response = self._client().get(url, params=params)
        body = response.content
        self._cache[key] = body
        return body

    def _client(self) -> MarketHttpClient:
        if self._http is None:
            self._http = MarketHttpClient()
        return self._http

    def _now(self) -> datetime:
        current = self._clock()
        if current.tzinfo is None:
            return current.replace(tzinfo=UTC)
        return current.astimezone(UTC)


def _cap(limit: int) -> int:
    if limit <= 0:
        return 0
    return min(limit, ROW_CAP)


def _json(payload: bytes) -> dict[str, Any]:
    loaded = json.loads(payload)
    if not isinstance(loaded, dict):
        return {}
    return loaded


def _load_object(raw: bytes) -> dict[str, Any] | None:
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded


def _description_only(payload: Mapping[str, Any]) -> bool:
    return "description" in payload and "boards" not in payload and "securities" not in payload


def _listing_limitations(*, truncated: bool = False) -> tuple[str, ...]:
    notes = [
        "no_listed_from_column",
        "no_listed_till_column",
        "no_identifier_change_series",
        "history_window_is_not_a_listing_event",
        "description_endpoint_not_a_listing_event",
        "no_publication_timestamp",
        "no_cursor_block",
        "row_cap_100",
        "first_page_only",
    ]
    if truncated:
        notes.append("truncated_to_100")
    return tuple(notes)


def _board_limitations(*, truncated: bool = False) -> tuple[str, ...]:
    notes = [
        "current_board_snapshot",
        "listed_till_is_not_a_delist_event",
        "no_publication_timestamp",
        "description_endpoint_not_a_listing_event",
        "row_cap_100",
    ]
    if truncated:
        notes.append("truncated_to_100")
    return tuple(notes)


def _page_artifact(
    *,
    source_id: str,
    url: str,
    document_id: str,
    document_type: str,
    parser_version: str,
    payload: bytes,
    observed_at: datetime,
    title: str,
    entity_identifiers: dict[str, str],
    evidence: str,
    quality: RecordQuality,
    row_count: int,
    response_rows: int,
    limitations: tuple[str, ...],
) -> HistoricalArtifact:
    fetch_status = FetchStatus.OK if row_count else FetchStatus.EMPTY
    return HistoricalArtifact(
        source_id=source_id,
        source_url=url,
        external_document_id=document_id,
        document_type=document_type,
        content_hash=_sha256(payload),
        parser_version=parser_version,
        fetch_status=fetch_status,
        first_observed_at=observed_at,
        title=title,
        entity_identifiers=entity_identifiers,
        reporting_period=None,
        period_end=None,
        event_date=None,
        published_at=None,
        published_at_precision=PublishedAtPrecision.UNKNOWN,
        historical_availability_evidence=evidence,
        historical_pit_quality=PitQuality.RESEARCH_ONLY,
        raw_artifact_reference=None,
        quality_status=quality if row_count else RecordQuality.UNRESOLVED,
        limitations=limitations + (f"response_rows={response_rows}", f"kept_rows={row_count}"),
    )


def _listing_observations(artifact: HistoricalArtifact, payload: Mapping[str, Any]) -> tuple[ParsedObservation, ...]:
    rows, _total = _table(payload, "securities")
    observations: list[ParsedObservation] = []
    for row in rows:
        secid = _secid(row)
        board = _board_id(row)
        if not secid or not board:
            continue
        present = {str(key) for key in row}
        observations.append(
            ParsedObservation(
                metric_id="market.listing.history_window",
                source_id=LISTING_SOURCE_ID,
                content_hash=artifact.content_hash,
                normalization_version=LISTING_NORMALIZATION,
                quality_status=RecordQuality.UNRESOLVED,
                period_end=None,
                issuer_identity={"secid": secid, "board": board},
                limitations=(
                    "no_list_delist_field",
                    "history_window_is_not_a_listing_event",
                    "no_identifier_change",
                ),
                extra={
                    "secid": secid,
                    "board": board,
                    "shortname": _text(row.get("SHORTNAME")) or None,
                    "name": _text(row.get("NAME")) or None,
                    "history_from": _iso(row.get("history_from")),
                    "history_till": _iso(row.get("history_till")),
                    "listed_from": _iso(row.get("listed_from")) if "listed_from" in present else None,
                    "listed_till": _iso(row.get("listed_till")) if "listed_till" in present else None,
                    "listing_columns": list(LISTING_COLUMNS),
                    "absent_listing_columns": list(ABSENT_LISTING_COLUMNS),
                },
            )
        )
    return tuple(observations)


def _catalogue_observations(artifact: HistoricalArtifact, payload: Mapping[str, Any]) -> tuple[ParsedObservation, ...]:
    rows, _total = _table(payload, "boards")
    observations: list[ParsedObservation] = []
    for row in rows:
        board = _board_id(row)
        if not board:
            continue
        observations.append(
            ParsedObservation(
                metric_id="market.board.catalogue",
                source_id=BOARDS_SOURCE_ID,
                content_hash=artifact.content_hash,
                normalization_version=BOARDS_NORMALIZATION,
                quality_status=RecordQuality.ACCEPTED,
                period_end=None,
                evidence=f"ISS boards.boardid={board}",
                issuer_identity={"board": board},
                limitations=("no_secid", "no_list_delist_date", "current_snapshot"),
                extra={
                    "board": board,
                    "title": _text(row.get("title")) or None,
                    "is_traded": row.get("is_traded"),
                    "listed_from": None,
                    "listed_till": None,
                },
            )
        )
    return tuple(observations)


def _security_board_observations(
    artifact: HistoricalArtifact, payload: Mapping[str, Any]
) -> tuple[ParsedObservation, ...]:
    """Read the boards block only. Description rows are never events."""
    rows, _total = _table(payload, "boards")
    observations: list[ParsedObservation] = []
    for row in rows:
        secid = _secid(row)
        board = _board_id(row)
        if not secid or not board:
            continue
        listed_from = _iso(row.get("listed_from"))
        listed_till = _iso(row.get("listed_till"))
        history_from = _iso(row.get("history_from"))
        history_till = _iso(row.get("history_till"))
        observations.append(
            ParsedObservation(
                metric_id="market.board.window",
                source_id=BOARDS_SOURCE_ID,
                content_hash=artifact.content_hash,
                normalization_version=BOARDS_NORMALIZATION,
                quality_status=RecordQuality.ACCEPTED,
                period_end=None,
                evidence=(
                    f"ISS boards.secid={secid} boardid={board} " f"listed_from={listed_from} listed_till={listed_till}"
                ),
                issuer_identity={"secid": secid, "board": board},
                limitations=(
                    "board_window_snapshot",
                    "listed_till_is_not_a_delist_event",
                    "no_publication_timestamp",
                ),
                extra={
                    "secid": secid,
                    "board": board,
                    "listed_from": listed_from,
                    "listed_till": listed_till,
                    "history_from": history_from,
                    "history_till": history_till,
                    "is_traded": row.get("is_traded"),
                    "is_primary": row.get("is_primary"),
                    "market": _text(row.get("market")) or None,
                },
            )
        )
    return tuple(observations)


def _quarantine(item: ParsedObservation, *notes: str) -> ParsedObservation:
    return replace(
        item,
        quality_status=RecordQuality.QUARANTINE,
        limitations=item.limitations + notes,
    )
