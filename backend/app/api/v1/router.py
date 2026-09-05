"""Aggregate API v1 routers."""

from fastapi import APIRouter

from app.api.v1.analytics import router as analytics_router
from app.api.v1.fundamentals import router as fundamentals_router
from app.api.v1.learning import router as learning_router
from app.api.v1.market import router as market_router
from app.api.v1.market import workflows_router
from app.api.v1.market_history import router as market_history_router
from app.api.v1.model_edge import router as model_edge_router
from app.api.v1.predictions import router as predictions_router
from app.api.v1.relations import router as relations_router
from app.api.v1.research_cycle import router as research_cycle_router
from app.api.v1.research_lab import router as research_lab_router
from app.api.v1.shadow import router as shadow_router
from app.api.v1.simulator import router as simulator_router
from app.api.v1.system import router as system_router
from app.api.v1.technical import router as technical_router

api_router = APIRouter()
api_router.include_router(system_router, prefix="/system", tags=["system"])
api_router.include_router(market_router, prefix="/market", tags=["market"])
api_router.include_router(
    market_history_router, prefix="/market-history/external", tags=["market-history"]
)
api_router.include_router(analytics_router, prefix="/analytics", tags=["analytics"])
api_router.include_router(relations_router, prefix="/relations", tags=["relations"])
api_router.include_router(technical_router, prefix="/technical", tags=["technical"])
api_router.include_router(learning_router, prefix="/learning", tags=["learning"])
api_router.include_router(predictions_router, prefix="/predictions", tags=["predictions"])
api_router.include_router(shadow_router, prefix="/shadow", tags=["shadow"])
api_router.include_router(simulator_router, prefix="/simulator", tags=["simulator"])
api_router.include_router(research_lab_router, prefix="/research-lab", tags=["research-lab"])
api_router.include_router(research_cycle_router, prefix="/research-cycle", tags=["research-cycle"])
api_router.include_router(model_edge_router, tags=["model-edge"])
api_router.include_router(fundamentals_router, prefix="/fundamentals", tags=["fundamentals"])
api_router.include_router(workflows_router, prefix="/workflows", tags=["workflows"])
