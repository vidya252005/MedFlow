from __future__ import annotations

from datetime import datetime, timezone

from medflow_shared.config import Settings
from medflow_shared.errors import ClockSkewError, ValidationError
from medflow_shared.events import PAYLOAD_BY_TYPE, EventType, HealthcareEvent


def parse_event(raw: dict) -> HealthcareEvent:
    try:
        event = HealthcareEvent.model_validate(raw)
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(f"invalid event: {exc}") from exc
    return event


def validate_event(event: HealthcareEvent, settings: Settings, now: datetime | None = None) -> HealthcareEvent:
    now = now or datetime.now(timezone.utc)
    try:
        ts = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError("timestamp is not ISO-8601") from exc
    if ts.tzinfo is None:
        raise ValidationError("timestamp must be timezone-aware")

    skew = (ts - now).total_seconds()
    if skew > settings.allowed_clock_skew_seconds:
        raise ClockSkewError("event timestamp is too far in the future")
    age = (now - ts).total_seconds()
    if age > settings.allowed_event_age_seconds:
        raise ValidationError("event timestamp is too old")

    if event.event_type in {EventType.PATIENT_VITAL, EventType.DEVICE_READING, EventType.LAB_RESULT}:
        if not event.patient_id:
            raise ValidationError(f"{event.event_type.value} requires patient_id")

    if event.event_type == EventType.DEVICE_READING and not event.device_id:
        raise ValidationError("device_reading requires device_id")

    payload_model = PAYLOAD_BY_TYPE.get(event.event_type)
    if payload_model is None:
        raise ValidationError("unsupported event type")
    try:
        payload_model.model_validate(event.payload)
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(f"invalid payload: {exc}") from exc

    return event
