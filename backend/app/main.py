"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1.router import api_router
from app.application.system.event_log import cleanup_old_days, enforce_day_limit, new_trace_id
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.responses import UTF8JSONResponse
from app.infrastructure.db.session import core_session

logger = get_logger(__name__)


class TraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get("x-trace-id") or request.headers.get("X-Trace-Id")
        trace_id = (incoming or new_trace_id()).strip()[:64] or new_trace_id()
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    settings = get_settings()
    logger.info("service_starting", extra={"component": "backend", "env": settings.app_env})
    try:
        with core_session() as session:
            deleted = cleanup_old_days(session)
            trimmed = enforce_day_limit(session)
            from app.modules.analytics.application.seed import seed_feature_sets

            seed_feature_sets(session)
        if deleted or trimmed:
            logger.info(
                "technology_log_safety_cleanup",
                extra={"deleted_old": deleted, "trimmed": trimmed},
            )
    except Exception as exc:  # noqa: BLE001 — startup must not fail on cleanup
        logger.warning("technology_log_cleanup_failed", extra={"error": str(exc)})
    # Catch-up: if live automation is on and Shadow exists with lagging analytics, trigger once.
    try:
        with core_session() as session:
            from app.modules.shadow.application.daily_operations import maybe_startup_catchup

            catchup = maybe_startup_catchup(session)
            logger.info("startup_research_catchup", extra={"catchup": catchup})
    except Exception as exc:  # noqa: BLE001 — broker/DB must not block boot
        logger.warning("startup_research_catchup_failed", extra={"error": str(exc)})
    # Instrument Master stale catch-up (non-blocking schedule only).
    try:
        with core_session() as session:
            from app.modules.market.application.instrument_master_sync import (
                maybe_startup_instrument_master_catchup,
            )

            master_catchup = maybe_startup_instrument_master_catchup(session)
            logger.info("startup_instrument_master_catchup", extra={"catchup": master_catchup})
    except Exception as exc:  # noqa: BLE001
        logger.warning("startup_instrument_master_catchup_failed", extra={"error": str(exc)})
    # FI enrichment: optional P0 enqueue for Manual/Shadow bond positions only.
    try:
        with core_session() as session:
            from app.modules.investment.application.enrichment_service import (
                maybe_startup_fi_enrichment_p0,
            )

            fi_catchup = maybe_startup_fi_enrichment_p0(session)
            session.commit()
            logger.info("startup_fi_enrichment_p0", extra={"catchup": fi_catchup})
    except Exception as exc:  # noqa: BLE001
        logger.warning("startup_fi_enrichment_p0_failed", extra={"error": str(exc)})
    yield
    logger.info("service_stopping", extra={"component": "backend"})


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        default_response_class=UTF8JSONResponse,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(TraceIdMiddleware)
    application.include_router(api_router, prefix="/api/v1")
    return application


app = create_app()
