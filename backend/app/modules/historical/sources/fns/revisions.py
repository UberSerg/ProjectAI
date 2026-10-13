"""FNS-03: prior GIR BO corrections for one industrial issuer.

Public ``GET /nbo/organizations/{id}/bfo/`` for LKOH (INN 7708004767,
org 6681478, probed 2026-10-13) returns five periods. Each
``typeCorrections`` entry is ``{type: 12, correction: object}``.
``correctionVersion``, ``actualCorrectionNumber`` and
``publishedCorrectionNumber`` are the scalar ``0``. There is no
``corrections`` array. Sibling correction URLs answer 404. The open-web
client reads that singular object; a ``corrections`` list belongs to the
non-public branch and is not in this payload.

Missing versions are not invented. ``period_end`` is the fiscal year end
and is never ``published_at``. Bank periods are skipped, so industrial
ratios are not produced for them. This module does not write prospective
memory and does not call an LLM.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import httpx

from app.modules.fundamentals.infrastructure.fns_gir_bo_provider import (
    BANK_FI_SECIDS,
    FNS_BASE_URL,
    FNS_BFO_PATH,
    SUPPORT_INDUSTRIAL,
    FnsGirBoClient,
    FnsGirBoProvider,
    parse_bfo_periods,
    resolve_fns_identity,
    resolve_known_at,
)
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

SOURCE_ID = "FNS-03"
PARSER_VERSION = "fns_gir_bo_revisions_v1"
PILOT_INN = "7708004767"
PILOT_SECID = "LKOH"

_REVISION_LIST_KEYS = (
    "corrections",
    "previousCorrections",
    "priorCorrections",
    "revisionHistory",
    "revisions",
    "history",
    "versions",
)


@dataclass(frozen=True, slots=True)
class LatestCorrectionEvidence:
    """The current correction object. This is not a prior revision row."""

    bfo_id: str
    fiscal_year: int
    period_end: date
    published_at: datetime | None
    published_at_precision: PublishedAtPrecision
    pit_quality: PitQuality
    revision_identifier: str
    correction_version: int | None
    actual_correction_number: int | None
    published_correction_number: int | None


@dataclass(frozen=True, slots=True)
class FnsRevisionResult:
    discover_status: AdapterStatus
    revisions_status: AdapterStatus
    payload_has_revision_list: bool
    period_count: int
    latest_correction_count: int
    prior_revision_count: int
    latest: tuple[LatestCorrectionEvidence, ...]
    prior_revisions: tuple[HistoricalArtifact, ...]
    pit: tuple[str, ...]
    limitations: tuple[str, ...]
    blockers: tuple[str, ...]
    evidence: tuple[str, ...]
    http_error: str | None
    observations: tuple[ParsedObservation, ...]


def payload_has_revision_list(periods: Sequence[Mapping[str, Any]]) -> bool:
    """True when an industrial period actually carries a list of corrections."""
    return any(_period_has_revision_list(period) for period in periods if not _is_bank_period(period))


class FnsGirBoRevisionSource:
    """Discover whether the public BFO feed has prior corrections for one issuer."""

    source_id = SOURCE_ID

    def __init__(
        self,
        client: FnsGirBoClient | None = None,
        *,
        provider: FnsGirBoProvider | None = None,
        inn: str = PILOT_INN,
        secid: str = PILOT_SECID,
        observed_at: datetime | None = None,
    ) -> None:
        if provider is not None:
            self.client = provider.client
            self._owns_client = False
        else:
            self.client = client or FnsGirBoClient()
            self._owns_client = client is None
        self.provider = provider or FnsGirBoProvider(self.client)
        self.inn = inn
        self.secid = secid.upper()
        self.observed_at = observed_at or datetime.now(UTC)
        self._result: FnsRevisionResult | None = None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def run(self) -> FnsRevisionResult:
        if self._result is None:
            try:
                self._result = self._execute()
            finally:
                self.close()
        return self._result

    def discover(self) -> CoverageReport:
        result = self.run()
        ends = [item.period_end for item in result.latest]
        ends.extend(item.period_end for item in result.prior_revisions if item.period_end is not None)
        return CoverageReport(
            source_id=self.source_id,
            status=result.discover_status,
            earliest=min(ends) if ends else None,
            latest=max(ends) if ends else None,
            formats=("application/json",),
            limitations=result.limitations,
        )

    def inspect_coverage(self) -> CoverageReport:
        return self.discover()

    def fetch_sample(self, *, limit: int = 30) -> tuple[HistoricalArtifact, ...]:
        return self.run().prior_revisions[:limit]

    def fetch_range(self, *, start: date, end: date, limit: int) -> tuple[HistoricalArtifact, ...]:
        selected = [
            item
            for item in self.run().prior_revisions
            if item.period_end is not None and start <= item.period_end <= end
        ]
        return tuple(selected[:limit])

    def parse(self, artifact: HistoricalArtifact, raw: bytes) -> tuple[ParsedObservation, ...]:
        del artifact, raw
        return ()

    def validate(self, observations: tuple[ParsedObservation, ...]) -> tuple[ParsedObservation, ...]:
        return observations

    def _execute(self) -> FnsRevisionResult:
        if self.observed_at.tzinfo is None:
            return _empty(
                discover_status=AdapterStatus.FAILED,
                revisions_status=AdapterStatus.BLOCKED,
                limitations=("first_observed_at_must_be_timezone_aware",),
                blockers=("first_observed_at_must_be_timezone_aware",),
            )
        if self.secid in BANK_FI_SECIDS:
            resolution = resolve_fns_identity(self.client, inn=self.inn, secid=self.secid)
            return _empty(
                discover_status=AdapterStatus.PARTIAL,
                revisions_status=AdapterStatus.BLOCKED,
                limitations=(resolution.reason or resolution.support_status, "industrial_ratios_not_emitted"),
                blockers=("BANK_FI_NOT_SUPPORTED_BY_FNS_RAS_V1",),
                evidence=("bank_secid_skipped",),
            )
        try:
            resolution = resolve_fns_identity(self.client, inn=self.inn, secid=self.secid)
        except httpx.HTTPStatusError as exc:
            return _http_status(exc)
        except httpx.HTTPError as exc:
            return _http_failed(exc)

        if resolution.support_status != SUPPORT_INDUSTRIAL or resolution.org is None:
            reason = resolution.reason or resolution.support_status
            return _empty(
                discover_status=AdapterStatus.PARTIAL,
                revisions_status=AdapterStatus.BLOCKED,
                limitations=(reason, "industrial_ratios_not_emitted"),
                blockers=(reason,),
            )

        org = resolution.org
        try:
            periods = self.client.fetch_bfo(org.org_id)
        except httpx.HTTPStatusError as exc:
            return _http_status(exc)
        except httpx.HTTPError as exc:
            return _http_failed(exc)

        bundles = parse_bfo_periods(periods, issuer_id=0, org_id=org.org_id)
        provider_latest = {
            str(bundle.metadata.get("fns_bfo_id")): _identifier(bundle.metadata.get("fns_correction_id"))
            for bundle in bundles
        }
        return _from_periods(
            periods,
            org_id=org.org_id,
            inn=org.inn,
            secid=self.secid,
            observed_at=self.observed_at,
            provider_latest=provider_latest,
        )


def _from_periods(
    periods: Sequence[Mapping[str, Any]],
    *,
    org_id: int,
    inn: str,
    secid: str,
    observed_at: datetime,
    provider_latest: Mapping[str, str | None],
) -> FnsRevisionResult:
    latest_rows: list[LatestCorrectionEvidence] = []
    priors: list[HistoricalArtifact] = []
    evidence: list[str] = []
    limitations: list[str] = [
        "single_issuer_no_registry_crawl",
        "industrial_ratios_not_emitted_for_banks",
        "period_end_is_not_published_at",
    ]
    has_list = False
    bank_periods = 0
    industrial_periods = 0

    for period in periods:
        if not isinstance(period, Mapping):
            continue
        if _is_bank_period(period):
            bank_periods += 1
            continue
        industrial_periods += 1
        period_list = _period_has_revision_list(period)
        has_list = has_list or period_list
        evidence.extend(_period_evidence(period))
        inspection = _inspect_period(period, provider_id=provider_latest.get(str(period.get("id"))))
        if inspection.latest_body is None or inspection.latest_identifier is None:
            continue
        published = _publication(period, inspection.latest_body)
        year = _fiscal_year(period)
        if year is None:
            continue
        period_end = date(year, 12, 31)
        if published.published_at is not None and published.published_at.date() == period_end:
            limitations.append("period_end_equals_published_at")
        bfo_id = str(period.get("id"))
        provider_id = provider_latest.get(bfo_id)
        if provider_id is not None and provider_id != inspection.latest_identifier:
            limitations.append("provider_latest_identifier_mismatch")
        latest_rows.append(
            LatestCorrectionEvidence(
                bfo_id=bfo_id,
                fiscal_year=year,
                period_end=period_end,
                published_at=published.published_at,
                published_at_precision=published.precision,
                pit_quality=published.quality,
                revision_identifier=inspection.latest_identifier,
                correction_version=_optional_int(
                    inspection.latest_body.get("correctionVersion"),
                ),
                actual_correction_number=_optional_int(period.get("actualCorrectionNumber")),
                published_correction_number=_optional_int(period.get("publishedCorrectionNumber")),
            )
        )
        for prior in inspection.priors:
            artifact = _prior_artifact(
                period,
                prior,
                org_id=org_id,
                inn=inn,
                secid=secid,
                observed_at=observed_at,
                year=year,
                period_end=period_end,
            )
            if artifact is not None:
                priors.append(artifact)

    if bank_periods:
        limitations.append("is_cb_period_skipped")
    if has_list:
        limitations.append("parsed_only_corrections_present_in_payload")
    else:
        limitations.extend(
            (
                "fns_public_bfo_latest_correction_only",
                "no_prior_revision_list",
                "revision_history_incomplete",
            )
        )

    latest_sorted = tuple(sorted(latest_rows, key=lambda item: item.period_end))
    priors_sorted = tuple(
        sorted(priors, key=lambda item: (item.period_end or date.min, item.revision_identifier or ""))
    )
    discover_status, revisions_status, blockers = _statuses(
        has_list=has_list,
        prior_count=len(priors_sorted),
        industrial_periods=industrial_periods,
    )
    pit = tuple(sorted({item.pit_quality.value for item in latest_sorted}))
    return FnsRevisionResult(
        discover_status=discover_status,
        revisions_status=revisions_status,
        payload_has_revision_list=has_list,
        period_count=industrial_periods,
        latest_correction_count=len(latest_sorted),
        prior_revision_count=len(priors_sorted),
        latest=latest_sorted,
        prior_revisions=priors_sorted,
        pit=pit,
        limitations=tuple(dict.fromkeys(limitations)),
        blockers=blockers,
        evidence=tuple(dict.fromkeys(evidence)),
        http_error=None,
        observations=(),
    )


@dataclass(frozen=True, slots=True)
class _Inspection:
    latest_body: Mapping[str, Any] | None
    latest_identifier: str | None
    priors: tuple[Mapping[str, Any], ...]


def _inspect_period(period: Mapping[str, Any], *, provider_id: str | None) -> _Inspection:
    slots = period.get("typeCorrections")
    if not isinstance(slots, list):
        return _Inspection(None, None, ())

    singulars: list[Mapping[str, Any]] = []
    listed: list[Mapping[str, Any]] = []
    singular_groups: dict[int, list[Mapping[str, Any]]] = {}
    for slot in slots:
        if not isinstance(slot, Mapping):
            continue
        try:
            type_code = int(slot.get("type") or 0)
        except (TypeError, ValueError):
            type_code = 0
        for key in _REVISION_LIST_KEYS:
            value = slot.get(key)
            if isinstance(value, list):
                listed.extend(item for item in value if isinstance(item, Mapping))
        correction = slot.get("correction")
        if isinstance(correction, list):
            listed.extend(item for item in correction if isinstance(item, Mapping))
        elif isinstance(correction, Mapping):
            singulars.append(correction)
            singular_groups.setdefault(type_code, []).append(correction)
    for key in _REVISION_LIST_KEYS:
        value = period.get(key)
        if isinstance(value, list):
            listed.extend(item for item in value if isinstance(item, Mapping))
    for group in singular_groups.values():
        if len(group) > 1:
            listed.extend(group)

    if not _period_has_revision_list(period):
        body = _provider_body(provider_id, singulars) or _annual_or_first(singular_groups, singulars)
        return _Inspection(body, _identifier(None if body is None else body.get("id")), ())

    latest_body = _provider_body(provider_id, [*singulars, *listed]) or _choose_latest(singulars, listed, period)
    latest_id = _identifier(None if latest_body is None else latest_body.get("id"))
    priors: list[Mapping[str, Any]] = []
    seen = {latest_id} if latest_id is not None else set()
    for item in listed:
        item_id = _identifier(item.get("id"))
        if item_id is None or item_id in seen:
            continue
        seen.add(item_id)
        priors.append(item)
    return _Inspection(latest_body, latest_id, tuple(priors))


def _provider_body(
    provider_id: str | None,
    bodies: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    if provider_id is None:
        return None
    for body in bodies:
        if _identifier(body.get("id")) == provider_id:
            return body
    return None


def _annual_or_first(
    groups: Mapping[int, Sequence[Mapping[str, Any]]],
    singulars: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    annual = groups.get(12)
    if annual:
        return annual[0]
    return singulars[0] if singulars else None


def _choose_latest(
    singulars: Sequence[Mapping[str, Any]],
    listed: Sequence[Mapping[str, Any]],
    period: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    """Keep the provider's current object when it is present.

    A listed earlier filing must not replace that object. Without a singular
    ``correction``, the highest ``correctionVersion`` already in the list is
    the latest present row.
    """
    if singulars:
        return singulars[0]
    if not listed:
        return None
    target = _optional_int(period.get("actualCorrectionNumber"))

    def sort_key(item: Mapping[str, Any]) -> tuple[int, int, int]:
        version = _optional_int(item.get("correctionVersion"))
        matches = 1 if target is not None and version == target else 0
        return (matches, version if version is not None else -1, _optional_int(item.get("id")) or -1)

    return max(listed, key=sort_key)


def _prior_artifact(
    period: Mapping[str, Any],
    correction: Mapping[str, Any],
    *,
    org_id: int,
    inn: str,
    secid: str,
    observed_at: datetime,
    year: int,
    period_end: date,
) -> HistoricalArtifact | None:
    revision_id = _identifier(correction.get("id"))
    if revision_id is None:
        return None
    published = _publication(period, correction)
    limitations = ["present_correction_from_payload", *published.limitations]
    if published.published_at is not None and published.published_at.date() == period_end:
        limitations.append("period_end_equals_published_at")
    quality = RecordQuality.ACCEPTED
    artifact = HistoricalArtifact(
        source_id=SOURCE_ID,
        source_url=f"{FNS_BASE_URL}{FNS_BFO_PATH.format(org_id=org_id)}",
        external_document_id=f"bfo:{period.get('id')}:correction:{revision_id}",
        document_type="fns_bfo_prior_correction",
        content_hash=_content_hash(correction),
        parser_version=PARSER_VERSION,
        fetch_status=FetchStatus.OK,
        first_observed_at=observed_at,
        entity_identifiers={"inn": inn, "secid": secid, "fns_org_id": str(org_id)},
        reporting_period=f"FY:{year}",
        period_end=period_end,
        published_at=published.published_at,
        published_at_precision=published.precision,
        historical_availability_evidence=published.evidence,
        historical_pit_quality=published.quality,
        revision_identifier=revision_id,
        quality_status=quality,
        limitations=tuple(dict.fromkeys(limitations)),
    )
    if artifact.chronology_errors() or (
        artifact.published_at is not None and artifact.period_end == artifact.published_at.date()
    ):
        artifact = HistoricalArtifact(
            source_id=artifact.source_id,
            source_url=artifact.source_url,
            external_document_id=artifact.external_document_id,
            document_type=artifact.document_type,
            content_hash=artifact.content_hash,
            parser_version=artifact.parser_version,
            fetch_status=artifact.fetch_status,
            first_observed_at=artifact.first_observed_at,
            title=artifact.title,
            entity_identifiers=dict(artifact.entity_identifiers),
            reporting_period=artifact.reporting_period,
            period_end=artifact.period_end,
            event_date=artifact.event_date,
            published_at=artifact.published_at,
            published_at_precision=artifact.published_at_precision,
            historical_availability_evidence=artifact.historical_availability_evidence,
            historical_pit_quality=artifact.historical_pit_quality,
            revision_identifier=artifact.revision_identifier,
            raw_artifact_reference=artifact.raw_artifact_reference,
            quality_status=RecordQuality.QUARANTINE,
            limitations=artifact.limitations,
        )
    return artifact


@dataclass(frozen=True, slots=True)
class _Publication:
    quality: PitQuality
    precision: PublishedAtPrecision
    published_at: datetime | None
    limitations: tuple[str, ...]
    evidence: str | None


def _publication(period: Mapping[str, Any], correction: Mapping[str, Any]) -> _Publication:
    limitations: list[str] = []
    try:
        _known_at, published_at, _precision = resolve_known_at(period, correction)
    except ValueError:
        return _Publication(
            PitQuality.RESEARCH_ONLY,
            PublishedAtPrecision.UNKNOWN,
            None,
            ("fns_publication_timestamp_absent",),
            None,
        )
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
        limitations.append("fns_naive_datetime_anchored_utc")
    else:
        published_at = published_at.astimezone(UTC)
    clock = (published_at.hour, published_at.minute, published_at.second, published_at.microsecond) != (0, 0, 0, 0)
    if clock:
        precision = PublishedAtPrecision.TIMESTAMP
        limitations.append("fns_date_present_timezone_unspecified")
    else:
        precision = PublishedAtPrecision.DATE_ONLY
        limitations.append("fns_publication_timestamp_absent")
    corrected = _iso_date(period.get("publishedCorrectionDate"))
    if corrected is not None and corrected != published_at.date():
        limitations.append("fns_published_correction_date_differs_from_date_present")
        quality = PitQuality.RESEARCH_ONLY
    else:
        quality = PitQuality.PIT_PROXY
    return _Publication(quality, precision, published_at, tuple(limitations), "fns_gir_bo.correction.datePresent")


def _period_has_revision_list(period: Mapping[str, Any]) -> bool:
    if _is_bank_period(period):
        return False
    for key in _REVISION_LIST_KEYS:
        if isinstance(period.get(key), list):
            return True
    slots = period.get("typeCorrections")
    if not isinstance(slots, list):
        return False
    groups: dict[int, int] = {}
    for slot in slots:
        if not isinstance(slot, Mapping):
            continue
        try:
            type_code = int(slot.get("type") or 0)
        except (TypeError, ValueError):
            type_code = 0
        for key in _REVISION_LIST_KEYS:
            if isinstance(slot.get(key), list):
                return True
        correction = slot.get("correction")
        if isinstance(correction, list):
            return True
        if isinstance(correction, Mapping):
            groups[type_code] = groups.get(type_code, 0) + 1
    return any(count > 1 for count in groups.values())


def _period_evidence(period: Mapping[str, Any]) -> tuple[str, ...]:
    notes = ["typeCorrections_is_period_type_slot_list"]
    if _scalar(period.get("actualCorrectionNumber")):
        notes.append("actualCorrectionNumber_is_scalar")
    if "publishedCorrectionNumber" in period and _scalar(period.get("publishedCorrectionNumber")):
        notes.append("publishedCorrectionNumber_is_scalar")
    slots = period.get("typeCorrections")
    if isinstance(slots, list):
        for slot in slots:
            if not isinstance(slot, Mapping):
                continue
            correction = slot.get("correction")
            if isinstance(correction, dict):
                notes.append("correction_value_is_object")
            elif isinstance(correction, list):
                notes.append("correction_value_is_list")
            if isinstance(slot.get("corrections"), list):
                notes.append("corrections_array_present")
    if not _period_has_revision_list(period):
        notes.append("no_revision_list")
    return tuple(notes)


def _statuses(
    *,
    has_list: bool,
    prior_count: int,
    industrial_periods: int,
) -> tuple[AdapterStatus, AdapterStatus, tuple[str, ...]]:
    if industrial_periods == 0:
        return AdapterStatus.PARTIAL, AdapterStatus.BLOCKED, ("no_industrial_bfo_periods",)
    if not has_list or prior_count == 0:
        return AdapterStatus.PARTIAL, AdapterStatus.BLOCKED, ("prior_corrections_not_in_public_bfo",)
    return AdapterStatus.PARTIAL, AdapterStatus.PARTIAL, ("revision_list_completeness_not_proven",)


def _empty(
    *,
    discover_status: AdapterStatus,
    revisions_status: AdapterStatus,
    limitations: tuple[str, ...],
    blockers: tuple[str, ...],
    evidence: tuple[str, ...] = (),
    http_error: str | None = None,
) -> FnsRevisionResult:
    return FnsRevisionResult(
        discover_status=discover_status,
        revisions_status=revisions_status,
        payload_has_revision_list=False,
        period_count=0,
        latest_correction_count=0,
        prior_revision_count=0,
        latest=(),
        prior_revisions=(),
        pit=(),
        limitations=limitations,
        blockers=blockers,
        evidence=evidence,
        http_error=http_error,
        observations=(),
    )


def _http_status(exc: httpx.HTTPStatusError) -> FnsRevisionResult:
    code = exc.response.status_code
    http_error = f"HTTP {code}"
    return _empty(
        discover_status=AdapterStatus.BLOCKED,
        revisions_status=AdapterStatus.BLOCKED,
        limitations=(f"http_{code}",),
        blockers=(http_error,),
        http_error=http_error,
    )


def _http_failed(exc: httpx.HTTPError) -> FnsRevisionResult:
    name = type(exc).__name__
    return _empty(
        discover_status=AdapterStatus.FAILED,
        revisions_status=AdapterStatus.BLOCKED,
        limitations=(name,),
        blockers=(name,),
        http_error=name,
    )


def _is_bank_period(period: Mapping[str, Any]) -> bool:
    return period.get("isCb") is True


def _fiscal_year(period: Mapping[str, Any]) -> int | None:
    try:
        return int(str(period.get("period")))
    except (TypeError, ValueError):
        return None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return None


def _identifier(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _scalar(value: object) -> bool:
    return value is not None and not isinstance(value, list | dict)


def _iso_date(value: object) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _content_hash(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
