"""Research Evidence Engine V1 orchestration (research-only, no production writes)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.infrastructure.db.session import core_session
from app.modules.learning.application.compare_v3_v4 import compare_v3_v4_builds
from app.modules.learning.application.research_eval import FairCompareError
from app.modules.prediction.application.research_dataset_loader import load_research_frame
from app.modules.research_evidence.ablation import run_v4_ablation
from app.modules.research_evidence.bundle import write_evidence_bundle
from app.modules.research_evidence.economics import (
    EconomicsContractError,
    EconomicsProvenanceError,
    run_all_model_variants,
)
from app.modules.research_evidence.experiment import ResearchEvidenceExperimentV1
from app.modules.research_evidence.oos import run_chronological_oos
from app.modules.research_evidence.overview_map import empty_overview, overview_from_dir
from app.modules.research_evidence.paired_delta import paired_v4_vs_base
from app.modules.research_evidence.pairing import prove_paired_v3_v4
from app.modules.research_evidence.paths import experiment_dir, find_experiment_dir, list_experiment_dirs
from app.modules.research_evidence.prospective import build_prospective_evidence_v1
from app.modules.research_evidence.stability import slice_stability
from app.modules.simulator.application.market_view import load_market_view

_VARIANT_ECON = {
    "BASE": "BASE",
    "BASE+FUNDAMENTALS": "FUNDAMENTALS",
    "BASE+EVENTS": "EVENTS",
    "V4_FULL": "V4_FULL",
}


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, pd.DataFrame):
        return None
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, date):
        return obj.isoformat()
    return obj


def resolve_frozen_run_ids(
    experiment_id: str,
    *,
    artifact_root: Path | None = None,
) -> dict[str, int] | None:
    """Read frozen dataset_v3_run_id / dataset_v4_run_id from manifest.identity.

    Returns None if the experiment directory or identity is missing.
    """
    path = find_experiment_dir(experiment_id, root=artifact_root)
    if path is None:
        return None
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    identity = raw.get("identity") if isinstance(raw.get("identity"), dict) else {}
    v3 = identity.get("dataset_v3_run_id")
    v4 = identity.get("dataset_v4_run_id")
    if not isinstance(v3, int) or isinstance(v3, bool) or not isinstance(v4, int) or isinstance(v4, bool):
        return None
    return {"dataset_v3_run_id": v3, "dataset_v4_run_id": v4}


def get_latest_evidence(*, artifact_root: Path | None = None) -> dict[str, Any]:
    dirs = list_experiment_dirs(root=artifact_root)
    if not dirs:
        return empty_overview()
    return overview_from_dir(dirs[0])


def get_evidence(experiment_id: str, *, artifact_root: Path | None = None) -> dict[str, Any] | None:
    for path in list_experiment_dirs(root=artifact_root):
        if path.name == experiment_id or path.name.startswith(experiment_id):
            return overview_from_dir(path)
        overview = overview_from_dir(path)
        if (overview.get("experiment") or {}).get("id") == experiment_id:
            return overview
    direct = experiment_dir(experiment_id, root=artifact_root)
    if (direct / "evidence_overview.json").exists():
        return overview_from_dir(direct)
    return None


def get_prospective_evidence(
    *,
    memory: Session | None = None,
    core: Session | None = None,
    portfolio_id: int | None = None,
) -> dict[str, Any]:
    if memory is not None or core is not None:
        raw = build_prospective_evidence_v1(
            memory_session=memory, core_session=core, portfolio_id=portfolio_id
        )
        from app.modules.research_evidence.overview_map import map_prospective_ui

        ui = map_prospective_ui(raw)
        ui["raw"] = raw
        return ui
    latest = get_latest_evidence()
    return latest.get("prospective") or empty_overview()["prospective"]


def _attach_econ_rows(
    ablation: dict[str, Any],
    *,
    fingerprint: str,
    values_hash: str | None,
) -> pd.DataFrame | None:
    parts: list[pd.DataFrame] = []
    for name, payload in (ablation.get("variants") or {}).items():
        if not isinstance(payload, dict):
            continue
        preds = payload.get("predictions")
        if not isinstance(preds, pd.DataFrame) or preds.empty:
            continue
        mapped = _VARIANT_ECON.get(str(name))
        if mapped is None:
            continue
        df = preds.copy()
        fold_cut: dict[Any, Any] = {}
        for fold in payload.get("folds") or []:
            if isinstance(fold, dict) and fold.get("fold_id") is not None:
                fold_cut[fold["fold_id"]] = fold.get("train_end")
        df["model_variant"] = mapped
        df["is_oos"] = True
        df["split"] = "oos"
        df["universe_policy"] = "historical_equity_universe_v2"
        df["experiment_fingerprint"] = fingerprint
        df["dataset_values_hash"] = values_hash
        df["prediction_source"] = "research_evidence_oos"
        df["is_production_candidate"] = False
        if "train_cutoff" not in df.columns:
            df["train_cutoff"] = df["fold_id"].map(fold_cut)
        parts.append(df)
    if not parts:
        return None
    return pd.concat(parts, ignore_index=True)


def resolve_paired_runs(
    session: Session,
    *,
    v3_run_id: int | None,
    v4_run_id: int | None,
    date_from: date | None,
    date_to: date | None,
    instrument_ids: list[int] | None,
    rebuild: bool,
) -> dict[str, Any]:
    if v3_run_id is not None and v4_run_id is not None:
        return prove_paired_v3_v4(session, v3_run_id, v4_run_id)
    if date_from is None or date_to is None:
        raise ValueError(
            "Нужны dataset_v3_run_id и dataset_v4_run_id либо явный интервал date_from/date_to. "
            "Текущая активная вселенная не используется скрыто."
        )
    compare = compare_v3_v4_builds(
        session,
        date_from=date_from,
        date_to=date_to,
        instrument_ids=instrument_ids,
        v3_run_id=v3_run_id,
        v4_run_id=v4_run_id,
        rebuild=rebuild,
    )
    v3_id = int((compare.get("v3") or {})["run_id"])
    v4_id = int((compare.get("v4") or {})["run_id"])
    proof = prove_paired_v3_v4(session, v3_id, v4_id)
    proof["dataset_compare"] = compare
    return proof


def run_historical_evidence(
    session: Session,
    *,
    v3_run_id: int | None = None,
    v4_run_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    instrument_ids: list[int] | None = None,
    rebuild: bool = False,
    persist_registry: bool = False,
    model_factory: Any | None = None,
    artifact_root: Path | None = None,
    run_economics: bool = True,
    min_train_n: int = 100,
    min_val_n: int = 20,
) -> dict[str, Any]:
    if persist_registry:
        raise ValueError("research evidence must not persist the production registry")
    proof = resolve_paired_runs(
        session,
        v3_run_id=v3_run_id,
        v4_run_id=v4_run_id,
        date_from=date_from,
        date_to=date_to,
        instrument_ids=instrument_ids,
        rebuild=rebuild,
    )
    if (
        proof.get("fair_contract_status") != "PASS"
        or proof.get("sample_identity_match") is not True
    ):
        raise FairCompareError(
            "FAIR_CONTRACT_FAIL: model and economics steps must not run without paired V3/V4 identity"
        )
    experiment = ResearchEvidenceExperimentV1(
        dataset_v3_run_id=int(proof["dataset_v3_run_id"]),
        dataset_v4_run_id=int(proof["dataset_v4_run_id"]),
        dataset_v3_hash=str(proof["dataset_v3_hash"] or ""),
        dataset_v4_hash=str(proof["dataset_v4_hash"] or ""),
        dataset_v3_values_hash=proof.get("dataset_v3_values_hash"),
        dataset_v4_values_hash=proof.get("dataset_v4_values_hash"),
        date_from=proof["date_from"],
        date_to=proof["date_to"],
        persist_registry=False,
    )
    _run, frame = load_research_frame(
        session,
        dataset_spec_version=4,
        dataset_run_id=int(proof["dataset_v4_run_id"]),
    )
    regression = run_chronological_oos(
        frame,
        semantic="regression",
        persist_registry=False,
        model_factory=model_factory,
        min_train_n=min_train_n,
        min_val_n=min_val_n,
        random_seed=experiment.model_seed,
    )
    ranker = run_chronological_oos(
        frame,
        semantic="ranking",
        persist_registry=False,
        model_factory=model_factory,
        min_train_n=min_train_n,
        min_val_n=min_val_n,
        random_seed=experiment.model_seed,
    )
    ablation = run_v4_ablation(
        frame,
        semantic="ranking",
        persist_registry=False,
        model_factory=model_factory,
        min_train_n=min_train_n,
        min_val_n=min_val_n,
        random_seed=experiment.model_seed,
    )
    base_preds = (ablation.get("variants") or {}).get("BASE", {}).get("predictions")
    full_preds = (ablation.get("variants") or {}).get("V4_FULL", {}).get("predictions")
    if isinstance(base_preds, pd.DataFrame) and isinstance(full_preds, pd.DataFrame):
        ablation["paired_delta"] = paired_v4_vs_base(full_preds, base_preds)
    rank_preds = ranker.get("predictions")
    stability = (
        slice_stability(rank_preds, semantic="ranking")
        if isinstance(rank_preds, pd.DataFrame)
        else {"status": "PENDING"}
    )
    economics: dict[str, Any] = {"status": "PENDING", "reason": "not_run"}
    if run_economics:
        econ_frame = _attach_econ_rows(
            ablation,
            fingerprint=experiment.experiment_fingerprint,
            values_hash=proof.get("dataset_v4_values_hash"),
        )
        if econ_frame is None:
            economics = {"status": "PENDING", "reason": "no_oos_predictions"}
        else:
            try:
                iids = set(int(x) for x in econ_frame["instrument_id"].unique())
                d0 = min(pd.to_datetime(econ_frame["as_of_date"]).dt.date)
                d1 = max(pd.to_datetime(econ_frame["as_of_date"]).dt.date)
                market = load_market_view(session, instrument_ids=iids, date_from=d0, date_to=d1)
                economics = run_all_model_variants(
                    predictions=econ_frame,
                    market=market,
                    expected_dataset_values_hash=proof.get("dataset_v4_values_hash"),
                    expected_experiment_fingerprint=experiment.experiment_fingerprint,
                )
            except (EconomicsProvenanceError, EconomicsContractError, ValueError) as exc:
                economics = {"status": "PARTIAL", "reason": str(exc)}
    try:
        prospective = build_prospective_evidence_v1(core_session=session)
    except Exception:  # noqa: BLE001 — prospective is optional overlay
        prospective = {"status": "PENDING", "reason": "prospective_unavailable"}

    record = experiment.to_record()
    root = experiment_dir(experiment.experiment_fingerprint, root=artifact_root)
    manifest = {
        **record,
        "bundle_status": "PARTIAL" if economics.get("status") in {"PENDING", "PARTIAL"} else "COMPLETE",
    }
    dataset_part = proof.get("dataset_compare") or {
        "sample_identity_match": proof.get("sample_identity_match"),
        "population": proof.get("population"),
        "schema": proof.get("schema"),
        "dataset_v3_run_id": proof["dataset_v3_run_id"],
        "dataset_v4_run_id": proof["dataset_v4_run_id"],
    }
    written = write_evidence_bundle(
        root,
        {
            "manifest": manifest,
            "dataset_compare": _jsonable(dataset_part),
            "model_regression": _jsonable(regression),
            "model_ranker": _jsonable(ranker),
            "ablation": _jsonable(ablation),
            "stability": _jsonable(stability),
            "economics": _jsonable(economics),
            "prospective": _jsonable(prospective),
        },
    )
    overview = overview_from_dir(root)
    write_evidence_bundle(
        root,
        {
            "manifest": manifest,
            "dataset_compare": _jsonable(dataset_part),
            "model_regression": _jsonable(regression),
            "model_ranker": _jsonable(ranker),
            "ablation": _jsonable(ablation),
            "stability": _jsonable(stability),
            "economics": _jsonable(economics),
            "prospective": _jsonable(prospective),
            "evidence_overview": overview,
        },
    )
    return {
        "experiment_fingerprint": experiment.experiment_fingerprint,
        "artifact_root": str(root),
        "bundle_hash": written["bundle_hash"],
        "overview": overview,
        "persist_registry": False,
        "research_only": True,
    }


def run_historical_evidence_task(**kwargs: Any) -> dict[str, Any]:
    with core_session() as session:
        return run_historical_evidence(session, **kwargs)
