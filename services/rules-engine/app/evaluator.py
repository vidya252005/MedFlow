from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from medflow_shared.events import Decision, EventType, FeatureVector, HealthcareEvent, Prediction


SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


@dataclass
class RuleResult:
    name: str
    triggered: bool
    severity: str = "LOW"
    reason: str = ""
    score: float = 0.0


class Rule(ABC):
    name: str

    @abstractmethod
    def evaluate(self, context: dict[str, Any]) -> RuleResult:
        raise NotImplementedError


class LowSpo2Rule(Rule):
    name = "low_spo2"

    def evaluate(self, context: dict[str, Any]) -> RuleResult:
        spo2 = context["features"].get("spo2")
        spo2_min = context["features"].get("spo2_min_5m", spo2)
        value = spo2_min if spo2_min is not None else spo2
        if value is not None and value < 92:
            severity = "CRITICAL" if value < 88 else "HIGH"
            return RuleResult(self.name, True, severity, f"SpO2 {value} below 92", 0.9)
        return RuleResult(self.name, False)


class TachycardiaRule(Rule):
    name = "tachycardia"

    def evaluate(self, context: dict[str, Any]) -> RuleResult:
        hr = context["features"].get("heart_rate")
        if hr is not None and hr >= 120:
            severity = "HIGH" if hr >= 140 else "MEDIUM"
            return RuleResult(self.name, True, severity, f"heart_rate {hr} >= 120", 0.7)
        return RuleResult(self.name, False)


class HighRespiratoryRateRule(Rule):
    name = "high_respiratory_rate"

    def evaluate(self, context: dict[str, Any]) -> RuleResult:
        rr = context["features"].get("respiratory_rate")
        if rr is not None and rr >= 26:
            return RuleResult(self.name, True, "HIGH", f"respiratory_rate {rr} >= 26", 0.75)
        return RuleResult(self.name, False)


class OccupancyRule(Rule):
    name = "resource_congestion"

    def evaluate(self, context: dict[str, Any]) -> RuleResult:
        occ = context["features"].get("occupancy_ratio")
        if occ is not None and occ >= 0.9:
            return RuleResult(self.name, True, "HIGH", f"occupancy {occ:.2f}", 0.8)
        if occ is not None and occ >= 0.8:
            return RuleResult(self.name, True, "MEDIUM", f"occupancy {occ:.2f}", 0.55)
        return RuleResult(self.name, False)


class ImagingWaitRule(Rule):
    name = "imaging_backlog"

    def evaluate(self, context: dict[str, Any]) -> RuleResult:
        wait = context["features"].get("waiting_minutes")
        if wait is not None and wait >= 90:
            return RuleResult(self.name, True, "HIGH", f"imaging wait {wait}m", 0.7)
        return RuleResult(self.name, False)


class DataQualityRule(Rule):
    name = "data_quality_issue"

    def evaluate(self, context: dict[str, Any]) -> RuleResult:
        if context["features"].get("missing_ratio", 0) >= 0.66:
            return RuleResult(self.name, True, "LOW", "high missingness", 0.4)
        preds = [p for p in context["predictions"] if p.model_name == "data_quality_scorer" and (p.score or 0) >= 0.4]
        if preds:
            return RuleResult(self.name, True, "LOW", "model flagged data quality", 0.4)
        return RuleResult(self.name, False)


class ModelConfidenceRule(Rule):
    name = "model_confidence_low"

    def evaluate(self, context: dict[str, Any]) -> RuleResult:
        usable = [p for p in context["predictions"] if p.status == "success" and not p.shadow]
        if not usable:
            return RuleResult(self.name, True, "LOW", "no successful primary predictions", 0.3)
        low = [p for p in usable if (p.confidence or 0) < 0.5]
        if len(low) == len(usable):
            return RuleResult(self.name, True, "LOW", "all model confidences low", 0.3)
        return RuleResult(self.name, False)


RULES: list[Rule] = [
    LowSpo2Rule(),
    TachycardiaRule(),
    HighRespiratoryRateRule(),
    OccupancyRule(),
    ImagingWaitRule(),
    DataQualityRule(),
    ModelConfidenceRule(),
]


SAFE_ACTIONS = {
    "HIGH": "REVIEW_RECOMMENDED",
    "CRITICAL": "REVIEW_RECOMMENDED",
    "MEDIUM": "ANOMALY_DETECTED",
    "LOW": "MONITOR",
}


def action_for(severity: str, rules: list[RuleResult], event_type: EventType) -> str:
    names = {r.name for r in rules if r.triggered}
    if "resource_congestion" in names:
        return "RESOURCE_CONGESTION"
    if "data_quality_issue" in names and severity == "LOW":
        return "DATA_QUALITY_ISSUE"
    if "model_confidence_low" in names and not (names - {"model_confidence_low"}):
        return "MODEL_CONFIDENCE_LOW"
    if "imaging_backlog" in names:
        return "REVIEW_RECOMMENDED"
    if event_type == EventType.PATIENT_VITAL and severity in {"HIGH", "CRITICAL", "MEDIUM"}:
        return "ANOMALY_DETECTED" if severity == "MEDIUM" else "REVIEW_RECOMMENDED"
    return SAFE_ACTIONS[severity]


def aggregate(
    event: HealthcareEvent,
    features: FeatureVector,
    predictions: list[Prediction],
    weights: dict[str, float],
) -> Decision:
    context = {"event": event, "features": features.features, "predictions": predictions}
    results = [rule.evaluate(context) for rule in RULES]
    triggered = [r for r in results if r.triggered]
    severity = "LOW"
    for result in triggered:
        if SEVERITY_RANK[result.severity] > SEVERITY_RANK[severity]:
            severity = result.severity

    primary = [p for p in predictions if p.status in {"success", "fallback"} and not p.shadow]
    anomaly = next((p.score or 0 for p in primary if p.model_name == "anomaly_detector"), 0.0)
    if anomaly == 0:
        anomaly = next((p.score or 0 for p in primary if p.model_name == "threshold_detector"), 0.0)
    risk = next((p.score or 0 for p in primary if p.model_name == "risk_predictor"), 0.0)
    rule_score = max((r.score for r in triggered), default=0.0)
    w_a = weights.get("anomaly_detector", 0.45)
    w_r = weights.get("risk_predictor", 0.30)
    w_rule = weights.get("rules", 0.25)
    decision_score = w_a * anomaly + w_r * risk + w_rule * rule_score
    if event.event_type == EventType.BED_STATUS:
        cap = next((p.score or 0 for p in primary if p.model_name == "capacity_forecaster"), 0.0)
        decision_score = 0.7 * cap + 0.3 * rule_score
    if event.event_type == EventType.IMAGING_REQUEST:
        img = next((p.score or 0 for p in primary if p.model_name == "imaging_prioritizer"), 0.0)
        decision_score = 0.7 * img + 0.3 * rule_score

    if decision_score >= 0.85 and SEVERITY_RANK[severity] < SEVERITY_RANK["HIGH"]:
        severity = "HIGH"
    elif decision_score >= 0.65 and severity == "LOW":
        severity = "MEDIUM"

    confidence = 0.5
    confs = [p.confidence for p in primary if p.confidence is not None]
    if confs:
        confidence = sum(confs) / len(confs)

    action = action_for(severity, triggered, event.event_type)
    explanation = {
        "ai": "probability / score of pattern being unusual — not a diagnosis",
        "rules": "deterministic thresholds on configured features",
        "triggered_rules": [r.name for r in triggered],
        "rule_reasons": [r.reason for r in triggered if r.reason],
        "weights": {"anomaly_detector": w_a, "risk_predictor": w_r, "rules": w_rule},
        "components": {"anomaly": anomaly, "risk": risk, "rules": rule_score},
        "features_used": {k: features.features.get(k) for k in ("heart_rate", "spo2", "respiratory_rate", "occupancy_ratio", "waiting_minutes")},
        "partial": any(p.status in {"timeout", "error", "circuit_open"} for p in predictions),
        "shadow_models": [p.model_name for p in predictions if p.shadow],
    }
    return Decision(
        event_id=event.event_id,
        patient_id=event.patient_id,
        severity=severity,  # type: ignore[arg-type]
        action=action,
        decision_score=round(decision_score, 4),
        confidence=round(confidence, 4),
        triggered_rules=[r.name for r in triggered],
        predictions=predictions,
        explanation=explanation,
        trace_id=event.trace_id,
    )
