from __future__ import annotations

RAW_EVENTS = "healthcare.events.raw"
VALIDATED_EVENTS = "healthcare.events.validated"
FEATURES_READY = "healthcare.features.ready"
PREDICTIONS = "healthcare.predictions"
DECISIONS = "healthcare.decisions"
ALERTS = "healthcare.alerts"
AUDIT = "healthcare.audit"
DLQ = "healthcare.events.dlq"

ALL_TOPICS = [
    RAW_EVENTS,
    VALIDATED_EVENTS,
    FEATURES_READY,
    PREDICTIONS,
    DECISIONS,
    ALERTS,
    AUDIT,
    DLQ,
]
