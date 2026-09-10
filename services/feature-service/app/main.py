from __future__ import annotations

import json
from datetime import datetime, timezone

from medflow_shared.config import Settings
from medflow_shared.db import session_scope
from medflow_shared.events import EventType, FeatureVector, HealthcareEvent
from medflow_shared.features import extract_bed_features, extract_imaging_features, extract_vital_features
from medflow_shared.kafka import KafkaProducer, KafkaWorker, ensure_topics
from medflow_shared.logging import configure_logging, get_logger
from medflow_shared.metrics import PIPELINE_LATENCY
from medflow_shared.orm import EventRow
from medflow_shared.redis_utils import FeatureCache, create_redis
from medflow_shared.topics import FEATURES_READY, VALIDATED_EVENTS

log = get_logger(service="feature-service")

WINDOWS = {"5m": 5 * 60, "15m": 15 * 60, "30m": 30 * 60}


class FeatureService:
    def __init__(self, settings: Settings, session_factory, cache: FeatureCache, producer: KafkaProducer) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.cache = cache
        self.producer = producer

    async def handle(self, raw: dict, _message) -> None:
        event = HealthcareEvent.model_validate({k: v for k, v in raw.items() if k != "canonical"})
        ts = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        stale = (now - ts).total_seconds() > self.settings.allowed_lateness_seconds
        encoded = json.dumps({"ts": event.timestamp, "payload": event.payload, "type": event.event_type.value})
        if event.patient_id:
            await self.cache.add_event(event.patient_id, int(ts.timestamp() * 1000), encoded)

        history_payloads = await self._history(event, ts)
        if event.event_type == EventType.PATIENT_VITAL:
            features = extract_vital_features(event.payload, history_payloads)
        elif event.event_type == EventType.BED_STATUS:
            features = extract_bed_features(event.payload, history_payloads)
        elif event.event_type == EventType.IMAGING_REQUEST:
            features = extract_imaging_features(event.payload)
        elif event.event_type == EventType.LAB_RESULT:
            features = {
                "lab_value": event.payload.get("value"),
                "abnormal_flag": 1 if event.payload.get("abnormal_flag") else 0,
                "missing_ratio": 0.0,
            }
        elif event.event_type == EventType.RESOURCE_UPDATE:
            cap = event.payload.get("capacity") or 1
            features = {
                "occupancy_ratio": 1 - (event.payload.get("available", 0) / cap),
                "occupied_count": cap - event.payload.get("available", 0),
                "available_count": event.payload.get("available", 0),
                "missing_ratio": 0.0,
            }
        else:
            features = {"missing_ratio": 0.0}

        insufficient = int(features.get("observation_count") or 0) < 3 and event.event_type == EventType.PATIENT_VITAL
        vector = FeatureVector(
            event_id=event.event_id,
            patient_id=event.patient_id,
            event_type=event.event_type,
            event_time=event.timestamp,
            trace_id=event.trace_id,
            features=features,
            window_sizes={"5m": len(history_payloads)},
            stale=stale,
            insufficient_observations=insufficient,
        )
        if event.patient_id:
            await self.cache.set_features(event.patient_id, "5m", vector.model_dump_json())

        async with session_scope(self.session_factory) as session:
            row = await session.get(EventRow, event.event_id)
            if row:
                row.processing_status = "FEATURE_EXTRACTION"
                row.updated_at = now

        await self.producer.publish(
            FEATURES_READY,
            {"event": event.model_dump(), "features": vector.model_dump()},
            key=event.partition_key,
        )
        PIPELINE_LATENCY.labels("features").observe(0.0)
        log.info("features_ready", event_id=event.event_id, stale=stale, insufficient=insufficient)

    async def _history(self, event: HealthcareEvent, ts: datetime) -> list[dict]:
        if not event.patient_id:
            return [event.payload]
        start_ms = int((ts.timestamp() - WINDOWS["5m"]) * 1000)
        end_ms = int(ts.timestamp() * 1000)
        rows = await self.cache.window(event.patient_id, start_ms, end_ms)
        payloads = []
        for item in rows:
            parsed = json.loads(item)
            if parsed.get("type") == event.event_type.value:
                payloads.append(parsed["payload"])
        if not payloads:
            payloads = [event.payload]
        return payloads


async def run() -> None:
    from medflow_shared.config import get_settings
    from medflow_shared.db import create_engine, create_session_factory

    settings = get_settings()
    configure_logging("feature-service")
    await ensure_topics(settings.kafka_bootstrap_servers)
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    redis = create_redis(settings)
    producer = KafkaProducer(settings.kafka_bootstrap_servers, "feature-service")
    await producer.start()
    service = FeatureService(settings, factory, FeatureCache(redis), producer)
    worker = KafkaWorker(
        bootstrap=settings.kafka_bootstrap_servers,
        topic=VALIDATED_EVENTS,
        group_id="feature-workers",
        service="feature-service",
        handler=service.handle,
        max_workers=settings.max_workers,
    )
    from medflow_shared.worker_app import run_worker_with_health

    try:
        await run_worker_with_health("feature-service", 8002, worker.start())
    finally:
        await producer.stop()
        await redis.close()
        await engine.dispose()


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
