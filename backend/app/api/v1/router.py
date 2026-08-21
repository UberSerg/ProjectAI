"""Aggregate API v1 routers."""

from fastapi import APIRouter

from app.api.v1.system import router as system_router

api_router = APIRouter()
api_router.include_router(system_router, prefix="/system", tags=["system"])
