from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ModelMetadata:
    name: str
    version: str
    timeout_ms: int
    enabled: bool
    fallback: str | None
    shadow: bool
    artifact_path: str | None
    input_features: list[str]


@dataclass(frozen=True)
class RoutingPolicy:
    event_type: str
    models: list[str]


@dataclass(frozen=True)
class Registry:
    models: dict[str, ModelMetadata]
    routing: dict[str, RoutingPolicy]
    aggregation_weights: dict[str, float]


def load_registry(path: str) -> Registry:
    raw: dict[str, Any] = yaml.safe_load(Path(path).read_text())
    models = {
        item["name"]: ModelMetadata(
            name=item["name"],
            version=str(item["version"]),
            timeout_ms=int(item.get("timeout_ms", 200)),
            enabled=bool(item.get("enabled", True)),
            fallback=item.get("fallback"),
            shadow=bool(item.get("shadow", False)),
            artifact_path=item.get("artifact_path"),
            input_features=list(item.get("input_features", [])),
        )
        for item in raw.get("models", [])
    }
    routing = {
        event_type: RoutingPolicy(event_type=event_type, models=list(cfg.get("models", [])))
        for event_type, cfg in raw.get("routing", {}).items()
    }
    weights = {k: float(v) for k, v in raw.get("aggregation_weights", {}).items()}
    return Registry(models=models, routing=routing, aggregation_weights=weights)


def model_hash(name: str, version: str) -> str:
    return hashlib.sha256(f"{name}:{version}".encode()).hexdigest()[:16]
