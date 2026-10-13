"""One document from raw bytes to a durable checkpoint.

Order is fixed: hash the body, write it, then parse, validate, import, and
only then move the cursor. A failed parse or a failed import leaves the
cursor where it was. The whole body is parsed. A stage budget may commit
only a prefix; the checkpoint stores that intra-document offset, and a later
pass over the same bytes imports the tail without a second fact for an
observation that was already stored.

``RESEARCH_ONLY`` artifacts are stored and imported as quarantine when
``strict_pit`` is on. They are not accepted facts. ``first_observed_at`` is
taken from the artifact and is never copied from ``period_end``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from app.modules.historical.application.import_facts import (
    FactRevisionStore,
    ImportAction,
    ImportOutcome,
    SourceRevision,
)
from app.modules.historical.application.pit_policy import apply_pit_policy
from app.modules.historical.application.validate import validate_observation
from app.modules.historical.domain.evidence import (
    FetchStatus,
    HistoricalArtifact,
    ParsedObservation,
    RecordQuality,
)
from app.modules.historical.infrastructure.checkpoint_store import STAGE_LIMITS, CheckpointStore
from app.modules.historical.infrastructure.raw_store import RawArtifactStore, RawIntegrityError, content_hash

RESEARCH_ONLY_EXCLUDED = "research_only_excluded_from_strict_replay"

ParseDocument = Callable[[HistoricalArtifact, bytes], Sequence[ParsedObservation]]


@dataclass(frozen=True, slots=True)
class IngestResult:
    """One raw body. Observation counts are not artifact counts."""

    content_hash: str
    raw_stored: bool
    checkpoint_advanced: bool
    cursor: str | None
    inserted: int
    skipped: int
    accepted_inserted: int
    quarantined_inserted: int
    stop_reason: str | None
    outcomes: tuple[ImportOutcome, ...]
    document_offset: int | None
    document_complete: bool


def commit_fetched(
    *,
    raw_store: RawArtifactStore,
    facts: FactRevisionStore,
    checkpoints: CheckpointStore,
    raw: bytes,
    artifacts: Sequence[HistoricalArtifact],
    parse: ParseDocument,
    stage: str,
    run_new_items: int,
    next_cursor: str,
    strict_pit: bool = True,
    normalization_version: str | None = None,
    pit_mode: str = "research",
    partition: str = "",
) -> IngestResult:
    """Persist ``raw`` before parsing it, then import the uncommitted tail.

    ``pit_mode="verified"`` quarantines anything that is not PIT_VERIFIED.
    ``pit_mode="research"`` may accept PIT_PROXY and still stores that label.
    ``partition`` is forwarded to the checkpoint.
    """
    if not artifacts:
        raise ValueError("at least one artifact is required")
    source_ids = {artifact.source_id for artifact in artifacts}
    if len(source_ids) != 1:
        raise ValueError("one raw body must belong to one source")
    digest = content_hash(raw)
    for artifact in artifacts:
        if artifact.content_hash != digest:
            raise RawIntegrityError("artifact content hash does not match the raw body")
        _require_observed_clock(artifact)

    raw_store.put(digest, raw)
    if any(artifact.fetch_status is not FetchStatus.OK for artifact in artifacts):
        return _stopped(digest, "fetch_not_ok")

    parsed: list[tuple[HistoricalArtifact, ParsedObservation]] = []
    for artifact in artifacts:
        for observation in parse(artifact, raw):
            parsed.append((artifact, observation))
    if not parsed:
        return _stopped(digest, "no_observations")

    source_id = artifacts[0].source_id
    progress = checkpoints.document_progress(source_id, digest, partition=partition)
    if normalization_version is None and progress is not None and progress.complete:
        return _paused(
            digest,
            document_offset=max(int(progress.committed), len(parsed)),
            document_complete=True,
        )

    if stage not in STAGE_LIMITS:
        raise ValueError(f"unknown backfill stage: {stage}")
    remaining = STAGE_LIMITS[stage] - run_new_items
    if remaining <= 0:
        return _stopped(digest, "stage_budget_exhausted")

    already = 0 if progress is None or normalization_version is not None else int(progress.committed)
    selected = parsed[already : already + remaining]
    if not selected:
        return _paused(
            digest,
            document_offset=already,
            document_complete=already >= len(parsed),
        )

    items = tuple(
        _prepare(artifact, observation, strict_pit, normalization_version, pit_mode)
        for artifact, observation in selected
    )
    outcomes = facts.import_all(items)
    inserted = sum(1 for outcome in outcomes if outcome.action is ImportAction.INSERTED)
    skipped = sum(1 for outcome in outcomes if outcome.action is ImportAction.SKIPPED)
    accepted = sum(1 for outcome in outcomes if outcome.counted_as_accepted)
    quarantined = inserted - accepted
    document_offset = already + len(selected)
    document_complete = document_offset >= len(parsed)
    cursor = next_cursor if document_complete else f"{digest[:12]}:{document_offset}"
    document_accepted = any(outcome.quality_status is RecordQuality.ACCEPTED for outcome in outcomes)
    checkpoints.advance_after_commit(
        source_id,
        digest,
        cursor,
        document_accepted,
        stage,
        run_new_items=run_new_items + inserted,
        partition=partition,
        document_offset=document_offset,
        document_complete=document_complete,
    )
    return IngestResult(
        content_hash=digest,
        raw_stored=True,
        checkpoint_advanced=True,
        cursor=cursor,
        inserted=inserted,
        skipped=skipped,
        accepted_inserted=accepted,
        quarantined_inserted=quarantined,
        stop_reason=None,
        outcomes=outcomes,
        document_offset=document_offset,
        document_complete=document_complete,
    )


def _prepare(
    artifact: HistoricalArtifact,
    observation: ParsedObservation,
    strict_pit: bool,
    normalization_version: str | None,
    pit_mode: str,
) -> tuple[ParsedObservation, SourceRevision]:
    checked = validate_observation(artifact, observation)
    if checked.content_hash != artifact.content_hash:
        limitations = checked.limitations
        if "content_hash_mismatch" not in limitations:
            limitations = (*limitations, "content_hash_mismatch")
        checked = replace(
            checked,
            content_hash=artifact.content_hash,
            quality_status=RecordQuality.QUARANTINE,
            limitations=limitations,
        )
    if normalization_version is not None:
        checked = replace(checked, normalization_version=normalization_version)
    if pit_mode == "verified" or (strict_pit and pit_mode == "research"):
        checked = apply_pit_policy(
            checked,
            artifact,
            mode="verified" if pit_mode == "verified" else "research",
        )
    elif pit_mode != "research":
        raise ValueError(f"unknown pit mode: {pit_mode}")
    identifier = (artifact.revision_identifier or artifact.external_document_id).strip()
    if not identifier:
        raise ValueError("revision identifier is required")
    revision = SourceRevision(
        revision_identifier=identifier,
        first_observed_at=artifact.first_observed_at,
        published_at=artifact.published_at,
        published_at_precision=artifact.published_at_precision,
        historical_pit_quality=artifact.historical_pit_quality.value,
        pit_evidence=artifact.historical_availability_evidence,
    )
    return checked, revision


def _require_observed_clock(artifact: HistoricalArtifact) -> None:
    observed = artifact.first_observed_at
    if observed.tzinfo is None or observed.tzinfo.utcoffset(observed) is None:
        raise ValueError("first_observed_at must be timezone-aware")


def _stopped(digest: str, reason: str) -> IngestResult:
    return IngestResult(
        content_hash=digest,
        raw_stored=True,
        checkpoint_advanced=False,
        cursor=None,
        inserted=0,
        skipped=0,
        accepted_inserted=0,
        quarantined_inserted=0,
        stop_reason=reason,
        outcomes=(),
        document_offset=None,
        document_complete=False,
    )


def _paused(
    digest: str,
    *,
    document_offset: int,
    document_complete: bool,
) -> IngestResult:
    return IngestResult(
        content_hash=digest,
        raw_stored=True,
        checkpoint_advanced=False,
        cursor=None,
        inserted=0,
        skipped=0,
        accepted_inserted=0,
        quarantined_inserted=0,
        stop_reason=None,
        outcomes=(),
        document_offset=document_offset,
        document_complete=document_complete,
    )
