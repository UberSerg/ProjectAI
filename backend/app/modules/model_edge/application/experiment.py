"""PROSPECTIVE_MODEL_AB_V0 activation and status.

Activation freezes "what was already knowable" as a market watermark. Every paired
comparison must belong to an as_of date strictly after that watermark, which is what makes
the experiment prospective rather than a re-scored replay of observed history.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Candle
from app.modules.model_edge.config import (
    CANDIDATE_A_NAME,
    CANDIDATE_A_VERSION,
    CANDIDATE_B_NAME,
    CANDIDATE_B_VERSION,
    EXPERIMENT_CODE,
    EXPERIMENT_HUMAN_NAME,
    INITIAL_CAPITAL,
    SEMANTIC_EXPECTED_RETURN,
    SEMANTIC_RANKING_SCORE,
    SHADOW_POLICY_NAME,
    SHADOW_PORTFOLIO_A_NAME,
    SHADOW_PORTFOLIO_B_NAME,
    SHADOW_RISK_NAME,
    STATUS_ACTIVE,
    STATUS_REGISTERED,
    candidate_a_config_hash,
    candidate_b_config_hash,
)
from app.modules.model_edge.domain.types import (
    ActivationWatermark,
    BackfillForbidden,
    CandidateRef,
    ProspectiveExperimentError,
)
from app.modules.model_edge.infrastructure.models import (
    ProspectiveModelComparisonBatch,
    ProspectiveModelExperiment,
)
from app.modules.shadow.application.service import initialize_empty_shadow_portfolios
from app.modules.shadow.config import model_ab_shadow_configs
from app.modules.shadow.infrastructure.models import ShadowPortfolio, ShadowPortfolioSpec


def latest_raw_market_date(session: Session) -> date | None:
    """Watermark of RAW daily observations. Read-only; market.candles is never written."""
    ts = session.scalar(select(func.max(Candle.timestamp)).where(Candle.timeframe == "1d"))
    return ts.date() if ts is not None else None


def candidate_a_ref() -> CandidateRef:
    return CandidateRef(
        name=CANDIDATE_A_NAME,
        version=CANDIDATE_A_VERSION,
        config_hash=candidate_a_config_hash(),
        prediction_semantic=SEMANTIC_EXPECTED_RETURN,
    )


def candidate_b_ref() -> CandidateRef:
    return CandidateRef(
        name=CANDIDATE_B_NAME,
        version=CANDIDATE_B_VERSION,
        config_hash=candidate_b_config_hash(),
        prediction_semantic=SEMANTIC_RANKING_SCORE,
    )


def get_experiment(session: Session) -> ProspectiveModelExperiment | None:
    return session.scalar(
        select(ProspectiveModelExperiment).where(
            ProspectiveModelExperiment.code == EXPERIMENT_CODE
        )
    )


def require_experiment(session: Session) -> ProspectiveModelExperiment:
    row = get_experiment(session)
    if row is None:
        raise ProspectiveExperimentError(
            f"{EXPERIMENT_CODE} is not activated; run `model_edge activate` first"
        )
    return row


def activation_watermark(experiment: ProspectiveModelExperiment) -> ActivationWatermark:
    return ActivationWatermark(
        activated_at=experiment.activated_at or datetime.now(UTC),
        market_watermark=experiment.activation_market_watermark,
    )


def assert_prospective(experiment: ProspectiveModelExperiment, as_of: date) -> None:
    """Reject any as_of that was already observable when the experiment was activated."""
    watermark = activation_watermark(experiment)
    if not watermark.allows(as_of):
        raise BackfillForbidden(
            f"as_of {as_of.isoformat()} is at or before the activation market watermark "
            f"{watermark.market_watermark}; historical paired backfill is not allowed"
        )


def activate_experiment(
    session: Session,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Register the experiment and freeze its activation watermark. Idempotent."""
    moment = now or datetime.now(UTC)
    existing = get_experiment(session)
    if existing is not None and existing.status == STATUS_ACTIVE:
        return {
            "status": "ALREADY_ACTIVE",
            **experiment_payload(session, existing),
        }

    watermark = latest_raw_market_date(session)
    a, b = candidate_a_ref(), candidate_b_ref()
    row = existing or ProspectiveModelExperiment(
        code=EXPERIMENT_CODE,
        human_name=EXPERIMENT_HUMAN_NAME,
        status=STATUS_REGISTERED,
        candidate_a_name=a.name,
        candidate_a_version=a.version,
        candidate_a_config_hash=a.config_hash,
        candidate_b_name=b.name,
        candidate_b_version=b.version,
        candidate_b_config_hash=b.config_hash,
        policy_name=SHADOW_POLICY_NAME,
        risk_name=SHADOW_RISK_NAME,
        capital=INITIAL_CAPITAL,
    )
    row.status = STATUS_ACTIVE
    row.activated_at = moment
    row.activation_market_watermark = watermark
    row.first_eligible_market_date = None
    row.metadata_ = {
        "candidate_a": a.to_dict(),
        "candidate_b": b.to_dict(),
        "shadow_portfolio_a_name": SHADOW_PORTFOLIO_A_NAME,
        "shadow_portfolio_b_name": SHADOW_PORTFOLIO_B_NAME,
        "historical_backfill": False,
        "only_intended_difference": "MODEL",
        "note": (
            "Paired comparisons are created only for as_of dates strictly after "
            "activation_market_watermark."
        ),
    }
    row.updated_at = moment
    if existing is None:
        session.add(row)
    session.flush()

    # Synchronized empty shadows — same activation instant, no pre-activation history.
    initialize_empty_shadow_portfolios(session, configs=model_ab_shadow_configs(), clock=lambda: moment)
    bind_shadow_portfolios(session, row)
    session.flush()
    return {"status": "ACTIVATED", **experiment_payload(session, row)}


def bind_shadow_portfolios(
    session: Session, experiment: ProspectiveModelExperiment
) -> dict[str, int | None]:
    """Attach already-created MODEL_AB shadow portfolio ids to the experiment row."""
    mapping = {
        SHADOW_PORTFOLIO_A_NAME: "shadow_portfolio_a_id",
        SHADOW_PORTFOLIO_B_NAME: "shadow_portfolio_b_id",
    }
    out: dict[str, int | None] = {}
    for name, attr in mapping.items():
        portfolio = session.scalar(
            select(ShadowPortfolio)
            .join(ShadowPortfolioSpec, ShadowPortfolio.spec_id == ShadowPortfolioSpec.id)
            .where(ShadowPortfolioSpec.name == name)
        )
        pid = portfolio.id if portfolio is not None else None
        setattr(experiment, attr, pid)
        out[name] = pid
    session.flush()
    return out


def experiment_payload(
    session: Session, experiment: ProspectiveModelExperiment
) -> dict[str, Any]:
    batches = list(
        session.scalars(
            select(ProspectiveModelComparisonBatch)
            .where(ProspectiveModelComparisonBatch.experiment_id == experiment.id)
            .order_by(ProspectiveModelComparisonBatch.as_of_date)
        )
    )
    return {
        "code": experiment.code,
        "human_name": experiment.human_name,
        "experiment_status": experiment.status,
        "activated_at": experiment.activated_at.isoformat()
        if experiment.activated_at
        else None,
        "activation_market_watermark": experiment.activation_market_watermark.isoformat()
        if experiment.activation_market_watermark
        else None,
        "first_eligible_market_date": experiment.first_eligible_market_date.isoformat()
        if experiment.first_eligible_market_date
        else None,
        "candidate_a": {
            "candidate_name": experiment.candidate_a_name,
            "candidate_version": experiment.candidate_a_version,
            "candidate_config_hash": experiment.candidate_a_config_hash,
            "prediction_semantic": SEMANTIC_EXPECTED_RETURN,
        },
        "candidate_b": {
            "candidate_name": experiment.candidate_b_name,
            "candidate_version": experiment.candidate_b_version,
            "candidate_config_hash": experiment.candidate_b_config_hash,
            "prediction_semantic": SEMANTIC_RANKING_SCORE,
        },
        "policy_name": experiment.policy_name,
        "risk_name": experiment.risk_name,
        "capital": float(experiment.capital),
        "shadow_portfolio_a_id": experiment.shadow_portfolio_a_id,
        "shadow_portfolio_b_id": experiment.shadow_portfolio_b_id,
        "comparison_batches": len(batches),
        "latest_comparison_as_of": batches[-1].as_of_date.isoformat() if batches else None,
        "historical_backfill": False,
        "metadata": experiment.metadata_ or {},
    }


def experiment_status(session: Session) -> dict[str, Any]:
    experiment = get_experiment(session)
    market_watermark = latest_raw_market_date(session)
    if experiment is None:
        return {
            "status": "NOT_ACTIVATED",
            "code": EXPERIMENT_CODE,
            "market_watermark": market_watermark.isoformat() if market_watermark else None,
            "candidate_a": candidate_a_ref().to_dict(),
            "candidate_b": candidate_b_ref().to_dict(),
        }
    payload = experiment_payload(session, experiment)
    payload["status"] = experiment.status
    payload["market_watermark"] = (
        market_watermark.isoformat() if market_watermark else None
    )
    payload["awaiting_new_market_date"] = bool(
        experiment.activation_market_watermark is not None
        and market_watermark is not None
        and market_watermark <= experiment.activation_market_watermark
    )
    return payload
