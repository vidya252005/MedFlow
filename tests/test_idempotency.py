from __future__ import annotations

import asyncio

import fakeredis

from medflow_shared.redis_utils import AlertDedup, IdempotencyStore


async def test_idempotency_only_first_wins() -> None:
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    store = IdempotencyStore(redis, ttl_seconds=60)
    got = await asyncio.gather(*[store.acquire("evt_1:src") for _ in range(100)])
    assert sum(got) == 1
    assert got.count(False) == 99


async def test_alert_dedup() -> None:
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    dedup = AlertDedup(redis, ttl_seconds=30)
    first = await dedup.should_emit("pat_1:ANOMALY:1")
    second = await dedup.should_emit("pat_1:ANOMALY:1")
    assert first is True
    assert second is False
