from __future__ import annotations

from medflow_shared.events import FeatureVector, HealthcareEvent, Prediction
from tests.imports import load
from tests.test_validation import make_event

evaluator = load("rules_evaluator", "services/rules-engine/app/evaluator.py")


def _ctx(spo2=None, hr=80, extra=None):
    features = {"spo2": spo2, "spo2_min_5m": spo2, "heart_rate": hr, "missing_ratio": 0}
    if extra:
        features.update(extra)
    return {"features": features, "predictions": []}


def test_low_spo2_triggers_high() -> None:
    result = evaluator.LowSpo2Rule().evaluate(_ctx(spo2=91))
    assert result.triggered
    assert result.severity == "HIGH"


def test_spo2_normal() -> None:
    result = evaluator.LowSpo2Rule().evaluate(_ctx(spo2=97))
    assert not result.triggered


def test_missing_spo2() -> None:
    result = evaluator.LowSpo2Rule().evaluate(_ctx(spo2=None))
    assert not result.triggered


def test_aggregate_review_recommended() -> None:
    event = HealthcareEvent.model_validate(make_event())
    features = FeatureVector(
        event_id=event.event_id,
        patient_id=event.patient_id,
        event_type=event.event_type,
        event_time=event.timestamp,
        trace_id=event.trace_id,
        features={"heart_rate": 128, "spo2": 91, "respiratory_rate": 27, "spo2_min_5m": 91, "missing_ratio": 0},
        window_sizes={"5m": 4},
    )
    predictions = [
        Prediction(model_name="anomaly_detector", model_version="2.1", score=0.94, confidence=0.91, status="success"),
        Prediction(model_name="risk_predictor", model_version="1.4", score=0.81, confidence=0.8, status="success"),
    ]
    decision = evaluator.aggregate(
        event, features, predictions, {"anomaly_detector": 0.45, "risk_predictor": 0.3, "rules": 0.25}
    )
    assert decision.severity in {"HIGH", "CRITICAL"}
    assert decision.action == "REVIEW_RECOMMENDED"
    assert "low_spo2" in decision.triggered_rules
    assert decision.explanation["ai"]
