from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.errors import TopicAlreadyExistsError

from medflow_shared.logging import get_logger
from medflow_shared.metrics import MESSAGES_CONSUMED, MESSAGES_FAILED, MESSAGES_PRODUCED, QUEUE_DEPTH
from medflow_shared.topics import ALL_TOPICS, DLQ

log = get_logger(component="kafka")

Handler = Callable[[dict[str, Any], Any], Awaitable[None]]


async def ensure_topics(bootstrap: str) -> None:
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap)
    await admin.start()
    try:
        topics = [NewTopic(name=name, num_partitions=6, replication_factor=1) for name in ALL_TOPICS]
        try:
            await admin.create_topics(topics)
        except TopicAlreadyExistsError:
            pass
        except Exception as exc:  # noqa: BLE001
            log.warning("topic_create_partial", error=str(exc))
    finally:
        await admin.close()


class KafkaProducer:
    def __init__(self, bootstrap: str, service: str) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=bootstrap,
            value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
            key_serializer=lambda v: v.encode("utf-8") if v else None,
            linger_ms=5,
            acks="all",
        )
        self._service = service

    async def start(self) -> None:
        await self._producer.start()

    async def stop(self) -> None:
        await self._producer.stop()

    async def publish(self, topic: str, payload: dict[str, Any], key: str | None = None) -> None:
        await self._producer.send_and_wait(topic, payload, key=key)
        MESSAGES_PRODUCED.labels(self._service, topic).inc()

    async def publish_dlq(self, record: dict[str, Any], key: str | None = None) -> None:
        await self.publish(DLQ, record, key=key)


class KafkaWorker:
    """Bounded-concurrency Kafka consumer with graceful drain on shutdown."""

    def __init__(
        self,
        *,
        bootstrap: str,
        topic: str,
        group_id: str,
        service: str,
        handler: Handler,
        max_workers: int = 16,
    ) -> None:
        self.topic = topic
        self.service = service
        self.handler = handler
        self.max_workers = max_workers
        self._stopping = asyncio.Event()
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=max_workers * 4)
        self._consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=bootstrap,
            group_id=group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        )

    async def start(self) -> None:
        await self._consumer.start()
        workers = [asyncio.create_task(self._worker(i), name=f"{self.service}-w{i}") for i in range(self.max_workers)]
        fetcher = asyncio.create_task(self._fetch(), name=f"{self.service}-fetch")
        try:
            await asyncio.gather(fetcher, *workers)
        finally:
            await self._consumer.stop()

    async def stop(self) -> None:
        self._stopping.set()

    async def _fetch(self) -> None:
        try:
            async for message in self._consumer:
                if self._stopping.is_set():
                    break
                await self._queue.put(message)
                QUEUE_DEPTH.labels(self.service).set(self._queue.qsize())
        except asyncio.CancelledError:
            raise
        finally:
            for _ in range(self.max_workers):
                await self._queue.put(None)

    async def _worker(self, worker_id: int) -> None:
        while True:
            message = await self._queue.get()
            QUEUE_DEPTH.labels(self.service).set(self._queue.qsize())
            if message is None:
                return
            try:
                MESSAGES_CONSUMED.labels(self.service, self.topic).inc()
                await self.handler(message.value, message)
                await self._consumer.commit()
            except Exception as exc:  # noqa: BLE001
                MESSAGES_FAILED.labels(self.service, self.topic, type(exc).__name__).inc()
                log.exception("handler_failed", worker=worker_id, error=str(exc))
                await self._consumer.commit()
