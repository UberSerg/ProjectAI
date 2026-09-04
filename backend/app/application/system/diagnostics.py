"""Build plaintext diagnostic report for operators / Cursor."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, selectinload

from app.application.system.event_log import list_events
from app.application.system.health import get_system_health
from app.application.system.info import get_system_info
from app.application.system.sanitize import sanitize_text
from app.infrastructure.analytics.models import FeatureRun, FeatureSet, InstrumentFeatureDaily
from app.infrastructure.analytics.relation_models import (
    RelationInput,
    RelationLagMetric,
    RelationRun,
    RelationSet,
    RelationSnapshot,
)
from app.infrastructure.market.models import (
    Candle,
    CorporateAction,
    DataQualityIssue,
    IngestionBatch,
    Instrument,
    InstrumentSource,
    Series,
    Workflow,
)
from app.infrastructure.technical.models import (
    InstrumentTechnicalFeatureDaily,
    TechnicalRun,
    TechnicalSignalDaily,
)
from app.modules.analytics.application.seed import seed_feature_sets
from app.modules.market.application.identity import windows_overlap
from app.modules.market.application.split_events import SPLIT_FEED_EVENT_TYPES
from app.modules.relations.application.seed import seed_relation_sets
from app.modules.technical.technical_config import RULES_V1_CODE, RULES_V1_VERSION, RULES_V2_VERSION


def _count_mapping_overlaps(session: Session) -> int:
    rows = list(session.scalars(select(InstrumentSource)))
    by_key: dict[tuple[int, str], list[InstrumentSource]] = {}
    for row in rows:
        by_key.setdefault((row.instrument_id, row.source), []).append(row)
    errors = 0
    for group in by_key.values():
        for index, left in enumerate(group):
            for right in group[index + 1 :]:
                if windows_overlap(left, right):
                    errors += 1
    return errors


def _mechanical_analytics_lines(session: Session) -> list[str]:
    v2 = session.scalar(select(FeatureSet).where(FeatureSet.code == "basic_daily", FeatureSet.version == 2))
    ca_count = (
        session.scalar(
            select(func.count())
            .select_from(CorporateAction)
            .where(CorporateAction.event_type.in_(SPLIT_FEED_EVENT_TYPES))
        )
        or 0
    )
    if v2 is None:
        return [
            "Mechanical adjustment (H4A): basic_daily v2 not seeded",
            f"Mechanical CA (SPLIT/REVERSE_SPLIT): {ca_count}",
        ]
    rows = (
        session.scalar(
            select(func.count())
            .select_from(InstrumentFeatureDaily)
            .where(InstrumentFeatureDaily.feature_set_id == v2.id)
        )
        or 0
    )
    latest = session.scalar(
        select(func.max(InstrumentFeatureDaily.date)).where(InstrumentFeatureDaily.feature_set_id == v2.id)
    )
    last_v2 = session.scalar(
        select(FeatureRun)
        .where(FeatureRun.feature_set_id == v2.id, FeatureRun.status.in_(["SUCCESS", "WARNING"]))
        .order_by(desc(FeatureRun.finished_at))
        .limit(1)
    )
    last_err = session.scalar(
        select(FeatureRun)
        .where(FeatureRun.feature_set_id == v2.id, FeatureRun.status == "ERROR")
        .order_by(desc(FeatureRun.created_at))
        .limit(1)
    )
    last_ts = last_v2.finished_at.isoformat() if last_v2 and last_v2.finished_at else "—"
    return [
        "Mechanical adjustment (H4A): basic_daily v2 (SPLIT/REVERSE_SPLIT; not total return)",
        f"V2 history coverage: rows={rows} latest={latest.isoformat() if latest else '—'}",
        f"Mechanical CA count: {ca_count}",
        f"Latest V2 run: {last_ts}",
        f"Latest V2 error: {last_err.error_message if last_err else '—'}",
    ]


def _relations_version_lines(session: Session, version: int) -> list[str]:
    row = session.scalar(
        select(RelationSet).where(RelationSet.code == "basic_relations", RelationSet.version == version)
    )
    label = f"Relations V{version}"
    if row is None:
        return [f"{label}: basic_relations v{version} not seeded"]
    params = row.parameters or {}
    pin_ver = params.get("analytics_feature_set_version")
    if pin_ver is None:
        pin_ver = 1
    basis = params.get("price_basis") or ("raw" if version == 1 else "—")
    status = "active" if row.is_active else "not active"
    snaps = (
        session.scalar(
            select(func.count()).select_from(RelationSnapshot).where(RelationSnapshot.relation_set_id == row.id)
        )
        or 0
    )
    valid = (
        session.scalar(
            select(func.count())
            .select_from(RelationSnapshot)
            .where(RelationSnapshot.relation_set_id == row.id, RelationSnapshot.is_valid.is_(True))
        )
        or 0
    )
    invalid = (
        session.scalar(
            select(func.count())
            .select_from(RelationSnapshot)
            .where(RelationSnapshot.relation_set_id == row.id, RelationSnapshot.is_valid.is_(False))
        )
        or 0
    )
    lags = (
        session.scalar(
            select(func.count())
            .select_from(RelationLagMetric)
            .join(RelationSnapshot, RelationLagMetric.snapshot_id == RelationSnapshot.id)
            .where(RelationSnapshot.relation_set_id == row.id)
        )
        or 0
    )
    latest = session.scalar(
        select(func.max(RelationSnapshot.as_of_date)).where(RelationSnapshot.relation_set_id == row.id)
    )
    last_run = session.scalar(
        select(RelationRun)
        .where(RelationRun.relation_set_id == row.id, RelationRun.status.in_(["SUCCESS", "WARNING", "NO_CHANGES"]))
        .order_by(desc(RelationRun.finished_at))
        .limit(1)
    )
    last_ts = last_run.finished_at.isoformat() if last_run and last_run.finished_at else "—"
    last_status = last_run.status if last_run else "—"
    return [
        f"{label}: basic_relations v{version} ({basis}; {status})",
        f"Analytics pin: basic_daily v{pin_ver}",
        f"V{version} snapshots: {snaps} valid={valid} invalid={invalid} lags={lags}",
        f"V{version} latest as_of: {latest.isoformat() if latest else '—'}",
        f"Latest V{version} run: {last_ts} status={last_status}",
    ]


def _technical_v2_lines(session: Session) -> list[str]:
    v2 = session.scalar(select(FeatureSet).where(FeatureSet.code == "technical_daily", FeatureSet.version == 2))
    if v2 is None:
        return [
            "Technical V2 (H5A): technical_daily v2 not seeded",
            f"Signal model: {RULES_V1_CODE} v{RULES_V2_VERSION} (not active)",
        ]
    rows = (
        session.scalar(
            select(func.count())
            .select_from(InstrumentTechnicalFeatureDaily)
            .where(InstrumentTechnicalFeatureDaily.feature_set_id == v2.id)
        )
        or 0
    )
    valid = (
        session.scalar(
            select(func.count())
            .select_from(InstrumentTechnicalFeatureDaily)
            .where(
                InstrumentTechnicalFeatureDaily.feature_set_id == v2.id,
                InstrumentTechnicalFeatureDaily.is_valid.is_(True),
            )
        )
        or 0
    )
    invalid = (
        session.scalar(
            select(func.count())
            .select_from(InstrumentTechnicalFeatureDaily)
            .where(
                InstrumentTechnicalFeatureDaily.feature_set_id == v2.id,
                InstrumentTechnicalFeatureDaily.is_valid.is_(False),
            )
        )
        or 0
    )
    latest = session.scalar(
        select(func.max(InstrumentTechnicalFeatureDaily.date)).where(
            InstrumentTechnicalFeatureDaily.feature_set_id == v2.id
        )
    )
    last_v2 = session.scalar(
        select(TechnicalRun)
        .where(
            TechnicalRun.model_code == RULES_V1_CODE,
            TechnicalRun.model_version == RULES_V2_VERSION,
            TechnicalRun.status.in_(["SUCCESS", "WARNING"]),
        )
        .order_by(desc(TechnicalRun.finished_at))
        .limit(1)
    )
    last_ts = last_v2.finished_at.isoformat() if last_v2 and last_v2.finished_at else "—"
    return [
        "Technical V2 (H5A): technical_daily v2 (mechanical-adjusted; not active)",
        f"V2 rows: {rows} valid={valid} invalid={invalid} latest={latest.isoformat() if latest else '—'}",
        f"Signal model: {RULES_V1_CODE} v{RULES_V2_VERSION} (same scoring, pinned to Analytics v2)",
        f"Latest V2 run: {last_ts}",
    ]


def _dataset_v2_lines(session: Session) -> list[str]:
    from app.infrastructure.learning.models import DatasetRun, DatasetSpec

    v2 = session.scalar(select(DatasetSpec).where(DatasetSpec.code == "pit_daily_core", DatasetSpec.version == 2))
    if v2 is None:
        return [
            "Dataset V2 (H6): pit_daily_core v2 not seeded",
            "Deep History ML-ready: NO",
        ]
    last = session.scalar(
        select(DatasetRun)
        .where(DatasetRun.dataset_spec_id == v2.id, DatasetRun.status.in_(["SUCCESS", "WARNING"]))
        .order_by(desc(DatasetRun.finished_at))
        .limit(1)
    )
    values_hash = ((last.manifest or {}) if last else {}).get("values_hash", "—") if last else "—"
    ready = "YES" if last is not None else "NO"
    return [
        "Dataset V2 (H6): pit_daily_core v2 (mechanical price-return labels; not active)",
        (
            "Pins: Analytics basic_daily v2 | Technical technical_daily v2 | "
            "rules v2 | Relations basic_relations v2"
        ),
        f"Samples (last V2 run): {last.samples_total if last else 0}",
        (
            f"Coverage: {last.date_from.isoformat() if last and last.date_from else '—'} → "
            f"{last.date_to.isoformat() if last and last.date_to else '—'}"
        ),
        f"PIT: {last.pit_status if last else '—'}",
        f"values_hash: {values_hash}",
        f"Deep History ML-ready: {ready} (mechanical price returns only; dividends deferred)",
    ]


def _prediction_ml_lines(session: Session) -> list[str]:
    from sqlalchemy import text

    from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG

    row = session.execute(
        text(
            """
SELECT model_name, model_version, status, metrics, parameters, training_dataset
FROM learning.model_registry
WHERE model_name = :name AND model_version = :version
"""
        ),
        {
            "name": CANDIDATE_V0_CONFIG.candidate_name,
            "version": CANDIDATE_V0_CONFIG.candidate_version,
        },
    ).mappings().first()
    lines = [
        "=== PREDICTION ML ===",
        "",
        "Prediction ML: Candidate V0",
        "Dataset: pit_daily_core v2",
        "Target: 20d mechanical return",
        "Model: CatBoostRegressor",
    ]
    if row is None:
        lines.extend(["Status: not trained", "Research verdict: —"])
        return lines
    params = row["parameters"] or {}
    metrics = row["metrics"] or {}
    lines.extend(
        [
            f"Status: {row['status']}",
            f"Research verdict: {params.get('research_verdict', '—')}",
            f"Config hash: {params.get('config_hash', '—')}",
            f"Training dataset: {row['training_dataset'] or '—'}",
            f"Dev mean IC: {metrics.get('dev_mean_ic', '—')}",
            f"Holdout mean IC: {metrics.get('holdout_mean_ic', '—')}",
            "Note: research metrics on current cohort (survivorship); not Simulator PnL",
        ]
    )
    return lines


def _forward_signal_lines(session: Session) -> list[str]:
    from sqlalchemy import func, select

    from app.infrastructure.market.models import Candle
    from app.modules.prediction.infrastructure.forward_models import ForwardPredictionBatch

    lines = [
        "=== FORWARD SIGNAL ===",
        "",
        "Forward Signal V0",
        "Segment: FORWARD_LIVE",
        "Candidate: prediction_ml_candidate / v0 (frozen)",
    ]
    try:
        latest_batch = session.scalar(
            select(ForwardPredictionBatch)
            .where(ForwardPredictionBatch.status == "SUCCESS")
            .order_by(ForwardPredictionBatch.as_of_date.desc(), ForwardPredictionBatch.id.desc())
            .limit(1)
        )
    except Exception:  # noqa: BLE001 — table may not exist before migration
        lines.append("Status: migration pending / unavailable")
        return lines

    latest_mkt = session.scalar(select(func.max(Candle.timestamp)).where(Candle.timeframe == "1d"))
    latest_mkt_date = latest_mkt.date() if latest_mkt is not None and hasattr(latest_mkt, "date") else None

    if latest_batch is None:
        lines.extend(
            [
                "Latest batch: —",
                "Status: no forward predictions yet",
                f"Latest market date: {latest_mkt_date or '—'}",
            ]
        )
        return lines

    stale = (
        latest_mkt_date is not None
        and latest_batch.as_of_date is not None
        and latest_mkt_date > latest_batch.as_of_date
    )
    lines.extend(
        [
            f"Latest as_of: {latest_batch.as_of_date.isoformat()}",
            f"Latest batch id: {latest_batch.id}",
            f"Status: {latest_batch.status}" + (" / SIGNAL_STALE" if stale else ""),
            f"Candidate hash: {latest_batch.candidate_config_hash[:16]}…",
            f"Eligible: {latest_batch.eligible_count}",
            f"Predictions: {latest_batch.prediction_count}",
            f"Prediction hash: {latest_batch.prediction_hash or '—'}",
            f"PIT: {latest_batch.pit_status}",
            f"Generated_at: {latest_batch.generated_at.isoformat() if latest_batch.generated_at else '—'}",
            f"Latest market date: {latest_mkt_date or '—'}",
            "Note: not investment advice; outcomes PENDING_OUTCOME until +20 trading days",
        ]
    )
    return lines


def _shadow_portfolio_lines(session: Session) -> list[str]:
    from sqlalchemy import func, select

    from app.modules.shadow.infrastructure.models import (
        ShadowFill,
        ShadowOrder,
        ShadowPortfolio,
        ShadowPortfolioSpec,
    )

    lines = [
        "=== SHADOW PORTFOLIO ===",
        "",
        "Shadow Portfolio V0 (FORWARD_SHADOW — not Historical Simulator)",
    ]
    try:
        rows = session.execute(
            select(ShadowPortfolio, ShadowPortfolioSpec)
            .join(ShadowPortfolioSpec, ShadowPortfolio.spec_id == ShadowPortfolioSpec.id)
            .order_by(ShadowPortfolio.id)
        ).all()
    except Exception:  # noqa: BLE001
        lines.append("Status: migration pending / unavailable")
        return lines
    if not rows:
        lines.append("Status: not initialized")
        return lines
    for portfolio, spec in rows:
        pending = int(
            session.scalar(
                select(func.count()).select_from(ShadowOrder).where(
                    ShadowOrder.portfolio_id == portfolio.id, ShadowOrder.status == "PENDING"
                )
            )
            or 0
        )
        fills = int(
            session.scalar(
                select(func.count()).select_from(ShadowFill).where(
                    ShadowFill.portfolio_id == portfolio.id
                )
            )
            or 0
        )
        lines.extend(
            [
                f"— {spec.name}",
                f"  status: {portfolio.status}",
                f"  activated_at: {portfolio.activated_at.isoformat() if portfolio.activated_at else '—'}",
                "  latest forward batch: "
                f"{portfolio.last_processed_prediction_batch_id or portfolio.first_forward_batch_id}",
                f"  last market date: {portfolio.last_processed_market_date or '—'}",
                f"  last decision week: {portfolio.last_decision_iso_week or '—'}",
                f"  cash: {portfolio.cash:.2f}",
                f"  positions: {len(portfolio.positions or {})}",
                f"  pending orders: {pending}",
                f"  fills: {fills}",
                f"  risk state: {portfolio.risk_mode} (cap={portfolio.exposure_cap})",
            ]
        )
    return lines


def _simulator_lines(session: Session) -> list[str]:
    from sqlalchemy import text

    lines = [
        "=== SIMULATOR ===",
        "",
        "Historical Simulator V0: price-return portfolio life (dividends excluded)",
        "Policy: RANK_LONG_ONLY_V0 | Risk: guardrails only | Execution: next_open",
    ]
    try:
        row = session.execute(
            text(
                """
SELECT id, segment, status, date_from, date_to, values_hash, metrics, candidate_config_hash
FROM portfolio.simulation_runs
ORDER BY id DESC
LIMIT 1
"""
            )
        ).mappings().first()
    except Exception:  # noqa: BLE001 — table may not exist before migration
        lines.append("Status: schema not migrated")
        return lines
    if row is None:
        lines.extend(["Status: no runs", "Final NAV: —", "Max DD: —"])
        return lines
    metrics = row["metrics"] or {}
    lines.extend(
        [
            f"Last run: id={row['id']} status={row['status']} segment={row['segment']}",
            (
                f"Dates: {row['date_from'].isoformat() if row['date_from'] else '—'} → "
                f"{row['date_to'].isoformat() if row['date_to'] else '—'}"
            ),
            f"Candidate config hash: {row['candidate_config_hash'] or '—'}",
            f"Final NAV: {metrics.get('final_nav', '—')}",
            f"Total price return: {metrics.get('total_price_return', '—')}",
            f"Max DD: {metrics.get('max_drawdown', '—')}",
            f"values_hash: {row['values_hash'] or '—'}",
            "Note: survivorship bias; not production profitability",
        ]
    )
    return lines


def _svc(services: dict[str, str], key: str, label: str) -> str:
    value = services.get(key)
    if value is None:
        return f"{label}: UNKNOWN"
    return f"{label}: {value.upper()}"


def build_diagnostics_text(session: Session) -> str:
    info = get_system_info()
    health = get_system_health()
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    instruments = session.scalar(select(func.count()).select_from(Instrument)) or 0
    candles = session.scalar(select(func.count()).select_from(Candle)) or 0
    series = session.scalar(select(func.count()).select_from(Series)) or 0
    last_ts = session.scalar(select(func.max(Candle.timestamp)))
    split_count = (
        session.scalar(
            select(func.count())
            .select_from(CorporateAction)
            .where(CorporateAction.event_type.in_(SPLIT_FEED_EVENT_TYPES))
        )
        or 0
    )
    last_split_batch = session.scalar(
        select(IngestionBatch)
        .where(IngestionBatch.source == "MOEX", IngestionBatch.data_type == "splits")
        .order_by(desc(IngestionBatch.finished_at), desc(IngestionBatch.id))
        .limit(1)
    )
    last_split_at = "—"
    last_unresolved = "—"
    if last_split_batch is not None:
        last_split_at = (
            last_split_batch.finished_at.isoformat()
            if last_split_batch.finished_at
            else last_split_batch.status
        )
        last_unresolved = str((last_split_batch.meta or {}).get("unresolved", 0))
    source_total = session.scalar(select(func.count()).select_from(InstrumentSource)) or 0
    source_current = (
        session.scalar(
            select(func.count()).select_from(InstrumentSource).where(InstrumentSource.valid_to.is_(None))
        )
        or 0
    )
    source_historical = (
        session.scalar(
            select(func.count())
            .select_from(InstrumentSource)
            .where(InstrumentSource.valid_from.is_not(None))
        )
        or 0
    )
    source_proven = (
        session.scalar(
            select(func.count())
            .select_from(InstrumentSource)
            .where(InstrumentSource.valid_from.is_not(None), InstrumentSource.valid_to.is_(None))
        )
        or 0
    )
    source_unknown = (
        session.scalar(
            select(func.count())
            .select_from(InstrumentSource)
            .where(InstrumentSource.valid_from.is_(None), InstrumentSource.valid_to.is_(None))
        )
        or 0
    )
    source_closed = (
        session.scalar(
            select(func.count()).select_from(InstrumentSource).where(InstrumentSource.valid_to.is_not(None))
        )
        or 0
    )
    overlap_errors = _count_mapping_overlaps(session)
    dq_errors = (
        session.scalar(
            select(func.count())
            .select_from(DataQualityIssue)
            .where(DataQualityIssue.severity == "error", DataQualityIssue.resolved_at.is_(None))
        )
        or 0
    )
    dq_warnings = (
        session.scalar(
            select(func.count())
            .select_from(DataQualityIssue)
            .where(DataQualityIssue.severity == "warning", DataQualityIssue.resolved_at.is_(None))
        )
        or 0
    )

    workflows = list(
        session.scalars(
            select(Workflow)
            .options(selectinload(Workflow.steps))
            .order_by(desc(Workflow.started_at), desc(Workflow.id))
            .limit(10)
        ).all()
    )
    running = list(
        session.scalars(
            select(Workflow)
            .where(Workflow.status.in_(["RUNNING", "PENDING", "running", "pending"]))
            .order_by(desc(Workflow.started_at))
            .limit(20)
        ).all()
    )

    errors = list_events(session, level="ERROR", limit=100)
    warnings = list_events(session, level="WARNING", limit=100)
    infos = list_events(session, level="INFO", limit=200)

    lines: list[str] = [
        "ProjectAI Diagnostic Report",
        f"Generated: {now}",
        "",
        "=== APPLICATION ===",
        "",
        f"Version: {info.version}",
        f"Environment: {info.environment}",
        f"API: {info.api_version}",
        "",
        "=== HEALTH ===",
        "",
        _svc(health.services, "backend", "Backend"),
        _svc(health.services, "core_database", "Core DB"),
        _svc(health.services, "memory_database", "Memory DB"),
        _svc(health.services, "redis", "Redis"),
        _svc(health.services, "worker", "Worker"),
        "Scheduler: NOT MONITORED",
        "",
        "=== MARKET DATA ===",
        "",
        f"Instruments: {instruments}",
        f"Candles: {candles}",
        f"Series: {series}",
        f"Last market data: {last_ts.isoformat() if last_ts else '—'}",
        "",
        f"Corporate actions (SPLIT/REVERSE_SPLIT): {split_count}",
        f"Last SPLIT ingest: {last_split_at}",
        f"Unresolved last SPLIT run: {last_unresolved}",
        "",
        f"Instrument source mappings: {source_total}",
        f"Current mappings: {source_current}",
        f"Historical mappings: {source_historical}",
        (
            "MOEX source windows: "
            f"proven={source_proven} unknown={source_unknown} "
            f"historical={source_closed} overlaps={overlap_errors}"
        ),
        "RAW deep history: official ISS/CBR candles available (H3)",
        "Deep history ML-ready: NO — H4A/H5A/H5B mechanical only; pending H4B TR, H6",
        "",
    ]

    seed_feature_sets(session)
    active_fs = session.scalar(select(FeatureSet).where(FeatureSet.is_active.is_(True)))
    last_success_run = session.scalar(
        select(FeatureRun)
        .where(FeatureRun.status.in_(["SUCCESS", "WARNING"]))
        .order_by(desc(FeatureRun.finished_at))
        .limit(1)
    )
    analytics_latest = None
    instrument_feat_rows = 0
    series_feat_rows = 0
    invalid_rows = 0
    warning_rows = 0
    last_analytics_error = session.scalar(
        select(FeatureRun).where(FeatureRun.status == "ERROR").order_by(desc(FeatureRun.created_at)).limit(1)
    )
    if active_fs:
        analytics_latest = session.scalar(
            select(func.max(InstrumentFeatureDaily.date)).where(
                InstrumentFeatureDaily.feature_set_id == active_fs.id
            )
        )
        instrument_feat_rows = (
            session.scalar(
                select(func.count())
                .select_from(InstrumentFeatureDaily)
                .where(InstrumentFeatureDaily.feature_set_id == active_fs.id)
            )
            or 0
        )
        from app.infrastructure.analytics.models import SeriesFeatureDaily

        series_feat_rows = (
            session.scalar(
                select(func.count())
                .select_from(SeriesFeatureDaily)
                .where(SeriesFeatureDaily.feature_set_id == active_fs.id)
            )
            or 0
        )
        invalid_rows = (
            session.scalar(
                select(func.count())
                .select_from(InstrumentFeatureDaily)
                .where(
                    InstrumentFeatureDaily.feature_set_id == active_fs.id,
                    InstrumentFeatureDaily.is_valid.is_(False),
                )
            )
            or 0
        )
        warning_rows = (
            session.scalar(
                select(func.count())
                .select_from(InstrumentFeatureDaily)
                .where(
                    InstrumentFeatureDaily.feature_set_id == active_fs.id,
                    InstrumentFeatureDaily.quality_flags.contains({"price_discontinuity": True}),
                )
            )
            or 0
        )

    last_run_ts = (
        last_success_run.finished_at.isoformat()
        if last_success_run and last_success_run.finished_at
        else "—"
    )
    lines.extend(
        [
            "=== ANALYTICS ===",
            "",
            f"Active feature set: {active_fs.code} v{active_fs.version}" if active_fs else "Active feature set: —",
            f"Last successful feature run: {last_run_ts}",
            f"Latest calculated market date: {analytics_latest.isoformat() if analytics_latest else '—'}",
            f"Instrument feature rows: {instrument_feat_rows}",
            f"Series feature rows: {series_feat_rows}",
            f"Invalid rows: {invalid_rows}",
            f"Rows with quality warnings: {warning_rows}",
            f"Last analytics error: {last_analytics_error.error_message if last_analytics_error else '—'}",
            "",
            *_mechanical_analytics_lines(session),
            "",
        ]
    )

    seed_relation_sets(session)
    active_rs = session.scalar(select(RelationSet).where(RelationSet.is_active.is_(True)))
    last_rel_run = session.scalar(
        select(RelationRun)
        .where(RelationRun.status.in_(["SUCCESS", "WARNING", "NO_CHANGES"]))
        .order_by(desc(RelationRun.finished_at))
        .limit(1)
    )
    latest_as_of = session.scalar(select(func.max(RelationSnapshot.as_of_date)))
    inputs_active = (
        session.scalar(select(func.count()).select_from(RelationInput).where(RelationInput.is_active.is_(True)))
        or 0
    )
    snap_total = session.scalar(select(func.count()).select_from(RelationSnapshot)) or 0
    snap_valid = (
        session.scalar(
            select(func.count()).select_from(RelationSnapshot).where(RelationSnapshot.is_valid.is_(True))
        )
        or 0
    )
    snap_invalid = (
        session.scalar(
            select(func.count()).select_from(RelationSnapshot).where(RelationSnapshot.is_valid.is_(False))
        )
        or 0
    )
    last_rel_error = session.scalar(
        select(RelationRun).where(RelationRun.status == "ERROR").order_by(desc(RelationRun.created_at)).limit(1)
    )
    last_rel_ts = (
        last_rel_run.finished_at.isoformat() if last_rel_run and last_rel_run.finished_at else "—"
    )

    lines.extend(
        [
            "=== RELATIONS ===",
            "",
            (
                f"Active relation set: {active_rs.code} v{active_rs.version}"
                if active_rs
                else "Active relation set: —"
            ),
            f"Active relation inputs: {inputs_active}",
            f"Last successful relation run: {last_rel_ts}",
            f"Latest as_of_date: {latest_as_of.isoformat() if latest_as_of else '—'}",
            f"Snapshots total: {snap_total}",
            f"Snapshots valid: {snap_valid}",
            f"Snapshots invalid: {snap_invalid}",
            f"Last relations error: {last_rel_error.error_message if last_rel_error else '—'}",
            "",
            *_relations_version_lines(session, 1),
            "",
            *_relations_version_lines(session, 2),
            "",
        ]
    )

    seed_feature_sets(session)
    tech_fs = session.scalar(
        select(FeatureSet).where(FeatureSet.code == "technical_daily", FeatureSet.is_active.is_(True))
    )
    last_tech_run = session.scalar(
        select(TechnicalRun)
        .where(TechnicalRun.status.in_(["SUCCESS", "WARNING", "NO_CHANGES"]))
        .order_by(desc(TechnicalRun.finished_at))
        .limit(1)
    )
    tech_latest = session.scalar(select(func.max(TechnicalSignalDaily.as_of_date)))
    tech_signals = session.scalar(select(func.count()).select_from(TechnicalSignalDaily)) or 0
    tech_bullish = tech_neutral = tech_bearish = tech_invalid = 0
    if tech_latest is not None:
        latest_signals = list(
            session.scalars(select(TechnicalSignalDaily).where(TechnicalSignalDaily.as_of_date == tech_latest))
        )
        for sig in latest_signals:
            if not sig.is_valid:
                tech_invalid += 1
            if sig.direction == "bullish":
                tech_bullish += 1
            elif sig.direction == "bearish":
                tech_bearish += 1
            else:
                tech_neutral += 1
    last_tech_error = session.scalar(
        select(TechnicalRun).where(TechnicalRun.status == "ERROR").order_by(desc(TechnicalRun.finished_at)).limit(1)
    )
    last_tech_ts = (
        last_tech_run.finished_at.isoformat() if last_tech_run and last_tech_run.finished_at else "—"
    )
    lines.extend(
        [
            "=== TECHNICAL ===",
            "",
            f"Active model: {RULES_V1_CODE}_v{RULES_V1_VERSION}",
            (
                f"Technical feature set: {tech_fs.code} v{tech_fs.version}"
                if tech_fs
                else "Technical feature set: —"
            ),
            f"Latest successful run: {last_tech_ts}",
            f"Latest as-of: {tech_latest.isoformat() if tech_latest else '—'}",
            f"Signals: {tech_signals}",
            f"Bullish: {tech_bullish}",
            f"Neutral: {tech_neutral}",
            f"Bearish: {tech_bearish}",
            f"Invalid: {tech_invalid}",
            f"Latest technical error: {last_tech_error.error_message if last_tech_error else '—'}",
            "",
            *_technical_v2_lines(session),
            "",
        ]
    )

    from app.infrastructure.learning.models import DatasetRun, DatasetSpec
    from app.modules.learning.application.seed import seed_dataset_specs

    seed_dataset_specs(session)
    active_ds = session.scalar(select(DatasetSpec).where(DatasetSpec.is_active.is_(True)))
    last_ds = session.scalar(
        select(DatasetRun)
        .where(DatasetRun.status.in_(["SUCCESS", "WARNING"]))
        .order_by(desc(DatasetRun.finished_at))
        .limit(1)
    )
    last_ds_error = session.scalar(
        select(DatasetRun).where(DatasetRun.status == "ERROR").order_by(desc(DatasetRun.finished_at)).limit(1)
    )
    last_ds_ts = last_ds.finished_at.isoformat() if last_ds and last_ds.finished_at else "—"
    lines.extend(
        [
            "=== DATASET / PIT ===",
            "",
            (
                f"Active dataset spec: {active_ds.code} v{active_ds.version}"
                if active_ds
                else "Active dataset spec: —"
            ),
            f"Latest successful run: {last_ds_ts}",
            f"Dataset hash: {last_ds.dataset_hash if last_ds else '—'}",
            f"Samples: {last_ds.samples_total if last_ds else 0}",
            f"Eligible 1d: {last_ds.eligible_1d if last_ds else 0}",
            f"Eligible 5d: {last_ds.eligible_5d if last_ds else 0}",
            f"Eligible 10d: {last_ds.eligible_10d if last_ds else 0}",
            f"Eligible 20d: {last_ds.eligible_20d if last_ds else 0}",
            (
                "Relations coverage: "
                f"{((last_ds.coverage_summary or {}).get('relations') or {}).get('by_context') if last_ds else '—'}"
            ),
            (
                f"Label eligible 1/5/10/20d: {last_ds.eligible_1d}/{last_ds.eligible_5d}/"
                f"{last_ds.eligible_10d}/{last_ds.eligible_20d}"
                if last_ds
                else "Label eligible 1/5/10/20d: —"
            ),
            f"PIT violations: {last_ds.pit_violations if last_ds else 0}",
            f"Latest dataset error: {last_ds_error.error_message if last_ds_error else '—'}",
            "",
            *_dataset_v2_lines(session),
            "",
            *_prediction_ml_lines(session),
            "",
            *_forward_signal_lines(session),
            "",
            *_shadow_portfolio_lines(session),
            "",
            *_simulator_lines(session),
            "",
            "=== WORKFLOWS ===",
            "",
            "Last 10 processes:",
            "",
        ]
    )

    if not workflows:
        lines.append("(none)")
    for wf in workflows:
        lines.append(
            f"- id={wf.id} type={wf.workflow_type or wf.name} status={wf.status} "
            f"started={wf.started_at.isoformat() if wf.started_at else '—'}"
        )
        if wf.error:
            lines.append(f"  error: {sanitize_text(wf.error, max_len=300)}")

    lines.extend(["", "=== RUNNING WORKFLOWS ===", ""])
    if not running:
        lines.append("(none)")
    now_utc = datetime.now(UTC)
    for wf in running:
        age_min = "—"
        stale_hint = ""
        if wf.started_at is not None:
            started = wf.started_at if wf.started_at.tzinfo else wf.started_at.replace(tzinfo=UTC)
            age = (now_utc - started).total_seconds() / 60.0
            age_min = f"{age:.0f}m"
            # Light signal only — no auto-recovery. Worker death can leave RUNNING forever.
            if age >= 15:
                stale_hint = " [POSSIBLY STALE — check meta heartbeat / abort manually if worker restarted]"
        meta = wf.meta or {}
        progress = (
            meta.get("as_of_progress")
            or meta.get("persist_progress")
            or (
                f"{meta.get('processed_instruments')}/{meta.get('total_instruments')}"
                if meta.get("processed_instruments") is not None
                else ""
            )
        )
        progress_bit = f" progress={progress}" if progress else ""
        lines.append(
            f"- id={wf.id} type={wf.workflow_type or wf.name} status={wf.status} "
            f"age={age_min}{progress_bit}{stale_hint}"
        )

    lines.extend(
        [
            "",
            "=== DATA QUALITY ===",
            "",
            f"Current errors: {dq_errors}",
            f"Current warnings: {dq_warnings}",
            "",
            "=== ERRORS TODAY ===",
            "",
        ]
    )
    if not errors:
        lines.append("(none)")
    for ev in errors:
        lines.append(
            f"- {ev.timestamp.isoformat() if ev.timestamp else ''} [{ev.component}] "
            f"{ev.event_type}: {ev.message}"
        )
        if ev.workflow_id or ev.trace_id:
            lines.append(f"  workflow_id={ev.workflow_id} trace_id={ev.trace_id}")

    lines.extend(["", "=== RECENT WARNINGS ===", ""])
    if not warnings:
        lines.append("(none)")
    for ev in warnings:
        lines.append(
            f"- {ev.timestamp.isoformat() if ev.timestamp else ''} [{ev.component}] "
            f"{ev.event_type}: {ev.message}"
        )

    lines.extend(["", "=== RECENT EVENTS ===", ""])
    if not infos:
        lines.append("(none)")
    for ev in infos:
        lines.append(
            f"- {ev.timestamp.isoformat() if ev.timestamp else ''} [{ev.component}] "
            f"{ev.event_type}: {ev.message}"
        )

    lines.extend(["", "=== TRACE / IDS ===", ""])
    trace_lines: list[str] = []
    for ev in (*errors[:20], *warnings[:20], *infos[:20]):
        if ev.trace_id or ev.workflow_id:
            trace_lines.append(f"- event={ev.id} workflow_id={ev.workflow_id} trace_id={ev.trace_id}")
    lines.extend(trace_lines or ["(none)"])
    lines.append("")
    return "\n".join(lines)


def build_diagnostics_payload(session: Session) -> dict[str, Any]:
    return {"generated_at": datetime.now(UTC).isoformat(), "text": build_diagnostics_text(session)}
