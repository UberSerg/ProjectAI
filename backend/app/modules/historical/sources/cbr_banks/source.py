"""Wrap the existing CBR CreditOrgInfo SOAP bundle as historical evidence.

Forms:
- CBR-06 form 0409101 — no assets/loans/deposits unless the SOAP parser emits them
- CBR-07 form 0409102 — RAS net profit (symbol 61101) when the parser emits it
- CBR-08 form 0409123 — regulatory own funds (line 000) when the parser emits it
- CBR-09 form 0409135 — N1.0 when the parser emits it

Does not reimplement SOAP and does not write prospective captures.
``known_at`` / ``first_observed_at`` is the observation
clock, never the form's reporting period. CreditOrgInfo SOAP exposes report
dates (``OnDate``, ``DT``) only. PIT stays ``PIT_PROXY`` (or ``RESEARCH_ONLY``
when the form has no metrics). An undocumented element is not a publication
timestamp and is not copied from the fetch clock.
"""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

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
from app.modules.historical.sources.cbr_banks.fixtures import (
    ORIGIN_FIXTURE_NOT_LIVE,
    ORIGIN_INJECTED_FIXTURE,
    ORIGIN_LIVE,
    SBER_SOAP_FIXTURE_NOT_LIVE,
)
from app.modules.intelligence.banks.cbr_soap import (
    KNOWN_AT_POLICY,
    PARSER_VERSION,
    SOAP_URL,
    fetch_cbr_soap_bundle,
    parse_cbr_soap_metrics,
)
from app.modules.intelligence.banks.metrics import is_industrial_ratio_code
from app.modules.intelligence.banks.providers import CBR_CREDIT_ORG_BY_SECID

NORMALIZATION_VERSION = "cbr_banks_historical_v1"
SECID = "SBER"
PIT_PROXY_EVIDENCE = "cbr_reporting_period_not_verified_archive_snapshot"
FORM101_EVIDENCE = "form101_not_in_soap_bundle_assets_loans_deposits_not_proved"
UNDOCUMENTED_PUBLICATION_LIMITATION = "undocumented_publication_element_not_a_publication_timestamp"

# Not CreditOrgInfo fields. The proved SOAP payload has OnDate and DT only,
# and those are report dates. A hit is recorded and is not publication proof.
_UNDOCUMENTED_PUBLICATION_TAGS = frozenset(
    {"PubDate", "PublicationDate", "PublishedAt", "DatePublish", "publication_timestamp"}
)
_BALANCE_METRICS = frozenset({"TOTAL_ASSETS", "LOAN_BOOK", "DEPOSITS"})
_ENVELOPE_SCHEMA = "cbr_banks_soap_bundle_v1"

_FORM_SPECS: tuple[dict[str, Any], ...] = (
    {
        "source_id": "CBR-06",
        "form": "0409101",
        "document_type": "cbr_form_101",
        "soap_op": "Data101FullXML",
        "metric_ids": _BALANCE_METRICS,
        "xml_keys": (),
    },
    {
        "source_id": "CBR-07",
        "form": "0409102",
        "document_type": "cbr_form_102",
        "soap_op": "Data102FormXML",
        "metric_ids": frozenset({"NET_PROFIT"}),
        "xml_keys": ("form102", "form102_enum"),
    },
    {
        "source_id": "CBR-08",
        "form": "0409123",
        "document_type": "cbr_form_123",
        "soap_op": "Data123FormFullXML",
        "metric_ids": frozenset({"EQUITY"}),
        "xml_keys": ("form123",),
    },
    {
        "source_id": "CBR-09",
        "form": "0409135",
        "document_type": "cbr_form_135",
        "soap_op": "Data135FormFullXML",
        "metric_ids": frozenset({"CAPITAL_ADEQUACY"}),
        "xml_keys": ("form135",),
    },
)

_REPORTING_STANDARD = {
    "NET_PROFIT": "RAS_0409102",
    "EQUITY": "CBR_0409123_regulatory_own_funds",
    "CAPITAL_ADEQUACY": "CBR_0409135_N1.0",
    "TOTAL_ASSETS": "CBR_0409101",
    "LOAN_BOOK": "CBR_0409101",
    "DEPOSITS": "CBR_0409101",
}


@dataclass(frozen=True, slots=True)
class CbrBanksBundleResult:
    origin: str
    status: AdapterStatus
    artifacts: tuple[HistoricalArtifact, ...]
    observations: tuple[ParsedObservation, ...]
    raw_by_hash: dict[str, bytes]
    fetch_error: str | None = None


def _dedupe(items: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for item in items if item))


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def _publication_timestamps(xml_chunks: tuple[str, ...]) -> tuple[datetime, ...] | None:
    """Return clocks found on tags that are not CreditOrgInfo fields.

    ``None`` means those tags disagree. An empty tuple means none were present.
    Reporting dates (``OnDate``, ``DT``) are not publication timestamps, and
    neither is any name in ``_UNDOCUMENTED_PUBLICATION_TAGS``.
    """
    found: list[datetime] = []
    for chunk in xml_chunks:
        try:
            root = ET.fromstring(chunk)
        except ET.ParseError:
            continue
        for element in root.iter():
            if _local(element.tag) not in _UNDOCUMENTED_PUBLICATION_TAGS:
                continue
            raw = " ".join((element.text or "").split())
            if "T" not in raw:
                continue
            try:
                parsed = datetime.fromisoformat(raw)
            except ValueError:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            found.append(parsed.astimezone(UTC))
    unique = {item.isoformat(): item for item in found}
    if len(unique) > 1:
        return None
    return tuple(unique.values())


def _metric_float(raw: Any) -> float | None:
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, int | float):
        return float(raw)
    if isinstance(raw, str):
        try:
            return float(raw.replace(" ", "").replace(",", "."))
        except ValueError:
            return None
    return None


def _metric_period(metric: Mapping[str, Any], fallback: date | None) -> date | None:
    raw = metric.get("period_end")
    if isinstance(raw, str) and raw:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return fallback
    return fallback


def _envelope(
    *,
    form: str,
    origin: str,
    observed_at: datetime,
    bundle: Mapping[str, str],
    fetch_error: str | None,
) -> bytes:
    payload = {
        "bundle": {key: bundle.get(key) for key in ("identity", "form123", "form135", "form102", "form102_enum")},
        "fetch_error": fetch_error,
        "form": form,
        "observed_at": observed_at.isoformat(),
        "origin": origin,
        "schema": _ENVELOPE_SCHEMA,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _content_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def wrap_sber_soap_bundle(
    bundle: Mapping[str, str],
    *,
    origin: str,
    observed_at: datetime,
    fetch_error: str | None = None,
) -> CbrBanksBundleResult:
    """Turn one SOAP bundle into per-form artifacts and observations."""
    if observed_at.tzinfo is None:
        raise ValueError("observed_at_must_be_timezone_aware")
    ref = CBR_CREDIT_ORG_BY_SECID[SECID]
    parsed = parse_cbr_soap_metrics(
        form123_xml=bundle.get("form123"),
        form135_xml=bundle.get("form135"),
        form102_xml=bundle.get("form102"),
        form102_enum_xml=bundle.get("form102_enum"),
        identity_xml=bundle.get("identity"),
        expected_regnum=ref.regnum,
        expected_ogrn=ref.ogrn,
    )
    identity = {}
    if parsed.facts:
        identity = dict(parsed.facts[0].get("identity") or {})
    identity_ok = identity.get("checked") is True and "cbr_identity_mismatch" not in parsed.limitations
    identifiers = {
        "secid": ref.secid,
        "regnum": ref.regnum,
        "ogrn": ref.ogrn,
    }
    if identity_ok and identity.get("title"):
        identifiers["title"] = str(identity["title"])

    artifacts: list[HistoricalArtifact] = []
    observations: list[ParsedObservation] = []
    raw_by_hash: dict[str, bytes] = {}
    base_limitations = [
        *parsed.limitations,
        "industrial_fns_ratios_forbidden",
        "partial_not_ready",
        "first_observed_at_is_observation_clock_not_form_period",
    ]
    if origin == ORIGIN_FIXTURE_NOT_LIVE:
        base_limitations.extend(("fixture_not_live", "not_live_history"))
    elif origin == ORIGIN_INJECTED_FIXTURE:
        base_limitations.append("injected_fixture_not_live")
    if fetch_error:
        base_limitations.append(fetch_error)

    for spec in _FORM_SPECS:
        form_metrics = {
            code: value
            for code, value in parsed.metrics.items()
            if code in spec["metric_ids"] and not is_industrial_ratio_code(code)
        }
        xml_chunks = tuple(bundle.get(key) or "" for key in spec["xml_keys"] if bundle.get(key))
        publication_found = _publication_timestamps(xml_chunks) if xml_chunks else ()
        publication: datetime | None = None
        publication_note: str | None = None
        if publication_found is None:
            publication_note = "publication_timestamp_ambiguous"
        elif len(publication_found) == 1:
            publication = publication_found[0]

        periods = {
            period
            for metric in form_metrics.values()
            if isinstance(metric, Mapping)
            for period in [_metric_period(metric, parsed.period_end)]
            if period is not None
        }
        period_end = next(iter(periods)) if len(periods) == 1 else None
        form_limitations = list(base_limitations)
        if len(periods) > 1:
            form_limitations.append("form_period_end_ambiguous")
            period_end = None
        if publication_note:
            form_limitations.append(publication_note)

        pit = PitQuality.PIT_PROXY
        published_at: datetime | None = None
        precision = PublishedAtPrecision.PERIOD_ONLY if period_end is not None else PublishedAtPrecision.UNKNOWN
        availability = PIT_PROXY_EVIDENCE
        saw_undocumented = publication is not None or publication_note == "publication_timestamp_ambiguous"
        if saw_undocumented:
            form_limitations.append(UNDOCUMENTED_PUBLICATION_LIMITATION)
        if spec["form"] == "0409101" and not form_metrics:
            pit = PitQuality.RESEARCH_ONLY
            precision = PublishedAtPrecision.UNKNOWN
            availability = FORM101_EVIDENCE
            form_limitations.append("assets_loans_deposits_absent")
        if publication is not None and period_end is not None and publication.date() == period_end:
            # Same calendar day is allowed. Do not store the report date as a
            # publication timestamp; that would be a chronology error.
            form_limitations.append("publication_timestamp_equals_period_end_not_used")
        if publication is not None and publication == observed_at:
            form_limitations.append("publication_timestamp_equals_fetch_clock_not_used")
        if publication is not None and observed_at < publication:
            form_limitations.append("publication_timestamp_after_first_observed_at_not_used")

        if period_end is not None and period_end == observed_at.date():
            form_limitations.append("period_end_equals_first_observed_at")

        raw = _envelope(
            form=spec["form"],
            origin=origin,
            observed_at=observed_at,
            bundle=bundle,
            fetch_error=fetch_error,
        )
        digest = _content_hash(raw)
        raw_by_hash[digest] = raw
        period_token = period_end.isoformat() if period_end is not None else "absent"
        fetch_status = FetchStatus.OK if form_metrics else FetchStatus.EMPTY
        quality = RecordQuality.QUARANTINE if form_metrics else RecordQuality.UNRESOLVED
        artifact = HistoricalArtifact(
            source_id=spec["source_id"],
            source_url=f"{SOAP_URL}?op={spec['soap_op']}",
            external_document_id=f"{ref.secid}:{ref.regnum}:{spec['form']}:{period_token}:{origin}",
            document_type=spec["document_type"],
            content_hash=digest,
            parser_version=PARSER_VERSION,
            fetch_status=fetch_status,
            first_observed_at=observed_at,
            title=f"{ref.title or ref.secid} {spec['document_type']}",
            entity_identifiers=dict(identifiers),
            reporting_period=period_end.isoformat() if period_end is not None else None,
            period_end=period_end,
            published_at=published_at,
            published_at_precision=precision,
            historical_availability_evidence=availability,
            historical_pit_quality=pit,
            revision_identifier=f"{PARSER_VERSION}:{origin}",
            raw_artifact_reference=f"sha256:{digest}",
            quality_status=quality,
            limitations=_dedupe(form_limitations),
        )
        artifacts.append(artifact)

        for code, metric in sorted(form_metrics.items()):
            if not isinstance(metric, Mapping):
                continue
            value = _metric_float(metric.get("value"))
            if value is None:
                continue
            obs_period = _metric_period(metric, period_end)
            if obs_period is not None and obs_period == observed_at.date():
                continue
            limitations = list(form_limitations)
            if value == 0:
                limitations.append("explicit_zero")
            unit = str(metric["unit"]) if metric.get("unit") else None
            observations.append(
                ParsedObservation(
                    metric_id=code,
                    source_id=spec["source_id"],
                    content_hash=digest,
                    normalization_version=NORMALIZATION_VERSION,
                    quality_status=RecordQuality.QUARANTINE,
                    value=value,
                    unit=unit,
                    currency="RUB" if unit == "thousand_rub" else None,
                    period=obs_period.isoformat() if obs_period is not None else None,
                    period_end=obs_period,
                    reporting_standard=_REPORTING_STANDARD.get(code),
                    issuer_identity=dict(identifiers),
                    evidence=(
                        f"{PARSER_VERSION} form {metric.get('form')} field {metric.get('field')} "
                        f"origin {origin}"
                    ),
                    limitations=_dedupe(limitations),
                    extra={
                        "origin": origin,
                        "form": spec["form"],
                        "field": metric.get("field"),
                        "definition": metric.get("definition"),
                        "known_at": observed_at.isoformat(),
                        "known_at_policy": KNOWN_AT_POLICY,
                        "period_end_is_not_known_at": True,
                        "pit": pit.value,
                        "raw_value": metric.get("value"),
                        "parser_proved": True,
                        "parser_version": PARSER_VERSION,
                    },
                )
            )

    return CbrBanksBundleResult(
        origin=origin,
        status=AdapterStatus.PARTIAL,
        artifacts=tuple(artifacts),
        observations=tuple(observations),
        raw_by_hash=raw_by_hash,
        fetch_error=fetch_error,
    )


class CbrBanksHistoricalSource:
    """Historical adapter for curated SBER CBR forms. Status stays PARTIAL."""

    source_id = "cbr_banks"

    def __init__(
        self,
        *,
        live: bool = False,
        observed_at: datetime | None = None,
        fixtures: Mapping[str, str] | None = None,
        timeout_s: float = 60.0,
    ) -> None:
        if observed_at is not None and observed_at.tzinfo is None:
            raise ValueError("observed_at_must_be_timezone_aware")
        self._live = live
        self._observed_at = observed_at
        self._fixtures = fixtures
        self._timeout_s = timeout_s
        self._result: CbrBanksBundleResult | None = None

    def _clock(self) -> datetime:
        if self._observed_at is not None:
            return self._observed_at
        return datetime.now(UTC)

    def _load(self) -> CbrBanksBundleResult:
        if self._result is not None:
            return self._result
        observed_at = self._clock()
        if self._fixtures is not None:
            origin = (
                ORIGIN_FIXTURE_NOT_LIVE
                if dict(self._fixtures) == SBER_SOAP_FIXTURE_NOT_LIVE
                else ORIGIN_INJECTED_FIXTURE
            )
            self._result = wrap_sber_soap_bundle(
                self._fixtures,
                origin=origin,
                observed_at=observed_at,
            )
            return self._result
        if self._live:
            ref = CBR_CREDIT_ORG_BY_SECID[SECID]
            try:
                bundle = fetch_cbr_soap_bundle(regnum=ref.regnum, timeout_s=self._timeout_s)
            except Exception as exc:  # noqa: BLE001 — failed live fetch must not invent metrics
                fetch_error = f"cbr_soap_fetch_failed:{type(exc).__name__}"
                self._result = wrap_sber_soap_bundle(
                    SBER_SOAP_FIXTURE_NOT_LIVE,
                    origin=ORIGIN_FIXTURE_NOT_LIVE,
                    observed_at=observed_at,
                    fetch_error=fetch_error,
                )
                return self._result
            self._result = wrap_sber_soap_bundle(
                bundle,
                origin=ORIGIN_LIVE,
                observed_at=observed_at,
            )
            return self._result
        self._result = wrap_sber_soap_bundle(
            SBER_SOAP_FIXTURE_NOT_LIVE,
            origin=ORIGIN_FIXTURE_NOT_LIVE,
            observed_at=observed_at,
        )
        return self._result

    def discover(self) -> CoverageReport:
        """Static coverage. Does not fetch."""
        return CoverageReport(
            source_id=self.source_id,
            status=AdapterStatus.PARTIAL,
            earliest=None,
            latest=None,
            formats=tuple(spec["form"] for spec in _FORM_SPECS),
            limitations=(
                "sber_regnum_1481_only",
                "historical_span_not_verified",
                "pit_proxy_creditorginfo_soap_has_no_official_publication_timestamp",
                "form101_assets_loans_deposits_not_proved_by_current_parser",
                "industrial_fns_ratios_forbidden",
                "partial_not_ready",
            ),
        )

    def inspect_coverage(self) -> CoverageReport:
        result = self._load()
        periods = [item.period_end for item in result.artifacts if item.period_end is not None]
        limitations = ["partial_not_ready", f"origin_{result.origin}"]
        if result.fetch_error:
            limitations.append(result.fetch_error)
        if result.origin == ORIGIN_FIXTURE_NOT_LIVE:
            limitations.append("fixture_not_live")
        return CoverageReport(
            source_id=self.source_id,
            status=result.status,
            earliest=min(periods) if periods else None,
            latest=max(periods) if periods else None,
            formats=tuple(spec["form"] for spec in _FORM_SPECS),
            limitations=tuple(dict.fromkeys(limitations)),
        )

    def fetch_sample(self, *, limit: int = 30) -> tuple[HistoricalArtifact, ...]:
        return self._load().artifacts[:limit]

    def fetch_range(self, *, start: date, end: date, limit: int) -> tuple[HistoricalArtifact, ...]:
        if start > end:
            return ()
        chosen = [
            item
            for item in self._load().artifacts
            if item.period_end is None or start <= item.period_end <= end
        ]
        return tuple(chosen[:limit])

    def raw_for(self, artifact: HistoricalArtifact) -> bytes:
        return self._load().raw_by_hash[artifact.content_hash]

    def parse(self, artifact: HistoricalArtifact, raw: bytes) -> tuple[ParsedObservation, ...]:
        if _content_hash(raw) != artifact.content_hash:
            raise ValueError("content_hash_mismatch")
        payload = json.loads(raw.decode("utf-8"))
        if payload.get("schema") != _ENVELOPE_SCHEMA:
            raise ValueError("unexpected_raw_schema")
        if payload.get("form") != _form_of(artifact):
            raise ValueError("raw_form_mismatch")
        observed_at = datetime.fromisoformat(payload["observed_at"])
        if observed_at != artifact.first_observed_at:
            raise ValueError("observed_at_mismatch")
        wrapped = wrap_sber_soap_bundle(
            payload.get("bundle") or {},
            origin=str(payload.get("origin") or ""),
            observed_at=observed_at,
            fetch_error=payload.get("fetch_error"),
        )
        matched = tuple(item for item in wrapped.observations if item.source_id == artifact.source_id)
        if any(item.content_hash != artifact.content_hash for item in matched):
            raise ValueError("reparse_hash_drift")
        return matched

    def validate(self, observations: tuple[ParsedObservation, ...]) -> tuple[ParsedObservation, ...]:
        kept: list[ParsedObservation] = []
        for item in observations:
            if is_industrial_ratio_code(item.metric_id):
                continue
            if item.metric_id in _BALANCE_METRICS and item.extra.get("parser_proved") is not True:
                continue
            if item.quality_errors():
                continue
            known_at = item.extra.get("known_at")
            if (
                item.period_end is not None
                and isinstance(known_at, str)
                and known_at[:10] == item.period_end.isoformat()
            ):
                continue
            kept.append(item)
        return tuple(kept)

    def summary(self) -> dict[str, Any]:
        result = self._load()
        forms: list[dict[str, Any]] = []
        for artifact in result.artifacts:
            parsed = self.parse(artifact, result.raw_by_hash[artifact.content_hash])
            forms.append(
                {
                    "source_id": artifact.source_id,
                    "document_type": artifact.document_type,
                    "fetch_status": artifact.fetch_status.value,
                    "pit": artifact.historical_pit_quality.value,
                    "period_end": artifact.period_end.isoformat() if artifact.period_end else None,
                    "first_observed_at": artifact.first_observed_at.isoformat(),
                    "metrics": [
                        {
                            "metric_id": item.metric_id,
                            "value": item.value,
                            "unit": item.unit,
                        }
                        for item in parsed
                    ],
                }
            )
        return {
            "source_id": self.source_id,
            "status": result.status.value,
            "origin": result.origin,
            "fetch_error": result.fetch_error,
            "forms": forms,
        }


def _form_of(artifact: HistoricalArtifact) -> str:
    for spec in _FORM_SPECS:
        if spec["source_id"] == artifact.source_id:
            return str(spec["form"])
    raise ValueError(f"unknown cbr banks artifact source_id: {artifact.source_id}")
