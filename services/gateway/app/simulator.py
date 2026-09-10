from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4


SCENARIOS = {
    "normal_ward",
    "deteriorating_patient",
    "duplicate_storm",
    "bed_crunch",
    "imaging_backlog",
    "malformed_poison",
    "clock_skew",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _evt(event_type: str, payload: dict, **kwargs) -> dict:
    ts = kwargs.pop("timestamp", None) or _now().isoformat().replace("+00:00", "Z")
    return {
        "event_id": kwargs.get("event_id", f"evt_{uuid4().hex[:12]}"),
        "source_id": kwargs.get("source_id", "simulator"),
        "event_type": event_type,
        "patient_id": kwargs.get("patient_id"),
        "device_id": kwargs.get("device_id"),
        "resource_id": kwargs.get("resource_id"),
        "timestamp": ts,
        "schema_version": 1,
        "payload": payload,
        "trace_id": kwargs.get("trace_id", uuid4().hex),
    }


def build_scenario_events(name: str, *, count: int, patient_id: str | None) -> list[dict]:
    if name not in SCENARIOS:
        return []
    patient = patient_id or "pat_10092"
    events: list[dict] = []
    now = _now()

    if name == "normal_ward":
        for i in range(count):
            ts = (now - timedelta(seconds=count - i)).isoformat().replace("+00:00", "Z")
            events.append(
                _evt(
                    "patient_vital",
                    {
                        "heart_rate": 72 + (i % 5),
                        "spo2": 98 - (i % 2) * 0.5,
                        "respiratory_rate": 16,
                        "temperature_c": 36.8,
                        "systolic_bp": 118,
                        "diastolic_bp": 76,
                    },
                    patient_id=patient,
                    device_id="monitor_17",
                    timestamp=ts,
                )
            )
    elif name == "deteriorating_patient":
        for i in range(count):
            ts = (now - timedelta(seconds=count - i)).isoformat().replace("+00:00", "Z")
            events.append(
                _evt(
                    "patient_vital",
                    {
                        "heart_rate": 90 + i * 1.4,
                        "spo2": max(84.0, 97 - i * 0.35),
                        "respiratory_rate": 18 + i * 0.4,
                        "temperature_c": 37.1 + i * 0.02,
                        "systolic_bp": 128 + i * 0.4,
                        "diastolic_bp": 82,
                    },
                    patient_id=patient,
                    device_id="monitor_17",
                    timestamp=ts,
                )
            )
    elif name == "duplicate_storm":
        event_id = "evt_dup_storm_1"
        payload = {"heart_rate": 141, "spo2": 89, "respiratory_rate": 29}
        for _ in range(count):
            events.append(
                _evt(
                    "patient_vital",
                    payload,
                    event_id=event_id,
                    patient_id=patient,
                    device_id="monitor_17",
                    source_id="monitor_17",
                )
            )
    elif name == "bed_crunch":
        for i in range(count):
            ratio = min(0.99, 0.7 + i * 0.01)
            events.append(
                _evt(
                    "bed_status",
                    {
                        "ward_id": "ward_icu_1",
                        "bed_id": f"bed_{i % 12}",
                        "status": "occupied" if ratio > 0.75 else "available",
                        "occupancy_ratio": ratio,
                    },
                    resource_id="ward_icu_1",
                )
            )
    elif name == "imaging_backlog":
        modalities = ["CT", "MRI", "XRAY", "US"]
        for i in range(count):
            events.append(
                _evt(
                    "imaging_request",
                    {
                        "modality": modalities[i % 4],
                        "body_part": "chest",
                        "waiting_minutes": 20 + i * 8,
                        "acuity_hint": "high" if i % 3 == 0 else "medium",
                    },
                    patient_id=f"pat_{10001 + (i % 5)}",
                )
            )
    elif name == "malformed_poison":
        events.append(
            {
                "event_id": f"evt_poison_{uuid4().hex[:8]}",
                "source_id": "simulator",
                "event_type": "patient_vital",
                "patient_id": patient,
                "timestamp": now.isoformat().replace("+00:00", "Z"),
                "schema_version": 1,
                "payload": {"heart_rate": 9000, "spo2": -4},
                "trace_id": uuid4().hex,
            }
        )
        events.append(
            {
                "event_id": "x",
                "source_id": "",
                "event_type": "not_a_type",
                "timestamp": "yesterday",
                "schema_version": 99,
                "payload": {},
                "trace_id": "short",
            }
        )
    elif name == "clock_skew":
        future = (now + timedelta(hours=6)).isoformat().replace("+00:00", "Z")
        events.append(
            _evt(
                "patient_vital",
                {"heart_rate": 80, "spo2": 98, "respiratory_rate": 16},
                patient_id=patient,
                timestamp=future,
            )
        )
    return events
