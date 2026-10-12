"""Bounded FNS GIR BO historical adapter.

Reuses ``FnsGirBoClient`` / ``resolve_fns_identity`` / ``parse_bfo_periods``.
One exact-INN organization, then only the BFO list that endpoint already
returns. No registry crawl, no second HTTP client, no decision-memory writes.

Publication time follows the provider (``datePresent``, else ``actualBfoDate``).
A midnight ``datePresent`` is not a clock timestamp. A later
``publishedCorrectionDate`` keeps the period at ``RESEARCH_ONLY``.
``period_end`` is the fiscal year end and is never the observation time.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import Any

import httpx

from app.modules.fundamentals.infrastructure.fns_gir_bo_provider import (
    FNS_SEARCH_PATH,
    SUPPORT_INDUSTRIAL,
    FnsGirBoClient,
    FnsIdentityResolution,
    FnsOrgHit,
    FnsReportBundle,
    parse_bfo_periods,
    resolve_fns_identity,
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

SOURCE_STATEMENTS = "FNS-01"
SOURCE_IDENTITY = "FNS-02"
PARSER_VERSION = "fns_gir_bo_historical_v1"
NORMALIZATION_VERSION = "fns_ras_okud_lines_v1"
PILOT_INN = "7708004767"
PILOT_SECID = "LKOH"

_RAS_PREFIX = "ras."


@dataclass(frozen=True, slots=True)
class FnsPilotResult:
    status: AdapterStatus
    identity_basis: dict[str, str]
    statement_artifacts: tuple[HistoricalArtifact, ...]
    identity_artifact: HistoricalArtifact | None
    observations: tuple[ParsedObservation, ...]
    periods: tuple[str, ...]
    fact_count: int
    pit: tuple[str, ...]
    http_error: str | None
    limitations: tuple[str, ...]
    blockers: tuple[str, ...]
    raw_by_document_id: dict[str, bytes]


def chronology_problems(artifact: HistoricalArtifact) -> tuple[str, ...]:
    """Domain chronology plus the swarm rule that period end is not observation time."""
    errors = list(artifact.chronology_errors())
    if artifact.period_end is not None and artifact.first_observed_at.date() == artifact.period_end:
        errors.append("period_end_equals_first_observed_at")
    return tuple(errors)


def _canonical_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _content_hash(payload: Any) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _as_utc(value: datetime) -> tuple[datetime, bool]:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC), True
    return value.astimezone(UTC), False


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


def _has_clock(value: datetime) -> bool:
    return (value.hour, value.minute, value.second, value.microsecond) != (0, 0, 0, 0)


def _classify_publication(
    published_at: datetime | None,
    published_correction_date: date | None,
) -> tuple[PitQuality, PublishedAtPrecision, datetime | None, tuple[str, ...], str | None]:
    limitations = ["fns_online_latest_correction_only"]
    if published_at is None:
        return (
            PitQuality.RESEARCH_ONLY,
            PublishedAtPrecision.UNKNOWN,
            None,
            tuple(limitations + ["fns_publication_timestamp_absent"]),
            None,
        )
    aware, anchored = _as_utc(published_at)
    if anchored:
        limitations.append("fns_naive_datetime_anchored_utc")
    clock = _has_clock(aware)
    if clock:
        precision = PublishedAtPrecision.TIMESTAMP
        limitations.append("fns_date_present_timezone_unspecified")
        evidence = "fns_gir_bo.correction.datePresent"
    else:
        precision = PublishedAtPrecision.DATE_ONLY
        limitations.append("fns_publication_timestamp_absent")
        evidence = "fns_gir_bo.correction.datePresent"
    disagrees = published_correction_date is not None and published_correction_date != aware.date()
    if disagrees:
        limitations.append("fns_published_correction_date_differs_from_date_present")
        quality = PitQuality.RESEARCH_ONLY
    else:
        quality = PitQuality.PIT_PROXY
    return quality, precision, aware, tuple(limitations), evidence


def _identity_map(org: FnsOrgHit, secid: str, resolution: FnsIdentityResolution) -> dict[str, str]:
    mapped = {
        "inn": org.inn,
        "fns_org_id": str(org.org_id),
        "secid": secid,
        "support_status": resolution.support_status,
        "mapping_status": resolution.status,
    }
    if org.ogrn:
        mapped["ogrn"] = org.ogrn
    return mapped


def _statement_artifact(
    period: dict[str, Any],
    bundle: FnsReportBundle,
    *,
    identity: dict[str, str],
    observed_at: datetime,
    title: str | None,
) -> HistoricalArtifact:
    published_correction = _iso_date(period.get("publishedCorrectionDate"))
    quality, precision, published_at, limitations, evidence = _classify_publication(
        bundle.published_at,
        published_correction,
    )
    if published_correction is not None:
        limitations = (*limitations, f"published_correction_date:{published_correction.isoformat()}")
    year = bundle.report.period_end.year
    bfo_id = period.get("id")
    correction_id = bundle.metadata.get("fns_correction_id")
    artifact = HistoricalArtifact(
        source_id=SOURCE_STATEMENTS,
        source_url=bundle.source_url or "",
        external_document_id=f"bfo:{bfo_id}",
        document_type="fns_bfo_ras",
        content_hash=_content_hash(period),
        parser_version=PARSER_VERSION,
        fetch_status=FetchStatus.OK,
        first_observed_at=observed_at,
        title=title,
        entity_identifiers=dict(identity),
        reporting_period=f"FY:{year}",
        period_end=bundle.report.period_end,
        published_at=published_at,
        published_at_precision=precision,
        historical_availability_evidence=evidence,
        historical_pit_quality=quality,
        revision_identifier=str(correction_id) if correction_id is not None else None,
        quality_status=RecordQuality.ACCEPTED,
        limitations=limitations,
    )
    if chronology_problems(artifact):
        artifact = replace(artifact, quality_status=RecordQuality.QUARANTINE)
    return artifact


def _statement_observations(
    bundle: FnsReportBundle,
    artifact: HistoricalArtifact,
    identity: dict[str, str],
) -> tuple[ParsedObservation, ...]:
    observations: list[ParsedObservation] = []
    for fact in bundle.facts:
        limitations = tuple(artifact.limitations)
        if fact.value == 0 and "explicit_zero" not in limitations:
            limitations = (*limitations, "explicit_zero")
        observations.append(
            ParsedObservation(
                metric_id=f"{_RAS_PREFIX}{fact.metric_code}",
                source_id=SOURCE_STATEMENTS,
                content_hash=artifact.content_hash,
                normalization_version=NORMALIZATION_VERSION,
                quality_status=artifact.quality_status,
                value=fact.value,
                unit=fact.unit_scale,
                currency=fact.currency,
                period=artifact.reporting_period,
                period_end=artifact.period_end,
                reporting_standard="RAS",
                issuer_identity=dict(identity),
                evidence=fact.source_metric_name or None,
                limitations=limitations,
                extra={"fns_bfo_id": str(bundle.metadata.get("fns_bfo_id") or "")},
            )
        )
    return tuple(observations)


def _identity_records(
    org: FnsOrgHit,
    identity: dict[str, str],
    *,
    observed_at: datetime,
    client: FnsGirBoClient,
) -> tuple[HistoricalArtifact, ParsedObservation]:
    payload = {"inn": org.inn, "ogrn": org.ogrn, "fns_org_id": org.org_id}
    limitations = (
        "fns_search_snapshot_has_no_publication_timestamp",
        "ogrn_from_fns_search_hit",
        "identity_basis_exact_inn",
    )
    artifact = HistoricalArtifact(
        source_id=SOURCE_IDENTITY,
        source_url=f"{client.base_url}{FNS_SEARCH_PATH}?query={org.inn}",
        external_document_id=f"org:{org.org_id}",
        document_type="fns_org_identity",
        content_hash=_content_hash(payload),
        parser_version=PARSER_VERSION,
        fetch_status=FetchStatus.OK,
        first_observed_at=observed_at,
        title=org.short_name,
        entity_identifiers=dict(identity),
        published_at_precision=PublishedAtPrecision.UNKNOWN,
        historical_pit_quality=PitQuality.RESEARCH_ONLY,
        quality_status=RecordQuality.ACCEPTED,
        limitations=limitations,
    )
    observation = ParsedObservation(
        metric_id="issuer.identity",
        source_id=SOURCE_IDENTITY,
        content_hash=artifact.content_hash,
        normalization_version=NORMALIZATION_VERSION,
        quality_status=RecordQuality.ACCEPTED,
        issuer_identity=dict(identity),
        evidence="fns_advanced_search_exact_inn",
        limitations=limitations,
    )
    return artifact, observation


def _empty_result(
    *,
    status: AdapterStatus,
    limitations: tuple[str, ...],
    blockers: tuple[str, ...],
    http_error: str | None = None,
    identity_basis: dict[str, str] | None = None,
    identity_artifact: HistoricalArtifact | None = None,
    observations: tuple[ParsedObservation, ...] = (),
) -> FnsPilotResult:
    return FnsPilotResult(
        status=status,
        identity_basis=dict(identity_basis or {}),
        statement_artifacts=(),
        identity_artifact=identity_artifact,
        observations=observations,
        periods=(),
        fact_count=0,
        pit=(),
        http_error=http_error,
        limitations=limitations,
        blockers=blockers,
        raw_by_document_id={},
    )


def _http_error_result(exc: httpx.HTTPStatusError) -> FnsPilotResult:
    code = exc.response.status_code
    http_error = f"HTTP {code}"
    return _empty_result(
        status=AdapterStatus.BLOCKED,
        limitations=(f"http_{code}", "live_call_blocked"),
        blockers=(http_error,),
        http_error=http_error,
    )


class FnsGirBoHistoricalSource:
    """FNS-01 report pilot and FNS-02 exact-INN identity map for one organization."""

    source_id = SOURCE_STATEMENTS

    def __init__(
        self,
        client: FnsGirBoClient | None = None,
        *,
        inn: str = PILOT_INN,
        secid: str = PILOT_SECID,
        observed_at: datetime | None = None,
        fixture_origin: str | None = None,
    ) -> None:
        self.client = client or FnsGirBoClient()
        self._owns_client = client is None
        self.inn = inn
        self.secid = secid.upper()
        self.observed_at = observed_at or datetime.now(UTC)
        self.fixture_origin = fixture_origin
        self._result: FnsPilotResult | None = None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def run(self) -> FnsPilotResult:
        if self._result is None:
            try:
                self._result = self._execute()
            finally:
                self.close()
        return self._result

    def discover(self) -> CoverageReport:
        result = self.run()
        ends = [item.period_end for item in result.statement_artifacts if item.period_end is not None]
        return CoverageReport(
            source_id=self.source_id,
            status=result.status,
            earliest=min(ends) if ends else None,
            latest=max(ends) if ends else None,
            formats=("application/json",),
            limitations=result.limitations,
        )

    def inspect_coverage(self) -> CoverageReport:
        return self.discover()

    def fetch_sample(self, *, limit: int = 30) -> tuple[HistoricalArtifact, ...]:
        return self.run().statement_artifacts[:limit]

    def fetch_range(self, *, start: date, end: date, limit: int) -> tuple[HistoricalArtifact, ...]:
        selected = [
            item
            for item in self.run().statement_artifacts
            if item.period_end is not None and start <= item.period_end <= end
        ]
        return tuple(selected[:limit])

    def parse(self, artifact: HistoricalArtifact, raw: bytes) -> tuple[ParsedObservation, ...]:
        if artifact.document_type == "fns_org_identity":
            return _parse_identity(artifact)
        period = json.loads(raw.decode("utf-8"))
        if not isinstance(period, dict):
            return ()
        org_id = int(artifact.entity_identifiers.get("fns_org_id") or 0)
        bundles = parse_bfo_periods([period], issuer_id=0, org_id=org_id)
        if not bundles:
            return ()
        digest = _content_hash(period)
        observations = _statement_observations(bundles[0], artifact, dict(artifact.entity_identifiers))
        if digest != artifact.content_hash:
            return tuple(
                replace(
                    item,
                    quality_status=RecordQuality.QUARANTINE,
                    limitations=(*item.limitations, "content_hash_mismatch"),
                )
                for item in observations
            )
        return observations

    def validate(self, observations: tuple[ParsedObservation, ...]) -> tuple[ParsedObservation, ...]:
        checked: list[ParsedObservation] = []
        for item in observations:
            if item.quality_errors():
                checked.append(replace(item, quality_status=RecordQuality.QUARANTINE))
            else:
                checked.append(item)
        return tuple(checked)

    def _execute(self) -> FnsPilotResult:
        if self.observed_at.tzinfo is None:
            return _empty_result(
                status=AdapterStatus.FAILED,
                limitations=("first_observed_at_must_be_timezone_aware",),
                blockers=("first_observed_at_must_be_timezone_aware",),
            )
        try:
            resolution = resolve_fns_identity(self.client, inn=self.inn, secid=self.secid)
        except httpx.HTTPStatusError as exc:
            return _http_error_result(exc)
        except httpx.HTTPError as exc:
            name = type(exc).__name__
            return _empty_result(
                status=AdapterStatus.FAILED,
                limitations=(name,),
                blockers=(name,),
                http_error=name,
            )

        if resolution.support_status != SUPPORT_INDUSTRIAL or resolution.org is None:
            reason = resolution.reason or resolution.support_status
            return _empty_result(
                status=AdapterStatus.PARTIAL,
                identity_basis={
                    "inn": self.inn,
                    "secid": self.secid,
                    "support_status": resolution.support_status,
                    "mapping_status": resolution.status,
                },
                limitations=(reason, "industrial_ratios_not_emitted"),
                blockers=(reason,),
            )

        org = resolution.org
        identity = _identity_map(org, self.secid, resolution)
        try:
            periods = self.client.fetch_bfo(org.org_id)
        except httpx.HTTPStatusError as exc:
            identity_artifact, identity_observation = _identity_records(
                org, identity, observed_at=self.observed_at, client=self.client
            )
            blocked = _http_error_result(exc)
            return replace(
                blocked,
                identity_basis=identity,
                identity_artifact=identity_artifact,
                observations=(identity_observation,),
            )
        except httpx.HTTPError as exc:
            name = type(exc).__name__
            return _empty_result(
                status=AdapterStatus.FAILED,
                identity_basis=identity,
                limitations=(name,),
                blockers=(name,),
                http_error=name,
            )

        identity_artifact, identity_observation = _identity_records(
            org, identity, observed_at=self.observed_at, client=self.client
        )
        statements: list[HistoricalArtifact] = []
        observations: list[ParsedObservation] = [identity_observation]
        raw_by_document_id: dict[str, bytes] = {}
        bundles = parse_bfo_periods(periods, issuer_id=0, org_id=org.org_id)
        bundles_by_bfo = {str(item.metadata.get("fns_bfo_id")): item for item in bundles}
        for period in periods:
            if not isinstance(period, dict):
                continue
            bundle = bundles_by_bfo.get(str(period.get("id")))
            if bundle is None:
                continue
            artifact = _statement_artifact(
                period,
                bundle,
                identity=identity,
                observed_at=self.observed_at,
                title=org.short_name,
            )
            raw = _canonical_bytes(period)
            raw_by_document_id[artifact.external_document_id] = raw
            statements.append(artifact)
            observations.extend(_statement_observations(bundle, artifact, identity))

        statements_sorted = tuple(sorted(statements, key=lambda item: item.period_end or date.min))
        ras = [item for item in observations if item.metric_id.startswith(_RAS_PREFIX)]
        pit = tuple(sorted({item.historical_pit_quality.value for item in statements_sorted}))
        periods_out = tuple(artifact.reporting_period or "" for artifact in statements_sorted)
        notes = ["single_org_pilot_no_registry_crawl", "industrial_ras_only_banks_excluded"]
        for artifact in statements_sorted:
            notes.extend(artifact.limitations)
        chronology_blockers = tuple(
            f"{artifact.external_document_id}:{error}"
            for artifact in statements_sorted
            for error in chronology_problems(artifact)
        )
        status = AdapterStatus.READY
        blockers: tuple[str, ...] = ()
        if not statements_sorted:
            status = AdapterStatus.PARTIAL
            blockers = ("no_statements_in_org_bfo",)
        elif chronology_blockers:
            status = AdapterStatus.PARTIAL
            blockers = chronology_blockers
        elif not _origin_can_claim_ready(self.fixture_origin, self.client):
            status = AdapterStatus.PENDING
            mark = self.fixture_origin or "unmarked"
            notes.append(f"{mark}_fixture_cannot_claim_ready")
            blockers = (f"{mark}_fixture_cannot_claim_ready",)
        return FnsPilotResult(
            status=status,
            identity_basis=identity,
            statement_artifacts=statements_sorted,
            identity_artifact=identity_artifact,
            observations=tuple(observations),
            periods=periods_out,
            fact_count=len(ras),
            pit=pit,
            http_error=None,
            limitations=tuple(dict.fromkeys(notes)),
            blockers=blockers,
            raw_by_document_id=raw_by_document_id,
        )


def _origin_can_claim_ready(origin: str | None, client: FnsGirBoClient) -> bool:
    """Captured live payload may be READY offline. A mock transport must not impersonate live HTTP."""
    if origin == "live_capture":
        return True
    if origin != "live_http":
        return False
    inner = getattr(client, "_client", None)
    transport = getattr(inner, "_transport", None)
    return not isinstance(transport, httpx.MockTransport)


def _parse_identity(artifact: HistoricalArtifact) -> tuple[ParsedObservation, ...]:
    if not artifact.entity_identifiers.get("inn"):
        return ()
    return (
        ParsedObservation(
            metric_id="issuer.identity",
            source_id=SOURCE_IDENTITY,
            content_hash=artifact.content_hash,
            normalization_version=NORMALIZATION_VERSION,
            quality_status=RecordQuality.ACCEPTED,
            issuer_identity=dict(artifact.entity_identifiers),
            evidence="fns_advanced_search_exact_inn",
            limitations=artifact.limitations,
        ),
    )

