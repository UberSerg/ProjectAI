"""Test fixtures and shared env defaults."""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

# Defaults suit docker-compose service DNS. CI overrides via job env.
_DEFAULTS = {
    "APP_ENV": "test",
    "APP_NAME": "ProjectAI",
    "CORE_DATABASE_HOST": "postgres-core",
    "CORE_DATABASE_PORT": "5432",
    "CORE_DATABASE_NAME": "projectai_core",
    "CORE_DATABASE_USER": "projectai",
    "CORE_DATABASE_PASSWORD": "projectai_core_dev",
    "MEMORY_DATABASE_HOST": "postgres-memory",
    "MEMORY_DATABASE_PORT": "5432",
    "MEMORY_DATABASE_NAME": "projectai_memory",
    "MEMORY_DATABASE_USER": "projectai",
    "MEMORY_DATABASE_PASSWORD": "projectai_memory_dev",
    "REDIS_HOST": "redis",
    "REDIS_PORT": "6379",
    "REDIS_DB": "0",
    "CELERY_BROKER_URL": "redis://redis:6379/0",
    "CELERY_RESULT_BACKEND": "redis://redis:6379/1",
    "TECH_LOG_MAX_EVENTS_PER_DAY": "20000",
    "TECH_LOG_CLIENT_MAX_STACK_CHARS": "4000",
}

for key, value in _DEFAULTS.items():
    os.environ.setdefault(key, value)

from app.core.config import get_settings  # noqa: E402
from app.infrastructure.db.session import get_core_engine  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _block_live_moex_in_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ordinary automated tests must not call live MOEX (project rule + CI hangs).

    Blocks cold-start fetch when no provider is injected. Focused market tests may
    still pass an explicit ``provider`` (FakeProvider) through equity_mark /
    ensure_operational_quote. Patch both the operational_quote module (covers
    valuation.ensure_operational_quote → ensure_operational_quotes) and the
    personal_portfolio_service local import binding.
    """
    from app.modules.market.application import operational_quote as _oq

    _original_ensure = _oq.ensure_operational_quotes

    def _no_network_quotes(session, instruments, *, cache=None, provider=None):  # noqa: ANN001
        if provider is not None:
            return _original_ensure(session, instruments, cache=cache, provider=provider)

        from app.modules.market.application.intraday_cache import IntradayQuoteCache
        from app.modules.market.application.operational_quote import resolve_board_secid

        class _NoRedis:
            def get(self, *_a, **_k):  # noqa: ANN001
                return None

            def set(self, *_a, **_k):  # noqa: ANN001
                return True

        quote_cache = cache if cache is not None else IntradayQuoteCache(client=_NoRedis())
        out = {}
        for inst in instruments or []:
            board, secid = resolve_board_secid(session, inst)
            hit = quote_cache.get(board, secid)
            if hit is not None:
                out[(board, secid)] = hit
        return out

    monkeypatch.setattr(
        "app.modules.market.application.operational_quote.ensure_operational_quotes",
        _no_network_quotes,
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.personal_portfolio_service.ensure_operational_quotes",
        _no_network_quotes,
    )


@pytest.fixture
def core_db() -> Generator[Session, None, None]:
    """Transactional core DB session; rolled back after each test.

    Uses a connection-bound session so ORM flushes stay inside the outer
    transaction and never persist to the shared CI/dev database.
    """
    engine = get_core_engine()
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, autoflush=False, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
