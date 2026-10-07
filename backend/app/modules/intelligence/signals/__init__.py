"""Independent analytical model adapters emitting SignalOutputV1.

Models do not read each other. Committee is the first combination layer.
No orders / broker intents.
"""

from app.modules.intelligence.signals.collect import collect_instrument_signals
from app.modules.intelligence.signals.cross_sectional_ml import CrossSectionalMLModelV1
from app.modules.intelligence.signals.event import EventModelV1
from app.modules.intelligence.signals.fundamental import FundamentalModelV1
from app.modules.intelligence.signals.intraday import IntradayStructureModelV1
from app.modules.intelligence.signals.macro import MacroModelV1
from app.modules.intelligence.signals.technical import TechnicalModelV1

__all__ = [
    "CrossSectionalMLModelV1",
    "EventModelV1",
    "FundamentalModelV1",
    "IntradayStructureModelV1",
    "MacroModelV1",
    "TechnicalModelV1",
    "collect_instrument_signals",
]
