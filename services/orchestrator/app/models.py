from __future__ import annotations

import asyncio
import hashlib
import time
from abc import ABC, abstractmethod
from typing import Any

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import LogisticRegression

from medflow_shared.circuit import RedisCircuitBreaker
from medflow_shared.events import FeatureVector, Prediction
from medflow_shared.metrics import MODEL_ERRORS, MODEL_INFERENCE, MODEL_LATENCY, MODEL_TIMEOUTS
from medflow_shared.registry import ModelMetadata, model_hash


class AIModel(ABC):
    name: str
    version: str

    @abstractmethod
    async def predict(self, features: dict[str, Any]) -> Prediction:
        raise NotImplementedError

    @property
    def digest(self) -> str:
        return model_hash(self.name, self.version)


def _f(features: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = features.get(key)
    if value is None or value is False:
        return default
    if value is True:
        return 1.0
    return float(value)


class SklearnAnomalyModel(AIModel):
    def __init__(self, name: str, version: str, contamination: float = 0.03) -> None:
        self.name = name
        self.version = version
        rng = np.random.default_rng(42)
        n = 2500
        x = np.column_stack(
            [
                rng.normal(78, 8, n).clip(50, 110),
                rng.normal(98, 1.2, n).clip(94, 100),
                rng.normal(16, 2, n).clip(10, 24),
                rng.normal(78, 6, n),
                rng.normal(0, 0.4, n),
                rng.uniform(1, 10, n),
            ]
        )
        self.model = IsolationForest(n_estimators=60, contamination=contamination, random_state=7)
        self.model.fit(x)

    async def predict(self, features: dict[str, Any]) -> Prediction:
        vec = np.array(
            [
                [
                    _f(features, "heart_rate", 80),
                    _f(features, "spo2", 98),
                    _f(features, "respiratory_rate", 16),
                    _f(features, "heart_rate_mean_5m", _f(features, "heart_rate", 80)),
                    _f(features, "spo2_delta_5m", 0),
                    _f(features, "hr_variance_5m", 4),
                ]
            ]
        )
        raw = -self.model.decision_function(vec)[0]
        score = float(1 / (1 + np.exp(-4 * (raw - 0.05))))
        label = "anomalous" if score >= 0.65 else "nominal"
        return Prediction(
            model_name=self.name,
            model_version=self.version,
            model_hash=self.digest,
            score=score,
            label=label,
            confidence=min(0.99, abs(score - 0.5) * 1.8 + 0.4),
            status="success",
            explanation={"backend": "sklearn.IsolationForest", "decision_function": float(raw)},
        )


class ThresholdDetector(AIModel):
    name = "threshold_detector"
    version = "1.0"

    async def predict(self, features: dict[str, Any]) -> Prediction:
        hr = features.get("heart_rate")
        spo2 = features.get("spo2")
        rr = features.get("respiratory_rate")
        hits = 0
        reasons = []
        if hr is not None and (hr > 120 or hr < 45):
            hits += 1
            reasons.append("hr_threshold")
        if spo2 is not None and spo2 < 92:
            hits += 1
            reasons.append("spo2_threshold")
        if rr is not None and rr > 26:
            hits += 1
            reasons.append("rr_threshold")
        score = min(1.0, hits / 3 + (0.35 if hits else 0.05))
        return Prediction(
            model_name=self.name,
            model_version=self.version,
            model_hash=self.digest,
            score=score,
            label="anomalous" if hits else "nominal",
            confidence=0.7 if hits else 0.55,
            status="fallback",
            explanation={"backend": "heuristic", "reasons": reasons},
        )


class RiskPredictor(AIModel):
    def __init__(self) -> None:
        self.name = "risk_predictor"
        self.version = "1.4"
        rng = np.random.default_rng(7)
        n = 2000
        hr = rng.normal(78, 8, n)
        spo2 = rng.normal(98, 1.1, n)
        rr = rng.normal(16, 2, n)
        temp = rng.normal(36.8, 0.3, n)
        sbp = rng.normal(118, 10, n)
        y = ((hr > 115) | (spo2 < 93) | (rr > 25)).astype(int)
        y[:60] = 1
        x = np.column_stack([hr, spo2, rr, temp, sbp, hr])
        self.model = LogisticRegression(max_iter=400)
        self.model.fit(x, y)

    async def predict(self, features: dict[str, Any]) -> Prediction:
        vec = np.array(
            [
                [
                    _f(features, "heart_rate", 80),
                    _f(features, "spo2", 98),
                    _f(features, "respiratory_rate", 16),
                    _f(features, "temperature_c", 36.8),
                    _f(features, "systolic_bp", 120),
                    _f(features, "heart_rate_mean_15m", _f(features, "heart_rate", 80)),
                ]
            ]
        )
        proba = float(self.model.predict_proba(vec)[0][1])
        return Prediction(
            model_name=self.name,
            model_version=self.version,
            model_hash=self.digest,
            score=proba,
            label="elevated_risk" if proba >= 0.55 else "low_risk",
            confidence=max(proba, 1 - proba),
            status="success",
            explanation={"backend": "sklearn.LogisticRegression"},
        )


class CapacityForecaster(AIModel):
    name = "capacity_forecaster"
    version = "1.0"

    async def predict(self, features: dict[str, Any]) -> Prediction:
        occ = _f(features, "occupancy_ratio", 0.5)
        score = min(1.0, occ * 1.05 + 0.05 * _f(features, "occupied_count", 0) / 20)
        label = "congestion" if score >= 0.85 else "stable"
        return Prediction(
            model_name=self.name,
            model_version=self.version,
            model_hash=self.digest,
            score=score,
            label=label,
            confidence=0.8,
            status="success",
            explanation={"backend": "numpy_heuristic", "occupancy_ratio": occ},
        )


class ImagingPrioritizer(AIModel):
    name = "imaging_prioritizer"
    version = "1.0"

    async def predict(self, features: dict[str, Any]) -> Prediction:
        wait = _f(features, "waiting_minutes", 0)
        acuity = _f(features, "acuity_code", 2)
        modality = _f(features, "modality_code", 2)
        score = min(1.0, (wait / 180) * 0.5 + acuity / 3 * 0.35 + modality / 5 * 0.15)
        label = "prioritize" if score >= 0.6 else "routine"
        return Prediction(
            model_name=self.name,
            model_version=self.version,
            model_hash=self.digest,
            score=score,
            label=label,
            confidence=0.75,
            status="success",
            explanation={"backend": "weighted_score", "wait": wait, "acuity": acuity},
        )


class DataQualityScorer(AIModel):
    name = "data_quality_scorer"
    version = "1.0"

    async def predict(self, features: dict[str, Any]) -> Prediction:
        missing = _f(features, "missing_ratio", 0)
        stale = 1.0 if features.get("stale") else 0.0
        insufficient = 1.0 if features.get("insufficient_observations") else 0.0
        # invert: high score = poor quality
        score = min(1.0, missing * 0.5 + stale * 0.3 + insufficient * 0.2)
        label = "data_quality_issue" if score >= 0.4 else "quality_ok"
        return Prediction(
            model_name=self.name,
            model_version=self.version,
            model_hash=self.digest,
            score=score,
            label=label,
            confidence=0.9,
            status="success",
            explanation={"missing": missing, "stale": stale, "insufficient": insufficient},
        )


class ModelFactory:
    @staticmethod
    def build(meta: ModelMetadata) -> AIModel:
        mapping = {
            "anomaly_detector": lambda: SklearnAnomalyModel("anomaly_detector", meta.version, 0.03),
            "anomaly_detector_shadow": lambda: SklearnAnomalyModel("anomaly_detector_shadow", meta.version, 0.08),
            "threshold_detector": ThresholdDetector,
            "risk_predictor": RiskPredictor,
            "capacity_forecaster": CapacityForecaster,
            "imaging_prioritizer": ImagingPrioritizer,
            "data_quality_scorer": DataQualityScorer,
        }
        ctor = mapping.get(meta.name)
        if ctor is None:
            raise KeyError(meta.name)
        return ctor()


class ModelExecutor:
    def __init__(self, redis, settings) -> None:
        self.redis = redis
        self.settings = settings
        self.semaphore = asyncio.Semaphore(settings.inference_semaphore)
        self.breakers: dict[str, RedisCircuitBreaker] = {}

    def breaker(self, name: str) -> RedisCircuitBreaker:
        if name not in self.breakers:
            self.breakers[name] = RedisCircuitBreaker(
                self.redis, name, self.settings.circuit_failure_threshold, self.settings.circuit_reset_seconds
            )
        return self.breakers[name]

    async def execute(self, model: AIModel, features: dict[str, Any], timeout_ms: int, shadow: bool = False) -> Prediction:
        breaker = self.breaker(model.name)
        if not await breaker.allow():
            MODEL_INFERENCE.labels(model.name, "circuit_open").inc()
            return Prediction(
                model_name=model.name,
                model_version=model.version,
                status="circuit_open",
                shadow=shadow,
                explanation={"reason": "circuit_open"},
            )
        start = time.perf_counter()
        try:
            async with self.semaphore:
                result = await asyncio.wait_for(model.predict(features), timeout=timeout_ms / 1000)
            latency = (time.perf_counter() - start) * 1000
            result.latency_ms = latency
            result.shadow = shadow
            if shadow:
                result.status = "shadow"
            MODEL_LATENCY.labels(model.name).observe(latency / 1000)
            MODEL_INFERENCE.labels(model.name, result.status).inc()
            await breaker.record_success()
            return result
        except TimeoutError:
            MODEL_TIMEOUTS.labels(model.name).inc()
            MODEL_INFERENCE.labels(model.name, "timeout").inc()
            await breaker.record_failure()
            return Prediction(
                model_name=model.name,
                model_version=getattr(model, "version", "?"),
                latency_ms=(time.perf_counter() - start) * 1000,
                status="timeout",
                shadow=shadow,
            )
        except Exception as exc:  # noqa: BLE001
            MODEL_ERRORS.labels(model.name).inc()
            MODEL_INFERENCE.labels(model.name, "error").inc()
            await breaker.record_failure()
            return Prediction(
                model_name=model.name,
                model_version=getattr(model, "version", "?"),
                latency_ms=(time.perf_counter() - start) * 1000,
                status="error",
                shadow=shadow,
                explanation={"error": str(exc)},
            )

    async def execute_many(
        self,
        items: list[tuple[AIModel, ModelMetadata]],
        features: dict[str, Any],
        fallbacks: dict[str, AIModel],
    ) -> list[Prediction]:
        async def one(model: AIModel, meta: ModelMetadata) -> Prediction:
            pred = await self.execute(model, features, meta.timeout_ms, shadow=meta.shadow)
            if pred.status in {"timeout", "error", "circuit_open"} and meta.fallback and meta.fallback in fallbacks:
                fb = await self.execute(fallbacks[meta.fallback], features, 50, shadow=False)
                fb.explanation = {**fb.explanation, "fallback_for": meta.name, "primary_status": pred.status}
                return fb
            return pred

        return list(await asyncio.gather(*(one(model, meta) for model, meta in items)))
