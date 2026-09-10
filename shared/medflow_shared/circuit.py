from __future__ import annotations

import time
from enum import Enum

from redis.asyncio import Redis


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class RedisCircuitBreaker:
    def __init__(self, redis: Redis, name: str, failure_threshold: int, reset_seconds: int) -> None:
        self.redis = redis
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self.key = f"model:circuit:{name}"

    async def _load(self) -> dict[str, str]:
        data = await self.redis.hgetall(self.key)
        if not data:
            return {"state": CircuitState.CLOSED.value, "failures": "0", "opened_at": "0"}
        return data

    async def allow(self) -> bool:
        data = await self._load()
        state = data.get("state", CircuitState.CLOSED.value)
        if state == CircuitState.CLOSED.value:
            return True
        opened_at = float(data.get("opened_at", "0"))
        if time.time() - opened_at >= self.reset_seconds:
            await self.redis.hset(self.key, mapping={"state": CircuitState.HALF_OPEN.value})
            return True
        return False

    async def record_success(self) -> None:
        await self.redis.hset(
            self.key,
            mapping={"state": CircuitState.CLOSED.value, "failures": "0", "opened_at": "0"},
        )

    async def record_failure(self) -> CircuitState:
        data = await self._load()
        failures = int(data.get("failures", "0")) + 1
        state = CircuitState.OPEN if failures >= self.failure_threshold else CircuitState.CLOSED
        mapping = {"failures": str(failures), "state": state.value}
        if state == CircuitState.OPEN:
            mapping["opened_at"] = str(time.time())
        await self.redis.hset(self.key, mapping=mapping)
        return state

    async def snapshot(self) -> dict[str, str]:
        return await self._load()
