from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from medflow_shared.config import Settings
from medflow_shared.db import session_scope
from medflow_shared.errors import DuplicateEventError, MedFlowError, ValidationError
from medflow_shared.events import CanonicalEvent
from medflow_shared.kafka import KafkaProducer, KafkaWorker, ensure_topics
from medflow_shared.logging import configure_logging, get_logger
from medflow_shared.metrics import DLQ_MESSAGES, DUPLICATES_SUPPRESSED, PIPELINE_LATENCY
from medflow_shared.orm import AuditRow, DlqRow, EventRow
from medflow_shared.redis_utils import IdempotencyStore, create_redis
from medflow_shared.topics import RAW_EVENTS, VALIDATED_EVENTS
from medflow_shared.validation import parse_event, validate_event

log = get_logger(service="ingestion")


class IngestionService:
    def __init__(self, settings: Settings, session_factory, redis, producer: KafkaProducer) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.producer = producer
        self.idempotency = IdempotencyStore(redis, settings.idempotency_ttl_seconds)

    async def handle(self, raw: dict, _message) -> None:
        start = datetime.now(timezone.utc)
        try:
            event = parse_event(raw)
            validate_event(event, self.settings)
            acquired = await self.idempotency.acquire(event.dedup_key)
            if not acquired:
                DUPLICATES_SUPPRESSED.inc()
                log.info("duplicate_suppressed", event_id=event.event_id, trace_id=event.trace_id)
                return
            canonical = CanonicalEvent.from_healthcare_event(event)
            async with session_scope(self.session_factory) as session:
                await self._persist(session, event)
            await self.producer.publish(
                VALIDATED_EVENTS,
                {
                    **event.model_dump(),
                    "canonical": canonical.model_dump(),
                },
                key=event.partition_key,
            )
            elapsed = (datetime.now(timezone.utc) - start).total_seconds()
            PIPELINE_LATENCY.labels("ingestion").observe(elapsed)
        except DuplicateEventError:
            DUPLICATES_SUPPRESSED.inc()
        except MedFlowError as exc:
            await self._dlq(raw, exc)
        except Exception as exc:  # noqa: BLE001
            await self._dlq(raw, ValidationError(str(exc), code="PERMANENT_FAILURE"))

    async def _persist(self, session: AsyncSession, event) -> None:
        existing = await session.get(EventRow, event.event_id)
        if existing:
            raise DuplicateEventError(event.event_id)
        ts = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
        session.add(
            EventRow(
                event_id=event.event_id,
                source_id=event.source_id,
                patient_id=event.patient_id,
                device_id=event.device_id,
                resource_id=event.resource_id,
                event_type=event.event_type.value,
                event_timestamp=ts,
                schema_version=event.schema_version,
                payload=event.payload,
                trace_id=event.trace_id,
                processing_status="VALIDATING",
            )
        )
        session.add(
            AuditRow(
                trace_id=event.trace_id,
                actor="ingestion",
                action="EVENT_VALIDATED",
                resource_type="event",
                resource_id=event.event_id,
            )
        )

    async def _dlq(self, raw: dict, exc: MedFlowError) -> None:
        DLQ_MESSAGES.labels(exc.code).inc()
        record = {
            "original_topic": RAW_EVENTS,
            "event_id": raw.get("event_id"),
            "failure_code": exc.code,
            "error": str(exc),
            "payload": raw,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self.producer.publish_dlq(record, key=str(raw.get("event_id") or "unknown"))
        async with session_scope(self.session_factory) as session:
            session.add(
                DlqRow(
                    id=str(uuid4()),
                    original_topic=RAW_EVENTS,
                    event_id=raw.get("event_id"),
                    failure_code=exc.code,
                    error=str(exc)[:2000],
                    payload=raw,
                )
            )
        log.warning("sent_to_dlq", code=exc.code, event_id=raw.get("event_id"))


async def run() -> None:
    from medflow_shared.config import get_settings
    from medflow_shared.db import create_engine, create_session_factory

    settings = get_settings()
    configure_logging("ingestion")
    await ensure_topics(settings.kafka_bootstrap_servers)
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    redis = create_redis(settings)
    producer = KafkaProducer(settings.kafka_bootstrap_servers, "ingestion")
    await producer.start()
    service = IngestionService(settings, factory, redis, producer)
    worker = KafkaWorker(
        bootstrap=settings.kafka_bootstrap_servers,
        topic=RAW_EVENTS,
        group_id="ingestion-workers",
        service="ingestion",
        handler=service.handle,
        max_workers=settings.max_workers,
    )
    from medflow_shared.worker_app import run_worker_with_health

    try:
        await run_worker_with_health("ingestion", 8001, worker.start())
    finally:
        await producer.stop()
        await redis.close()
        await engine.dispose()


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
