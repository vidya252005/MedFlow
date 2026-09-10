from __future__ import annotations

from uuid import uuid4

from app.evaluator import aggregate
from medflow_shared.config import Settings
from medflow_shared.db import session_scope
from medflow_shared.events import FeatureVector, HealthcareEvent, Prediction
from medflow_shared.kafka import KafkaProducer, KafkaWorker, ensure_topics
from medflow_shared.logging import configure_logging, get_logger
from medflow_shared.metrics import PIPELINE_LATENCY
from medflow_shared.orm import DecisionRow, EventRow
from medflow_shared.topics import DECISIONS, PREDICTIONS

log = get_logger(service="rules-engine")


class RulesService:
    def __init__(self, settings: Settings, session_factory, producer: KafkaProducer) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.producer = producer

    async def handle(self, raw: dict, _message) -> None:
        event = HealthcareEvent.model_validate(raw["event"])
        features = FeatureVector.model_validate(raw["features"])
        predictions = [Prediction.model_validate(p) for p in raw.get("predictions", [])]
        weights = raw.get("weights") or {}
        decision = aggregate(event, features, predictions, weights)
        async with session_scope(self.session_factory) as session:
            existing = None
            from sqlalchemy import select
            from medflow_shared.orm import DecisionRow as DR

            existing = await session.scalar(select(DR).where(DR.event_id == event.event_id))
            if existing is None:
                session.add(
                    DecisionRow(
                        id=str(uuid4()),
                        event_id=event.event_id,
                        patient_id=event.patient_id,
                        severity=decision.severity,
                        action=decision.action,
                        decision_score=decision.decision_score,
                        confidence=decision.confidence,
                        triggered_rules=decision.triggered_rules,
                        explanation=decision.explanation,
                    )
                )
            row = await session.get(EventRow, event.event_id)
            if row:
                row.processing_status = "DECISION"
        await self.producer.publish(
            DECISIONS,
            {"event": event.model_dump(), "decision": decision.model_dump()},
            key=event.partition_key,
        )
        PIPELINE_LATENCY.labels("rules").observe(0.0)
        log.info("decision_ready", event_id=event.event_id, severity=decision.severity, action=decision.action)


async def run() -> None:
    from medflow_shared.config import get_settings
    from medflow_shared.db import create_engine, create_session_factory

    settings = get_settings()
    configure_logging("rules-engine")
    await ensure_topics(settings.kafka_bootstrap_servers)
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    producer = KafkaProducer(settings.kafka_bootstrap_servers, "rules-engine")
    await producer.start()
    service = RulesService(settings, factory, producer)
    worker = KafkaWorker(
        bootstrap=settings.kafka_bootstrap_servers,
        topic=PREDICTIONS,
        group_id="rules-workers",
        service="rules-engine",
        handler=service.handle,
        max_workers=settings.max_workers,
    )
    from medflow_shared.worker_app import run_worker_with_health

    try:
        await run_worker_with_health("rules-engine", 8004, worker.start())
    finally:
        await producer.stop()
        await engine.dispose()


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
