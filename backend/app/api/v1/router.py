"""Aggregate API v1 routers."""

from fastapi import APIRouter

from app.api.v1.analytics import router as analytics_router
from app.api.v1.learning import router as learning_router
from app.api.v1.market import router as market_router
from app.api.v1.market import workflows_router
from app.api.v1.relations import router as relations_router
from app.api.v1.system import router as system_router
from app.api.v1.technical import router as technical_router

api_router = APIRouter()
api_router.include_router(system_router, prefix="/system", tags=["system"])
api_router.include_router(market_router, prefix="/market", tags=["market"])
api_router.include_router(analytics_router, prefix="/analytics", tags=["analytics"])
api_router.include_router(relations_router, prefix="/relations", tags=["relations"])
api_router.include_router(technical_router, prefix="/technical", tags=["technical"])
api_router.include_router(learning_router, prefix="/learning", tags=["learning"])
api_router.include_router(workflows_router, prefix="/workflows", tags=["workflows"])

