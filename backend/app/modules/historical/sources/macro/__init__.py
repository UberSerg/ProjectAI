"""Macro historical sources owned by HDS-MACRO."""

from app.modules.historical.sources.macro.eia import EiaNaturalGasSource, EiaPetroleumSource
from app.modules.historical.sources.macro.rosstat_cpi import RosstatCpiSource
from app.modules.historical.sources.macro.rosstat_industry import (
    RosstatIndustrialProductionSource,
    RosstatUnemploymentSource,
)

__all__ = [
    "EiaNaturalGasSource",
    "EiaPetroleumSource",
    "RosstatCpiSource",
    "RosstatIndustrialProductionSource",
    "RosstatUnemploymentSource",
]
