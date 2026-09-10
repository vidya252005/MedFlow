from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", protected_namespaces=())

    app_env: str = "development"
    service_name: str = "medflow"
    jwt_secret: str = "change-me-in-any-non-local-environment"
    jwt_expire_minutes: int = 480
    demo_password: str = "medflow"

    database_url: str = "postgresql+asyncpg://medflow:medflow@postgres:5432/medflow"
    redis_url: str = "redis://redis:6379/0"
    kafka_bootstrap_servers: str = "kafka:9092"

    model_registry_path: str = "/app/models/registry.yaml"
    max_workers: int = 16
    model_timeout_ms: int = 200
    rate_limit_per_minute: int = 120

    allowed_clock_skew_seconds: int = 300
    allowed_event_age_seconds: int = 86400
    allowed_lateness_seconds: int = 120
    idempotency_ttl_seconds: int = 86400
    alert_dedup_seconds: int = 300

    inference_semaphore: int = 32
    retry_max_attempts: int = 3
    retry_base_ms: int = 100
    circuit_failure_threshold: int = 5
    circuit_reset_seconds: int = 15

    cors_origins: str = "http://localhost:5173,http://localhost:3000,http://localhost:8080"
    otel_exporter_otlp_endpoint: str | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
