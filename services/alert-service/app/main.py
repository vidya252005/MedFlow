from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from medflow_shared.config import Settings
from medflow_shared.db import session_scope
from medflow_shared.events import Decision, HealthcareEvent
from medflow_shared.kafka import KafkaProducer, KafkaWorker, ensure_topics
from medflow_shared.logging import configure_logging, get_logger
from medflow_shared.metrics import ALERTS_CREATED, END_TO_END_LATENCY, PIPELINE_LATENCY
from medflow_shared.orm import AlertRow, AuditRow, EventRow, OutboxRow
from medflow_shared.redis_utils import AlertDedup, create_redis
from medflow_shared.topics import ALERTS, DECISIONS

log = get_logger(service="alert-service")

# Actions that should not open an alert
SILENT_ACTIONS = {"MONITOR"}


def bucket(ts: datetime, seconds: int) -> int:
    return int(ts.timestamp() // seconds)


class AlertService:
    def __init__(self, settings: Settings, session_factory, redis, producer: KafkaProducer) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.redis = redis
        self.producer = producer
        self.dedup = AlertDedup(redis, settings.alert_dedup_seconds)

    async def handle(self, raw: dict, _message) -> None:
        event = HealthcareEvent.model_validate(raw["event"])
        decision = Decision.model_validate(raw["decision"])
        if decision.action in SILENT_ACTIONS and decision.severity == "LOW":
            async with session_scope(self.session_factory) as session:
                row = await session.get(EventRow, event.event_id)
                if row:
                    row.processing_status = "COMPLETED"
            return

        now = datetime.now(timezone.utc)
        key_id = decision.patient_id or event.resource_id or event.source_id
        dedup_key = f"{key_id}:{decision.action}:{bucket(now, self.settings.alert_dedup_seconds)}"
        emit = await self.dedup.should_emit(dedup_key)
        if not emit:
            log.info("alert_deduplicated", dedup_key=dedup_key, event_id=event.event_id)
            async with session_scope(self.session_factory) as session:
                row = await session.get(EventRow, event.event_id)
                if row:
                    row.processing_status = "COMPLETED"
            return

        alert_id = str(uuid4())
        message = _message_for(decision)
        payload = {
            "id": alert_id,
            "patient_id": decision.patient_id,
            "event_id": event.event_id,
            "alert_type": decision.action,
            "severity": decision.severity,
            "status": "OPEN",
            "message": message,
            "explanation": decision.explanation,
            "created_at": now.isoformat(),
        }
        async with session_scope(self.session_factory) as session:
            session.add(
                AlertRow(
                    id=alert_id,
                    patient_id=decision.patient_id,
                    event_id=event.event_id,
                    alert_type=decision.action,
                    severity=decision.severity,
                    status="OPEN",
                    message=message,
                    dedup_key=dedup_key,
                    explanation=decision.explanation,
                )
            )
            session.add(
                OutboxRow(
                    id=str(uuid4()),
                    aggregate_id=alert_id,
                    event_type="ALERT_CREATED",
                    payload=payload,
                    published=True,
                )
            )
            session.add(
                AuditRow(
                    trace_id=event.trace_id,
                    actor="alert-service",
                    action="ALERT_CREATED",
                    resource_type="alert",
                    resource_id=alert_id,
                    metadata_={"severity": decision.severity, "type": decision.action},
                )
            )
            row = await session.get(EventRow, event.event_id)
            if row:
                row.processing_status = "COMPLETED"
                created = row.created_at
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                END_TO_END_LATENCY.observe((now - created).total_seconds())

        await self.producer.publish(ALERTS, {"type": "ALERT_CREATED", "alert": payload}, key=key_id)
        await self.redis.publish("alerts:stream", json.dumps({"type": "ALERT_CREATED", "alert": payload}))
        ALERTS_CREATED.labels(decision.severity, decision.action).inc()
        PIPELINE_LATENCY.labels("alerts").observe(0.0)
        log.info("alert_created", alert_id=alert_id, severity=decision.severity, action=decision.action)


def _message_for(decision: Decision) -> str:
    rules = ", ".join(decision.triggered_rules) or "model scores"
    return (
        f"{decision.action} ({decision.severity}) for {decision.patient_id or 'resource'} "
        f"— score={decision.decision_score:.2f}, rules=[{rules}]. "
        "Synthetic data; not a clinical diagnosis."
    )


async def run() -> None:
    from medflow_shared.config import get_settings
    from medflow_shared.db import create_engine, create_session_factory

    settings = get_settings()
    configure_logging("alert-service")
    await ensure_topics(settings.kafka_bootstrap_servers)
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    redis = create_redis(settings)
    producer = KafkaProducer(settings.kafka_bootstrap_servers, "alert-service")
    await producer.start()
    service = AlertService(settings, factory, redis, producer)
    worker = KafkaWorker(
        bootstrap=settings.kafka_bootstrap_servers,
        topic=DECISIONS,
        group_id="alert-workers",
        service="alert-service",
        handler=service.handle,
        max_workers=settings.max_workers,
    )
    from medflow_shared.worker_app import run_worker_with_health

    try:
        await run_worker_with_health("alert-service", 8005, worker.start())
    finally:
        await producer.stop()
        await redis.close()
        await engine.dispose()


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
