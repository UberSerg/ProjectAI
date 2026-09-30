"""Declarative base for Memory DB tables.

Separate from the Core ``Base`` on purpose: metadata of this base must never be
used to create tables on the Core database, and Core metadata must never contain
``memory`` schema tables. Access only through ``memory_session``.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class MemoryBase(DeclarativeBase):
    pass
