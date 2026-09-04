"""Redis lock for single Daily Research Cycle execution."""

from __future__ import annotations

from dataclasses import dataclass

import redis

from app.core.config import get_settings
from app.modules.research_cycle.config import LOCK_KEY, LOCK_TTL_SECONDS


@dataclass
class LockHandle:
    key: str
    token: str
    acquired: bool

    def release(self) -> None:
        if not self.acquired:
            return
        client = _client()
        current = client.get(self.key)
        if current is not None and current.decode() == self.token:
            client.delete(self.key)
        self.acquired = False


def _client() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=False)


def try_acquire_cycle_lock(token: str, *, ttl: int = LOCK_TTL_SECONDS) -> LockHandle:
    client = _client()
    ok = bool(client.set(LOCK_KEY, token, nx=True, ex=ttl))
    return LockHandle(key=LOCK_KEY, token=token, acquired=ok)


def is_cycle_lock_held() -> bool:
    return _client().exists(LOCK_KEY) == 1
