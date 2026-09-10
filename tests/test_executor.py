from __future__ import annotations

import asyncio
from types import SimpleNamespace

import fakeredis
import pytest

from medflow_shared.events import Prediction
from tests.imports import load

models = load("orch_models", "services/orchestrator/app/models.py")


class SlowModel(models.AIModel):
    name = "slow"
    version = "1"

    async def predict(self, features: dict) -> Prediction:
        await asyncio.sleep(1)
        return Prediction(model_name=self.name, model_version=self.version, score=1, status="success")


class BoomModel(models.AIModel):
    name = "boom"
    version = "1"

    async def predict(self, features: dict) -> Prediction:
        raise RuntimeError("boom")


@pytest.fixture
async def executor():
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    settings = SimpleNamespace(inference_semaphore=4, circuit_failure_threshold=3, circuit_reset_seconds=1)
    return models.ModelExecutor(redis, settings)


async def test_success(executor) -> None:
    pred = await executor.execute(
        models.ThresholdDetector(), {"heart_rate": 80, "spo2": 98, "respiratory_rate": 16}, 200
    )
    assert pred.status in {"success", "fallback"}
    assert pred.latency_ms >= 0


async def test_timeout(executor) -> None:
    pred = await executor.execute(SlowModel(), {}, timeout_ms=20)
    assert pred.status == "timeout"


async def test_exception(executor) -> None:
    pred = await executor.execute(BoomModel(), {}, timeout_ms=200)
    assert pred.status == "error"


async def test_circuit_opens(executor) -> None:
    for _ in range(3):
        await executor.execute(BoomModel(), {}, timeout_ms=50)
    pred = await executor.execute(BoomModel(), {}, timeout_ms=50)
    assert pred.status == "circuit_open"
