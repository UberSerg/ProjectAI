"""Intraday Redis cache behaviour — fake client, no live Redis required."""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.domain.ports.intraday_market import (
    IntradayQuote,
    MarketSessionStatus,
    QuoteFreshness,
)
from app.modules.market.application.intraday_cache import IntradayQuoteCache, quote_key


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    def get(self, key: str) -> str | None:
        return self.store.get(key)


class _BrokenRedis:
    def set(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise ConnectionError("down")

    def get(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise ConnectionError("down")


def _quote() -> IntradayQuote:
    return IntradayQuote(
        secid="SBER",
        board="TQBR",
        trading_date=date(2026, 9, 5),
        observed_at=datetime(2026, 9, 5, 10, 5, tzinfo=UTC),
        source_timestamp=datetime(2026, 9, 5, 10, 5, tzinfo=UTC),
        market_status=MarketSessionStatus.OPEN,
        open_price=251.0,
        last_price=252.0,
        bid=251.5,
        ask=252.1,
        previous_close=249.0,
        volume=1000.0,
        source="MOEX_ISS",
        freshness=QuoteFreshness.LIVE,
        quality="ok",
        instrument_id=7,
    )


def test_cache_roundtrip_and_ttl() -> None:
    fake = _FakeRedis()
    cache = IntradayQuoteCache(ttl_seconds=1200, client=fake)
    assert cache.set(_quote()) is True
    key = quote_key("TQBR", "SBER")
    assert key in fake.store
    assert fake.ttls[key] == 1200
    got = cache.get("TQBR", "SBER")
    assert got is not None
    assert got.open_price == 251.0
    assert got.instrument_id == 7


def test_cache_missing_returns_none() -> None:
    cache = IntradayQuoteCache(ttl_seconds=60, client=_FakeRedis())
    assert cache.get("TQBR", "MISSING") is None


def test_cache_unavailable_returns_none_no_fake_data() -> None:
    cache = IntradayQuoteCache(ttl_seconds=60, client=_BrokenRedis())
    assert cache.set(_quote()) is False
    assert cache.get("TQBR", "SBER") is None


def test_get_many() -> None:
    fake = _FakeRedis()
    cache = IntradayQuoteCache(ttl_seconds=60, client=fake)
    cache.set(_quote())
    many = cache.get_many([("TQBR", "SBER"), ("TQBR", "GAZP")])
    assert ("TQBR", "SBER") in many
    assert ("TQBR", "GAZP") not in many
