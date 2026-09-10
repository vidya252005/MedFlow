from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import select

from app.api.routes import router
from app.middleware.observability import ObservabilityMiddleware
from medflow_shared.auth import hash_password
from medflow_shared.config import get_settings
from medflow_shared.db import create_engine, create_session_factory
from medflow_shared.health import router as health_router
from medflow_shared.kafka import KafkaProducer, ensure_topics
from medflow_shared.logging import configure_logging, get_logger
from medflow_shared.orm import UserRow
from medflow_shared.redis_utils import create_redis
from medflow_shared.tracing import init_tracing

log = get_logger(service="gateway")


async def seed_users(session_factory, password: str) -> None:
    async with session_factory() as session:
        existing = await session.scalar(select(UserRow).limit(1))
        if existing:
            return
        for username, role in (("admin", "ADMIN"), ("analyst", "ANALYST"), ("viewer", "VIEWER")):
            session.add(
                UserRow(
                    id=str(uuid4()),
                    username=username,
                    password_hash=hash_password(password),
                    role=role,
                )
            )
        await session.commit()
        log.info("seeded_demo_users")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging("gateway")
    init_tracing("gateway")
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    redis = create_redis(settings)
    await ensure_topics(settings.kafka_bootstrap_servers)
    producer = KafkaProducer(settings.kafka_bootstrap_servers, "gateway")
    await producer.start()
    await seed_users(session_factory, settings.demo_password)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.redis = redis
    app.state.producer = producer
    log.info("gateway_started")
    try:
        yield
    finally:
        await producer.stop()
        await redis.close()
        await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="MedFlow Gateway",
        description="Synthetic healthcare event orchestration API. Not for clinical use.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(ObservabilityMiddleware, service_name="gateway")
    app.include_router(health_router)
    app.include_router(router, prefix="/api/v1")
    Instrumentator().instrument(app).expose(app, include_in_schema=False, should_gzip=True)

    @app.get("/health/ready")
    async def ready() -> dict:
        try:
            await app.state.redis.ping()
        except Exception as exc:  # noqa: BLE001
            return {"status": "degraded", "redis": str(exc)}
        return {"status": "ok"}

    return app


app = create_app()
