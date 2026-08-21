"""Dual PostgreSQL connections: core (ops) and memory (Decision Memory)."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__, component="infrastructure")

_core_engine: Engine | None = None
_memory_engine: Engine | None = None
_CoreSessionLocal: sessionmaker[Session] | None = None
_MemorySessionLocal: sessionmaker[Session] | None = None


def get_core_engine() -> Engine:
    global _core_engine, _CoreSessionLocal
    if _core_engine is None:
        settings = get_settings()
        _core_engine = create_engine(settings.core_database_url, pool_pre_ping=True)
        _CoreSessionLocal = sessionmaker(bind=_core_engine, autoflush=False, autocommit=False)
    return _core_engine


def get_memory_engine() -> Engine:
    global _memory_engine, _MemorySessionLocal
    if _memory_engine is None:
        settings = get_settings()
        _memory_engine = create_engine(settings.memory_database_url, pool_pre_ping=True)
        _MemorySessionLocal = sessionmaker(bind=_memory_engine, autoflush=False, autocommit=False)
    return _memory_engine


@contextmanager
def core_session() -> Generator[Session, None, None]:
    get_core_engine()
    assert _CoreSessionLocal is not None
    session = _CoreSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def memory_session() -> Generator[Session, None, None]:
    get_memory_engine()
    assert _MemorySessionLocal is not None
    session = _MemorySessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_core_database() -> bool:
    try:
        with get_core_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 — health probe must not raise
        logger.warning("core_database_unhealthy", extra={"error": str(exc)})
        return False


def check_memory_database() -> bool:
    try:
        with get_memory_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("memory_database_unhealthy", extra={"error": str(exc)})
        return False
