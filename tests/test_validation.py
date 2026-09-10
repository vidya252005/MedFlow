from datetime import datetime, timedelta, timezone

import pytest

from medflow_shared.config import Settings


def make_event(**overrides) -> dict:
    base = {
        "event_id": "evt_102931",
        "source_id": "monitor_17",
        "event_type": "patient_vital",
        "patient_id": "pat_10092",
        "device_id": "monitor_17",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "schema_version": 1,
        "payload": {"heart_rate": 128, "spo2": 91, "respiratory_rate": 27},
        "trace_id": "trace_abc12345",
    }
    base.update(overrides)
    return base


def test_valid_vital_parses() -> None:
    event = parse_event(make_event())
    assert event.event_type == EventType.PATIENT_VITAL
    assert event.dedup_key == "evt_102931:monitor_17"
    assert event.partition_key == "pat_10092"


def test_missing_patient_rejected() -> None:
    from medflow_shared.errors import ValidationError

    event = parse_event(make_event(patient_id=None))
    with pytest.raises(ValidationError):
        validate_event(event, Settings())


def test_invalid_heart_rate_rejected() -> None:
    from medflow_shared.errors import ValidationError

    event = parse_event(make_event(payload={"heart_rate": 900, "spo2": 91}))
    with pytest.raises(ValidationError):
        validate_event(event, Settings())


def test_future_timestamp_clock_skew() -> None:
    from medflow_shared.errors import ClockSkewError

    ts = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat().replace("+00:00", "Z")
    event = parse_event(make_event(timestamp=ts))
    with pytest.raises(ClockSkewError):
        validate_event(event, Settings())


def test_invalid_timestamp() -> None:
    from medflow_shared.errors import ValidationError

    event = parse_event(make_event(timestamp="yesterday"))
    with pytest.raises(ValidationError):
        validate_event(event, Settings())


def test_unsupported_schema_fails_parse() -> None:
    from pydantic import ValidationError as PydanticError
    from medflow_shared.errors import ValidationError

    with pytest.raises((ValidationError, PydanticError)):
        parse_event(make_event(schema_version=9))


def test_frozen_event_immutable() -> None:
    event = HealthcareEvent.model_validate(make_event())
    with pytest.raises(Exception):
        event.event_id = "nope"  # type: ignore[misc]
