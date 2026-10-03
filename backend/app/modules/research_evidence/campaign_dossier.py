"""Prospective Evidence Snapshot V1 + immutable EvidenceDossierV1.

Reuses ProspectiveEvidenceV1 / map_prospective_ui: captures are not matured proof,
horizons stay 5/20/60, forward freshness is separate, no combined accuracy.

Does not write Personal Decision Memory. Official outcome refresh is optional and
off unless the caller injects an existing refresh callable (tests must not).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.modules.memory.domain.decision_memory import HORIZONS
from app.modules.prediction.infrastructure.artifacts import write_json
from app.modules.research_evidence.bundle import RUNTIME_TIMESTAMP_KEYS, payload_file_hash
from app.modules.research_evidence.experiment import EVALUATION_WORDING, fingerprint_identity
from app.modules.research_evidence.overview_map import FORBIDDEN_OVERVIEW_KEYS, map_prospective_ui
from app.modules.research_evidence.paths import research_evidence_root
from app.modules.research_evidence.prospective import PROSPECTIVE_EVIDENCE_VERSION, build_prospective_evidence_v1

EVIDENCE_DOSSIER_VERSION = "EvidenceDossierV1"
PROSPECTIVE_SNAPSHOT_VERSION = "ProspectiveEvidenceSnapshotV1"
# Public/UI campaign name. Frozen identity hash uses campaign_contract.CAMPAIGN_VERSION.
CAMPAIGN_VERSION = "CanonicalEvidenceCampaignV1"
DOSSIER_FILENAME = "evidence_dossier.json"

STATUS_COMPLETE = "COMPLETE"
STATUS_PARTIAL = "PARTIAL"
STATUS_BLOCKED = "BLOCKED"
STATUS_INSUFFICIENT = "INSUFFICIENT"
STATUS_OBSERVED = "OBSERVED"
STATUS_INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
STATUS_EMPTY = "EMPTY"
STATUS_PENDING = "PENDING"
OWNER_INCOMPLETE = "EVIDENCE_INCOMPLETE"
OWNER_DOSSIER_COMPLETE = "EVIDENCE_DOSSIER_COMPLETE"

DOSSIER_SECTION_KEYS: tuple[str, ...] = (
    "identity",
    "data_snapshot",
    "dataset_pair",
    "historical_oos",
    "ablation",
    "stability",
    "economics_primary",
    "economics_robustness",
    "prospective",
    "limitations",
    "evidence_completeness",
)

FORBIDDEN_DOSSIER_KEYS = frozenset(
    {
        *FORBIDDEN_OVERVIEW_KEYS,
        "accuracy",
        "winner",
        "combined_score",
        "alpha_score",
    }
)

DEFAULT_LIMITATIONS: tuple[str, ...] = (
    "NO_COMBINED_MASTER_SCORE",
    "NOT_KRAKEN_ACCURACY",
    "NO_V4_WINNER_VERDICT",
    "NO_CANDIDATE_PROMOTION",
    "OWNER_REVIEW_STATE_IS_NOT_PROMOTION",
    "PROSPECTIVE_SEPARATE_FROM_HISTORICAL_OOS",
    "CAPTURES_ARE_NOT_MATURED_EVIDENCE",
    "CONFIRMED_OPERATION_LINK_IS_METADATA_ONLY",
    "PRICE_RETURN_UNADJUSTED_FOR_DIVIDENDS_AND_SPLITS",
    "CHRONOLOGICAL_OOS_RESEARCH_NOT_PRISTINE_HOLDOUT",
    EVALUATION_WORDING,
)


class DossierImmutabilityError(ValueError):
    """Refuse silent overwrite of a completed dossier with different semantics."""


def _strip_runtime(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            key: _strip_runtime(value)
            for key, value in obj.items()
            if key not in RUNTIME_TIMESTAMP_KEYS
        }
    if isinstance(obj, list):
        return [_strip_runtime(item) for item in obj]
    return obj


def _drop_forbidden_keys(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            key: _drop_forbidden_keys(value)
            for key, value in obj.items()
            if str(key) not in FORBIDDEN_DOSSIER_KEYS
        }
    if isinstance(obj, list):
        return [_drop_forbidden_keys(item) for item in obj]
    return obj


def _part_status(part: Any) -> str | None:
    if not isinstance(part, dict) or not part:
        return None
    status = part.get("status")
    return status if isinstance(status, str) and status else None


def _executed(part: Any) -> bool:
    status = _part_status(part)
    return isinstance(part, dict) and bool(part) and status != STATUS_PENDING


def fingerprint_campaign_identity(identity: dict[str, Any]) -> str:
    """SHA-256 of canonical semantic identity (runtime timestamps excluded)."""
    return fingerprint_identity(_strip_runtime(identity))


def campaign_artifact_dir(fingerprint: str, *, root: Path | None = None) -> Path:
    return research_evidence_root(root) / "campaigns" / fingerprint


def on_disk_semantic_hash(payload: Any, *, tmp_path: Path) -> str:
    """#76 hash: write JSON (NaN/Inf → disk null), hash the file after stripping timestamps."""
    tmp_path = Path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "on_disk_hash.json"
    write_json(path, payload)
    disk = json.loads(path.read_text(encoding="utf-8"))
    return payload_file_hash(disk)


def dossier_file_hash(path: Path) -> str:
    disk = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload_file_hash(disk)


def build_prospective_snapshot_v1(
    *,
    memory_session: Session | None = None,
    core_session: Session | None = None,
    portfolio_id: int | None = None,
    official_refresh: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Read-only prospective snapshot. Empty matured evidence is a valid result."""
    if official_refresh is not None:
        official_refresh()
    raw = build_prospective_evidence_v1(
        memory_session=memory_session,
        core_session=core_session,
        portfolio_id=portfolio_id,
    )
    ui = map_prospective_ui(raw)
    pdm = ui.get("personal_decision_memory") if isinstance(ui.get("personal_decision_memory"), dict) else {}
    horizons = pdm.get("horizons") if isinstance(pdm.get("horizons"), list) else []
    horizon_sessions = [row.get("horizon_sessions") for row in horizons if isinstance(row, dict)]
    return {
        "schema": PROSPECTIVE_SNAPSHOT_VERSION,
        "source_schema": PROSPECTIVE_EVIDENCE_VERSION,
        "status": ui.get("status"),
        "empty": bool(ui.get("empty")),
        "notes": ui.get("notes"),
        "personal_decision_memory": ui.get("personal_decision_memory"),
        "forward_predictions": ui.get("forward_predictions"),
        "horizon_contract": list(HORIZONS),
        "horizons_present": horizon_sessions == list(HORIZONS) or set(horizon_sessions) >= set(HORIZONS),
        "limitations": list(raw.get("limitations") or []),
    }


def classify_prospective_completeness(prospective: dict[str, Any] | None) -> str:
    """Captures ≠ matured. OBSERVED only when a horizon/forward sample actually matured enough."""
    if not isinstance(prospective, dict) or not prospective:
        return STATUS_EMPTY
    pdm = prospective.get("personal_decision_memory")
    if not isinstance(pdm, dict):
        pdm = {}
    fwd = prospective.get("forward_predictions")
    if not isinstance(fwd, dict):
        fwd = {}
    captures = int(pdm.get("captures_total") or 0)
    horizons = pdm.get("horizons") if isinstance(pdm.get("horizons"), list) else []
    matured_pdm = 0
    observed = False
    insufficient = False
    for row in horizons:
        if not isinstance(row, dict):
            continue
        matured_pdm += int(row.get("matured_count") or 0)
        status = row.get("status")
        price = row.get("price_return") if isinstance(row.get("price_return"), dict) else {}
        price_status = price.get("status")
        if status == STATUS_OBSERVED or price_status == STATUS_OBSERVED:
            observed = True
        if status == STATUS_INSUFFICIENT_SAMPLE or price_status == STATUS_INSUFFICIENT_SAMPLE:
            insufficient = True
    freshness = fwd.get("freshness") if isinstance(fwd.get("freshness"), dict) else {}
    fwd_matured = int(freshness.get("matured_count") or 0)
    expected = fwd.get("expected_return") if isinstance(fwd.get("expected_return"), dict) else {}
    ranking = fwd.get("ranking_score") if isinstance(fwd.get("ranking_score"), dict) else {}
    if expected.get("status") == STATUS_OBSERVED or ranking.get("status") == STATUS_OBSERVED:
        observed = True
    if prospective.get("empty") is True and captures == 0 and matured_pdm == 0 and fwd_matured == 0:
        return STATUS_EMPTY
    if observed:
        return STATUS_OBSERVED
    if captures > 0 or matured_pdm > 0 or fwd_matured > 0 or insufficient:
        return STATUS_INSUFFICIENT_SAMPLE
    if prospective.get("status") == STATUS_EMPTY or prospective.get("empty") is True:
        return STATUS_EMPTY
    return STATUS_EMPTY


def classify_data_integrity(data_snapshot: Any) -> str:
    if not _executed(data_snapshot):
        return STATUS_BLOCKED
    status = _part_status(data_snapshot)
    if status in {STATUS_COMPLETE, STATUS_PARTIAL, STATUS_BLOCKED}:
        return status
    nested = data_snapshot.get("DATA_INTEGRITY") if isinstance(data_snapshot, dict) else None
    if nested in {STATUS_COMPLETE, STATUS_PARTIAL, STATUS_BLOCKED}:
        return str(nested)
    return STATUS_PARTIAL


def classify_historical_oos(historical_oos: Any, dataset_pair: Any = None) -> str:
    pair_status = _part_status(dataset_pair)
    if pair_status in {"FAIR_CONTRACT_FAIL", STATUS_BLOCKED}:
        return STATUS_BLOCKED
    if not _executed(historical_oos):
        return STATUS_BLOCKED
    status = _part_status(historical_oos)
    if status in {STATUS_COMPLETE, STATUS_INSUFFICIENT, STATUS_BLOCKED}:
        return status
    if status in {STATUS_INSUFFICIENT_SAMPLE, "INSUFFICIENT_SAMPLE"}:
        return STATUS_INSUFFICIENT
    if status == STATUS_PARTIAL:
        return STATUS_INSUFFICIENT
    return STATUS_COMPLETE


def classify_economics(economics_primary: Any, economics_robustness: Any) -> str:
    primary_status = _part_status(economics_primary)
    robust_status = _part_status(economics_robustness)
    if not _executed(economics_primary) and not _executed(economics_robustness):
        return STATUS_INSUFFICIENT
    statuses = {s for s in (primary_status, robust_status) if s}
    if STATUS_PARTIAL in statuses:
        return STATUS_PARTIAL
    if STATUS_INSUFFICIENT in statuses:
        return STATUS_INSUFFICIENT
    if not _executed(economics_primary) or not _executed(economics_robustness):
        return STATUS_PARTIAL
    if primary_status == STATUS_COMPLETE and robust_status == STATUS_COMPLETE:
        return STATUS_COMPLETE
    if primary_status in {None, STATUS_PENDING}:
        return STATUS_INSUFFICIENT
    return STATUS_PARTIAL


def classify_owner_review_state(
    *,
    data_snapshot: Any,
    dataset_pair: Any,
    historical_oos: Any,
    economics_primary: Any,
    economics_robustness: Any,
    prospective: Any,
) -> str:
    """Dossier complete = planned sections executed. Never means promote a Candidate."""
    planned_ok = (
        _executed(data_snapshot)
        and (_executed(dataset_pair) or _executed(historical_oos))
        and _executed(historical_oos)
        and _executed(economics_primary)
        and _executed(economics_robustness)
        and isinstance(prospective, dict)
        and bool(prospective)
    )
    return OWNER_DOSSIER_COMPLETE if planned_ok else OWNER_INCOMPLETE


def build_evidence_completeness(
    *,
    data_snapshot: Any,
    dataset_pair: Any,
    historical_oos: Any,
    economics_primary: Any,
    economics_robustness: Any,
    prospective: Any,
) -> dict[str, str]:
    return {
        "DATA_INTEGRITY": classify_data_integrity(data_snapshot),
        "HISTORICAL_OOS": classify_historical_oos(historical_oos, dataset_pair),
        "ECONOMICS": classify_economics(economics_primary, economics_robustness),
        "PROSPECTIVE": classify_prospective_completeness(
            prospective if isinstance(prospective, dict) else None
        ),
        "OWNER_REVIEW_STATE": classify_owner_review_state(
            data_snapshot=data_snapshot,
            dataset_pair=dataset_pair,
            historical_oos=historical_oos,
            economics_primary=economics_primary,
            economics_robustness=economics_robustness,
            prospective=prospective,
        ),
    }


def build_evidence_dossier_v1(
    *,
    identity: dict[str, Any] | None = None,
    data_snapshot: dict[str, Any] | None = None,
    dataset_pair: dict[str, Any] | None = None,
    historical_oos: dict[str, Any] | None = None,
    ablation: dict[str, Any] | None = None,
    stability: dict[str, Any] | None = None,
    economics_primary: dict[str, Any] | None = None,
    economics_robustness: dict[str, Any] | None = None,
    prospective: dict[str, Any] | None = None,
    limitations: list[Any] | None = None,
    memory_session: Session | None = None,
    core_session: Session | None = None,
    portfolio_id: int | None = None,
    official_refresh: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    ident = dict(identity or {})
    if "campaign_version" not in ident:
        ident["campaign_version"] = CAMPAIGN_VERSION
    fingerprint = fingerprint_campaign_identity(ident)

    if prospective is None:
        prospective = build_prospective_snapshot_v1(
            memory_session=memory_session,
            core_session=core_session,
            portfolio_id=portfolio_id,
            official_refresh=official_refresh,
        )

    data_snapshot = data_snapshot if isinstance(data_snapshot, dict) else {"status": STATUS_PENDING}
    dataset_pair = dataset_pair if isinstance(dataset_pair, dict) else {"status": STATUS_PENDING}
    historical_oos = historical_oos if isinstance(historical_oos, dict) else {"status": STATUS_PENDING}
    ablation = ablation if isinstance(ablation, dict) else {"status": STATUS_PENDING}
    stability = stability if isinstance(stability, dict) else {"status": STATUS_PENDING}
    economics_primary = (
        economics_primary if isinstance(economics_primary, dict) else {"status": STATUS_PENDING}
    )
    economics_robustness = (
        economics_robustness if isinstance(economics_robustness, dict) else {"status": STATUS_PENDING}
    )

    completeness = build_evidence_completeness(
        data_snapshot=data_snapshot,
        dataset_pair=dataset_pair,
        historical_oos=historical_oos,
        economics_primary=economics_primary,
        economics_robustness=economics_robustness,
        prospective=prospective,
    )
    payload = {
        "schema": EVIDENCE_DOSSIER_VERSION,
        "campaign_fingerprint": fingerprint,
        "identity": ident,
        "data_snapshot": data_snapshot,
        "dataset_pair": dataset_pair,
        "historical_oos": historical_oos,
        "ablation": ablation,
        "stability": stability,
        "economics_primary": economics_primary,
        "economics_robustness": economics_robustness,
        "prospective": prospective,
        "limitations": list(limitations) if limitations is not None else list(DEFAULT_LIMITATIONS),
        "evidence_completeness": completeness,
    }
    return _drop_forbidden_keys(payload)


def persist_evidence_dossier(
    dossier: dict[str, Any],
    *,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    """Write dossier under campaign fingerprint. Reuse same semantics; refuse different overwrite."""
    identity = dossier.get("identity") if isinstance(dossier.get("identity"), dict) else {}
    fingerprint = str(dossier.get("campaign_fingerprint") or fingerprint_campaign_identity(identity))
    dest = campaign_artifact_dir(fingerprint, root=artifact_root)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / DOSSIER_FILENAME
    tmp = dest / ".evidence_dossier.tmp.json"
    write_json(tmp, dossier)
    new_disk = json.loads(tmp.read_text(encoding="utf-8"))
    new_hash = payload_file_hash(new_disk)
    if path.is_file():
        existing_hash = dossier_file_hash(path)
        tmp.unlink(missing_ok=True)
        if existing_hash == new_hash:
            return {
                "status": "REUSED",
                "reuse": True,
                "campaign_fingerprint": fingerprint,
                "dossier_hash": existing_hash,
                "path": str(path),
            }
        raise DossierImmutabilityError(
            "Evidence dossier already exists for this campaign fingerprint with different "
            "semantics; refuse overwrite"
        )
    tmp.replace(path)
    return {
        "status": "WRITTEN",
        "reuse": False,
        "campaign_fingerprint": fingerprint,
        "dossier_hash": new_hash,
        "path": str(path),
    }
