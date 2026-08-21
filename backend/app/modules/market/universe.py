"""Curated Market Data V1 universe."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InstrumentDefinition:
    symbol: str
    name: str
    asset_class: str = "equity"
    currency: str = "RUB"
    exchange: str = "MOEX"
    source: str = "MOEX"
    board: str = "TQBR"


@dataclass(frozen=True, slots=True)
class SeriesDefinition:
    code: str
    name: str
    unit: str
    source: str
    external_id: str


_STOCKS = (
    ("SBER", "Sberbank"),
    ("LKOH", "Lukoil"),
    ("ROSN", "Rosneft"),
    ("GAZP", "Gazprom"),
    ("NVTK", "NOVATEK"),
    ("GMKN", "Nornickel"),
    ("PLZL", "Polyus"),
    ("YDEX", "Yandex"),
    ("T", "T-Technologies"),
    ("MGNT", "Magnit"),
    ("SBERP", "Sberbank preferred"),
    ("TATN", "Tatneft"),
    ("TATNP", "Tatneft preferred"),
    ("SNGS", "Surgutneftegas"),
    ("SNGSP", "Surgutneftegas preferred"),
    ("CHMF", "Severstal"),
    ("NLMK", "NLMK"),
    ("MAGN", "MMK"),
    ("ALRS", "ALROSA"),
    ("MTSS", "MTS"),
    ("MOEX", "Moscow Exchange"),
    ("VTBR", "VTB"),
    ("RUAL", "RUSAL"),
    ("PHOR", "PhosAgro"),
    ("PIKK", "PIK"),
    ("AFLT", "Aeroflot"),
    ("IRAO", "Inter RAO"),
    ("HYDR", "RusHydro"),
    ("FEES", "Rosseti"),
    ("TRNFP", "Transneft preferred"),
    ("BSPB", "Bank Saint Petersburg"),
    ("CBOM", "Credit Bank of Moscow"),
    ("FLOT", "Sovcomflot"),
    ("AFKS", "Sistema"),
    ("RTKM", "Rostelecom"),
    ("RTKMP", "Rostelecom preferred"),
    ("UPRO", "Unipro"),
    ("ENPG", "EN+ Group"),
    ("OZON", "Ozon"),
    ("HEAD", "HeadHunter"),
)

INSTRUMENTS = tuple(InstrumentDefinition(symbol, name) for symbol, name in _STOCKS) + (
    InstrumentDefinition("IMOEX", "MOEX Russia Index", asset_class="index", board="SNDX"),
    InstrumentDefinition("RTSI", "RTS Index", asset_class="index", board="RTSI"),
    InstrumentDefinition("RGBI", "Russian Government Bond Index", asset_class="index", board="SNDX"),
)

SERIES = (
    SeriesDefinition("KEY_RATE", "CBR key rate", "percent", "CBR", "KEY_RATE"),
    SeriesDefinition("RUONIA", "RUONIA overnight rate", "percent", "CBR", "RUONIA"),
    SeriesDefinition("USD_RUB_CBR", "Official USD/RUB", "RUB", "CBR", "R01235"),
    SeriesDefinition("EUR_RUB_CBR", "Official EUR/RUB", "RUB", "CBR", "R01239"),
    SeriesDefinition("CNY_RUB_CBR", "Official CNY/RUB", "RUB", "CBR", "R01375"),
)
