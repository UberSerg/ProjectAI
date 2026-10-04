"""Build or load paired Dataset V3/V4 runs for Canonical Evidence Campaign V1.

Uses existing PITDatasetBuilder (via compare_v3_v4_builds) and prove_paired_v3_v4.
Never seeds or activates DatasetSpec. Never trains models.
FAIR_CONTRACT_FAIL stops the campaign.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.learning.models import DatasetSpec
from app.modules.learning.application.compare_v3_v4 import (
    CompareContractError,
    compare_v3_v4_builds,
)
from app.modules.learning.application.research_eval import FairCompareError
from app.modules.learning.application.seed import snapshot_dataset_spec_flags
from app.modules.learning.dataset_config import (
    PIT_DAILY_CORE_ACTIVE_VERSION,
    PIT_DAILY_CORE_CODE,
    PIT_DAILY_CORE_V3_VERSION,
    PIT_DAILY_CORE_V4_VERSION,
)
from app.modules.market.application.historical_universe import HISTORICAL_EQUITY_UNIVERSE_V2
from app.modules.research_evidence.campaign_contract import CanonicalEvidenceCampaignV1
from app.modules.research_evidence.pairing import prove_paired_v3_v4


def _fair_stop(exc: BaseException) -> FairCompareError:
    text = str(exc)
    if "FAIR_CONTRACT_FAIL" not in text:
        text = f"FAIR_CONTRACT_FAIL: {text}"
    if isinstance(exc, FairCompareError) and "FAIR_CONTRACT_FAIL" in str(exc):
        return exc
    return FairCompareError(text)


def _require_persist_registry_false(persist_registry: bool) -> None:
    if persist_registry:
        raise ValueError(
            "persist_registry must be false: campaign must not mutate "
            "the production candidate registry"
        )


def _load_spec(session: Session, version: int) -> DatasetSpec:
    spec = session.scalar(
        select(DatasetSpec).where(
            DatasetSpec.code == PIT_DAILY_CORE_CODE,
            DatasetSpec.version == version,
        )
    )
    if spec is None:
        raise CompareContractError(
            f"missing DatasetSpec {PIT_DAILY_CORE_CODE}/v{version}; "
            "campaign does not seed or activate specs"
        )
    if spec.is_active:
        raise ValueError(
            f"campaign must not run against an activated {PIT_DAILY_CORE_CODE}/v{version} spec"
        )
    universe = getattr(spec, "universe_policy", None)
    if universe != HISTORICAL_EQUITY_UNIVERSE_V2:
        raise FairCompareError(
            "FAIR_CONTRACT_FAIL: campaign universe must be "
            f"{HISTORICAL_EQUITY_UNIVERSE_V2} (got {universe!r} on v{version})"
        )
    return spec


def assert_campaign_specs_ready(session: Session) -> dict[str, Any]:
    """Require V3/V4 research specs without seeding or activating them."""
    if PIT_DAILY_CORE_ACTIVE_VERSION != 1:
        raise ValueError("PIT_DAILY_CORE_ACTIVE_VERSION must remain 1")
    spec_v3 = _load_spec(session, PIT_DAILY_CORE_V3_VERSION)
    spec_v4 = _load_spec(session, PIT_DAILY_CORE_V4_VERSION)
    active = session.scalar(
        select(DatasetSpec).where(
            DatasetSpec.code == PIT_DAILY_CORE_CODE,
            DatasetSpec.is_active.is_(True),
        )
    )
    if active is not None and int(active.version) != PIT_DAILY_CORE_ACTIVE_VERSION:
        raise ValueError(
            "active pit_daily_core must remain v1 during campaign "
            f"(got version={active.version})"
        )
    return {
        "active_version": PIT_DAILY_CORE_ACTIVE_VERSION,
        "v3_spec_id": spec_v3.id,
        "v4_spec_id": spec_v4.id,
        "universe_policy": HISTORICAL_EQUITY_UNIVERSE_V2,
    }


def _assert_activation_unchanged(
    before: list[dict[str, Any]], after: list[dict[str, Any]]
) -> dict[str, Any]:
    if before != after:
        raise ValueError("campaign must not mutate DatasetSpec activation flags")
    return {
        "before": before,
        "after": after,
        "unchanged": True,
        "current_product_expected_active_version": PIT_DAILY_CORE_ACTIVE_VERSION,
    }


def campaign_from_proof(
    proof: dict[str, Any],
    *,
    data_snapshot_hash: str | None = None,
    created_at: datetime | str | None = None,
    persist_registry: bool = False,
) -> CanonicalEvidenceCampaignV1:
    _require_persist_registry_false(persist_registry)
    if (
        proof.get("fair_contract_status") != "PASS"
        or proof.get("sample_identity_match") is not True
        or proof.get("target_identity_match") is not True
    ):
        raise FairCompareError(
            "FAIR_CONTRACT_FAIL: campaign stops without proven paired V3/V4 identity"
        )
    return CanonicalEvidenceCampaignV1(
        dataset_v3_run_id=int(proof["dataset_v3_run_id"]),
        dataset_v4_run_id=int(proof["dataset_v4_run_id"]),
        dataset_v3_hash=str(proof["dataset_v3_hash"] or ""),
        dataset_v4_hash=str(proof["dataset_v4_hash"] or ""),
        dataset_v3_values_hash=proof.get("dataset_v3_values_hash"),
        dataset_v4_values_hash=proof.get("dataset_v4_values_hash"),
        date_from=proof["date_from"],
        date_to=proof["date_to"],
        data_snapshot_hash=data_snapshot_hash,
        persist_registry=False,
        created_at=created_at,
    )


def build_or_load_paired_v3_v4(
    session: Session,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    v3_run_id: int | None = None,
    v4_run_id: int | None = None,
    instrument_ids: list[int] | None = None,
    rebuild: bool = True,
    persist_registry: bool = False,
    data_snapshot_hash: str | None = None,
    created_at: datetime | str | None = None,
    progress_callback: Any | None = None,
    expected_samples: int | None = None,
) -> dict[str, Any]:
    """Load existing paired runs or build them via compare_v3_v4; then prove identity.

    Does not call seed_dataset_specs. Does not train models.
    """
    _require_persist_registry_false(persist_registry)
    specs = assert_campaign_specs_ready(session)
    active_before = snapshot_dataset_spec_flags(session)
    compare: dict[str, Any] | None = None
    try:
        if v3_run_id is not None and v4_run_id is not None:
            proof = prove_paired_v3_v4(session, int(v3_run_id), int(v4_run_id))
        else:
            if date_from is None or date_to is None:
                raise ValueError(
                    "paired campaign needs v3_run_id and v4_run_id or explicit date_from/date_to"
                )
            compare = compare_v3_v4_builds(
                session,
                date_from=date_from,
                date_to=date_to,
                instrument_ids=instrument_ids,
                v3_run_id=v3_run_id,
                v4_run_id=v4_run_id,
                rebuild=rebuild,
                progress_callback=progress_callback,
                expected_samples=expected_samples,
            )
            sample_status = (compare.get("sample_diff") or {}).get("fair_contract_status")
            if sample_status == "FAIR_CONTRACT_FAIL":
                raise FairCompareError(
                    "FAIR_CONTRACT_FAIL: V3/V4 sample identity mismatch; campaign stops"
                )
            v3_id = int((compare.get("v3") or {})["run_id"])
            v4_id = int((compare.get("v4") or {})["run_id"])
            proof = prove_paired_v3_v4(session, v3_id, v4_id)
    except (FairCompareError, CompareContractError, ValueError) as exc:
        if isinstance(exc, ValueError) and "persist_registry" in str(exc):
            raise
        if isinstance(exc, ValueError) and "date_from" in str(exc) and "date_to" in str(exc):
            raise
        if isinstance(exc, ValueError) and "activate" in str(exc).lower():
            raise
        if isinstance(exc, ValueError) and "must remain" in str(exc):
            raise
        raise _fair_stop(exc) from exc

    if (
        proof.get("fair_contract_status") != "PASS"
        or proof.get("sample_identity_match") is not True
        or proof.get("target_identity_match") is not True
    ):
        raise FairCompareError(
            "FAIR_CONTRACT_FAIL: campaign stops without proven paired V3/V4 identity"
        )

    active_after = snapshot_dataset_spec_flags(session)
    activation = _assert_activation_unchanged(active_before, active_after)
    campaign = campaign_from_proof(
        proof,
        data_snapshot_hash=data_snapshot_hash,
        created_at=created_at,
        persist_registry=False,
    )
    payload: dict[str, Any] = {
        "activation": activation,
        "campaign": campaign.to_record(),
        "campaign_fingerprint": campaign.campaign_fingerprint,
        "fair_contract_status": "PASS",
        "proof": proof,
        "specs": specs,
    }
    if compare is not None:
        payload["dataset_compare"] = compare
    return payload
