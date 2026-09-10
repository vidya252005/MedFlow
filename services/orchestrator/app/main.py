from __future__ import annotations

from uuid import uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import ModelExecutor, ModelFactory
from app.router import ModelRouter
from medflow_shared.config import Settings
from medflow_shared.db import session_scope
from medflow_shared.events import FeatureVector, HealthcareEvent
from medflow_shared.kafka import KafkaProducer, KafkaWorker, ensure_topics
from medflow_shared.logging import configure_logging, get_logger
from medflow_shared.metrics import PIPELINE_LATENCY, PREDICTIONS_GENERATED
from medflow_shared.orm import EventRow, PredictionRow
from medflow_shared.redis_utils import create_redis
from medflow_shared.registry import load_registry
from medflow_shared.topics import FEATURES_READY, PREDICTIONS

log = get_logger(service="orchestrator")


class AIOrchestrator:
    def __init__(self, settings: Settings, session_factory, redis, producer: KafkaProducer) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.producer = producer
        self.registry = load_registry(settings.model_registry_path)
        self.router = ModelRouter(self.registry)
        self.executor = ModelExecutor(redis, settings)
        self.models = {
            name: ModelFactory.build(meta)
            for name, meta in self.registry.models.items()
            if meta.enabled
        }

    async def handle(self, raw: dict, _message) -> None:
        event = HealthcareEvent.model_validate(raw["event"])
        features = FeatureVector.model_validate(raw["features"])
        selected = self.router.select(event.event_type)
        items = []
        for name in selected:
            meta = self.registry.models[name]
            model = self.models[name]
            items.append((model, meta))
        feature_payload = {**features.features, "stale": features.stale, "insufficient_observations": features.insufficient_observations}
        predictions = await self.executor.execute_many(items, feature_payload, self.models)
        for pred in predictions:
            PREDICTIONS_GENERATED.labels(pred.model_name, pred.status).inc()
        async with session_scope(self.session_factory) as session:
            for pred in predictions:
                session.add(
                    PredictionRow(
                        id=str(uuid4()),
                        event_id=event.event_id,
                        model_name=pred.model_name,
                        model_version=pred.model_version,
                        model_hash=pred.model_hash,
                        label=pred.label,
                        score=pred.score,
                        confidence=pred.confidence,
                        latency_ms=pred.latency_ms,
                        status=pred.status,
                        shadow=pred.shadow,
                        explanation=pred.explanation,
                    )
                )
            row = await session.get(EventRow, event.event_id)
            if row:
                statuses = {p.status for p in predictions}
                row.processing_status = "PARTIAL_SUCCESS" if "timeout" in statuses or "error" in statuses else "INFERENCE"
        await self.producer.publish(
            PREDICTIONS,
            {
                "event": event.model_dump(),
                "features": features.model_dump(),
                "predictions": [p.model_dump() for p in predictions],
                "weights": self.registry.aggregation_weights,
            },
            key=event.partition_key,
        )
        PIPELINE_LATENCY.labels("orchestrator").observe(0.0)
        log.info(
            "predictions_ready",
            event_id=event.event_id,
            models=[p.model_name for p in predictions],
            statuses=[p.status for p in predictions],
        )


async def run() -> None:
    from medflow_shared.config import get_settings
    from medflow_shared.db import create_engine, create_session_factory

    settings = get_settings()
    configure_logging("orchestrator")
    await ensure_topics(settings.kafka_bootstrap_servers)
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    redis = create_redis(settings)
    producer = KafkaProducer(settings.kafka_bootstrap_servers, "orchestrator")
    await producer.start()
    orch = AIOrchestrator(settings, factory, redis, producer)
    worker = KafkaWorker(
        bootstrap=settings.kafka_bootstrap_servers,
        topic=FEATURES_READY,
        group_id="orchestrator-workers",
        service="orchestrator",
        handler=orch.handle,
        max_workers=max(4, settings.max_workers // 2),
    )
    from medflow_shared.worker_app import run_worker_with_health

    try:
        await run_worker_with_health("orchestrator", 8003, worker.start())
    finally:
        await producer.stop()
        await redis.close()
        await engine.dispose()


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
