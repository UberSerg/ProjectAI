"""Resumable Canonical Evidence Campaign V1 orchestrator.

Composes snapshot, refresh, pair, OOS, economics, prospective, and dossier.
The production candidate registry is never persisted. Does not train production Candidates.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.modules.learning.application.research_eval import FairCompareError
from app.modules.prediction.infrastructure.artifacts import write_json
from app.modules.research_evidence.bundle import payload_file_hash
from app.modules.research_evidence.campaign_contract import CanonicalEvidenceCampaignV1
from app.modules.research_evidence.campaign_dossier import (
    DOSSIER_FILENAME,
    STATUS_BLOCKED,
    STATUS_PARTIAL,
    STATUS_PENDING,
    build_evidence_dossier_v1,
    build_prospective_snapshot_v1,
    campaign_artifact_dir,
    persist_evidence_dossier,
)
from app.modules.research_evidence.campaign_economics import run_economic_robustness_campaign
from app.modules.research_evidence.campaign_oos import run_paired_v3_v4_evidence_campaign
from app.modules.research_evidence.campaign_pair import build_or_load_paired_v3_v4
from app.modules.research_evidence.campaign_progress import (
    PROGRESS_FILENAME,
    CampaignProgress,
    wrap_step_hook,
)
from app.modules.research_evidence.campaign_recovery import (
    find_reusable_dataset_run,
    interrupt_stale_campaign_dataset_builds,
    verify_research_specs,
)
from app.modules.research_evidence.campaign_refresh import inspect_campaign_coverage, refresh_campaign_data
from app.modules.research_evidence.campaign_snapshot import (
    build_research_data_snapshot,
    write_research_data_snapshot,
)
from app.modules.research_evidence.campaign_window import (
    STATUS_INSUFFICIENT as CAMPAIGN_DATA_INSUFFICIENT,
)
from app.modules.research_evidence.campaign_window import (
    campaign_primary_bounds,
)
from app.modules.research_evidence.economics import required_market_date_to
from app.modules.research_evidence.experiment import fingerprint_identity
from app.modules.research_evidence.paths import campaign_runtime_dir, list_campaign_dirs
from app.modules.simulator.application.market_view import load_market_view

# API/UI version string. Identity hash stays campaign_contract.CAMPAIGN_VERSION.
PUBLIC_CAMPAIGN_VERSION = "CanonicalEvidenceCampaignV1"
_OOS_SPLITS = frozenset(
    {"oos", "val", "validation", "out_of_sample", "chrono_oos", "chronological_oos"}
)
CAMPAIGN_WORKFLOW_STEPS: tuple[str, ...] = (
    "DATA_SNAPSHOT",
    "SAFE_DATA_REFRESH",
    "BUILD_V3",
    "BUILD_V4",
    "FAIR_PAIR_PROOF",
    "OOS_REGRESSION",
    "OOS_RANKER",
    "ABLATION",
    "STABILITY",
    "ECONOMICS_PRIMARY",
    "ECONOMICS_ROBUSTNESS",
    "PROSPECTIVE_SNAPSHOT",
    "DOSSIER",
    "FINALIZE",
)

HISTORICAL_STAGES: tuple[str, ...] = (
    "BUILD_V3",
    "BUILD_V4",
    "FAIR_PAIR_PROOF",
    "OOS_REGRESSION",
    "OOS_RANKER",
    "ABLATION",
    "STABILITY",
    "ECONOMICS_PRIMARY",
    "ECONOMICS_ROBUSTNESS",
)

PAIR_STAGES: tuple[str, ...] = ("BUILD_V3", "BUILD_V4", "FAIR_PAIR_PROOF")
OOS_STAGES: tuple[str, ...] = ("OOS_REGRESSION", "OOS_RANKER", "ABLATION", "STABILITY")
ECON_STAGES: tuple[str, ...] = ("ECONOMICS_PRIMARY", "ECONOMICS_ROBUSTNESS")

ABLATION_TO_ECONOMICS = {
    "BASE": "BASE",
    "BASE+FUNDAMENTALS": "FUNDAMENTALS",
    "BASE+EVENTS": "EVENTS",
    "V4_FULL": "V4_FULL",
}

_JSON_DROP_KEYS = frozenset(
    {
        "predictions",
        "ledger",
        "fills",
        "train_df",
        "val_df",
        "frame",
    }
)
_STAGE_RESUME = frozenset({"SUCCESS", "SKIPPED_RESUME", "WARNING"})
_STAGE_DONE = _STAGE_RESUME | frozenset({"BLOCKED"})
_JSON_ARTIFACTS = (
    "research_data_snapshot.json",
    "refresh_audit.json",
    "pair_proof.json",
    "oos_regression.json",
    "oos_ranker.json",
    "ablation.json",
    "stability.json",
    "economics_primary.json",
    "economics_robustness.json",
    "prospective.json",
    "manifest.json",
    DOSSIER_FILENAME,
)

StepHook = Callable[[str, str, str | None], None]


def jsonable_campaign_payload(obj: Any) -> Any:
    """JSON-safe campaign payload: drop DataFrames and prediction frames."""
    if isinstance(obj, pd.DataFrame):
        return None
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, value in obj.items():
            if str(key) in _JSON_DROP_KEYS or str(key).startswith("_"):
                continue
            out[str(key)] = jsonable_campaign_payload(value)
        return out
    if isinstance(obj, list):
        return [jsonable_campaign_payload(item) for item in obj]
    if isinstance(obj, tuple):
        return [jsonable_campaign_payload(item) for item in obj]
    if isinstance(obj, date) and not isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, float) and (obj != obj or obj in (float("inf"), float("-inf"))):
        return None
    return obj


def stamp_oos_predictions_for_economics(
    frame: pd.DataFrame,
    *,
    model_variant: str,
    folds: list[dict[str, Any]] | None = None,
    fingerprint: str | None = None,
    values_hash: str | None = None,
) -> pd.DataFrame:
    """Stamp chronological OOS val-fold predictions for the economics provenance contract.

    Ranking score is a rank score, not a return percent.
    ``is_oos`` is True only for chronological validation rows, never train/in-sample.
    """
    if frame is None or frame.empty:
        return pd.DataFrame()
    df = frame.copy()
    if "split" in df.columns:
        split = df["split"].astype(str).str.lower().str.strip()
        df = df.loc[split.isin(_OOS_SPLITS)].copy()
    elif "is_oos" in df.columns:
        flag = df["is_oos"].map(
            lambda v: v is True or str(v).strip().lower() in {"true", "1", "yes"}
        )
        df = df.loc[flag].copy()
    if df.empty:
        return pd.DataFrame()
    mapped = ABLATION_TO_ECONOMICS.get(str(model_variant), str(model_variant))
    if "decision_date" not in df.columns and "as_of_date" in df.columns:
        df["decision_date"] = pd.to_datetime(df["as_of_date"]).map(
            lambda v: v.date() if hasattr(v, "date") else v
        )
    df["model_variant"] = mapped
    df["is_oos"] = True
    df["split"] = "oos"
    df["universe_policy"] = "historical_equity_universe_v2"
    df["prediction_source"] = "research_evidence_oos"
    df["is_production_candidate"] = False
    df["score_is_not_return_pct"] = True
    if fingerprint:
        df["experiment_fingerprint"] = fingerprint
    if values_hash is not None:
        df["dataset_values_hash"] = values_hash
    if "y_pred" not in df.columns:
        for alt in ("prediction_score", "score"):
            if alt in df.columns:
                df["y_pred"] = df[alt]
                break
    if "fold_id" not in df.columns and "fold" in df.columns:
        df["fold_id"] = df["fold"]
    if "train_cutoff" not in df.columns:
        fold_cut: dict[Any, Any] = {}
        for fold in folds or []:
            if isinstance(fold, dict) and fold.get("fold_id") is not None:
                fold_cut[fold["fold_id"]] = fold.get("train_end") or fold.get("train_cutoff")
        if "fold_id" in df.columns:
            df["train_cutoff"] = df["fold_id"].map(fold_cut)
    return df


def coverage_needs_refresh(inspect_payload: dict[str, Any]) -> bool:
    """Stale/incomplete local coverage — not a network health check."""
    if inspect_payload.get("fundamentals_schema_ready") is False:
        return True
    for key in ("equity_instruments", "daily_equity_candles", "instruments_with_daily_history"):
        value = inspect_payload.get(key)
        if value is None or value == 0:
            return True
    fns = inspect_payload.get("fns_gir_bo_reports")
    if fns is None or fns == 0:
        return True
    return False


def _require_persist_registry_false(persist_registry: bool) -> None:
    if persist_registry:
        raise ValueError(
            "persist_registry must be false: campaign must not mutate "
            "the production candidate registry"
        )


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_artifact(path: Path, payload: Any) -> str:
    cleaned = jsonable_campaign_payload(payload)
    write_json(path, cleaned if isinstance(cleaned, dict | list) else {"value": cleaned})
    disk = json.loads(path.read_text(encoding="utf-8"))
    return payload_file_hash(disk)


def _write_predictions(path: Path, frame: pd.DataFrame) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        frame.to_parquet(path, index=False)
        return str(path)
    except Exception:  # noqa: BLE001 — parquet engine is optional
        alt = path.with_suffix(".pkl")
        frame.to_pickle(alt)
        return str(alt)


def _read_predictions(path: Path) -> pd.DataFrame | None:
    parquet = path
    pickle_path = path.with_suffix(".pkl")
    if parquet.is_file():
        try:
            return pd.read_parquet(parquet)
        except Exception:  # noqa: BLE001
            pass
    if pickle_path.is_file():
        loaded = pd.read_pickle(pickle_path)
        return loaded if isinstance(loaded, pd.DataFrame) else None
    return None


def _missing_quality() -> dict[str, Any]:
    return {"missing": True}


def _quality_status(status: Any, *, value: Any = None) -> dict[str, Any]:
    if status is None and value is None:
        return _missing_quality()
    out: dict[str, Any] = {}
    if status is not None:
        out["status"] = status
    if value is not None:
        out["value"] = value
    return out


def _window_from_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}
    window = snapshot.get("campaign_window")
    return window if isinstance(window, dict) else {}


def _pre_pair_identity(snapshot: dict[str, Any]) -> str:
    window = _window_from_snapshot(snapshot)
    date_from, date_to = campaign_primary_bounds(window)
    return fingerprint_identity(
        {
            "campaign_version": PUBLIC_CAMPAIGN_VERSION,
            "data_snapshot_hash": snapshot.get("data_snapshot_hash"),
            "date_from": date_from,
            "date_to": date_to,
        }
    )


def _pit_count(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value == value:
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _pit_pass(proof: dict[str, Any] | None) -> bool:
    """Missing PIT is not PASS. Explicit PASS and zero violations are required."""
    if not isinstance(proof, dict):
        return False
    status = str(proof.get("pit_status") or "").strip().upper()
    if status != "PASS":
        return False
    violations = _pit_count(proof.get("pit_violations"))
    if violations != 0:
        return False
    for key in ("v3", "v4"):
        side = proof.get(key)
        if not isinstance(side, dict):
            continue
        side_status = side.get("pit_status")
        if side_status is not None and str(side_status).strip().upper() != "PASS":
            return False
        side_n = _pit_count(side.get("pit_violations"))
        if side_n is not None and side_n != 0:
            return False
    return True


def _economics_artifact_status(econ_result: dict[str, Any] | None) -> str | None:
    if not isinstance(econ_result, dict):
        return None
    if econ_result.get("status") == STATUS_BLOCKED:
        return STATUS_BLOCKED
    primary = econ_result.get("primary")
    strategy = None
    if isinstance(primary, dict):
        strategy = primary.get("strategy") if isinstance(primary.get("strategy"), dict) else primary
    events: list[Any] = []
    strat_status = None
    if isinstance(strategy, dict):
        strat_status = strategy.get("status")
        raw_events = strategy.get("unresolved_exit_events")
        if isinstance(raw_events, list):
            events = raw_events
    if events or strat_status == STATUS_PARTIAL:
        return STATUS_PARTIAL
    if strat_status:
        return str(strat_status)
    if "primary" in econ_result:
        return "COMPLETE"
    return econ_result.get("status")


def _blocked(reason: str, code: str) -> dict[str, Any]:
    return {"status": STATUS_BLOCKED, "reason": reason, "code": code}


def _oos_rows_from_ablation(
    ablation: dict[str, Any] | None,
    paired_deltas: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    variants = (ablation or {}).get("variants") if isinstance(ablation, dict) else {}
    if not isinstance(variants, dict):
        return []
    deltas = paired_deltas if isinstance(paired_deltas, dict) else {}
    delta_by_variant = {
        "V4_FULL": deltas.get("V4_FULL_vs_BASE"),
        "BASE+FUNDAMENTALS": deltas.get("FUNDAMENTALS_vs_BASE"),
        "BASE+EVENTS": deltas.get("EVENTS_vs_BASE"),
    }
    rows: list[dict[str, Any]] = []
    for name, payload in variants.items():
        if not isinstance(payload, dict):
            continue
        metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
        rank = metrics.get("rank_ic")
        mean_ic = rank.get("mean_ic") if isinstance(rank, dict) else None
        spread = None
        top_bottom = metrics.get("top_bottom")
        if isinstance(top_bottom, dict):
            spread = top_bottom.get("top_minus_bottom")
        delta = delta_by_variant.get(str(name))
        ic_delta = delta.get("ic_delta") if isinstance(delta, dict) else None
        rows.append(
            {
                "variant": ABLATION_TO_ECONOMICS.get(str(name), str(name)),
                "rank_ic": mean_ic,
                "mean_rank_ic": mean_ic,
                "spread": spread,
                "n": metrics.get("n"),
                "ci_low": ic_delta.get("ci95_low") if isinstance(ic_delta, dict) else None,
                "ci_high": ic_delta.get("ci95_high") if isinstance(ic_delta, dict) else None,
                "delta_vs_base": ic_delta.get("mean_delta") if isinstance(ic_delta, dict) else None,
                "delta_ci_low": ic_delta.get("ci95_low") if isinstance(ic_delta, dict) else None,
                "delta_ci_high": ic_delta.get("ci95_high") if isinstance(ic_delta, dict) else None,
            }
        )
    return rows


def map_data_quality(
    snapshot: dict[str, Any] | None,
    pair: dict[str, Any] | None,
) -> dict[str, Any]:
    """UI data-quality block: missing stays null/missing, never coerced to 0."""
    if not isinstance(snapshot, dict):
        return {
            "price_coverage": _missing_quality(),
            "pit_status": _missing_quality(),
            "v4_fundamental_coverage": _missing_quality(),
            "event_coverage": _missing_quality(),
            "issuer_identity_basis": _missing_quality(),
            "bank_fi_unsupported": _missing_quality(),
            "total_return_status": _missing_quality(),
        }
    domains = {d.get("code"): d for d in (snapshot.get("domains") or []) if isinstance(d, dict)}
    prices = domains.get("prices") or {}
    funds = domains.get("fundamentals") or {}
    events = domains.get("events") or {}
    banks = domains.get("banks") or domains.get("bank_fi") or {}
    total_return = domains.get("total_return") or {}
    proof = pair.get("proof") if isinstance(pair, dict) and isinstance(pair.get("proof"), dict) else pair
    pit = None
    if isinstance(proof, dict):
        pit = proof.get("pit_status")
    issuer = None
    fund_ev = snapshot.get("fundamentals") if isinstance(snapshot.get("fundamentals"), dict) else {}
    store = fund_ev.get("store") if isinstance(fund_ev.get("store"), dict) else {}
    counts = store.get("issuer_resolution_basis_counts") or fund_ev.get("issuer_resolution_basis_counts")
    if isinstance(counts, dict) and counts:
        issuer = {"counts": counts}
    bank_n = None
    bank_ev = snapshot.get("total_return") if isinstance(snapshot.get("total_return"), dict) else {}
    if isinstance(banks.get("evidence"), dict):
        bank_n = banks["evidence"].get("unsupported_samples") or banks["evidence"].get("bank_fi_unsupported_samples")
    return {
        "price_coverage": _quality_status(prices.get("status")),
        "pit_status": _quality_status(pit) if pit is not None else _missing_quality(),
        "v4_fundamental_coverage": _quality_status(funds.get("status")),
        "event_coverage": _quality_status(events.get("status")),
        "issuer_identity_basis": issuer if issuer is not None else _missing_quality(),
        "bank_fi_unsupported": _quality_status(banks.get("status"), value=bank_n)
        if banks or bank_n is not None
        else _missing_quality(),
        "total_return_status": _quality_status(
            total_return.get("status") or (bank_ev.get("status") if isinstance(bank_ev, dict) else None)
        ),
    }


def map_identity_for_ui(identity: dict[str, Any], fingerprint: str) -> dict[str, Any]:
    return {
        **identity,
        "campaign_version": PUBLIC_CAMPAIGN_VERSION,
        "fingerprint": fingerprint,
        "fingerprint_short": fingerprint[:12] if fingerprint else None,
        "v3_run_id": identity.get("dataset_v3_run_id"),
        "v4_run_id": identity.get("dataset_v4_run_id"),
        "v3_dataset_hash": identity.get("dataset_v3_hash"),
        "v4_dataset_hash": identity.get("dataset_v4_hash"),
        "v3_values_hash": identity.get("dataset_v3_values_hash"),
        "v4_values_hash": identity.get("dataset_v4_values_hash"),
        "universe_version": identity.get("historical_universe_version"),
        "data_snapshot_hash": identity.get("data_snapshot_hash"),
        "date_from": identity.get("date_from"),
        "date_to": identity.get("date_to"),
    }


def map_dossier_for_ui(dossier: dict[str, Any]) -> dict[str, Any]:
    fingerprint = str(dossier.get("campaign_fingerprint") or "")
    identity = dossier.get("identity") if isinstance(dossier.get("identity"), dict) else {}
    snapshot = dossier.get("data_snapshot") if isinstance(dossier.get("data_snapshot"), dict) else {}
    mapped_identity = map_identity_for_ui(identity, fingerprint)
    if not mapped_identity.get("data_snapshot_at"):
        mapped_identity["data_snapshot_at"] = snapshot.get("created_at")
    historical = dossier.get("historical_oos") if isinstance(dossier.get("historical_oos"), dict) else {}
    ablation = dossier.get("ablation") if isinstance(dossier.get("ablation"), dict) else {}
    rows = historical.get("rows")
    if not rows:
        rows = _oos_rows_from_ablation(ablation, historical.get("paired_deltas") or ablation.get("paired_deltas"))
    pair_section = dossier.get("dataset_pair") if isinstance(dossier.get("dataset_pair"), dict) else None
    quality = dossier.get("data_quality")
    if not isinstance(quality, dict):
        quality = map_data_quality(snapshot, pair_section)
    completeness_raw = dossier.get("evidence_completeness")
    completeness = completeness_raw if isinstance(completeness_raw, dict) else {}
    return {
        **dossier,
        "identity": mapped_identity,
        "data_snapshot": {
            "hash": snapshot.get("data_snapshot_hash") or identity.get("data_snapshot_hash"),
            "observed_at": snapshot.get("created_at"),
            "created_at": snapshot.get("created_at"),
        },
        "data_quality": quality,
        "historical_oos": {
            "rows": rows,
            "partial": historical.get("status") not in {None, "ok", "OK", "COMPLETE"},
            "notes": historical.get("reason") or historical.get("note"),
            "status": historical.get("status"),
        },
        "evidence_completeness": {
            "data_integrity": completeness.get("DATA_INTEGRITY"),
            "historical_oos": completeness.get("HISTORICAL_OOS"),
            "economics": completeness.get("ECONOMICS"),
            "prospective": completeness.get("PROSPECTIVE"),
            "owner_review_state": completeness.get("OWNER_REVIEW_STATE"),
        },
        "empty": False,
    }


def _campaign_hash(dest: Path) -> str:
    hashes: list[str] = []
    for name in _JSON_ARTIFACTS:
        path = dest / name
        payload = _read_json(path)
        if payload is None:
            continue
        hashes.append(f"{name}:{payload_file_hash(payload)}")
    return fingerprint_identity({"artifacts": hashes})


def _summary_from_dir(path: Path) -> dict[str, Any] | None:
    manifest = _read_json(path / "manifest.json") or {}
    dossier = _read_json(path / DOSSIER_FILENAME) or {}
    identity = (
        dossier.get("identity")
        if isinstance(dossier.get("identity"), dict)
        else manifest.get("identity") if isinstance(manifest.get("identity"), dict) else {}
    )
    fingerprint = str(
        dossier.get("campaign_fingerprint") or manifest.get("campaign_fingerprint") or path.name
    )
    execution = _read_json(path / "execution.json") or {}
    status = (
        execution.get("status")
        or manifest.get("status")
        or (dossier.get("evidence_completeness") or {}).get("OWNER_REVIEW_STATE")
    )
    return {
        "fingerprint": fingerprint,
        "fingerprint_short": fingerprint[:12],
        "campaign_version": PUBLIC_CAMPAIGN_VERSION,
        "date_from": identity.get("date_from"),
        "date_to": identity.get("date_to"),
        "status": status,
        "created_at": execution.get("created_at") or manifest.get("created_at"),
        "finalized_at": execution.get("finalized_at") or manifest.get("finalized_at"),
        "identity": map_identity_for_ui(identity, fingerprint) if identity else None,
        "data_quality": map_data_quality(
            _read_json(path / "research_data_snapshot.json"),
            _read_json(path / "pair_proof.json"),
        ),
        "historical_oos": {
            "rows": _oos_rows_from_ablation(
                _read_json(path / "ablation.json") or {},
                (
                    (dossier.get("historical_oos") or {}).get("paired_deltas")
                    if isinstance(dossier.get("historical_oos"), dict)
                    else None
                ),
            ),
        },
    }


def list_campaign_summaries(*, artifact_root: Path | None = None) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for path in list_campaign_dirs(root=artifact_root):
        row = _summary_from_dir(path)
        if row is None:
            continue
        items.append(
            {
                "fingerprint": row["fingerprint"],
                "fingerprint_short": row["fingerprint_short"],
                "campaign_version": row["campaign_version"],
                "date_from": row["date_from"],
                "date_to": row["date_to"],
                "status": row["status"],
                "created_at": row["created_at"],
                "finalized_at": row["finalized_at"],
            }
        )
    items.sort(key=lambda r: r.get("finalized_at") or r.get("created_at") or "", reverse=True)
    return {"items": items, "campaigns": items}


def load_campaign_summary(fingerprint: str, *, artifact_root: Path | None = None) -> dict[str, Any] | None:
    path = campaign_artifact_dir(fingerprint, root=artifact_root)
    if not path.is_dir():
        return None
    return _summary_from_dir(path)


def load_campaign_dossier(fingerprint: str, *, artifact_root: Path | None = None) -> dict[str, Any] | None:
    path = campaign_artifact_dir(fingerprint, root=artifact_root) / DOSSIER_FILENAME
    raw = _read_json(path)
    if raw is None:
        return None
    return map_dossier_for_ui(raw)


def find_completed_canonical_campaign(*, artifact_root: Path | None = None) -> dict[str, Any] | None:
    for path in list_campaign_dirs(root=artifact_root):
        dossier = path / DOSSIER_FILENAME
        manifest = _read_json(path / "manifest.json") or {}
        execution = _read_json(path / "execution.json") or {}
        if not dossier.is_file():
            continue
        status = str(execution.get("status") or manifest.get("status") or "")
        if status in {"FINALIZED", "SUCCESS", "COMPLETE", "EVIDENCE_DOSSIER_COMPLETE"}:
            return _summary_from_dir(path)
        completeness = (_read_json(dossier) or {}).get("evidence_completeness") or {}
        if completeness.get("OWNER_REVIEW_STATE") == "EVIDENCE_DOSSIER_COMPLETE":
            return _summary_from_dir(path)
    return None


class _CampaignState:
    def __init__(self, path: Path) -> None:
        self.path = path
        loaded = _read_json(path)
        self.data: dict[str, Any] = loaded if isinstance(loaded, dict) else {
            "stages": {},
            "persist_registry": False,
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_json(self.path, jsonable_campaign_payload(self.data))

    def stage(self, name: str) -> dict[str, Any]:
        stages = self.data.setdefault("stages", {})
        row = stages.get(name)
        return row if isinstance(row, dict) else {}

    def is_done(self, name: str) -> bool:
        """Resume only completed semantic stages. BLOCKED is audit, not reuse."""
        return self.stage(name).get("status") in _STAGE_RESUME

    def mark(
        self,
        name: str,
        status: str,
        *,
        reason: str | None = None,
        identity: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        row = {
            "status": status,
            "reason": reason,
            "identity": identity,
        }
        if extra:
            row.update(extra)
        self.data.setdefault("stages", {})[name] = row
        self.save()


def _emit(hook: StepHook | None, name: str, status: str, error: str | None = None) -> None:
    if hook is not None:
        hook(name, status, error)


def _mark_group_blocked(
    state: _CampaignState,
    names: tuple[str, ...],
    *,
    reason: str,
    code: str,
    hook: StepHook | None,
    identity: str | None = None,
) -> None:
    for name in names:
        if state.is_done(name) and state.stage(name).get("status") == "BLOCKED":
            continue
        state.mark(name, "BLOCKED", reason=reason, identity=identity, extra={"code": code})
        _emit(hook, name, "WARNING", f"{code}: {reason}")


def run_canonical_evidence_campaign_v1(
    core_session: Session,
    memory_session: Session | None = None,
    *,
    workflow_id: int | str,
    exact_rerun: bool = False,
    persist_registry: bool = False,
    artifact_root: Path | None = None,
    official_refresh: Callable[..., Any] | None = None,
    snapshot_builder: Callable[..., dict[str, Any]] | None = None,
    inspect_fn: Callable[..., dict[str, Any]] | None = None,
    refresh_fn: Callable[..., dict[str, Any]] | None = None,
    pair_fn: Callable[..., dict[str, Any]] | None = None,
    oos_fn: Callable[..., dict[str, Any]] | None = None,
    economics_fn: Callable[..., dict[str, Any]] | None = None,
    market_loader: Callable[..., Any] | None = None,
    step_hook: StepHook | None = None,
) -> dict[str, Any]:
    """Run or resume CanonicalEvidenceCampaignV1. Registry persist stays false."""
    _require_persist_registry_false(persist_registry)
    created_at = datetime.now(UTC).isoformat()
    runtime_dir = campaign_runtime_dir(workflow_id, root=artifact_root)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    state = _CampaignState(runtime_dir / "state.json")
    state.data["workflow_id"] = workflow_id
    state.data["exact_rerun"] = bool(exact_rerun)
    state.data["persist_registry"] = False
    state.data.setdefault("created_at", created_at)
    state.save()

    progress = CampaignProgress(
        runtime_dir / PROGRESS_FILENAME,
        campaign_id=str(workflow_id),
        campaign_fingerprint=state.data.get("fingerprint"),
    )
    resumed = [
        name
        for name, row in (state.data.get("stages") or {}).items()
        if isinstance(row, dict) and row.get("status") in {"SUCCESS", "SKIPPED_RESUME", "WARNING"}
    ]
    if resumed:
        progress.mark_completed(resumed)
    step_hook = wrap_step_hook(progress, step_hook)

    executed: list[str] = []
    skipped: list[str] = []
    fingerprint: str | None = state.data.get("fingerprint")
    dest: Path | None = campaign_artifact_dir(fingerprint, root=artifact_root) if fingerprint else None

    def resume_ok(stage: str, identity: str | None) -> bool:
        if not state.is_done(stage):
            return False
        recorded = state.stage(stage).get("identity")
        if recorded != identity:
            return False
        skipped.append(stage)
        prior = state.stage(stage).get("status") or "SUCCESS"
        _emit(step_hook, stage, "SUCCESS" if prior != "BLOCKED" else "WARNING", None)
        return True

    # --- DATA_SNAPSHOT ---
    snap_identity_key = "pre_pair"
    if not resume_ok("DATA_SNAPSHOT", state.data.get("pre_pair_identity") or snap_identity_key):
        _emit(step_hook, "DATA_SNAPSHOT", "RUNNING")
        builder = snapshot_builder or build_research_data_snapshot
        snapshot = builder(core_session)
        snap_path = runtime_dir / "research_data_snapshot.json"
        written = write_research_data_snapshot(snap_path, snapshot)
        snapshot["data_snapshot_hash"] = written["data_snapshot_hash"]
        pre_id = _pre_pair_identity(snapshot)
        state.data["pre_pair_identity"] = pre_id
        state.data["data_snapshot_hash"] = snapshot["data_snapshot_hash"]
        state.mark("DATA_SNAPSHOT", "SUCCESS", identity=pre_id)
        _emit(step_hook, "DATA_SNAPSHOT", "SUCCESS")
        executed.append("DATA_SNAPSHOT")
    snapshot = _read_json(runtime_dir / "research_data_snapshot.json") or {}
    pre_id = state.data.get("pre_pair_identity") or _pre_pair_identity(snapshot)

    # --- SAFE_DATA_REFRESH ---
    if not resume_ok("SAFE_DATA_REFRESH", pre_id):
        _emit(step_hook, "SAFE_DATA_REFRESH", "RUNNING")
        inspect_before = (inspect_fn or inspect_campaign_coverage)(core_session)
        runner = refresh_fn or refresh_campaign_data
        needs = coverage_needs_refresh(inspect_before)
        if needs:
            refresh_payload = runner(core_session, dry_run=False)
        else:
            refresh_payload = runner(core_session, dry_run=True)
            refresh_payload["skipped_refresh"] = True
            refresh_payload["reason"] = "coverage_not_stale"
        _write_artifact(runtime_dir / "refresh_audit.json", refresh_payload)
        if needs:
            builder = snapshot_builder or build_research_data_snapshot
            snapshot = builder(core_session)
            written = write_research_data_snapshot(runtime_dir / "research_data_snapshot.json", snapshot)
            snapshot["data_snapshot_hash"] = written["data_snapshot_hash"]
            pre_id = _pre_pair_identity(snapshot)
            state.data["pre_pair_identity"] = pre_id
            state.data["data_snapshot_hash"] = snapshot["data_snapshot_hash"]
        state.mark("SAFE_DATA_REFRESH", "SUCCESS", identity=pre_id)
        _emit(step_hook, "SAFE_DATA_REFRESH", "SUCCESS")
        executed.append("SAFE_DATA_REFRESH")
    snapshot = _read_json(runtime_dir / "research_data_snapshot.json") or snapshot
    pre_id = state.data.get("pre_pair_identity") or _pre_pair_identity(snapshot)
    window = _window_from_snapshot(snapshot)
    block_code: str | None = None
    block_reason: str | None = None
    if (
        snapshot.get("campaign_window_status") == CAMPAIGN_DATA_INSUFFICIENT
        or window.get("status") == CAMPAIGN_DATA_INSUFFICIENT
    ):
        block_code = CAMPAIGN_DATA_INSUFFICIENT
        block_reason = str(window.get("reason") or "campaign window is too short or immature")

    pair_payload: dict[str, Any] | None = _read_json(runtime_dir / "pair_proof.json")
    campaign_record: dict[str, Any] | None = None

    if block_code:
        _mark_group_blocked(
            state,
            HISTORICAL_STAGES,
            reason=block_reason or block_code,
            code=block_code,
            hook=step_hook,
            identity=pre_id,
        )
    else:
        if not all(resume_ok(name, state.data.get("fingerprint") or pre_id) for name in PAIR_STAGES):
            _emit(step_hook, "BUILD_V3", "RUNNING")
            bound_from, bound_to = campaign_primary_bounds(window)
            date_from = date.fromisoformat(bound_from) if bound_from else None
            date_to = date.fromisoformat(bound_to) if bound_to else None
            try:
                reuse_v3_id = None
                reuse_v4_id = None
                expected_samples: int | None = None
                if pair_fn is None:
                    verify_research_specs(core_session)
                    interrupt_stale_campaign_dataset_builds(core_session)
                    if date_from and date_to:
                        reuse_v3 = find_reusable_dataset_run(
                            core_session,
                            spec_version=3,
                            date_from=date_from,
                            date_to=date_to,
                        )
                        reuse_v4 = find_reusable_dataset_run(
                            core_session,
                            spec_version=4,
                            date_from=date_from,
                            date_to=date_to,
                        )
                        reuse_v3_id = None if reuse_v3 is None else int(reuse_v3.id)
                        reuse_v4_id = None if reuse_v4 is None else int(reuse_v4.id)
                        if reuse_v3_id is not None:
                            progress.complete_stage("BUILD_V3")
                        expected_samples = None if reuse_v3 is None else int(reuse_v3.samples_total or 0)
                builder_pair = pair_fn or build_or_load_paired_v3_v4
                pair_kwargs: dict[str, Any] = {
                    "date_from": date_from,
                    "date_to": date_to,
                    "instrument_ids": None,
                    "persist_registry": False,
                    "data_snapshot_hash": snapshot.get("data_snapshot_hash"),
                }
                if reuse_v3_id is not None:
                    pair_kwargs["v3_run_id"] = reuse_v3_id
                if reuse_v4_id is not None:
                    pair_kwargs["v4_run_id"] = reuse_v4_id
                if pair_fn is None:
                    pair_kwargs["expected_samples"] = expected_samples or None
                    pair_kwargs["progress_callback"] = lambda info: progress.update_stage_units(
                        "BUILD_V4",
                        current=int(info.get("current") or 0),
                        total=int(info.get("total") or 0),
                        unit=str(info.get("unit") or "samples"),
                    )
                pair_payload = builder_pair(core_session, **pair_kwargs)
            except FairCompareError as exc:
                block_code = "FAIR_CONTRACT_FAIL"
                block_reason = str(exc)
                pair_payload = _blocked(block_reason, block_code)
            except Exception as exc:  # noqa: BLE001
                text = str(exc)
                if "FAIR_CONTRACT_FAIL" in text or "pit" in text.lower():
                    block_code = "FAIR_CONTRACT_FAIL" if "FAIR_CONTRACT_FAIL" in text else "PIT_FAIL"
                    block_reason = text
                    pair_payload = _blocked(block_reason, block_code)
                else:
                    raise
            if pair_payload and not block_code:
                proof = pair_payload.get("proof") if isinstance(pair_payload.get("proof"), dict) else pair_payload
                fair_fail = (
                    isinstance(proof, dict)
                    and (
                        proof.get("fair_contract_status") == "FAIR_CONTRACT_FAIL"
                        or pair_payload.get("fair_contract_status") == "FAIR_CONTRACT_FAIL"
                    )
                )
                if fair_fail:
                    block_code = "FAIR_CONTRACT_FAIL"
                    block_reason = "paired V3/V4 identity failed"
                elif not _pit_pass(proof if isinstance(proof, dict) else None):
                    block_code = "PIT_FAIL"
                    block_reason = "missing PIT is not PASS; campaign stops before OOS"
            _write_artifact(runtime_dir / "pair_proof.json", pair_payload or {})
            if block_code:
                _mark_group_blocked(
                    state,
                    HISTORICAL_STAGES,
                    reason=block_reason or block_code,
                    code=block_code,
                    hook=step_hook,
                    identity=pre_id,
                )
            else:
                campaign_record = (pair_payload or {}).get("campaign")
                fingerprint = str((pair_payload or {}).get("campaign_fingerprint") or "")
                if not fingerprint and isinstance(campaign_record, dict):
                    fingerprint = str(campaign_record.get("campaign_fingerprint") or "")
                state.data["fingerprint"] = fingerprint
                dest = campaign_artifact_dir(fingerprint, root=artifact_root)
                dest.mkdir(parents=True, exist_ok=True)
                for name in ("research_data_snapshot.json", "refresh_audit.json", "pair_proof.json"):
                    src = runtime_dir / name
                    if src.is_file():
                        (dest / name).write_bytes(src.read_bytes())
                for name in PAIR_STAGES:
                    state.mark(name, "SUCCESS", identity=fingerprint)
                    _emit(step_hook, name, "SUCCESS")
                    executed.append(name)
        else:
            pair_payload = _read_json(runtime_dir / "pair_proof.json") or pair_payload
            fingerprint = state.data.get("fingerprint") or (pair_payload or {}).get("campaign_fingerprint")
            if fingerprint:
                dest = campaign_artifact_dir(str(fingerprint), root=artifact_root)

    identity_key = str(fingerprint or pre_id)
    if dest is None and fingerprint:
        dest = campaign_artifact_dir(str(fingerprint), root=artifact_root)
    artifact_dir = dest or runtime_dir

    oos_payload: dict[str, Any] | None = None
    if not block_code:
        if not all(resume_ok(name, identity_key) for name in OOS_STAGES):
            _emit(step_hook, "OOS_REGRESSION", "RUNNING")
            proof = (pair_payload or {}).get("proof") if isinstance(pair_payload, dict) else None
            if not isinstance(proof, dict):
                proof = pair_payload or {}
            v3_id = proof.get("dataset_v3_run_id")
            v4_id = proof.get("dataset_v4_run_id")
            runner_oos = oos_fn or run_paired_v3_v4_evidence_campaign
            oos_kwargs: dict[str, Any] = {
                "session": core_session,
                "v3_run_id": int(v3_id) if v3_id is not None else None,
                "v4_run_id": int(v4_id) if v4_id is not None else None,
                "persist_registry": False,
            }
            if oos_fn is None:

                def _fold_progress(info: dict[str, Any]) -> None:
                    semantic = str(info.get("semantic") or "")
                    stage = {
                        "regression": "OOS_REGRESSION",
                        "ranking": "OOS_RANKER",
                        "ablation": "ABLATION",
                    }.get(semantic, "OOS_REGRESSION")
                    total = int(info.get("fold_total") or 0)
                    current = int(info.get("fold_index") or 0)
                    progress.update_stage_units(
                        stage,
                        current=current,
                        total=max(total, current),
                        unit="folds",
                        message=f"{stage} fold {current}/{total}",
                    )

                def _variant_progress(info: dict[str, Any]) -> None:
                    total = int(info.get("total") or 0)
                    current = int(info.get("index") or 0)
                    variant = str(info.get("variant") or "")
                    progress.update_stage_units(
                        "ABLATION",
                        current=current,
                        total=max(total, current),
                        unit="variants",
                        message=f"{variant} {current}/{total}",
                    )

                oos_kwargs["fold_progress"] = _fold_progress
                oos_kwargs["variant_progress"] = _variant_progress
            oos_payload = runner_oos(**oos_kwargs)
            _write_artifact(artifact_dir / "oos_regression.json", oos_payload.get("regression") if oos_payload else {})
            _write_artifact(artifact_dir / "oos_ranker.json", oos_payload.get("ranking") if oos_payload else {})
            _write_artifact(artifact_dir / "ablation.json", oos_payload.get("ablation") if oos_payload else {})
            _write_artifact(artifact_dir / "stability.json", oos_payload.get("stability") if oos_payload else {})
            _write_artifact(artifact_dir / "oos_campaign.json", oos_payload or {})
            variants = (oos_payload or {}).get("ablation", {}).get("variants") or {}
            pred_dir = artifact_dir / "predictions"
            for variant_name, variant_payload in variants.items():
                if not isinstance(variant_payload, dict):
                    continue
                preds = variant_payload.get("predictions")
                if isinstance(preds, pd.DataFrame) and not preds.empty:
                    stamped = stamp_oos_predictions_for_economics(
                        preds,
                        model_variant=str(variant_name),
                        folds=variant_payload.get("folds") if isinstance(variant_payload.get("folds"), list) else None,
                        fingerprint=str(fingerprint) if fingerprint else None,
                        values_hash=(proof or {}).get("dataset_v4_values_hash"),
                    )
                    econ_name = ABLATION_TO_ECONOMICS.get(str(variant_name), variant_name)
                    _write_predictions(pred_dir / f"{econ_name}.parquet", stamped)
            for name in OOS_STAGES:
                state.mark(name, "SUCCESS", identity=identity_key)
                _emit(step_hook, name, "SUCCESS")
                executed.append(name)
        else:
            oos_payload = _read_json(artifact_dir / "oos_campaign.json")

        if not all(resume_ok(name, identity_key) for name in ECON_STAGES):
            _emit(step_hook, "ECONOMICS_PRIMARY", "RUNNING")
            parts: list[pd.DataFrame] = []
            pred_dir = artifact_dir / "predictions"
            for econ_name in ("BASE", "FUNDAMENTALS", "EVENTS", "V4_FULL"):
                loaded = _read_predictions(pred_dir / f"{econ_name}.parquet")
                if loaded is not None and not loaded.empty:
                    parts.append(loaded)
            if not parts:
                econ_result = _blocked("no stamped OOS prediction frames", "ECONOMICS_INSUFFICIENT")
            else:
                stamped = pd.concat(parts, ignore_index=True)
                ids = {int(x) for x in stamped["instrument_id"].dropna().unique()}
                decisions = [
                    d.date() if hasattr(d, "date") else date.fromisoformat(str(d)[:10])
                    for d in pd.to_datetime(stamped["decision_date"])
                ]
                d0, d1 = min(decisions), max(decisions)
                loader = market_loader or load_market_view
                probe = loader(
                    core_session,
                    instrument_ids=ids,
                    date_from=d0,
                    date_to=d1 + timedelta(days=90),
                )
                needed = required_market_date_to(decisions, list(probe.trading_days))
                market = loader(core_session, instrument_ids=ids, date_from=d0, date_to=needed)
                runner_e = economics_fn or run_economic_robustness_campaign
                econ_kwargs: dict[str, Any] = {"predictions": stamped, "market": market}
                if economics_fn is None:
                    cells_done = {"n": 0}

                    def _econ_observer(event: str, payload: Any = None) -> None:
                        if event != "cell_metrics_finished":
                            return
                        cells_done["n"] += 1
                        progress.update_stage_units(
                            "ECONOMICS_ROBUSTNESS",
                            current=cells_done["n"],
                            total=36,
                            unit="cells",
                            message=f"ECONOMICS_ROBUSTNESS {cells_done['n']}/36",
                        )

                    econ_kwargs["observer"] = _econ_observer
                econ_result = runner_e(**econ_kwargs)
            primary_status = _economics_artifact_status(
                econ_result if isinstance(econ_result, dict) else None
            )
            unresolved: list[Any] = []
            primary_row = (econ_result or {}).get("primary") if isinstance(econ_result, dict) else None
            if isinstance(primary_row, dict):
                strat = primary_row.get("strategy") if isinstance(primary_row.get("strategy"), dict) else primary_row
                if isinstance(strat, dict) and isinstance(strat.get("unresolved_exit_events"), list):
                    unresolved = strat["unresolved_exit_events"]
            primary = {
                "status": primary_status,
                "primary_settings": (econ_result or {}).get("primary_settings"),
                "primary": (econ_result or {}).get("primary"),
                "unresolved_exit_events": unresolved,
                "variants_under_primary_settings": jsonable_campaign_payload(
                    (econ_result or {}).get("variants_under_primary_settings")
                ),
                "prediction_semantic": "RANKING",
                "score_is_not_return_pct": True,
                "variant": "V4_FULL",
            }
            robustness = {
                "status": primary.get("status"),
                "predeclared_cells": (econ_result or {}).get("predeclared_cells"),
                "matrix": jsonable_campaign_payload((econ_result or {}).get("matrix")),
                "primary_chosen_as_best_cell": False,
                "cells_enumerated_before_metrics": (econ_result or {}).get("cells_enumerated_before_metrics"),
            }
            _write_artifact(artifact_dir / "economics_primary.json", primary)
            _write_artifact(artifact_dir / "economics_robustness.json", robustness)
            for name in ECON_STAGES:
                status = "BLOCKED" if (econ_result or {}).get("status") == STATUS_BLOCKED else "SUCCESS"
                state.mark(name, status, identity=identity_key, reason=(econ_result or {}).get("reason"))
                _emit(step_hook, name, "WARNING" if status == "BLOCKED" else "SUCCESS")
                executed.append(name)

    # --- PROSPECTIVE + DOSSIER always allowed ---
    if not resume_ok("PROSPECTIVE_SNAPSHOT", identity_key):
        _emit(step_hook, "PROSPECTIVE_SNAPSHOT", "RUNNING")
        try:
            prospective = build_prospective_snapshot_v1(
                memory_session=memory_session,
                core_session=core_session,
                official_refresh=official_refresh,
            )
        except Exception:  # noqa: BLE001 — incomplete Memory/Core must not abort dossier
            prospective = {"status": "PENDING", "reason": "prospective_unavailable", "empty": True}
        _write_artifact(artifact_dir / "prospective.json", prospective)
        state.mark("PROSPECTIVE_SNAPSHOT", "SUCCESS", identity=identity_key)
        _emit(step_hook, "PROSPECTIVE_SNAPSHOT", "SUCCESS")
        executed.append("PROSPECTIVE_SNAPSHOT")
    prospective = _read_json(artifact_dir / "prospective.json") or {"status": STATUS_PENDING}

    if not resume_ok("DOSSIER", identity_key):
        _emit(step_hook, "DOSSIER", "RUNNING")
        identity = {}
        if isinstance((pair_payload or {}).get("campaign"), dict):
            identity = ((pair_payload or {}).get("campaign") or {}).get("identity") or {}
        if not identity and fingerprint:
            try:
                # Fingerprint-only placeholder when pair never completed.
                bound_from, bound_to = campaign_primary_bounds(window)
                identity = {
                    "campaign_version": PUBLIC_CAMPAIGN_VERSION,
                    "data_snapshot_hash": snapshot.get("data_snapshot_hash"),
                    "date_from": bound_from,
                    "date_to": bound_to,
                }
            except Exception:  # noqa: BLE001
                identity = {"campaign_version": PUBLIC_CAMPAIGN_VERSION}
        historical = _read_json(artifact_dir / "oos_campaign.json") or _blocked(
            block_reason or "historical stages not run", block_code or STATUS_BLOCKED
        )
        ablation = _read_json(artifact_dir / "ablation.json") or {"status": STATUS_BLOCKED, "reason": block_reason}
        stability = _read_json(artifact_dir / "stability.json") or {"status": STATUS_BLOCKED, "reason": block_reason}
        if isinstance(historical, dict) and "rows" not in historical:
            historical = {
                **historical,
                "rows": _oos_rows_from_ablation(ablation, historical.get("paired_deltas")),
                "status": historical.get("status") or (STATUS_BLOCKED if block_code else STATUS_PENDING),
            }
        econ_p = _read_json(artifact_dir / "economics_primary.json") or {
            "status": STATUS_BLOCKED,
            "reason": block_reason,
        }
        econ_r = _read_json(artifact_dir / "economics_robustness.json") or {
            "status": STATUS_BLOCKED,
            "reason": block_reason,
        }
        pair_section = pair_payload or _blocked(block_reason or "pair not proven", block_code or STATUS_BLOCKED)
        dossier = build_evidence_dossier_v1(
            identity=identity if identity else {"campaign_version": PUBLIC_CAMPAIGN_VERSION},
            data_snapshot=snapshot,
            dataset_pair=jsonable_campaign_payload(pair_section),
            historical_oos=jsonable_campaign_payload(historical),
            ablation=jsonable_campaign_payload(ablation),
            stability=jsonable_campaign_payload(stability),
            economics_primary=jsonable_campaign_payload(econ_p),
            economics_robustness=jsonable_campaign_payload(econ_r),
            prospective=prospective,
        )
        persist_root = artifact_root
        if fingerprint:
            dossier["campaign_fingerprint"] = fingerprint
        persisted = persist_evidence_dossier(dossier, artifact_root=persist_root)
        if dest is None:
            dest = campaign_artifact_dir(str(persisted["campaign_fingerprint"]), root=artifact_root)
            artifact_dir = dest
            state.data["dossier_fingerprint"] = persisted["campaign_fingerprint"]
            if not block_code:
                fingerprint = persisted["campaign_fingerprint"]
                state.data["fingerprint"] = fingerprint
        state.mark("DOSSIER", "SUCCESS", identity=identity_key, extra={"dossier_hash": persisted.get("dossier_hash")})
        _emit(step_hook, "DOSSIER", "SUCCESS")
        executed.append("DOSSIER")

    if not resume_ok("FINALIZE", identity_key):
        _emit(step_hook, "FINALIZE", "RUNNING")
        final_dir = dest or artifact_dir
        campaign_hash = _campaign_hash(final_dir)
        execution = {
            "workflow_id": workflow_id,
            "exact_rerun": bool(exact_rerun),
            "persist_registry": False,
            "status": "FINALIZED" if not block_code else "BLOCKED",
            "block_code": block_code,
            "block_reason": block_reason,
            "created_at": state.data.get("created_at"),
            "finalized_at": datetime.now(UTC).isoformat(),
            "campaign_hash": campaign_hash,
            "fingerprint": fingerprint,
            "campaign_version": PUBLIC_CAMPAIGN_VERSION,
        }
        _write_artifact(final_dir / "execution.json", execution)
        if exact_rerun:
            _write_artifact(final_dir / f"execution-{workflow_id}.json", execution)
        manifest = {
            "campaign_fingerprint": fingerprint,
            "campaign_hash": campaign_hash,
            "campaign_version": PUBLIC_CAMPAIGN_VERSION,
            "persist_registry": False,
            "research_only": True,
            "status": execution["status"],
            "created_at": execution["created_at"],
            "finalized_at": execution["finalized_at"],
            "identity": ((pair_payload or {}).get("campaign") or {}).get("identity")
            if isinstance(pair_payload, dict)
            else None,
            "data_snapshot_hash": snapshot.get("data_snapshot_hash"),
        }
        _write_artifact(final_dir / "manifest.json", manifest)
        state.data["status"] = execution["status"]
        state.mark("FINALIZE", "SUCCESS", identity=identity_key)
        _emit(step_hook, "FINALIZE", "SUCCESS")
        executed.append("FINALIZE")

    report_fp = fingerprint or state.data.get("dossier_fingerprint")
    state.data["fingerprint"] = fingerprint
    state.save()
    result = {
        "status": state.data.get("status") or ("BLOCKED" if block_code else "FINALIZED"),
        "fingerprint": report_fp,
        "workflow_id": workflow_id,
        "persist_registry": False,
        "campaign_version": PUBLIC_CAMPAIGN_VERSION,
        "block_code": block_code,
        "block_reason": block_reason,
        "executed_stages": executed,
        "skipped_stages": skipped,
        "artifact_dir": str(dest or artifact_dir),
    }
    progress.set_fingerprint(str(report_fp) if report_fp else None)
    if block_code:
        progress.finish(status="BLOCKED", block_code=block_code, block_reason=block_reason)
    else:
        progress.finish(status="COMPLETE")
    return result


__all__ = [
    "ABLATION_TO_ECONOMICS",
    "CAMPAIGN_WORKFLOW_STEPS",
    "PUBLIC_CAMPAIGN_VERSION",
    "coverage_needs_refresh",
    "find_completed_canonical_campaign",
    "jsonable_campaign_payload",
    "list_campaign_summaries",
    "load_campaign_dossier",
    "load_campaign_summary",
    "map_dossier_for_ui",
    "run_canonical_evidence_campaign_v1",
    "stamp_oos_predictions_for_economics",
    "CanonicalEvidenceCampaignV1",
]
