from __future__ import annotations

import asyncio

import uvicorn
from fastapi import FastAPI

from medflow_shared.health import router as health_router


def health_app(service: str) -> FastAPI:
    app = FastAPI(title=f"{service} health", docs_url=None, redoc_url=None)
    app.include_router(health_router)

    @app.get("/health/ready")
    async def ready() -> dict[str, str]:
        return {"status": "ok", "service": service}

    return app


async def serve_health(service: str, port: int) -> None:
    config = uvicorn.Config(health_app(service), host="0.0.0.0", port=port, log_level="warning")
    await uvicorn.Server(config).serve()


async def run_worker_with_health(service: str, port: int, worker_coro) -> None:
    await asyncio.gather(serve_health(service, port), worker_coro)
