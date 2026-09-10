from __future__ import annotations

from redis.asyncio import Redis

from medflow_shared.config import Settings


def create_redis(settings: Settings) -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


class IdempotencyStore:
    def __init__(self, redis: Redis, ttl_seconds: int) -> None:
        self.redis = redis
        self.ttl_seconds = ttl_seconds

    async def acquire(self, key: str) -> bool:
        return bool(await self.redis.set(f"idempotency:{key}", "1", nx=True, ex=self.ttl_seconds))

    async def seen(self, key: str) -> bool:
        return bool(await self.redis.exists(f"idempotency:{key}"))


class FeatureCache:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    def _key(self, patient_id: str, window: str) -> str:
        return f"features:{patient_id}:{window}"

    async def set_features(self, patient_id: str, window: str, payload: str, ttl: int = 120) -> None:
        await self.redis.set(self._key(patient_id, window), payload, ex=ttl)

    async def get_features(self, patient_id: str, window: str) -> str | None:
        return await self.redis.get(self._key(patient_id, window))

    async def add_event(self, patient_id: str, timestamp_ms: int, encoded: str) -> None:
        key = f"events:{patient_id}"
        await self.redis.zadd(key, {encoded: timestamp_ms})
        await self.redis.expire(key, 3600)

    async def window(self, patient_id: str, start_ms: int, end_ms: int) -> list[str]:
        key = f"events:{patient_id}"
        return await self.redis.zrangebyscore(key, start_ms, end_ms)


class AlertDedup:
    def __init__(self, redis: Redis, ttl_seconds: int) -> None:
        self.redis = redis
        self.ttl_seconds = ttl_seconds

    async def should_emit(self, dedup_key: str) -> bool:
        return bool(await self.redis.set(f"alert:{dedup_key}", "1", nx=True, ex=self.ttl_seconds))
